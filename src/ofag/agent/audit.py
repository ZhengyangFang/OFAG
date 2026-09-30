"""Find the choices that were made and not fully written down."""

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["RecordedChoice", "audit_script", "audit_tree", "CHOICE_MARKERS", "REVERSAL_MARKERS"]

#: Phrases that mark a comment as arguing for one option over another.
CHOICE_MARKERS = (
    "rather than",
    "instead of",
    "not because",
    "deliberately",
    "on purpose",
    "chosen",
    "declared",
    "the choice",
    "decided",
    "excluded",
    "is used",
    "stays on",
)

#: Phrases that mark a comment as saying what would make the choice wrong. "until" was
#: here and is not: it matched twice across the five scripts and both were the word
#: appearing somewhere in a long comment, neither a reversal condition.
REVERSAL_MARKERS = (
    "would reverse",
    "reversed if",
    "revisit",
    "no longer holds",
    "stops being true",
    "if that changes",
    "this is wrong if",
    "worth revisiting",
)

#: A run of `#:` comment lines immediately above a module constant, or above the
#: function a constant turned into.
_DOCUMENTED = re.compile(
    r"((?:^#:[^\n]*\n)+)(?:^([A-Z][A-Z0-9_]*)\s*[:=]|^def (_?[a-z][a-z0-9_]*)\s*\()", re.M
)


@dataclass(frozen=True)
class RecordedChoice:
    """One documented constant, and how completely it records its decision."""

    #: The constant, or the function's name with parentheses where the choice is
    #: recorded above a function instead.
    constant: str
    path: Path
    line: int
    comment: str
    #: The markers that made this read as a choice.
    choice_markers: tuple[str, ...]
    #: The markers that made it read as carrying a reversal condition.
    reversal_markers: tuple[str, ...]

    @property
    def reads_as_choice(self) -> bool:
        return bool(self.choice_markers)

    @property
    def states_reversal(self) -> bool:
        return bool(self.reversal_markers)

    @property
    def incomplete(self) -> bool:
        """A choice that does not say what would make it wrong."""
        return self.reads_as_choice and not self.states_reversal

    @property
    def summary(self) -> str:
        """The comment's first real line, for a listing."""
        for line in self.comment.splitlines():
            text = line.lstrip("#:").strip()
            if len(text) > 4:
                return text
        return ""


def audit_script(path: Path) -> tuple[RecordedChoice, ...]:
    """Every documented constant in one file, and what its comment records."""
    text = path.read_text(encoding="utf-8")
    found: list[RecordedChoice] = []
    for match in _DOCUMENTED.finditer(text):
        comment = match.group(1)
        # A choice recorded above a function is named for the function, so a reader who
        # greps the listing finds the thing the comment is about.
        constant = match.group(2) or f"{match.group(3)}()"
        lowered = comment.lower()
        found.append(
            RecordedChoice(
                constant=constant,
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
                comment=comment,
                choice_markers=tuple(m for m in CHOICE_MARKERS if m in lowered),
                reversal_markers=tuple(m for m in REVERSAL_MARKERS if m in lowered),
            )
        )
    return tuple(found)


def audit_tree(root: Path, pattern: str = "case*.py") -> tuple[RecordedChoice, ...]:
    """The same over every case script, in a stable order."""
    return tuple(choice for path in sorted(root.glob(pattern)) for choice in audit_script(path))
