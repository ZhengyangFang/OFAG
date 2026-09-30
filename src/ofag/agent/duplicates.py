"""A8: two copies of a quantity are a test, and never a redundancy."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "NEITHER",
    "Copies",
    "UnresolvedCopies",
    "difference",
    "refuse_unresolved",
    "second_difference_scatter",
]

#: What `took` says when a third source settled two that disagree.
NEITHER = "neither"

#: Below this a criterion is a gesture. The same bar the decision record uses.
_MEANINGFUL = 24

#: Ways of saying "the first one".
_NOT_A_CRITERION = (
    "it was first",
    "the first one",
    "arbitrary",
    "no reason",
    "either would do",
    "it does not matter",
)


@dataclass(frozen=True)
class Copies:
    """Two statements of one quantity, and what differencing them gave."""

    quantity: str
    unit: str
    first_from: str
    second_from: str
    count: int
    largest: float
    median: float
    agree_within: float
    #: True when the two hold the same values against different positions, which is a
    #: scrambled pairing rather than a disagreement about the quantity.
    same_values_reordered: bool

    @property
    def agree(self) -> bool:
        return self.largest <= self.agree_within

    @property
    def summary(self) -> str:
        verdict = "agree" if self.agree else "disagree"
        scrambled = (
            "; they hold the same values against different positions, so the pairing is "
            "what differs"
            if self.same_values_reordered
            else ""
        )
        return (
            f"{self.quantity}: {self.first_from} against {self.second_from}, {self.count} "
            f"values, largest difference {self.largest:.4g} {self.unit}, median "
            f"{self.median:.4g} -- they {verdict} within {self.agree_within:.4g}{scrambled}"
        )


def difference(
    quantity: str,
    first: Sequence[float] | np.ndarray | float,
    second: Sequence[float] | np.ndarray | float,
    *,
    unit: str,
    first_from: str,
    second_from: str,
    agree_within: float,
) -> Copies:
    """Difference two statements of one quantity, aligned by position."""
    a = np.atleast_1d(np.asarray(first, dtype=float))
    b = np.atleast_1d(np.asarray(second, dtype=float))
    if a.shape != b.shape:
        raise ValueError(
            f"{quantity}: {first_from} has {a.size} values and {second_from} has {b.size}. "
            "Two copies of different length are not aligned, and differencing them against "
            "each other measures the alignment rather than the quantity."
        )
    if agree_within < 0:
        raise ValueError(f"{quantity}: a tolerance is not negative; got {agree_within}")
    gap = np.abs(a - b)
    return Copies(
        quantity=quantity,
        unit=unit,
        first_from=first_from,
        second_from=second_from,
        count=int(a.size),
        largest=float(gap.max()),
        median=float(np.median(gap)),
        agree_within=float(agree_within),
        # Sorted against the same tolerance the pairwise comparison uses, not against
        # numpy's default.
        same_values_reordered=bool(
            a.size > 1
            and gap.max() > agree_within
            and np.allclose(np.sort(a), np.sort(b), rtol=0.0, atol=agree_within)
        ),
    )


class UnresolvedCopies(RuntimeError):
    """Two copies disagree and nothing says which was taken, or why."""


def refuse_unresolved(copies: Copies, *, took: str = "", because: str = "") -> Copies:
    """Raise unless a disagreement has been settled on a stated criterion."""
    if copies.agree:
        return copies
    if not took:
        raise UnresolvedCopies(
            f"{copies.summary}. Name which copy was taken and what decided it. A reader that "
            "quietly takes the first one it finds makes the choice invisible, and the choice "
            "is worth up to the difference above."
        )
    if took not in (copies.first_from, copies.second_from, NEITHER):
        raise ValueError(
            f"took {took!r}, which is neither {copies.first_from!r} nor "
            f"{copies.second_from!r}. Pass NEITHER where a third source settled them, and "
            "name it in the criterion."
        )
    said = because.strip()
    if len(said) < _MEANINGFUL:
        raise UnresolvedCopies(
            f"{copies.quantity}: {took} was taken and the criterion is {said!r}. Say what "
            "separates the two -- a property of the copies that one has and the other does not."
        )
    gesture = [phrase for phrase in _NOT_A_CRITERION if phrase in said.lower()]
    if gesture:
        raise UnresolvedCopies(
            f"{copies.quantity}: {took} was taken because {gesture[0]!r}, which is the choice "
            "made invisible rather than made. The scatter of the second difference separates a "
            "surveyed profile from a scrambled column by a factor of six; something like that."
        )
    return copies


def second_difference_scatter(values: Sequence[float] | np.ndarray) -> float:
    """How rough a profile is, as the standard deviation of its curvature."""
    series = np.asarray(values, dtype=float).ravel()
    if series.size < 3:
        raise ValueError("a second difference needs at least three values")
    return float(np.std(np.diff(series, n=2)))
