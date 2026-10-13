"""Decisions this project made once, posed again without their answers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ofag.agent.decisions import DecisionRecord, Settlement
from ofag.agent.lessons import PROJECT_ROOT
from ofag.agent.resources import DOCS_ROOT

__all__ = ["Replay", "Score", "load_replays", "score", "DEFAULT_REPLAYS"]

DEFAULT_REPLAYS = DOCS_ROOT / "development" / "benchmark" / "judgement.yaml"


@dataclass(frozen=True)
class Replay:
    """One decision, posed again."""

    lesson: str
    #: Put to the agent as written. Carries no answer and no hint of one.
    question: str
    #: A script that prints the situation from the release, or None where one has not
    #: been written yet.
    probe: str | None
    #: `judged` for every one of these, and the first thing an answer is scored on.
    expect: Settlement
    #: Groups of alternatives.
    must_name: tuple[tuple[str, ...], ...]
    #: What was actually decided, where it has been written out.
    historical: DecisionRecord | None
    #: Why this one cannot be replayed, where it cannot.
    blocked_by: str | None = None
    #: How the situation differs from the one that was met, where it does.
    caveat: str | None = None

    @property
    def runnable(self) -> bool:
        """The probe exists and will produce the situation."""
        return self.probe is not None and (PROJECT_ROOT / self.probe).is_file()

    @property
    def blind(self) -> bool:
        """Runnable, and the answer is not somewhere the agent can reach."""
        return self.runnable and self.blocked_by is None


@dataclass(frozen=True)
class Score:
    """How one answer did, in parts rather than as a mark."""

    lesson: str
    #: Did it get the kind of decision right? The one binary here.
    settlement_correct: bool
    #: Groups from `must_name` the answer did not use.
    missed: tuple[str, ...]
    #: The schema accepts it, so it carries options, costs and a reversal.
    well_formed: bool

    @property
    def complete(self) -> bool:
        return self.settlement_correct and not self.missed and self.well_formed


def load_replays(path: Path | None = None) -> tuple[Replay, ...]:
    """Read the replay set, with the historical records validated as records."""
    source = DEFAULT_REPLAYS if path is None else path
    document: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "replays" not in document:
        raise ValueError(f"{source} has no 'replays' list")

    replays: list[Replay] = []
    for record in document["replays"]:
        historical = record.get("historical")
        replays.append(
            Replay(
                lesson=str(record["lesson"]),
                question=str(record["question"]),
                probe=None if record.get("probe") is None else str(record["probe"]),
                expect=Settlement(record["expect"]),
                must_name=tuple(tuple(group) for group in record.get("must_name", [])),
                historical=None if historical is None else DecisionRecord(**historical),
                blocked_by=_optional(record.get("blocked_by")),
                caveat=_optional(record.get("caveat")),
            )
        )
    if not replays:
        raise ValueError(f"{source} holds no replays")
    return tuple(replays)


def score(replay: Replay, answer: DecisionRecord) -> Score:
    """Grade one answer against one replay."""
    said = " ".join(
        [answer.question, answer.because, answer.reverses_if, *answer.informed_by]
        + [f"{option.name} {option.cost}" for option in answer.options]
        + ([answer.measurement] if answer.measurement else [])
    ).lower()
    missed = tuple(
        " or ".join(group)
        for group in replay.must_name
        if not any(term.lower() in said for term in group)
    )
    return Score(
        lesson=replay.lesson,
        settlement_correct=answer.settlement is replay.expect,
        missed=missed,
        well_formed=True,
    )


def _optional(value: Any) -> str | None:
    return None if value is None else str(value).strip()
