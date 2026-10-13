"""What a first-arrival file holds that is not a traveltime."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "GATHER_TOLERANCE_M",
    "REPEATS_ARE_A_DEFAULT",
    "Unsound",
    "UnsoundPicks",
    "inspect_picks",
    "refuse_unsound_picks",
]

#: How far a gather's earliest arrival may sit from its own shot, in metres.
GATHER_TOLERANCE_M = 8.0

#: Above this many identical traveltimes, the value is a default.
REPEATS_ARE_A_DEFAULT = 2


@dataclass(frozen=True)
class Unsound:
    """What a pick file holds that is not a measurement, and where."""

    #: Shot position to how far its earliest arrival sits from it.
    misplaced: Mapping[float, float]
    #: Traveltime to how many times it occurs, past coincidence.
    defaults: Mapping[float, int]
    zero_offset: int
    total: int
    gather_tolerance_m: float = field(default=GATHER_TOLERANCE_M)

    @property
    def sound(self) -> bool:
        """Whether the file holds anything that is not a measurement."""
        return not self.misplaced and not self.defaults

    @property
    def summary(self) -> str:
        parts = []
        for shot, distance in sorted(self.misplaced.items()):
            parts.append(
                f"the gather labelled x = {shot:.0f} m has its earliest arrival "
                f"{distance:.0f} m away, so it is not that shot's gather"
            )
        for value, count in sorted(self.defaults.items()):
            parts.append(f"{1e3 * value:.3f} ms occurs {count} times, which is a default")
        if self.zero_offset:
            parts.append(
                f"{self.zero_offset} picks are at zero offset, where the ray has no length"
            )
        if not parts:
            return f"all {self.total} picks are sound"
        return "; ".join(parts)


class UnsoundPicks(RuntimeError):
    """Picks that are not measurements were about to be inverted."""


def inspect_picks(arrivals: Any, *, gather_tolerance_m: float = GATHER_TOLERANCE_M) -> Unsound:
    """Read a pick file's three detectors without judging the keep-mask."""
    return Unsound(
        misplaced={
            shot: distance
            for shot, distance in arrivals.earliest_arrival_offset_m.items()
            if distance > gather_tolerance_m
        },
        defaults={
            value: count
            for value, count in arrivals.repeated_traveltimes.items()
            if count > REPEATS_ARE_A_DEFAULT
        },
        zero_offset=int((arrivals.offset_m == 0).sum()),
        total=int(arrivals.traveltime_s.size),
        gather_tolerance_m=gather_tolerance_m,
    )


def refuse_unsound_picks(
    arrivals: Any,
    keep: np.ndarray,
    *,
    gather_tolerance_m: float = GATHER_TOLERANCE_M,
) -> Unsound:
    """Raise unless the picks a caller means to invert are all measurements."""
    found = inspect_picks(arrivals, gather_tolerance_m=gather_tolerance_m)
    mask = np.asarray(keep, dtype=bool)
    if mask.shape != arrivals.traveltime_s.shape:
        raise ValueError(
            f"the keep mask has {mask.size} entries and the file has "
            f"{arrivals.traveltime_s.size} picks"
        )

    still: list[str] = []
    for shot in found.misplaced:
        if bool((mask & (arrivals.shot_x_m == shot)).any()):
            still.append(f"picks from the gather labelled x = {shot:.0f} m")
    for value in found.defaults:
        if bool((mask & np.isclose(arrivals.traveltime_s, value, atol=1e-9)).any()):
            still.append(f"picks reading {1e3 * value:.3f} ms, which is the picker's default")
    if bool((mask & (arrivals.offset_m == 0)).any()):
        still.append("picks at zero offset, whose ray has no length")

    if still:
        raise UnsoundPicks(
            "these would be inverted and are not measurements: "
            + "; ".join(still)
            + ". The reader surfaces all three and the file is not at fault for holding them; "
            "what is refused is handing them to an inversion, which will fit them."
        )
    return found
