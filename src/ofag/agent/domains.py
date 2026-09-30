"""A1: what the ground puts a quantity between, checked before any statistic."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ofag.core.constants import QuantityType

__all__ = [
    "Domain",
    "Extremes",
    "OutOfDomain",
    "DOMAINS",
    "domain_for",
    "inspect",
    "refuse_out_of_domain",
]


@dataclass(frozen=True)
class Domain:
    """What the ground puts a quantity between, in SI."""

    what: str
    unit: str
    low: float
    high: float
    because: str
    #: A separate bound on the median, where the column can be wholly plausible and the
    #: wrong quantity.
    median: tuple[float, float] | None = None


#: The quantities a bound can be defended for, in the SI units OFAG stores.
DOMAINS: dict[QuantityType, Domain] = {
    QuantityType.RESISTIVITY: Domain(
        what="resistivity",
        unit="ohm.m",
        low=1e-3,
        high=1e8,
        because="massive sulphide is about a milliohm-metre and dry halite reaches 1e8; "
        "seawater sits at 0.2 and dry granite at 1e5",
    ),
    QuantityType.APPARENT_RESISTIVITY: Domain(
        what="apparent resistivity",
        unit="ohm.m",
        low=1e-3,
        high=1e8,
        because="an apparent resistivity is a weighted average of real ones and cannot "
        "leave their range; 5e12 is the impedance chain missing mu-nought",
    ),
    QuantityType.CONDUCTIVITY: Domain(
        what="conductivity",
        unit="S/m",
        low=1e-8,
        high=1e3,
        because="the reciprocal of the resistivity domain, and the same rocks at each end",
    ),
    QuantityType.P_WAVE_VELOCITY: Domain(
        what="P-wave velocity",
        unit="m/s",
        low=250.0,
        high=9000.0,
        because="dry unconsolidated soil above the water table is 250 to 700 and the "
        "fastest crustal rock is under 9000; below 250 is air, above is not rock",
    ),
    QuantityType.S_WAVE_VELOCITY: Domain(
        what="S-wave velocity",
        unit="m/s",
        low=50.0,
        high=5000.0,
        because="soft sediment shears at tens of metres per second and no crustal rock "
        "exceeds about 5000; a fluid carries none at all",
    ),
    QuantityType.BULK_DENSITY: Domain(
        what="bulk density",
        unit="kg/m3",
        low=800.0,
        high=6000.0,
        because="peat and dry pumice are under a thousand and massive sulphide reaches "
        "about 5000; 2670 is the granite this project reduces against",
    ),
    QuantityType.MAGNETIC_ANOMALY: Domain(
        what="magnetic anomaly",
        unit="T",
        low=-2e-4,
        high=2e-4,
        because="the largest crustal anomalies are a few hundred thousand nanotesla over "
        "banded iron; Stillwater's reaches 45 per cent of the main field",
        median=(-5e-6, 5e-6),
        # The median is the half that catches F058.
    ),
    QuantityType.MAGNETIC_FLUX_DENSITY: Domain(
        what="magnetic flux density",
        unit="T",
        low=2.0e-5,
        high=7.0e-5,
        because="the Earth's core field runs 22,000 nT at the magnetic equator to "
        "67,000 nT at the poles, and a total-field reading is that plus a crustal part",
    ),
    QuantityType.TRAVELTIME: Domain(
        what="traveltime",
        unit="s",
        low=0.0,
        high=30.0,
        because="a first arrival across a near-surface spread is milliseconds and a "
        "teleseism is minutes; a column in milliseconds read as seconds lands here",
    ),
}


def domain_for(quantity: QuantityType) -> Domain | None:
    """The bound for a quantity, or None where none can be defended."""
    return DOMAINS.get(quantity)


class OutOfDomain(RuntimeError):
    """A column holds something the ground does not."""


@dataclass(frozen=True)
class Extremes:
    """What a column holds, before any statistic is taken from it."""

    domain: Domain
    count: int
    low: float
    high: float
    median: float
    #: Values that are not finite.
    non_finite: int
    #: How many sit outside the domain.
    outside: int

    @property
    def inside(self) -> bool:
        return self.outside == 0 and self.median_inside

    @property
    def median_inside(self) -> bool:
        if self.domain.median is None:
            return True
        low, high = self.domain.median
        return low <= self.median <= high

    @property
    def summary(self) -> str:
        span = f"{self.low:.4g} to {self.high:.4g} {self.domain.unit}"
        note = "" if self.inside else "  <- outside what the ground holds"
        missing = f", {self.non_finite} not finite" if self.non_finite else ""
        return (
            f"{self.domain.what}: {self.count} values, {span}, median "
            f"{self.median:.4g}{missing}{note}"
        )


def inspect(domain: Domain, values: Sequence[float] | np.ndarray) -> Extremes:
    """Read a column's extremes and median without judging them."""
    array = np.asarray(values, dtype=float).ravel()
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        raise ValueError(f"{domain.what}: no finite value to inspect")
    return Extremes(
        domain=domain,
        count=int(array.size),
        low=float(finite.min()),
        high=float(finite.max()),
        median=float(np.median(finite)),
        non_finite=int(array.size - finite.size),
        outside=int(((finite < domain.low) | (finite > domain.high)).sum()),
    )


def refuse_out_of_domain(domain: Domain, values: Sequence[float] | np.ndarray) -> Extremes:
    """Raise unless a column sits where the ground puts it."""
    seen = inspect(domain, values)
    if seen.outside:
        raise OutOfDomain(
            f"{seen.outside} of {seen.count} values are outside what {domain.what} can be "
            f"({domain.low:.4g} to {domain.high:.4g} {domain.unit}): the column runs "
            f"{seen.low:.4g} to {seen.high:.4g}. {domain.because}"
        )
    if not seen.median_inside:
        assert domain.median is not None
        raise OutOfDomain(
            f"every {domain.what} is possible and the column is not one: its median is "
            f"{seen.median:.4g} {domain.unit} against a median that has to fall between "
            f"{domain.median[0]:.4g} and {domain.median[1]:.4g}. {domain.because}"
        )
    return seen
