"""Running an inversion with the obligations enforced rather than intended."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ofag.agent.obligations import Ledger, Stage
from ofag.core.safety import SAMPLE_ABOVE_SECONDS
from ofag.core.schemas import ResourceEstimate, RunSpec, ValidationReport, spec_fingerprint

__all__ = [
    "GuardedRuns",
    "Dispatched",
    "Estimate",
    "SampleReport",
    "SAMPLE_ABOVE_SECONDS",
    "calibration",
]

#: What the ledger is called at the root of a project's runs.
LEDGER_NAME = "obligations.jsonl"


@dataclass(frozen=True)
class Estimate:
    """What a run is expected to cost, and what that means for the next step."""

    resources: ResourceEstimate
    #: Whether a walk on a smaller version is owed before this may execute.
    walk_owed: bool

    @property
    def why(self) -> str:
        return f"{self.resources.estimated_seconds} s (uncalibrated heuristic), " + (
            f"above the {SAMPLE_ABOVE_SECONDS} s a walk is owed at"
            if self.walk_owed
            else f"under the {SAMPLE_ABOVE_SECONDS} s a walk is owed at"
        )


@dataclass(frozen=True)
class SampleReport:
    """A walk on a smaller run, and whether it reached the consumer."""

    run_id: UUID
    seconds: float
    #: Every artifact the sample declared, and whether it could be opened at the path it
    #: declared.
    artifacts: tuple[tuple[str, bool], ...]

    @property
    def readable(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.artifacts if ok)

    @property
    def unreadable(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.artifacts if not ok)

    @property
    def reached_the_consumer(self) -> bool:
        """Whether the walk is worth anything."""
        return bool(self.artifacts) and not self.unreadable


@dataclass(frozen=True)
class Dispatched:
    """One run taken all the way through the gate."""

    run_id: UUID
    estimate: Estimate
    #: The walk, where one was owed. None where the estimate did not ask.
    walk: SampleReport | None
    seconds: float


class GuardedRuns:
    """`RunService` with the ledger in front of it."""

    def __init__(
        self,
        runs: Any,
        registry: Any = None,
        ledger: Ledger | None = None,
        actor: str = "",
        cancelled: Any = None,
    ) -> None:
        self._runs = runs
        self._cancelled = cancelled
        #: The name every stage this discharges is recorded under, so that a later audit
        #: can be refused if it comes from the same actor.
        self.actor = actor
        if registry is None:
            from ofag.plugins.registry import default_registry

            registry = default_registry()
        self._registry = registry
        root = Path(runs.artifact_root) if hasattr(runs, "artifact_root") else Path(".")
        self.ledger = ledger if ledger is not None else Ledger(root / LEDGER_NAME)

    def _discharge(self, stage: Stage, fingerprint: str, evidence: str) -> Any:
        return self.ledger.discharge(stage, fingerprint, evidence, by=self.actor)

    # -- the stages ---------------------------------------------------------

    def specify(self, spec: RunSpec) -> str:
        """Record the specification, and return what everything else keys on."""
        fingerprint = spec_fingerprint(spec)
        if not self.ledger.has(Stage.SPECIFIED, fingerprint):
            self._discharge(
                Stage.SPECIFIED,
                fingerprint,
                f"{spec.plugin_id} {spec.plugin_version}, {len(spec.datasets)} channels",
            )
        return fingerprint

    def validate(self, spec: RunSpec) -> ValidationReport:
        """Validate, which is also where the convention checks run."""
        fingerprint = self.specify(spec)
        report: ValidationReport = self._runs.validate(spec)
        if report.valid:
            if not self.ledger.has(Stage.VALIDATED, fingerprint):
                self._discharge(
                    Stage.VALIDATED, fingerprint, "validate returned a report with no issues"
                )
            if not self.ledger.has(Stage.CONVENTIONS_CHECKED, fingerprint):
                from ofag.core.conventions import _Unverified

                checks = getattr(self._plugin(spec), "conventions", lambda: ())()
                # UNVERIFIED is the plugin saying why it has none, which is what the
                # stage asks of a plugin without checks.
                self._discharge(
                    Stage.CONVENTIONS_CHECKED,
                    fingerprint,
                    "declared UNVERIFIED: no independent check exists, and validate reports "
                    "that on every run"
                    if isinstance(checks, _Unverified)
                    else f"{len(tuple(checks))} convention checks passed inside validate",
                )
        return report

    def estimate(self, spec: RunSpec) -> Estimate:
        """Ask what the run will cost, and whether that buys a walk first."""
        fingerprint = self.specify(spec)
        resources = self._plugin(spec).estimate_resources(self._context(), spec)
        estimate = Estimate(
            resources=resources,
            walk_owed=resources.estimated_seconds > SAMPLE_ABOVE_SECONDS,
        )
        if not self.ledger.has(Stage.ESTIMATED, fingerprint):
            self._discharge(Stage.ESTIMATED, fingerprint, estimate.why)
        return estimate

    def sample(self, spec: RunSpec, smaller: RunSpec) -> SampleReport:
        """Walk the whole path on a smaller run, and read its artifacts back."""
        fingerprint = self.specify(spec)
        if smaller.plugin_id != spec.plugin_id:
            raise ValueError(
                f"a walk has to go down the same path: {smaller.plugin_id} is not {spec.plugin_id}"
            )
        if spec_fingerprint(smaller) == fingerprint:
            raise ValueError("the walk is the run itself, which is not a walk")

        started = time.monotonic()
        self._runs.create(smaller)
        self._runs.start(smaller.run_id)
        self._wait(smaller.run_id)
        seconds = time.monotonic() - started

        result = self._runs.result(smaller.run_id)
        root = Path(self._runs.artifact_root)
        artifacts = tuple(
            (artifact.relative_path, (root / artifact.relative_path).is_file())
            for artifact in (result.artifacts if result else ())
        )
        report = SampleReport(run_id=smaller.run_id, seconds=seconds, artifacts=artifacts)
        if report.reached_the_consumer:
            self._discharge(
                Stage.SAMPLED,
                fingerprint,
                f"{seconds:.0f} s on a smaller spec; {len(report.readable)} artifacts read "
                f"back at their declared paths",
            )
        return report

    def execute(self, spec: RunSpec) -> Any:
        """Run it, if everything it owes has been discharged."""
        fingerprint = self.specify(spec)
        estimate = self.estimate(spec)
        also = (Stage.SAMPLED,) if estimate.walk_owed else ()
        self.ledger.require(Stage.EXECUTED, fingerprint, also=also)

        started = time.monotonic()
        self._runs.create(spec)
        self._runs.start(spec.run_id)
        self._wait(spec.run_id)
        seconds = time.monotonic() - started
        # Record the final run state.
        record = self._runs.get(spec.run_id)
        if record.state.value != "SUCCEEDED":
            return record

        # What was estimated beside what it took.
        self._discharge(
            Stage.EXECUTED,
            fingerprint,
            # A decimal place, because a run under a second recorded as "0 s" loses its
            # duration entirely and the calibration below divides by it.
            f"ran in {seconds:.1f} s against {estimate.resources.estimated_seconds} s estimated",
        )
        return record

    def take(self, spec: RunSpec, smaller: RunSpec | None = None) -> Dispatched:
        """Validate, estimate, walk if owed, and run."""
        report = self.validate(spec)
        if not report.valid:
            raise ValueError(
                "; ".join(f"{issue.field}: {issue.message}" for issue in report.issues)
            )
        estimate = self.estimate(spec)
        walk = None
        if estimate.walk_owed:
            if smaller is None:
                raise ValueError(
                    f"{estimate.why}, and no smaller version was offered. Write one, or say "
                    f"why this run does not owe a walk."
                )
            walk = self.sample(spec, smaller)
            if not walk.reached_the_consumer:
                raise ValueError(
                    f"the walk finished and {len(walk.unreadable)} of its artifacts could not "
                    f"be opened at the paths it declared: {', '.join(walk.unreadable)}"
                )
        started = time.monotonic()
        self.execute(spec)
        return Dispatched(
            run_id=spec.run_id,
            estimate=estimate,
            walk=walk,
            seconds=time.monotonic() - started,
        )

    # -- helpers ------------------------------------------------------------

    def owed(self, spec: RunSpec) -> tuple[Stage, ...]:
        """What this specification still owes before it may execute."""
        fingerprint = spec_fingerprint(spec)
        also = (
            (Stage.SAMPLED,)
            if self.ledger.has(Stage.ESTIMATED, fingerprint) and self._estimated_walk(fingerprint)
            else ()
        )
        return self.ledger.missing_for(Stage.EXECUTED, fingerprint, also=also)

    def _estimated_walk(self, fingerprint: str) -> bool:
        entry = next(
            (e for e in self.ledger.entries(fingerprint) if e.stage is Stage.ESTIMATED), None
        )
        return entry is not None and "above the" in entry.evidence

    def _plugin(self, spec: RunSpec) -> Any:
        return self._registry.get(spec.plugin_id)

    def _context(self) -> Any:
        from ofag.plugins.protocol import PluginContext

        return PluginContext(Path(self._runs.artifact_root))

    def _wait(self, run_id: UUID, poll: float = 2.0) -> None:
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}
        while self._runs.get(run_id).state.value not in terminal:
            if self._cancelled is not None and self._cancelled():
                self._runs.cancel(run_id)
                return
            time.sleep(poll)


#: How many runs of one plugin before its estimate is worth correcting.
ENOUGH_TO_CORRECT = 3


def calibration(ledger: Ledger) -> dict[str, dict[str, float | int]]:
    """What the estimates have been worth, per plugin, from the ledger."""
    import re

    seen: dict[str, list[tuple[float, float]]] = {}
    plugins: dict[str, str] = {}
    for entry in ledger.entries():
        if entry.stage is Stage.SPECIFIED:
            plugins[entry.fingerprint] = entry.evidence.split()[0]
        if entry.stage is not Stage.EXECUTED:
            continue
        found = re.search(r"ran in (\d+(?:\.\d+)?) s against (\d+(?:\.\d+)?) s", entry.evidence)
        plugin = plugins.get(entry.fingerprint)
        if found and plugin:
            seen.setdefault(plugin, []).append((float(found.group(1)), float(found.group(2))))

    summary: dict[str, dict[str, float | int]] = {}
    for plugin, pairs in sorted(seen.items()):
        ratios = [actual / estimated for actual, estimated in pairs if estimated > 0]
        summary[plugin] = {
            "runs": len(pairs),
            "actual_over_estimated": round(sum(ratios) / len(ratios), 2) if ratios else 0.0,
            "enough_to_correct": len(pairs) >= ENOUGH_TO_CORRECT,
        }
    return summary
