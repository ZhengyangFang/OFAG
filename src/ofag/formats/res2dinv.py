"""Read a RES2DINV general-array data file."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["Survey", "read_res2dinv"]

#: What the header's array-type line means, for the types this reads.
_GENERAL_ARRAY = 11

#: The measurement-type line: 0 is an apparent resistivity, 1 a resistance.
_APPARENT_RESISTIVITY = 0
_RESISTANCE = 1

#: How the trailing topography block announces itself.
_TOPOGRAPHY_MARKER = "topography"

#: The topography format this reads: one `x,elevation` pair per line, in the same along-
#: line coordinate the electrodes use.
_TOPOGRAPHY_XZ = 2


@dataclass(frozen=True)
class Survey:
    """One RES2DINV file: the electrodes, the quadrupoles and the measurement."""

    title: str
    #: `(electrode, 2)` as x along the line and z, in the file's own metres.
    electrodes_m: np.ndarray
    #: `(measurement, 4)` of indices into `electrodes_m`, as A, B, M, N.
    quadrupoles: np.ndarray
    #: Whatever the header says this column is, unconverted.
    values: np.ndarray
    #: `"resistance"` in ohms, or `"apparent_resistivity"` in ohm-metres.
    value_kind: str
    electrode_spacing_m: float
    array_type: int
    #: What the header claimed, against what was parsed.
    declared_measurements: int
    #: `(point, 2)` of along-line x and surface elevation, or None where the file
    #: carries no topography block.
    topography_m: np.ndarray | None = None

    @property
    def resistance_ohm(self) -> np.ndarray:
        """The transfer resistance, whichever way the file wrote it."""
        if self.value_kind == "resistance":
            return self.values
        return np.asarray(self.values / self.geometric_factor, dtype=float)

    @property
    def geometric_factor(self) -> np.ndarray:
        """K for a surface array, from the file's own electrode positions."""
        a, b, m, n = (self.electrodes_m[self.quadrupoles[:, i]] for i in range(4))

        def gap(p: np.ndarray, q: np.ndarray) -> np.ndarray:
            return np.asarray(np.linalg.norm(p - q, axis=1), dtype=float)

        return 2.0 * np.pi / (1.0 / gap(a, m) - 1.0 / gap(b, m) - 1.0 / gap(a, n) + 1.0 / gap(b, n))


def read_res2dinv(path: Path, *, tolerance_m: float = 0.01) -> Survey:
    """Parse one RES2DINV general-array file."""
    lines = [line.rstrip() for line in path.read_text(errors="ignore").splitlines()]
    if len(lines) < 9:
        raise ValueError(f"{path.name} is too short to be a RES2DINV file")

    title = lines[0].strip()
    spacing = float(lines[1])
    array_type = int(float(lines[2]))
    if array_type != _GENERAL_ARRAY:
        raise ValueError(
            f"{path.name} declares array type {array_type}; this reader handles the general "
            f"array ({_GENERAL_ARRAY}), which writes each measurement's own electrode positions"
        )

    # After the general-array line comes its sub-type, then a line of prose naming the
    # measurement-type flag, then the flag itself.
    cursor = 4
    while cursor < len(lines) and not lines[cursor].strip().lstrip("-").isdigit():
        cursor += 1
    kind_flag = int(float(lines[cursor]))
    declared = int(float(lines[cursor + 1]))
    value_kind = "resistance" if kind_flag == _RESISTANCE else "apparent_resistivity"
    if kind_flag not in (_RESISTANCE, _APPARENT_RESISTIVITY):
        raise ValueError(f"{path.name} declares measurement type {kind_flag}, which is neither")

    positions: list[np.ndarray] = []
    values: list[float] = []
    for line in lines[cursor + 2 :]:
        field = line.split()
        # A data line starts with the electrode count and carries two numbers per
        # electrode plus the value.
        if len(field) < 10 or field[0] != "4":
            continue
        try:
            numbers = [float(item) for item in field[1:10]]
        except ValueError:
            continue
        positions.append(np.asarray(numbers[:8], dtype=float).reshape(4, 2))
        values.append(numbers[8])
    if not values:
        raise ValueError(f"{path.name} has no parsable measurements")

    electrodes, index = _unique_positions(np.vstack(positions), tolerance_m)
    return Survey(
        topography_m=_read_topography(lines, path),
        title=title,
        electrodes_m=electrodes,
        quadrupoles=index.reshape(-1, 4),
        values=np.asarray(values, dtype=float),
        value_kind=value_kind,
        electrode_spacing_m=spacing,
        array_type=array_type,
        declared_measurements=declared,
    )


def _unique_positions(points: np.ndarray, tolerance_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Collapse repeated electrode positions, ordered along the line."""
    rounded = np.round(points / tolerance_m).astype(np.int64)
    first = np.unique(rounded, axis=0, return_index=True)[1]
    unique = points[np.sort(first)]
    electrodes = unique[np.lexsort((unique[:, 1], unique[:, 0]))]
    lookup = {
        tuple(row): position
        for position, row in enumerate(np.round(electrodes / tolerance_m).astype(np.int64))
    }
    return electrodes, np.array([lookup[tuple(row)] for row in rounded], dtype=np.int64)


def _read_topography(lines: list[str], path: Path) -> np.ndarray | None:
    """The trailing `x,elevation` block, where the file has one."""
    marker = next(
        (index for index, line in enumerate(lines) if _TOPOGRAPHY_MARKER in line.lower()), None
    )
    if marker is None or marker + 2 >= len(lines):
        return None
    try:
        kind = int(float(lines[marker + 1]))
        count = int(float(lines[marker + 2]))
    except ValueError:
        return None
    if kind != _TOPOGRAPHY_XZ:
        raise ValueError(
            f"{path.name} declares topography format {kind}; this reader handles format "
            f"{_TOPOGRAPHY_XZ}, one x,elevation pair per line"
        )
    points = []
    for line in lines[marker + 3 : marker + 3 + count]:
        field = line.replace(",", " ").split()
        if len(field) < 2:
            break
        try:
            points.append([float(field[0]), float(field[1])])
        except ValueError:
            break
    if len(points) != count:
        raise ValueError(
            f"{path.name} declares {count} topography points and carries {len(points)}"
        )
    return np.asarray(points, dtype=float)
