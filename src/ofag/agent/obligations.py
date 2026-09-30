"""What a run owes before it is allowed to be believed."""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "NotIndependent",
    "INDEPENDENT_OF",
    "EITHER",
    "SUPERSEDED_BY",
    "BLOCKED_BY",
    "Vetoed",
    "Stage",
    "Discharge",
    "Ledger",
    "ObligationError",
    "REQUIRES",
    "LEDGER_FILENAME",
]

#: What the ledger is called inside a run directory.
LEDGER_FILENAME = "obligations.jsonl"


class Stage(StrEnum):
    """The stages of one run, in the order they are owed."""

    #: A `RunSpec` exists and its fingerprint is what everything else is keyed on.
    SPECIFIED = "specified"
    #: The plugin's own `validate` returned a report with no issues.
    VALIDATED = "validated"
    #: Every `ConventionCheck` the plugin declares passed, against something outside the
    #: engine.
    CONVENTIONS_CHECKED = "conventions_checked"
    #: A `ResourceEstimate` exists, so the cost of the next stage is known before it is
    #: paid.
    ESTIMATED = "estimated"
    #: A smaller run of the same shape completed **and its artifacts were read back**.
    SAMPLED = "sampled"
    #: The run itself.
    EXECUTED = "executed"
    #: A run that was not inverted here: a published model read in by an importer and
    #: adopted as a run.
    ADOPTED = "adopted"
    #: The misfit was read, and where it missed its target, the ladder in section B was
    #: walked far enough to say why.
    DIAGNOSED = "diagnosed"
    #: Somebody other than whoever ran and diagnosed it read the evidence and did not
    #: veto.
    AUDITED = "audited"
    #: An auditor read the evidence and refused it.
    VETOED = "vetoed"
    #: The result was turned into geology, which is its own set of checks: what depth
    #: each method resolved, how far a label may travel, and what share of the volume
    #: nothing claims.
    READ_INTO_MODEL = "read_into_model"


#: What each stage owes before it can be entered.
REQUIRES: dict[Stage, tuple[Stage, ...]] = {
    Stage.SPECIFIED: (),
    Stage.VALIDATED: (Stage.SPECIFIED,),
    Stage.CONVENTIONS_CHECKED: (Stage.SPECIFIED,),
    Stage.ESTIMATED: (Stage.SPECIFIED,),
    Stage.SAMPLED: (Stage.VALIDATED, Stage.CONVENTIONS_CHECKED),
    Stage.EXECUTED: (Stage.VALIDATED, Stage.CONVENTIONS_CHECKED, Stage.ESTIMATED),
    Stage.ADOPTED: (),
    # Executed or adopted; `EITHER` says which of these may stand in for it.
    Stage.DIAGNOSED: (Stage.EXECUTED,),
    Stage.AUDITED: (Stage.DIAGNOSED,),
    Stage.VETOED: (Stage.DIAGNOSED,),
    Stage.READ_INTO_MODEL: (Stage.AUDITED,),
}

#: What makes an entry stale: a later entry of one of these stages for the same
#: specification.
SUPERSEDED_BY: dict[Stage, tuple[Stage, ...]] = {
    # A saved run may be adopted later for a new, named review.
    Stage.EXECUTED: (Stage.ADOPTED,),
    Stage.ADOPTED: (Stage.EXECUTED,),
    Stage.DIAGNOSED: (Stage.EXECUTED, Stage.ADOPTED),
    Stage.AUDITED: (Stage.EXECUTED, Stage.ADOPTED, Stage.VETOED),
    Stage.VETOED: (Stage.EXECUTED, Stage.ADOPTED),
    Stage.READ_INTO_MODEL: (Stage.EXECUTED, Stage.ADOPTED, Stage.VETOED),
}

#: A stage that may not be discharged while another stands.
BLOCKED_BY: dict[Stage, Stage] = {Stage.AUDITED: Stage.VETOED}

#: A requirement another stage may discharge instead.
EITHER: dict[Stage, tuple[Stage, ...]] = {
    Stage.EXECUTED: (Stage.ADOPTED,),
}

#: Stages that may not be discharged by whoever discharged these others.
INDEPENDENT_OF: dict[Stage, tuple[Stage, ...]] = {
    Stage.AUDITED: (Stage.EXECUTED, Stage.ADOPTED, Stage.DIAGNOSED),
    Stage.VETOED: (Stage.EXECUTED, Stage.ADOPTED, Stage.DIAGNOSED),
}


class NotIndependent(RuntimeError):
    """A stage that has to be someone else's was discharged by the same actor."""


class Vetoed(RuntimeError):
    """An audit was attempted while a veto on the same execution stands."""


class ObligationError(RuntimeError):
    """A stage was entered owing something."""

    def __init__(self, stage: Stage, missing: tuple[Stage, ...], fingerprint: str) -> None:
        self.stage = stage
        self.missing = missing
        self.fingerprint = fingerprint
        owed = ", ".join(step.value for step in missing)
        super().__init__(
            f"{stage.value} owes {owed} for specification {fingerprint[:12]}. "
            f"Discharge them against this fingerprint, not a neighbouring one: a "
            f"specification edited between the two is a different run."
        )


@dataclass(frozen=True)
class Discharge:
    """One obligation, discharged, with what discharged it."""

    stage: Stage
    #: The specification this was discharged against.
    fingerprint: str
    #: What was done, in one line a reader can check: "validate returned no issues", "5
    #: of 5 convention checks passed", "5 soundings, artifacts read back from
    #: progress.jsonl".
    evidence: str
    #: Who discharged it: the name the caller acts under, such as a role.
    by: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def as_json(self) -> str:
        return json.dumps(
            {
                "stage": self.stage.value,
                "fingerprint": self.fingerprint,
                "evidence": self.evidence,
                "by": self.by,
                "at": self.at,
            }
        )


class Ledger:
    """What has been discharged, for which specification."""

    #: Below this a piece of evidence is a gesture.
    MEANINGFUL_EVIDENCE = 12

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._discharged: list[Discharge] = []
        self._refresh()

    def _refresh(self) -> None:
        """Read durable entries, including changes made by another ledger instance."""
        path = self.path
        if path is None:
            return
        if path is not None and path.is_file():
            self._discharged = [
                Discharge(
                    stage=Stage(line["stage"]),
                    fingerprint=line["fingerprint"],
                    evidence=line["evidence"],
                    by=line.get("by", ""),
                    at=line["at"],
                )
                for line in (json.loads(raw) for raw in path.read_text("utf-8").splitlines() if raw)
            ]
        else:
            self._discharged = []

    def discharge(
        self, stage: Stage, fingerprint: str, evidence: str, *, by: str = ""
    ) -> Discharge:
        """Record an obligation as met, refusing one that is met out of order."""
        if len(evidence.strip()) < self.MEANINGFUL_EVIDENCE:
            raise ValueError(
                f"evidence for {stage.value} has to say what was done and checked, not that "
                f"it was: got {evidence!r}"
            )
        missing = self.missing_for(stage, fingerprint)
        if missing:
            raise ObligationError(stage, missing, fingerprint)
        self._refuse_self_review(stage, fingerprint, by.strip())
        blocker = BLOCKED_BY.get(stage)
        if blocker is not None:
            standing = self.current(blocker, fingerprint)
            if standing is not None:
                raise Vetoed(
                    f"{stage.value} for specification {fingerprint[:12]} is refused: "
                    f"{standing.by or 'someone'} vetoed it ({standing.evidence}). A veto stands "
                    "until the run is executed or adopted again; if it is wrong, that is the "
                    "lead's and a person's call, recorded as a decision."
                )
        entry = Discharge(stage=stage, fingerprint=fingerprint, evidence=evidence, by=by.strip())
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry.as_json() + "\n")
        self._discharged.append(entry)
        return entry

    def _refuse_self_review(self, stage: Stage, fingerprint: str, by: str) -> None:
        """Refuse a stage that has to be someone else's, discharged by the same actor."""
        against = INDEPENDENT_OF.get(stage, ())
        if not against:
            return
        if not by:
            raise NotIndependent(
                f"{stage.value} has to name who discharged it, because it may not be whoever "
                f"discharged {', '.join(s.value for s in against)}, and an unnamed entry "
                "cannot be told apart from one of theirs."
            )
        # Only the execution this would follow, and its diagnosis.
        for entry in (self.current(s, fingerprint) for s in against):
            if entry is None:
                continue
            if not entry.by:
                raise NotIndependent(
                    f"{entry.stage.value} for specification {fingerprint[:12]} names nobody, "
                    f"so {by!r} cannot be shown to be someone else. Execute or adopt it again "
                    "under a role's name; the new entry is the one an audit is checked against."
                )
            if entry.by == by:
                raise NotIndependent(
                    f"{by!r} discharged {entry.stage.value} for specification "
                    f"{fingerprint[:12]} and may not also discharge {stage.value}: a reader "
                    "that wrote what it is reading finds what it expected (F056)."
                )

    def current(self, stage: Stage, fingerprint: str) -> Discharge | None:
        """The latest entry of this stage that nothing later has superseded."""
        self._refresh()
        later = SUPERSEDED_BY.get(stage, ())
        found: Discharge | None = None
        for entry in self._discharged:
            if entry.fingerprint != fingerprint:
                continue
            if entry.stage is stage:
                found = entry
            elif found is not None and entry.stage in later:
                found = None
        return found

    def has(self, stage: Stage, fingerprint: str) -> bool:
        """Whether this stage stands for the specification, as of now."""
        return self.current(stage, fingerprint) is not None

    def missing_for(
        self, stage: Stage, fingerprint: str, *, also: Iterable[Stage] = ()
    ) -> tuple[Stage, ...]:
        """Which of a stage's obligations are not yet discharged."""
        owed = tuple(REQUIRES[stage]) + tuple(also)
        return tuple(
            step
            for step in dict.fromkeys(owed)
            if not self.has(step, fingerprint)
            and not any(self.has(instead, fingerprint) for instead in EITHER.get(step, ()))
        )

    def require(self, stage: Stage, fingerprint: str, *, also: Iterable[Stage] = ()) -> None:
        """Raise unless everything this stage owes has been discharged."""
        missing = self.missing_for(stage, fingerprint, also=also)
        if missing:
            raise ObligationError(stage, missing, fingerprint)

    def entries(self, fingerprint: str | None = None) -> tuple[Discharge, ...]:
        self._refresh()
        return tuple(
            entry
            for entry in self._discharged
            if fingerprint is None or entry.fingerprint == fingerprint
        )

    def report(self, fingerprint: str) -> str:
        """The ledger for one specification, as a reader would want it."""
        lines = [f"specification {fingerprint[:12]}"]
        taken = {stage for stage in Stage if self.has(stage, fingerprint)}
        stand_ins = {instead for options in EITHER.values() for instead in options}
        for stage in Stage:
            # Of a stage and its stand-in, show whichever was taken, and the canonical
            # one when neither was: an executed run is not "owed adopted", and an
            # adopted one is not "owed executed".
            if stage not in taken and (
                stage in stand_ins
                or stage is Stage.VETOED
                or any(i in taken for i in EITHER.get(stage, ()))
            ):
                continue
            entry = self.current(stage, fingerprint)
            mark = "done" if entry else "owed"
            lines.append(f"   {stage.value:22s} {mark:5s} {entry.evidence if entry else ''}"[:110])
        return "\n".join(lines)


def ledger_for_run(artifact_root: Path, run_id: Any) -> Ledger:
    """The ledger belonging to one run's artifact directory."""
    return Ledger(Path(artifact_root) / str(run_id) / LEDGER_FILENAME)
