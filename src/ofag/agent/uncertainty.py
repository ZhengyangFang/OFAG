"""A4: what an error bar is made of, carried as two things and not one."""

import math
from dataclasses import dataclass

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = [
    "Budget",
    "Implied",
    "RepeatabilityAlone",
    "refuse_repeatability_alone",
    "what_the_misfit_implies",
]

#: Below this a provenance is a gesture. The same bar the decision record uses.
_MEANINGFUL = 24

#: Phrases that mean the tolerance came from the model it will be used to judge.
_CIRCULAR = ("misfit", "chi-squared", "chi squared", "residual", "rms of the fit")


class Budget(StrictModel):
    """What a datum's error bar is made of, in the datum's own unit."""

    quantity: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)

    #: How well the instrument reproduces itself.
    repeatability: float = Field(gt=0)
    repeatability_from: str = Field(min_length=_MEANINGFUL, max_length=300)

    #: What a model of this ground can be expected to achieve, which is a different
    #: quantity and usually the larger.
    model_error: float = Field(ge=0)
    model_error_from: str = Field(min_length=_MEANINGFUL, max_length=300)

    @model_validator(mode="after")
    def the_model_error_is_not_read_off_the_model(self) -> "Budget":
        said = self.model_error_from.lower()
        found = [phrase for phrase in _CIRCULAR if phrase in said]
        if found:
            raise ValueError(
                f"{self.quantity}'s model error is attributed to {found[0]!r}. A tolerance "
                "taken from the misfit of the model it will be used to judge closes the loop "
                "and makes every model fit (A5). Take it from the physics, from a second "
                "method over the same ground, or from what the published work achieved."
            )
        return self

    @property
    def sigma(self) -> float:
        """The two in quadrature, which is what a chi-squared divides by."""
        return math.hypot(self.repeatability, self.model_error)

    @property
    def dominated_by(self) -> str:
        return "the instrument" if self.repeatability >= self.model_error else "the model"

    @property
    def summary(self) -> str:
        return (
            f"{self.quantity}: repeatability {self.repeatability:.4g} {self.unit} "
            f"({self.repeatability_from}), model error {self.model_error:.4g} {self.unit} "
            f"({self.model_error_from}); sigma {self.sigma:.4g}, dominated by "
            f"{self.dominated_by}"
        )


class RepeatabilityAlone(RuntimeError):
    """A chi-squared was to be taken against how well the instrument repeats."""


def refuse_repeatability_alone(budget: Budget) -> Budget:
    """Raise unless the budget has a model error worth the name."""
    if budget.model_error > 0:
        return budget
    raise RepeatabilityAlone(
        f"{budget.quantity}'s model error is zero, so a chi-squared against this budget is a "
        f"chi-squared against {budget.repeatability:.4g} {budget.unit} of instrument "
        "repeatability. Fifty repeats of a transient gate give 0.17 per cent and the first "
        "inversion divided by it reported 143,838, with nothing wrong but the denominator. "
        "Say what a model of this ground can achieve, or argue for the zero: "
        f"{budget.model_error_from}"
    )


@dataclass(frozen=True)
class Implied:
    """What a misfit says about the denominator it was taken against."""

    chi_squared: float
    budget: Budget
    #: The model error that would bring the misfit to one. Diagnostic.
    model_error: float

    @property
    def times_the_stated(self) -> float:
        """How far the implied value is from what was declared."""
        return (
            math.inf if self.budget.model_error == 0 else self.model_error / self.budget.model_error
        )

    @property
    def verdict(self) -> str:
        if self.chi_squared <= 1.0:
            return (
                f"chi-squared {self.chi_squared:.3g} is at or under one, which is a question "
                "about the denominator from the other side: an error bar this generous cannot "
                "be contradicted"
            )
        ratio = self.times_the_stated
        end = (
            "the denominator: the stated model error is too small by that much, and a residual "
            "this size is what an unmodelled part of the ground looks like"
            if ratio > 3.0
            else "the numerator: the stated model error is the right order, so the misfit is "
            "about the model rather than about the bar it is held to"
        )
        return (
            f"chi-squared {self.chi_squared:.3g} implies a model error of "
            f"{self.model_error:.4g} {self.budget.unit}, {ratio:.3g} times the "
            f"{self.budget.model_error:.4g} stated. The first question is about {end}"
        )


def what_the_misfit_implies(chi_squared: float, budget: Budget) -> Implied:
    """A4's "say which end", as a number and a sentence."""
    if chi_squared <= 0:
        raise ValueError(f"a chi-squared is positive; got {chi_squared}")
    inflation = max(chi_squared - 1.0, 0.0)
    return Implied(
        chi_squared=chi_squared,
        budget=budget,
        model_error=budget.repeatability * math.sqrt(inflation),
    )
