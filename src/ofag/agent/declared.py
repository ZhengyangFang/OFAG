"""A3: every acquisition parameter a file states, used or refused by name."""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = [
    "Disposition",
    "Accounted",
    "UnaccountedParameter",
    "UnreachedParameter",
    "refuse_unaccounted",
    "refuse_unreached",
]

#: Below this a reason is a gesture. The same bar the decision record uses.
_MEANINGFUL = 24


class Disposition(StrEnum):
    """What became of a parameter the file declared."""

    #: It reached the thing that needed it, and `arrives_at` says where.
    USED = "used"
    #: It was left out on purpose, and `because` says why.
    IGNORED = "ignored"


class Accounted(StrictModel):
    """One declared parameter, and what became of it."""

    parameter: str = Field(min_length=1, max_length=120)
    disposition: Disposition
    #: Where the value arrives, as a dotted path into whatever consumes it.
    arrives_at: str = ""
    #: Why it was left out. Required of an ignored one.
    because: str = ""

    @model_validator(mode="after")
    def the_disposition_carries_its_evidence(self) -> "Accounted":
        if self.disposition is Disposition.USED:
            if not self.arrives_at.strip():
                raise ValueError(
                    f"{self.parameter} is marked used and names nowhere it arrives. A parameter "
                    "read into an object and never reached by the run is F017, and it is the "
                    "case this field exists for: name the key, not the reading."
                )
            if self.because.strip():
                raise ValueError(f"{self.parameter} is used and carries a reason for being ignored")
        elif len(self.because.strip()) < _MEANINGFUL:
            raise ValueError(
                f"{self.parameter} is marked ignored and says {self.because.strip()!r}. "
                "Ignoring a declared parameter is a decision; say what makes it safe."
            )
        return self


class UnaccountedParameter(RuntimeError):
    """A file declared something and nothing said what became of it."""


class UnreachedParameter(RuntimeError):
    """A parameter was called used and its value is not where it was said to be."""


def refuse_unaccounted(
    declared: Iterable[str], accounted: Iterable[Accounted]
) -> tuple[Accounted, ...]:
    """Raise unless every declared parameter has been disposed of."""
    disposals = {item.parameter: item for item in accounted}
    names = list(declared)
    missing = [name for name in names if name not in disposals]
    if missing:
        raise UnaccountedParameter(
            "the file declares these and nothing says what became of them: "
            + ", ".join(missing)
            + ". Each is used -- naming where it arrives -- or ignored for a stated reason. "
            "One read into an object and never reached by the run is the worse case, because "
            "the pipeline looks complete."
        )
    invented = sorted(set(disposals) - set(names))
    if invented:
        raise UnaccountedParameter(
            f"these are accounted for and the file does not declare them: {invented}. An "
            "accounting that covers parameters the file has not got is one nobody compared "
            "with the file."
        )
    return tuple(disposals[name] for name in names)


def _at(destination: Mapping[str, Any], path: str) -> Any:
    """Follow a dotted path, returning None where it does not lead anywhere."""
    node: Any = destination
    for step in path.split("."):
        if not isinstance(node, Mapping) or step not in node:
            return None
        node = node[step]
    return node


def refuse_unreached(
    accounted: Iterable[Accounted], destination: Mapping[str, Any]
) -> tuple[str, ...]:
    """Raise unless every used parameter's value is where it said it would be."""
    used = [item for item in accounted if item.disposition is Disposition.USED]
    absent = [item for item in used if _at(destination, item.arrives_at) is None]
    if absent:
        raise UnreachedParameter(
            "these are marked used and their values are not where they were said to arrive: "
            + "; ".join(f"{item.parameter} at {item.arrives_at}" for item in absent)
            + ". Read, stored, and never reached by the thing that needed it is worse than "
            "never read, because the run succeeds and the number is wrong."
        )
    return tuple(item.arrives_at for item in used)
