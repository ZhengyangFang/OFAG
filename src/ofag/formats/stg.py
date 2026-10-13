"""Read an AGI SuperSting `.stg` file."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["Survey", "read_stg"]

#: Column positions in a data record, from the format's own documentation.
_RESISTANCE = 4
_ERROR_TENTHS_OF_PERCENT = 5
_CURRENT_MA = 6
_APPARENT_RESISTIVITY = 7
_ELECTRODE_X = (9, 12, 15, 18)  # A, B, M, N; y and z follow each

#: The shortest a data record can be and still carry all four electrodes.
_MINIMUM_FIELDS = 21


@dataclass(frozen=True)
class Survey:
    """One `.stg` file: the electrodes, the quadrupoles and the measurement."""

    #: `(electrode, 3)` in the file's own coordinates, ordered along the line.
    electrodes_m: np.ndarray
    #: `(measurement, 4)` of indices into `electrodes_m`, as A, B, M, N.
    quadrupoles: np.ndarray
    #: V/I in ohms.
    resistance_ohm: np.ndarray
    #: The instrument's own error estimate, converted from tenths of a percent.
    error_percent: np.ndarray
    current_ma: np.ndarray
    #: What the instrument reduced each reading to.
    apparent_resistivity_ohm_m: np.ndarray
    #: Records the file declared against records this reader could parse.
    declared_records: int | None
    unparsed_records: int

    @property
    def spacing_m(self) -> float:
        """The median gap between neighbouring electrodes."""
        along = np.sort(self.electrodes_m[:, 0])
        return float(np.median(np.diff(along))) if along.size > 1 else 0.0


def read_stg(path: Path, *, tolerance_m: float = 0.01) -> Survey:
    """Parse one SuperSting file."""
    lines = path.read_text(errors="ignore").splitlines()
    if len(lines) < 4:
        raise ValueError(f"{path.name} has no data records")
    declared = _declared_records(lines[1])

    positions: list[np.ndarray] = []
    rows: list[tuple[float, float, float, float]] = []
    unparsed = 0
    for line in lines[3:]:
        if not line.strip():
            continue
        field = line.split(",")
        if len(field) < _MINIMUM_FIELDS:
            unparsed += 1
            continue
        try:
            rows.append(
                (
                    float(field[_RESISTANCE]),
                    float(field[_ERROR_TENTHS_OF_PERCENT]) / 10.0,
                    float(field[_CURRENT_MA]),
                    float(field[_APPARENT_RESISTIVITY]),
                )
            )
            positions.append(
                np.array([[float(field[i + k]) for k in range(3)] for i in _ELECTRODE_X])
            )
        except ValueError:
            unparsed += 1
            if rows and len(rows) > len(positions):
                rows.pop()
    if not rows:
        raise ValueError(f"{path.name} has no parsable data records")

    stacked = np.vstack(positions)
    electrodes, index = _unique_positions(stacked, tolerance_m)
    values = np.asarray(rows, dtype=float)
    return Survey(
        electrodes_m=electrodes,
        quadrupoles=index.reshape(-1, 4),
        resistance_ohm=values[:, 0],
        error_percent=values[:, 1],
        current_ma=values[:, 2],
        apparent_resistivity_ohm_m=values[:, 3],
        declared_records=declared,
        unparsed_records=unparsed,
    )


def _declared_records(line: str) -> int | None:
    """How many records the second header line says the file holds."""
    marker = "Records:"
    if marker not in line:
        return None
    tail = line.split(marker, 1)[1].strip().split()
    try:
        return int(tail[0])
    except (IndexError, ValueError):
        return None


def _unique_positions(points: np.ndarray, tolerance_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Collapse repeated electrode coordinates, ordered along the line."""
    rounded = np.round(points / tolerance_m).astype(np.int64)
    first = np.unique(rounded, axis=0, return_index=True)[1]
    unique = points[np.sort(first)]
    order = np.lexsort((unique[:, 2], unique[:, 1], unique[:, 0]))
    electrodes = unique[order]

    # `inverse` indexes np.unique's own sorted order; remap it to ours.
    lookup = {
        tuple(row): position
        for position, row in enumerate(np.round(electrodes / tolerance_m).astype(np.int64))
    }
    index = np.array([lookup[tuple(row)] for row in rounded], dtype=np.int64)
    return electrodes, index
