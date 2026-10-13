"""What a library call does, as opposed to what it is called."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = [
    "Leans",
    "Behaviour",
    "UnaccountedCall",
    "refuse_assumed_behaviour",
    "refuse_unaccounted_calls",
]

#: Below this, an account of what a call does is a gesture.
_MEANINGFUL = 24

#: Ways of saying "I did not run anything".
_NOT_A_MEASUREMENT = (
    "docstring",
    "documentation",
    "the docs",
    "doc says",
    "the manual",
    "readme",
    "according to",
    "as documented",
    "the signature",
    "the tutorial",
)


class Leans(StrEnum):
    """How a run depends on the call."""

    #: The call is made and its return is used.
    RETURN = "return"
    #: A parameter is deliberately not set, so the library's default stands.
    UNSET = "unset"
    #: Two or more calls are made in an order that matters.
    ORDER = "order"


class Behaviour(StrictModel):
    """One library call, and what it was measured to do."""

    call: str = Field(min_length=1, max_length=200)
    leans: Leans
    #: What the name or the documentation implies, written out so the gap is on the
    #: record rather than in somebody's memory of being surprised.
    assumed: str = Field(min_length=1, max_length=400)
    #: What it does. Not a paraphrase of the name: the thing that was seen.
    observed: str = Field(min_length=_MEANINGFUL, max_length=600)
    #: What was run to find that out -- a probe, a test, a script, an experiment on the
    #: real array.
    probe: str = Field(min_length=1, max_length=300)
    #: What believing `assumed` would have cost here.
    costs: str = ""

    @model_validator(mode="after")
    def the_behaviour_was_run_and_not_read(self) -> "Behaviour":
        cited = [word for word in _NOT_A_MEASUREMENT if word in self.probe.lower()]
        if cited:
            raise ValueError(
                f"{self.call} says its behaviour was established by {self.probe!r}, which cites "
                f"{cited[0]!r}. A15 is five failures of reading rather than running, and in two "
                "of them the documentation was itself wrong. Name what was run."
            )
        return self


class UnaccountedCall(RuntimeError):
    """A run leans on a library call and nothing says what that call does."""


def refuse_assumed_behaviour(behaviours: Iterable[Behaviour]) -> tuple[Behaviour, ...]:
    """Raise unless every recorded behaviour was established by running something."""
    return tuple(behaviours)


def refuse_unaccounted_calls(
    leaned_on: Iterable[str], recorded: Iterable[Behaviour]
) -> tuple[Behaviour, ...]:
    """Raise unless every call the run leans on says what it actually does."""
    accounts = {item.call: item for item in recorded}
    wanted = tuple(leaned_on)
    missing = [call for call in wanted if call not in accounts]
    if missing:
        raise UnaccountedCall(
            f"{len(missing)} of {len(wanted)} calls this run leans on have no measured "
            "behaviour:\n" + "\n".join(f"  {call}" for call in missing)
        )
    return tuple(accounts[call] for call in wanted)
