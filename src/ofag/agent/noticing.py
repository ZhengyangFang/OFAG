"""Silent failures, posed as work rather than as questions."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ofag.agent.resources import DOCS_ROOT

__all__ = [
    "Tell",
    "SilentReplay",
    "Noticed",
    "refuse_hinting_tasks",
    "load_silent_replays",
    "score_noticing",
    "load_bearing",
]

#: Ways a brief turns into a warning.
WARNINGS = (
    "check",
    "careful",
    "verify",
    "make sure",
    "watch out",
    "problem",
    "defect",
    "wrong",
    "suspicious",
    "anomal",
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = DOCS_ROOT / "development" / "benchmark" / "silent.yaml"


@dataclass(frozen=True)
class Tell:
    """One observable the defect leaves in the data, and how to say it."""

    #: What a reader would have to notice, in a sentence.
    what: str
    #: Any of these appearing in the answer counts as having named it.
    names: tuple[str, ...]


@dataclass(frozen=True)
class SilentReplay:
    """A piece of work with a defect in it, and nothing saying so."""

    lesson: str
    #: The task, in the terms somebody would be asked in. It must not hint.
    task: str
    #: The gate this replay is asking about.
    gates: tuple[str, ...]
    #: What the defect leaves behind.
    tells: tuple[Tell, ...]
    #: Whether the task asks a question whose answer *is* the tell.
    on_path: bool
    #: What it cost when this project met it, for the write-up rather than the score.
    cost: str
    blocked_by: str | None = None

    @property
    def runnable(self) -> bool:
        return self.blocked_by is None


@dataclass(frozen=True)
class Noticed:
    """How one answer did at seeing what was there."""

    lesson: str
    #: The tells the answer named.
    saw: tuple[str, ...]
    #: And the ones it did not.
    missed: tuple[str, ...]

    @property
    def noticed(self) -> bool:
        """Whether every tell was named."""
        return not self.missed

    @property
    def summary(self) -> str:
        return f"{self.lesson}: saw {len(self.saw)} of {len(self.saw) + len(self.missed)}" + (
            f", missed {'; '.join(self.missed)}" if self.missed else " -- everything"
        )


def refuse_hinting_tasks(replays: Sequence[SilentReplay]) -> tuple[str, ...]:
    """Refuse a task that contains the answer to its own question."""
    refusals: list[str] = []
    for replay in replays:
        task = replay.task.lower()
        for tell in replay.tells:
            leaked = [n for n in tell.names if n.lower() in task]
            if leaked:
                refusals.append(
                    f"{replay.lesson}: the task contains {leaked}, which the tell "
                    f"{tell.what!r} is scored on -- an answer that repeats the brief scores it"
                )
        warned = [w for w in WARNINGS if w in task]
        if warned:
            refusals.append(f"{replay.lesson}: the task says something is wrong ({warned})")
    return tuple(refusals)


def load_silent_replays(path: Path | None = None) -> tuple[SilentReplay, ...]:
    """The silent corpus, in the order it is written."""
    source = DEFAULT_CORPUS if path is None else path
    document: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "silent" not in document:
        raise ValueError(f"{source} has no 'silent' list")
    replays: list[SilentReplay] = []
    seen: set[str] = set()
    for record in document["silent"]:
        lesson = str(record["lesson"])
        if lesson in seen:
            raise ValueError(f"{source}: {lesson} appears twice")
        seen.add(lesson)
        replays.append(
            SilentReplay(
                lesson=lesson,
                task=str(record["task"]).strip(),
                gates=tuple(str(g) for g in record.get("gates", ())),
                tells=tuple(
                    Tell(what=str(t["what"]).strip(), names=tuple(str(n) for n in t["names"]))
                    for t in record["tells"]
                ),
                on_path=bool(record["on_path"]),
                cost=str(record["cost"]).strip(),
                blocked_by=(
                    None if record.get("blocked_by") is None else str(record["blocked_by"]).strip()
                ),
            )
        )
    if not replays:
        raise ValueError(f"{source} holds no silent replays")
    hints = refuse_hinting_tasks(replays)
    if hints:
        raise ValueError(f"{source} hints:\n  " + "\n  ".join(hints))
    return tuple(replays)


def score_noticing(replay: SilentReplay, answer: str) -> Noticed:
    """Grade one answer on whether it saw what was in front of it."""
    said = answer.lower()
    saw = [tell.what for tell in replay.tells if any(n.lower() in said for n in tell.names)]
    missed = [tell.what for tell in replay.tells if tell.what not in saw]
    return Noticed(lesson=replay.lesson, saw=tuple(saw), missed=tuple(missed))


def load_bearing(replays: Sequence[SilentReplay] | None = None) -> dict[str, tuple[str, ...]]:
    """Which gate each runnable replay is asking about."""
    corpus = replays if replays is not None else load_silent_replays()
    return {replay.lesson: replay.gates for replay in corpus if replay.runnable}
