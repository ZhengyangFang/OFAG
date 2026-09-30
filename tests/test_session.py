"""Running an inversion with the obligations enforced."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ofag.agent.obligations import Ledger, ObligationError, Stage
from ofag.agent.session import (
    ENOUGH_TO_CORRECT,
    SAMPLE_ABOVE_SECONDS,
    GuardedRuns,
    calibration,
)
from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArtifactManifest,
    CoordinateConvention,
    DatasetSpec,
    ResourceEstimate,
    RunSpec,
    ValidationIssue,
    ValidationReport,
)


def _spec(label: str = "a run", seconds_hint: int = 1) -> RunSpec:
    return RunSpec(
        plugin_id="test.plugin",
        plugin_version="0.1.0",
        engine="test",
        project_id=uuid4(),
        label=label,
        dataset=DatasetSpec(
            name="d",
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            physical_quantity=QuantityType.LENGTH,
            units="m",
        ),
        physics={"seconds": seconds_hint},
    )


@dataclass
class FakeState:
    value: str = "SUCCEEDED"


@dataclass
class FakeRecord:
    spec: RunSpec
    state: FakeState = field(default_factory=FakeState)


@dataclass
class FakeResult:
    artifacts: tuple[ArtifactManifest, ...]
    summary: dict[str, Any] = field(default_factory=dict)


class FakePlugin:
    plugin_id = "test.plugin"
    plugin_version = "0.1.0"

    def conventions(self):
        from ofag.core.conventions import ConventionCheck, ConventionResult

        return (
            ConventionCheck(
                name="a check",
                catches="something silent",
                against="closed-form arithmetic",
                run=lambda: ConventionResult(passed=True, detail="held"),
            ),
        )

    def estimate_resources(self, context, spec) -> ResourceEstimate:
        return ResourceEstimate(
            cpu_cores=1, memory_mb=256, estimated_seconds=int(spec.physics["seconds"])
        )


class FakeRuns:
    """Enough of `RunService` to drive the gate, and no solver."""

    def __init__(self, root: Path, *, valid: bool = True, write_artifacts: bool = True) -> None:
        self.artifact_root = root
        self.valid = valid
        self.write_artifacts = write_artifacts
        self._records: dict[UUID, FakeRecord] = {}
        self.started: list[UUID] = []

    def validate(self, spec: RunSpec) -> ValidationReport:
        if self.valid:
            return ValidationReport(valid=True, issues=())
        return ValidationReport(
            valid=False,
            issues=(ValidationIssue(field="physics", message="no", remediation="fix it"),),
        )

    def create(self, spec: RunSpec) -> FakeRecord:
        self._records[spec.run_id] = FakeRecord(spec=spec)
        return self._records[spec.run_id]

    def start(self, run_id: UUID) -> FakeRecord:
        self.started.append(run_id)
        directory = self.artifact_root / str(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        if self.write_artifacts:
            (directory / "model.npy").write_bytes(b"\x00")
        return self._records[run_id]

    def get(self, run_id: UUID) -> FakeRecord:
        return self._records[run_id]

    def result(self, run_id: UUID) -> FakeResult:
        return FakeResult(
            artifacts=(
                ArtifactManifest(
                    artifact_type="array",
                    physical_quantity=QuantityType.LENGTH,
                    units="m",
                    source_run_id=run_id,
                    relative_path=f"{run_id}/model.npy",
                ),
            )
        )


class FakeRegistry:
    def get(self, plugin_id: str) -> FakePlugin:
        return FakePlugin()


@pytest.fixture
def guarded(tmp_path):
    runs = FakeRuns(tmp_path / "runs")
    session = GuardedRuns(
        runs, registry=FakeRegistry(), ledger=Ledger(tmp_path / "obligations.jsonl")
    )
    return session, runs


def test_a_run_that_owes_something_is_refused_by_name(guarded) -> None:
    session, runs = guarded

    with pytest.raises(ObligationError) as raised:
        session.execute(_spec())

    assert set(raised.value.missing) == {Stage.VALIDATED, Stage.CONVENTIONS_CHECKED}
    assert not runs.started


def test_validating_discharges_both_of_the_two_it_covers(guarded) -> None:
    """`RunService.validate` runs the convention checks inside itself, so the two obligations
    come from the one call."""
    session, _ = guarded
    spec = _spec()
    session.validate(spec)

    assert session.owed(spec) == (Stage.ESTIMATED,)
    session.estimate(spec)
    assert session.owed(spec) == ()


def test_an_invalid_specification_discharges_nothing(tmp_path) -> None:
    runs = FakeRuns(tmp_path / "runs", valid=False)
    session = GuardedRuns(runs, registry=FakeRegistry(), ledger=Ledger(tmp_path / "o.jsonl"))
    spec = _spec()

    assert not session.validate(spec).valid
    with pytest.raises(ObligationError):
        session.execute(spec)


def test_a_slow_run_owes_a_walk_and_a_fast_one_does_not(guarded) -> None:
    """C4. The threshold is set where being wrong is cheap, because the estimates are not
    calibrated -- this project's transient plugin estimates 184 seconds for a run that
    takes ten."""
    session, _ = guarded

    quick = _spec("quick", seconds_hint=SAMPLE_ABOVE_SECONDS - 1)
    session.validate(quick)
    assert not session.estimate(quick).walk_owed
    assert session.owed(quick) == ()

    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)
    session.validate(slow)
    assert session.estimate(slow).walk_owed
    assert session.owed(slow) == (Stage.SAMPLED,)


def test_a_slow_run_is_refused_until_the_walk_is_taken(guarded) -> None:
    session, runs = guarded
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)
    session.validate(slow)

    with pytest.raises(ObligationError) as raised:
        session.execute(slow)
    assert raised.value.missing == (Stage.SAMPLED,)
    assert not runs.started

    report = session.sample(slow, _spec("a smaller slow", seconds_hint=1))
    assert report.reached_the_consumer
    session.execute(slow)
    assert len(runs.started) == 2


def test_a_walk_whose_artifacts_cannot_be_read_does_not_count(tmp_path) -> None:
    """The half of C4 that costs the time, and the whole of F045."""
    runs = FakeRuns(tmp_path / "runs", write_artifacts=False)
    session = GuardedRuns(runs, registry=FakeRegistry(), ledger=Ledger(tmp_path / "o.jsonl"))
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)
    session.validate(slow)

    report = session.sample(slow, _spec("smaller", seconds_hint=1))

    assert not report.reached_the_consumer
    assert len(report.unreadable) == 1
    with pytest.raises(ObligationError, match="sampled"):
        session.execute(slow)


def test_a_walk_has_to_go_down_the_same_path(guarded) -> None:
    session, _ = guarded
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)
    session.validate(slow)
    elsewhere = _spec("elsewhere").model_copy(update={"plugin_id": "other.plugin"})

    with pytest.raises(ValueError, match="same path"):
        session.sample(slow, elsewhere)


def test_a_walk_cannot_be_the_run_itself(guarded) -> None:
    session, _ = guarded
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)
    session.validate(slow)

    with pytest.raises(ValueError, match="which is not a walk"):
        session.sample(slow, slow)


def test_what_was_estimated_is_recorded_beside_what_it_took(guarded) -> None:
    """The estimates are wrong in a way nobody has measured."""
    session, _ = guarded
    spec = _spec(seconds_hint=3)
    session.validate(spec)
    session.execute(spec)

    executed = next(entry for entry in session.ledger.entries() if entry.stage is Stage.EXECUTED)
    assert "against 3 s estimated" in executed.evidence
    assert " s against" in executed.evidence


def test_the_ledger_belongs_to_the_specification_not_the_run(guarded) -> None:
    """A RunSpec is edited in place while an agent iterates."""
    session, _ = guarded
    spec = _spec()
    session.validate(spec)
    edited = spec.model_copy(update={"physics": {"seconds": 2}})

    assert session.owed(spec) == (Stage.ESTIMATED,)
    assert set(session.owed(edited)) == {
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
    }


def test_the_gate_collects_what_would_fix_the_gate(guarded) -> None:
    """Every execution records the estimate beside what it took, so the calibration needs no
    instrumentation of its own."""
    session, _ = guarded
    for index in range(ENOUGH_TO_CORRECT):
        spec = _spec(f"run {index}", seconds_hint=2)
        session.validate(spec)
        session.execute(spec)

    measured = calibration(session.ledger)

    assert measured["test.plugin"]["runs"] == ENOUGH_TO_CORRECT
    assert measured["test.plugin"]["enough_to_correct"] is True


def test_one_observation_is_reported_and_not_acted_on(guarded) -> None:
    """The transient plugin estimates 184 seconds for a run that takes ten, and the
    temptation is to divide its formula by eighteen."""
    session, _ = guarded
    spec = _spec(seconds_hint=2)
    session.validate(spec)
    session.execute(spec)

    measured = calibration(session.ledger)

    assert measured["test.plugin"]["runs"] == 1
    assert measured["test.plugin"]["enough_to_correct"] is False


def test_a_ledger_with_nothing_executed_calibrates_nothing(guarded) -> None:
    session, _ = guarded
    session.validate(_spec())

    assert calibration(session.ledger) == {}


def test_the_whole_sequence_is_one_call(guarded) -> None:
    """Twenty-one dispatch sites across three case scripts."""
    session, runs = guarded
    taken = session.take(_spec(seconds_hint=2))

    assert taken.walk is None
    assert not taken.estimate.walk_owed
    assert len(runs.started) == 1
    assert taken.run_id == runs.started[0]


def test_the_sequence_walks_where_the_estimate_asks(guarded) -> None:
    session, runs = guarded
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)

    taken = session.take(slow, _spec("smaller", seconds_hint=1))

    assert taken.walk is not None
    assert taken.walk.reached_the_consumer
    assert len(runs.started) == 2


def test_the_sequence_refuses_rather_than_exiting(guarded) -> None:
    """A case script turns a refusal into a message and stops; something else might turn it
    into the next thing to do."""
    session, runs = guarded
    slow = _spec("slow", seconds_hint=SAMPLE_ABOVE_SECONDS + 1)

    with pytest.raises(ValueError, match="no smaller version was offered"):
        session.take(slow)
    assert not runs.started


def test_the_sequence_refuses_an_invalid_specification(tmp_path) -> None:
    runs = FakeRuns(tmp_path / "runs", valid=False)
    session = GuardedRuns(runs, registry=FakeRegistry(), ledger=Ledger(tmp_path / "o.jsonl"))

    with pytest.raises(ValueError, match="physics"):
        session.take(_spec())
    assert not runs.started


def test_a_plugin_that_declares_its_conventions_unverified_can_be_validated(tmp_path) -> None:
    """Found by the independent review."""
    from ofag.core.conventions import UNVERIFIED

    class Unverified(FakePlugin):
        def conventions(self):
            return UNVERIFIED

    class Registry:
        def get(self, plugin_id: str) -> FakePlugin:
            return Unverified()

    session = GuardedRuns(
        FakeRuns(tmp_path / "runs"), registry=Registry(), ledger=Ledger(tmp_path / "o.jsonl")
    )
    spec = _spec()

    assert session.validate(spec).valid
    (entry,) = [e for e in session.ledger.entries() if e.stage is Stage.CONVENTIONS_CHECKED]
    assert "UNVERIFIED" in entry.evidence


@pytest.mark.parametrize("ending", ["FAILED", "CANCELLED", "INTERRUPTED"])
def test_a_run_that_did_not_succeed_is_not_executed(tmp_path, ending) -> None:
    """Found by driving the roles end to end."""

    class EndsBadly(FakeRuns):
        def start(self, run_id: UUID) -> FakeRecord:
            record = super().start(run_id)
            record.state = FakeState(value=ending)
            return record

    session = GuardedRuns(
        EndsBadly(tmp_path / "runs"), registry=FakeRegistry(), ledger=Ledger(tmp_path / "o.jsonl")
    )
    spec = _spec()
    session.validate(spec)
    session.estimate(spec)

    record = session.execute(spec)

    assert record.state.value == ending
    from ofag.core.schemas import spec_fingerprint

    assert not session.ledger.has(Stage.EXECUTED, spec_fingerprint(spec))
