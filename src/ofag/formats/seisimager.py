"""Read a SeisImager/2D first-arrival pick file."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["FirstArrivals", "read_first_arrivals"]

#: Traveltimes are written in milliseconds; OFAG stores seconds.
_MILLISECONDS = 1.0e-3

#: How close two traveltimes must be to count as the same arrival, in seconds.
_TIE_S = 1.0e-9

#: Two lines before the first shot block: a format marker, then a line whose second and
#: third fields are the shot count and the geophone spacing.
_HEADER_LINES = 2


@dataclass(frozen=True)
class FirstArrivals:
    """One pick file: every trace, still carrying the shot it belongs to."""

    #: `(pick,)` along-line position of the shot, in metres.
    shot_x_m: np.ndarray
    #: `(pick,)` along-line position of the receiver, in metres.
    receiver_x_m: np.ndarray
    #: `(pick,)` first-arrival time, in seconds.
    traveltime_s: np.ndarray
    geophone_spacing_m: float
    #: What the header claimed, against the blocks actually parsed.
    declared_shots: int
    parsed_shots: int

    @property
    def offset_m(self) -> np.ndarray:
        """Source-receiver distance along the line."""
        return np.asarray(np.abs(self.receiver_x_m - self.shot_x_m), dtype=float)

    @property
    def apparent_velocity_m_s(self) -> np.ndarray:
        """Offset over traveltime, which is the crudest thing worth plotting."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(self.offset_m / self.traveltime_s, dtype=float)

    @property
    def repeated_traveltimes(self) -> dict[float, int]:
        """Exact traveltime values carried by more than one pick, and how many."""
        values, counts = np.unique(self.traveltime_s, return_counts=True)
        return {float(v): int(c) for v, c in zip(values, counts, strict=True) if c > 1}

    @property
    def earliest_arrival_offset_m(self) -> dict[float, float]:
        """Per shot, how far from it the earliest arrival in its gather sits."""
        result: dict[float, float] = {}
        for source in np.unique(self.shot_x_m):
            gather = self.shot_x_m == source
            times = self.traveltime_s[gather]
            tied = times <= times.min() + _TIE_S
            result[float(source)] = float(np.abs(self.receiver_x_m[gather][tied] - source).min())
        return result

    def reciprocal_pairs(self, *, tolerance_m: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        """Index pairs whose shot and receiver are each other's, swapped."""
        left: list[int] = []
        right: list[int] = []
        for i in range(self.traveltime_s.size):
            for j in range(i + 1, self.traveltime_s.size):
                if (
                    abs(self.shot_x_m[i] - self.receiver_x_m[j]) <= tolerance_m
                    and abs(self.receiver_x_m[i] - self.shot_x_m[j]) <= tolerance_m
                    and abs(self.shot_x_m[i] - self.receiver_x_m[i]) > tolerance_m
                ):
                    left.append(i)
                    right.append(j)
        return np.asarray(left, dtype=np.int64), np.asarray(right, dtype=np.int64)


def read_first_arrivals(path: Path) -> FirstArrivals:
    """Parse one SeisImager/2D pick file into SI units."""
    lines = [line.strip() for line in path.read_text(errors="ignore").splitlines()]
    if len(lines) <= _HEADER_LINES:
        raise ValueError(f"{path.name} is too short to be a pick file")

    header = lines[1].split()
    if len(header) < 3:
        raise ValueError(f"{path.name} has no shot count and geophone spacing on its second line")
    declared_shots = int(float(header[1]))
    spacing = float(header[2])

    shot_x: list[float] = []
    receiver_x: list[float] = []
    traveltime: list[float] = []
    parsed_shots = 0
    cursor = _HEADER_LINES
    while cursor < len(lines):
        block = lines[cursor].split()
        if len(block) != 3:
            break
        try:
            source, traces = float(block[0]), int(float(block[1]))
        except ValueError:
            break
        # The trailer is three short lines of zeros, and a zero-trace block is how it
        # starts.
        if traces <= 0 or cursor + traces >= len(lines):
            break
        for line in lines[cursor + 1 : cursor + 1 + traces]:
            field = line.split()
            if len(field) < 2:
                raise ValueError(f"{path.name}: a trace line carries fewer than two numbers")
            receiver_x.append(float(field[0]))
            traveltime.append(float(field[1]) * _MILLISECONDS)
            shot_x.append(source)
        parsed_shots += 1
        cursor += 1 + traces

    if not traveltime:
        raise ValueError(f"{path.name} has no parsable shot gathers")
    return FirstArrivals(
        shot_x_m=np.asarray(shot_x, dtype=float),
        receiver_x_m=np.asarray(receiver_x, dtype=float),
        traveltime_s=np.asarray(traveltime, dtype=float),
        geophone_spacing_m=spacing,
        declared_shots=declared_shots,
        parsed_shots=parsed_shots,
    )
