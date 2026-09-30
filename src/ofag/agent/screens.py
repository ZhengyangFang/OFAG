"""An index used as a filter, against the thing it claims to filter for."""

import math
from collections.abc import Iterable

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = [
    "Screen",
    "UnpredictiveScreen",
    "refuse_unpredictive",
]

#: How many standard errors an association has to clear to be read as one.
_SIGMAS = 2.0

#: Below four samples a rank correlation has no standard error at all.
_ENOUGH_TO_HAVE_AN_ERROR = 4


class Screen(StrictModel):
    """An index used to admit or reject, and what it was measured to predict."""

    what: str = Field(min_length=1, max_length=200)
    #: The outcome it claims to predict, in the terms it will be judged in.
    filters_for: str = Field(min_length=1, max_length=200)
    #: Rank correlation with that outcome.
    association: float = Field(ge=-1.0, le=1.0)
    #: The sample it was measured on.
    n: int = Field(ge=_ENOUGH_TO_HAVE_AN_ERROR)
    measured_on: str = Field(min_length=1, max_length=300)
    #: A nuisance that could reach this index, named.
    contaminated_by: str = ""
    #: How the index is known to be invariant to that nuisance.
    invariant_because: str = ""

    @property
    def standard_error(self) -> float:
        """Of a rank correlation, near enough for this purpose."""
        return 1.0 / math.sqrt(self.n - 3)

    @property
    def distinguishable_from_zero(self) -> bool:
        return abs(self.association) > _SIGMAS * self.standard_error

    @model_validator(mode="after")
    def a_named_nuisance_is_answered(self) -> "Screen":
        if self.contaminated_by.strip() and not self.invariant_because.strip():
            raise ValueError(
                f"{self.what} names {self.contaminated_by.strip()!r} as something that could "
                "reach it and does not say why it cannot. The admissibility index was multiplied "
                "by galvanic distortion and screened topsoil for a year (F022); say what makes "
                "this one invariant, or move the screen onto a quantity that is."
            )
        return self


class UnpredictiveScreen(RuntimeError):
    """An index is being used as a filter and does not predict what it filters for."""


def refuse_unpredictive(screens: Iterable[Screen]) -> tuple[Screen, ...]:
    """Raise unless every screen's association is visible above its own noise."""
    checked = tuple(screens)
    absent = [s for s in checked if not s.distinguishable_from_zero]
    if absent:
        lines = [
            f"  {s.what}: r = {s.association:+.3f} against {s.filters_for}, on n = {s.n}, "
            f"where one standard error is {s.standard_error:.3f}"
            for s in absent
        ]
        raise UnpredictiveScreen(
            f"{len(absent)} of {len(checked)} screens do not predict what they filter for:\n"
            + "\n".join(lines)
            + "\nAn index theoretically related to a failure is not one that correlates with "
            "it, and a cutoff tuned on the first is tuning on nothing."
        )
    return checked
