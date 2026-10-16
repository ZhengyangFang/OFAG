"""The corpus of things that have gone wrong, as records an agent can act on."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from ofag.agent.resources import DOCS_ROOT

__all__ = [
    "Lesson",
    "Tier",
    "Decision",
    "FoundBy",
    "METHOD_NAMES",
    "find",
    "load_lessons",
    "DEFAULT_CORPUS",
    "PROJECT_ROOT",
    "DATA_FOR_SOURCE",
    "search",
]

#: The repository root for optional local replay data.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Where the corpus lives, beside the prose it was drawn from.
DEFAULT_CORPUS = DOCS_ROOT / "lessons" / "lessons.yaml"

#: Public examples have no field-data release.
DATA_FOR_SOURCE = {
    "agent": "src/ofag",
}


class Tier(StrEnum):
    """What stands behind a lesson, and therefore what it may be used for."""

    #: Supported by project measurements.
    MEASURED = "measured"
    #: Supported by an external reproduction.
    REPRODUCIBLE = "reproducible"
    #: The engine's own documentation says so.
    DECLARED = "declared"
    #: A textbook or a standard says so.
    RECEIVED = "received"
    #: Used to test a check.
    SYNTHETIC = "synthetic"


class Decision(StrEnum):
    """Whether a lesson is about a choice, and whose choice it is."""

    #: A defect. Nobody chose anything; something was simply wrong.
    NONE = "none"
    #: A choice the data can settle. Measure it; do not ask.
    MEASURABLE = "measurable"
    #: A choice the data cannot settle.
    JUDGEMENT = "judgement"


class FoundBy(StrEnum):
    """Who found a lesson."""

    #: While the agent system was being developed and tested.
    DEVELOPMENT = "development"
    #: Reported by an agent.
    AGENT = "agent"
    #: While building or checking the agent layer itself.
    BUILDING = "building"


#: The methods a lesson can be about: the method whose data it happened on.
METHOD_NAMES = ("tdem", "fdem", "ert", "mt", "gravity", "magnetic", "seismic", "boreholes")

_IDENTIFIER = re.compile(r"^(?:F\d{3}|SYN\d{3})$")


@dataclass(frozen=True)
class Lesson:
    """One recorded failure."""

    id: str
    #: Reusable rule learned from the evidence.
    title: str
    source: str
    tier: Tier
    #: Did it run clean?
    silent: bool
    decision: Decision
    #: Which step of `docs/agent_validation_and_debugging.md` now covers it, or None
    #: where nothing does.
    procedure: str | None
    #: A test that demonstrably fires on it, or None.
    covered_by: str | None
    #: Evidence supporting the lesson.
    evidence: str
    #: The method whose data it happened on, or empty where no survey data was involved
    #: -- a scheduler, a harness, a constant in a script.
    methods: tuple[str, ...] = ()
    found_by: FoundBy = FoundBy.DEVELOPMENT
    #: Optional earlier identifier for an imported lesson.
    former_id: str | None = None

    @property
    def gates_work(self) -> bool:
        """Whether this lesson may be turned into a mandatory obligation."""
        return self.tier in (Tier.MEASURED, Tier.REPRODUCIBLE)

    @property
    def data_directory(self) -> Path | None:
        """The release a replay of this lesson would need."""
        relative = DATA_FOR_SOURCE.get(self.source)
        return None if relative is None else PROJECT_ROOT / relative

    @property
    def data_present(self) -> bool:
        """Whether this lesson's release is still on disk."""
        directory = self.data_directory
        if directory is None or not directory.is_dir():
            return False
        return any(directory.rglob("*"))


def load_lessons(path: Path | None = None) -> tuple[Lesson, ...]:
    """Read the corpus, refusing anything it cannot stand behind."""
    source = DEFAULT_CORPUS if path is None else path
    document: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "lessons" not in document:
        raise ValueError(f"{source} has no 'lessons' list")

    lessons: list[Lesson] = []
    seen: set[str] = set()
    for record in document["lessons"]:
        identifier = str(record["id"])
        if not _IDENTIFIER.match(identifier):
            raise ValueError(
                f"{source}: {identifier!r} is not a lesson identifier; use F or SYN "
                "followed by three digits"
            )
        if identifier.startswith("SYN") and record["tier"] != Tier.SYNTHETIC:
            raise ValueError(f"{source}: {identifier} must have a synthetic tier")
        if identifier in seen:
            raise ValueError(f"{source}: {identifier} appears twice")
        seen.add(identifier)
        former = _optional(record.get("former_id"))
        if former is not None and former in seen:
            raise ValueError(f"{source}: former id {former} appears twice")
        if former is not None:
            seen.add(former)
        methods = tuple(str(m) for m in record.get("methods") or ())
        unknown = sorted(set(methods) - set(METHOD_NAMES))
        if unknown:
            raise ValueError(
                f"{source}: {identifier} names methods {unknown}; the methods are "
                + ", ".join(METHOD_NAMES)
            )
        lessons.append(
            Lesson(
                id=identifier,
                title=str(record["title"]),
                source=str(record["source"]),
                tier=Tier(record["tier"]),
                silent=bool(record["silent"]),
                decision=Decision(record["decision"]),
                procedure=_optional(record.get("procedure")),
                covered_by=_optional(record.get("covered_by")),
                evidence=str(record["evidence"]),
                methods=methods,
                found_by=FoundBy(record.get("found_by", FoundBy.DEVELOPMENT)),
                former_id=former,
            )
        )
    if not lessons:
        raise ValueError(f"{source} holds no lessons")
    return tuple(lessons)


def _optional(value: Any) -> str | None:
    return None if value is None else str(value)


def find(lessons: tuple[Lesson, ...], identifier: str) -> Lesson:
    """One lesson by its identifier, or by the one it had before renumbering."""
    wanted = identifier.strip().upper()
    for lesson in lessons:
        if lesson.id == wanted or lesson.former_id == wanted:
            return lesson
    raise KeyError(f"no lesson {identifier!r}")


def uncovered(lessons: tuple[Lesson, ...]) -> Iterator[Lesson]:
    """Every lesson with no check that fires on it: the work still to do."""
    return (lesson for lesson in lessons if lesson.covered_by is None)


def judgements(lessons: tuple[Lesson, ...]) -> Iterator[Lesson]:
    """Every lesson that was a choice the data could not settle."""
    return (lesson for lesson in lessons if lesson.decision is Decision.JUDGEMENT)


def search(
    lessons: tuple[Lesson, ...],
    *,
    procedure: str | None = None,
    decision: Decision | str | None = None,
    uncovered_only: bool = False,
    text: str | None = None,
    method: str | None = None,
) -> tuple[Lesson, ...]:
    """Find lessons by what they are, not by what they sound like."""
    wanted = Decision(decision) if isinstance(decision, str) else decision
    needle = (text or "").lower().strip()
    if method is not None and method not in METHOD_NAMES:
        raise ValueError(f"no method {method!r}; the methods are {', '.join(METHOD_NAMES)}")
    found = [
        lesson
        for lesson in lessons
        if (method is None or method in lesson.methods)
        and (procedure is None or lesson.procedure == procedure)
        and (wanted is None or lesson.decision is wanted)
        and (not uncovered_only or lesson.covered_by is None)
        and (not needle or needle in f"{lesson.title} {lesson.evidence}".lower())
    ]
    return tuple(sorted(found, key=lambda lesson: lesson.id))
