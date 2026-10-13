"""Checks that stand between a number and a claim about the ground."""

from collections.abc import Mapping

import numpy as np
from pydantic import Field

from ofag.agent.diagnosis import Diagnosis
from ofag.core.schemas import StrictModel

__all__ = [
    "UnfittedRun",
    "UnmeasuredReach",
    "UnmeasuredTerrain",
    "Terrain",
    "unfitted",
    "refuse_unfitted",
    "refuse_unstated_reach",
    "measure_terrain",
    "refuse_unmeasured_terrain",
]


class UnfittedRun(RuntimeError):
    """A model was to be built on a run that missed its bar, unexplained."""


def unfitted(
    misfits: Mapping[str, float | None],
    bars: Mapping[str, float],
    diagnoses: Mapping[str, Diagnosis] = {},
) -> tuple[str, ...]:
    """Which runs missed their bar with no diagnosis behind them."""
    # Checked at runtime and not only in the annotation, because this is a gate: one
    # that took `{"ERT1": ""}` for a diagnosis would be a gate with a hole in it, and
    # the hole would be in the one place built to refuse.
    wrong = sorted(n for n, d in diagnoses.items() if not isinstance(d, Diagnosis))
    if wrong:
        raise TypeError(
            f"a diagnosis is a Diagnosis, not a sentence: {wrong} are something else. "
            "Where the misfit sits, what was ruled out and by what measurement, what is left."
        )
    missed = []
    for name, misfit in misfits.items():
        bar = bars.get(name)
        if bar is None or misfit is None:
            continue
        if misfit > bar and name not in diagnoses:
            missed.append(f"{name} at chi squared {misfit:.3f} against a bar of {bar:.0f}")
    return tuple(missed)


def refuse_unfitted(
    misfits: Mapping[str, float | None],
    bars: Mapping[str, float],
    diagnoses: Mapping[str, Diagnosis] = {},
) -> tuple[str, ...]:
    """Raise unless every run that missed its bar has been diagnosed."""
    missed = unfitted(misfits, bars, diagnoses)
    if missed:
        raise UnfittedRun(
            "these runs are read into a model and did not fit: "
            + "; ".join(missed)
            + ". Diagnose each -- where the misfit sits, what was ruled out and by what "
            "measurement, what is left -- or leave it out. A misfit that nothing "
            "acknowledges is a claim about the ground that nothing stands behind."
        )
    return tuple(name for name in misfits if name in diagnoses)


class UnmeasuredReach(RuntimeError):
    """A section was read into a model without saying how deep it resolved."""


def refuse_unstated_reach(reach: Mapping[str, tuple[float, str]]) -> tuple[str, ...]:
    """Raise unless every section says how deep it resolved and how it knows."""
    unstated = sorted(name for name, (_, how) in reach.items() if not (how or "").strip())
    if unstated:
        raise UnmeasuredReach(
            "these sections are read into a model without saying how deep they resolved: "
            + ", ".join(unstated)
            + ". Say where the depth came from -- a coverage array, a ray count, or a person."
        )
    return tuple(name for name, (_, how) in sorted(reach.items()) if "measur" not in how.lower())


class UnmeasuredTerrain(RuntimeError):
    """A geometry was to be built on ground nobody measured."""


#: Below this a terrain is a staircase, and what it mostly carries is the contour
#: interval it was read off.
ENOUGH_STEPS_TO_BE_TERRAIN = 10

#: Two elevations closer than this are the same elevation.
_SAME_ELEVATION_M = 1e-3


class Terrain(StrictModel):
    """What is known about the ground under one line, grid or model volume."""

    #: What the ground is under: a profile, a model footprint.
    name: str = Field(min_length=1, max_length=120)
    #: Where the elevations came from.
    source: str = Field(min_length=8, max_length=200)
    relief_m: float = Field(ge=0)
    #: The step the elevations are quantised to, or zero if they are not.
    quantum_m: float = Field(ge=0)
    count: int = Field(gt=0)
    distinct: int = Field(gt=0)
    #: Values that are not on the quantum, where there is one.
    off_the_grid: int = Field(ge=0)

    @property
    def steps(self) -> float:
        """How many quanta of relief there are: the terrain's own resolution."""
        return float("inf") if self.quantum_m == 0 else self.relief_m / self.quantum_m

    @property
    def modellable(self) -> bool:
        return self.steps >= ENOUGH_STEPS_TO_BE_TERRAIN

    @property
    def summary(self) -> str:
        quantum = "continuous" if self.quantum_m == 0 else f"quantised to {self.quantum_m:.4f} m"
        stray = f", {self.off_the_grid} off it" if self.off_the_grid else ""
        steps = "" if self.quantum_m == 0 else f", {self.steps:.0f} steps of relief"
        return (
            f"{self.name}: {self.relief_m:.2f} m of relief over {self.count} points, "
            f"{self.distinct} distinct, {quantum}{stray}{steps} -- {self.source}"
        )


#: The share of elevations that must sit on a candidate grid before the grid is called
#: the series' quantum.
_MOSTLY_ON_THE_GRID = 0.9


def _quantum(elevations: np.ndarray) -> float:
    """The step a series of elevations is quantised to, or zero if none."""
    values = np.unique(np.asarray(elevations, dtype=float))
    gaps = np.diff(values)
    gaps = gaps[gaps > _SAME_ELEVATION_M]
    if gaps.size == 0:
        return 0.0
    candidate = float(np.median(gaps))
    off = np.abs(values - values.min() - candidate * np.round((values - values.min()) / candidate))
    on_the_grid = float(np.mean(off <= _SAME_ELEVATION_M))
    return candidate if on_the_grid >= _MOSTLY_ON_THE_GRID else 0.0


def measure_terrain(name: str, elevations: np.ndarray, *, source: str) -> Terrain:
    """A12's two numbers, measured rather than asserted."""
    values = np.asarray(elevations, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"{name}: no finite elevation to measure")
    quantum = _quantum(values)
    if quantum == 0.0:
        stray = 0
    else:
        base = values.min()
        off = np.abs(values - base - quantum * np.round((values - base) / quantum))
        stray = int((off > _SAME_ELEVATION_M).sum())
    return Terrain(
        name=name,
        source=source,
        relief_m=float(np.ptp(values)),
        quantum_m=quantum,
        count=int(values.size),
        distinct=int(np.unique(np.round(values / _SAME_ELEVATION_M)).size),
        off_the_grid=stray,
    )


def refuse_unmeasured_terrain(ground: Mapping[str, Terrain | None]) -> tuple[str, ...]:
    """Raise unless the ground under every geometry has been measured."""
    unmeasured = sorted(name for name, terrain in ground.items() if terrain is None)
    if unmeasured:
        raise UnmeasuredTerrain(
            "the ground under these has not been measured: "
            + ", ".join(unmeasured)
            + ". Two numbers before any geometry, flat or not: the relief over the footprint, "
            "and the step the elevations are quantised to. Flat is an answer; silence is not."
        )
    return tuple(
        name
        for name, terrain in sorted(ground.items())
        if terrain is not None and not terrain.modellable
    )
