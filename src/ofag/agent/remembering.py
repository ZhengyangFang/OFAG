"""What a project cannot reconstruct from what it wrote down."""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

__all__ = ["Kind", "Note", "Journal", "journal_for", "UnsupportedNote"]

#: Below this a reason is a gesture.
MEANINGFUL = 12


class Kind(StrEnum):
    """What a note is, which decides what it has to carry."""

    #: Somebody asked for something.
    ASKED = "asked"
    #: What satisfied an earlier ask. Appended rather than editing the ask.
    SATISFIED = "satisfied"
    #: An approach taken and abandoned, and why, so nobody redoes it.
    TRIED = "tried"
    #: A hypothesis tested and refuted, with what was measured and where.
    RULED_OUT = "ruled_out"


class UnsupportedNote(ValueError):
    """A note that does not carry what its kind needs."""


@dataclass(frozen=True)
class Note:
    """One thing the project could not have worked out from its own artifacts."""

    kind: Kind
    #: The ask, the approach, or the hypothesis, in one line somebody can match against.
    what: str
    #: Why it was abandoned, or what measurement refuted it.
    because: str = ""
    #: Where the measurement behind a refutation was taken.
    measured_where: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not self.what.strip():
            raise UnsupportedNote("a note has to say what it is about")
        if self.kind is Kind.ASKED:
            return
        if len(self.because.strip()) < MEANINGFUL:
            raise UnsupportedNote(
                f"a {self.kind.value} note says {self.because.strip()!r}. Say what was "
                "measured or why it was dropped: the next reader has the same good idea."
            )
        if self.kind is Kind.RULED_OUT and len(self.measured_where.strip()) < MEANINGFUL:
            raise UnsupportedNote(
                f"ruling out {self.what.strip()!r} does not say where it was measured. F052 "
                "is a hypothesis ruled out on a figure taken twenty metres below the band "
                "and outside the window the claim lives in."
            )

    def as_json(self) -> str:
        return json.dumps(
            {
                "kind": self.kind.value,
                "what": self.what,
                "because": self.because,
                "measured_where": self.measured_where,
                "at": self.at,
            }
        )


class Journal:
    """What a project was asked, what it tried, and what it ruled out."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._notes: list[Note] = []
        if path is not None and path.is_file():
            self._notes = [
                Note(
                    kind=Kind(row["kind"]),
                    what=row["what"],
                    because=row.get("because", ""),
                    measured_where=row.get("measured_where", ""),
                    at=row["at"],
                )
                for row in (json.loads(raw) for raw in path.read_text("utf-8").splitlines() if raw)
            ]

    # -- writing ------------------------------------------------------------

    def note(
        self,
        kind: Kind,
        what: str,
        *,
        because: str = "",
        measured_where: str = "",
    ) -> Note:
        """Append one, having checked it carries what its kind needs."""
        entry = Note(kind=kind, what=what, because=because, measured_where=measured_where)
        self._notes.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(entry.as_json() + "\n")
        return entry

    def satisfy(self, what: str, *, by: str) -> Note:
        """Record that an ask has been met, and refuse one that was never made."""
        wanted = what.strip().casefold()
        asked = [
            n for n in self._notes if n.kind is Kind.ASKED and n.what.strip().casefold() == wanted
        ]
        if not asked:
            raise UnsupportedNote(
                f"nothing was asked for in these words: {what.strip()!r}. What is owed is "
                + (", ".join(repr(n.what) for n in self.still_owed()) or "nothing")
            )
        return self.note(Kind.SATISFIED, what, because=by)

    # -- reading ------------------------------------------------------------

    @property
    def notes(self) -> tuple[Note, ...]:
        return tuple(self._notes)

    def still_owed(self) -> tuple[Note, ...]:
        """Asks nothing has answered, oldest first."""
        met = {n.what.strip().casefold() for n in self._notes if n.kind is Kind.SATISFIED}
        return tuple(
            n for n in self._notes if n.kind is Kind.ASKED and n.what.strip().casefold() not in met
        )

    def of(self, kind: Kind) -> tuple[Note, ...]:
        return tuple(n for n in self._notes if n.kind is kind)

    def about(self, text: str) -> tuple[Note, ...]:
        """Anything already noted that mentions this, so a good idea that was already tried
        is found before it is had again."""
        needle = text.strip().casefold()
        return tuple(
            n for n in self._notes if needle in n.what.casefold() or needle in n.because.casefold()
        )

    def report(self) -> str:
        """What a reader resuming this project needs before planning anything."""
        owed = self.still_owed()
        lines = [f"{len(self._notes)} notes; {len(owed)} asks still owed"]
        lines += [f"  owed: {n.what}" for n in owed]
        lines += [f"  tried and dropped: {n.what} -- {n.because}" for n in self.of(Kind.TRIED)]
        lines += [
            f"  ruled out: {n.what} -- {n.because}, measured at {n.measured_where}"
            for n in self.of(Kind.RULED_OUT)
        ]
        return "\n".join(lines)


def journal_for(artifact_root: Path) -> Journal:
    """The journal beside a project's runs."""
    return Journal(Path(artifact_root) / "journal.jsonl")


def owed_summary(journals: Iterable[Journal]) -> tuple[str, ...]:
    """Everything still owed across several projects, for a session that spans more than one."""
    return tuple(note.what for journal in journals for note in journal.still_owed())
