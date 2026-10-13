"""An identifier nobody followed, refused before it is written down."""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = [
    "Resolution",
    "Source",
    "UnresolvedIdentifier",
    "refuse_unresolved",
]

#: Below this, saying where an unpublished source is held is a gesture.
_MEANINGFUL = 24


class Resolution(StrEnum):
    """What came back when the identifier was followed."""

    #: Followed, and what came back is the thing in hand.
    CONFIRMED = "confirmed"
    #: Followed, and what came back is something else.
    MISMATCHED = "mismatched"
    #: Followed, and nothing came back.
    DEAD = "dead"


class Source(StrictModel):
    """One input, its identifier, and what happened when it was followed."""

    what: str = Field(min_length=1, max_length=200)
    #: The DOI, accession or URL.
    identifier: str = ""
    #: `None` means nobody followed it.
    resolution: Resolution | None = None
    #: What came back, in enough words to recognise.
    resolved_to: str = ""
    #: When it was followed. An identifier resolves until it does not.
    checked_on: date | None = None
    #: Where an unpublished source is, when it was made and who holds it.
    held_at: str = ""

    @model_validator(mode="after")
    def the_claim_carries_its_evidence(self) -> "Source":
        if not self.identifier.strip():
            if len(self.held_at.strip()) < _MEANINGFUL:
                raise ValueError(
                    f"{self.what!r} has no identifier and says {self.held_at.strip()!r} about "
                    "where it is. A source without one is not refused -- data you collected "
                    "yourself has no DOI and needs none -- but it has to say where, when and "
                    "who holds it, which is what a dash and another name mean in these tables."
                )
            if self.resolution is not None:
                raise ValueError(
                    f"{self.what!r} has no identifier and a resolution of {self.resolution}; "
                    "there was nothing to follow"
                )
            return self
        if self.resolution is Resolution.CONFIRMED:
            if not self.resolved_to.strip():
                raise ValueError(
                    f"{self.what!r} says {self.identifier} was confirmed and does not say what "
                    "came back. Naming it is the whole check: three of case 1's DOIs were "
                    "well-formed, resolvable, and pointed at the wrong submission."
                )
            if self.checked_on is None:
                raise ValueError(f"{self.what!r} was confirmed on no date; an identifier decays")
        return self


class UnresolvedIdentifier(RuntimeError):
    """An identifier was written down and nobody followed it."""


def refuse_unresolved(sources: Iterable[Source]) -> tuple[Source, ...]:
    """Raise unless every identifier has been followed and came back right."""
    checked = tuple(sources)
    unfollowed = [s for s in checked if s.identifier.strip() and s.resolution is None]
    wrong = [s for s in checked if s.resolution in (Resolution.MISMATCHED, Resolution.DEAD)]
    if unfollowed or wrong:
        lines = [f"  {s.what}: {s.identifier} was never followed" for s in unfollowed] + [
            f"  {s.what}: {s.identifier} is {s.resolution}"
            + (f" -- it returns {s.resolved_to}" if s.resolved_to.strip() else "")
            for s in wrong
        ]
        raise UnresolvedIdentifier(
            f"{len(unfollowed) + len(wrong)} of {len(checked)} identifiers do not point at the "
            "thing in hand:\n" + "\n".join(lines)
        )
    return checked
