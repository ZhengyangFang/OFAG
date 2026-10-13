"""Read drill core logs into the boreholes a geological model is built on."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import numpy as np
from pydantic import Field, field_validator, model_validator

from ofag.core.constants import QuantityType
from ofag.core.crs import reproject
from ofag.core.schemas import (
    Borehole,
    BoreholeInterval,
    BoreholeSurveyStation,
    CoordinateConvention,
    StratigraphicUnit,
    StrictModel,
)
from ofag.core.units import canonicalize_quantity, validate_unit_dimension
from ofag.formats.raster import sample_elevation
from ofag.formats.tables import Table, read_table
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore

#: How far an interval may run past the collar's stated total depth before the two
#: tables are called inconsistent.
_DEPTH_TOLERANCE_M = 1.0

#: What `StratigraphicUnit.name` allows, checked here so the complaint names the logged
#: value and the way out rather than a schema constraint.
_MAX_UNIT_NAME = 80

#: Topography sources read as a raster rather than as a point cloud.
_RASTER_SUFFIXES = frozenset({".tif", ".tiff", ".vrt", ".img", ".asc"})


def _is_raster(path: str | None) -> bool:
    return path is not None and Path(path).suffix.lower() in _RASTER_SUFFIXES


class DrillLogImportRequest(StrictModel):
    """Two tables and the units they are in, stated rather than inferred."""

    collars_path: str = Field(min_length=1)
    lithology_path: str = Field(min_length=1)

    #: Collar table columns.
    hole_id_column: str = Field(min_length=1)
    x_column: str = Field(min_length=1)
    y_column: str = Field(min_length=1)
    z_column: str | None = None
    total_depth_column: str = Field(min_length=1)
    azimuth_column: str | None = None
    inclination_column: str | None = None
    #: What the inclination column measures from.
    inclination_reference: (
        Literal["from_vertical", "dip_negative_down", "dip_positive_down"] | None
    ) = None

    #: Lithology table columns.
    interval_hole_id_column: str = Field(min_length=1)
    from_column: str = Field(min_length=1)
    to_column: str = Field(min_length=1)
    unit_column: str = Field(min_length=1)

    #: Units, one declaration per file.
    coordinate_unit: str | None = None
    #: The system the collar columns are in, when it is not the project's.
    source_crs: str | None = None
    #: The unit of the elevation column, declared separately because a horizontal CRS
    #: says nothing about the vertical.
    elevation_unit: str | None = None
    collar_depth_unit: str = Field(min_length=1)
    interval_depth_unit: str = Field(min_length=1)
    coordinate_convention: CoordinateConvention

    #: Where collar elevations come from when the table has none: a canonical topography
    #: CSV with x_m, y_m and z_m columns, as `import_topography_csv` writes.
    topography_path: str | None = None

    #: Logged rock name to stratigraphic unit.
    unit_map: dict[str, str] | None = None

    #: Units the project already holds.
    known_units: tuple[StratigraphicUnit, ...] = ()

    #: Rock names to leave out entirely -- overburden and talus are not units of the
    #: intrusion.
    exclude_units: tuple[str, ...] = ()

    encoding: str | None = None

    @field_validator(
        "coordinate_unit", "elevation_unit", "collar_depth_unit", "interval_depth_unit"
    )
    @classmethod
    def units_are_lengths(cls, value: str | None) -> str | None:
        if value is not None:
            validate_unit_dimension(value, QuantityType.LENGTH)
        return value

    @model_validator(mode="after")
    def coordinates_are_described_once(self) -> "DrillLogImportRequest":
        """Either a unit or a system, because a system already implies a unit."""
        if (self.coordinate_unit is None) == (self.source_crs is None):
            raise ValueError(
                "give either coordinate_unit, for collars already in the project's system, "
                "or source_crs, for collars that have to be projected into it -- not both, "
                "because a CRS already states its own unit, and not neither"
            )
        return self

    @model_validator(mode="after")
    def elevation_has_a_source(self) -> "DrillLogImportRequest":
        needs_unit = self.z_column is not None or _is_raster(self.topography_path)
        if needs_unit and self.elevation_unit is None:
            raise ValueError(
                "elevation_unit is required for an elevation column or a raster: a "
                "horizontal CRS does not state the vertical unit, and a GeoTIFF rarely "
                "states its band's"
            )
        if not needs_unit and self.elevation_unit is not None:
            raise ValueError(
                "elevation_unit has nothing to describe: a canonical topography CSV is in "
                "metres by construction, since its columns are named for them"
            )
        if self.z_column is None and self.topography_path is None:
            raise ValueError(
                "collars have no elevation column, so a topography_path is required; "
                "a collar at an unknown height places every contact in the hole at an "
                "unknown depth"
            )
        if (self.azimuth_column is None) != (self.inclination_column is None):
            raise ValueError(
                "give both azimuth_column and inclination_column, or neither; "
                "an inclination without a bearing does not say where the hole went"
            )
        if (self.inclination_column is None) != (self.inclination_reference is None):
            raise ValueError(
                "inclination_reference is required with inclination_column: "
                "measured from vertical, or from horizontal with down negative or "
                "positive, are three different angles for the same hole"
            )
        return self


@dataclass(frozen=True)
class ImportedDrillLogs:
    """The holes, the units they are logged in, and what the reader had to do."""

    dataset_id: UUID
    boreholes: tuple[Borehole, ...]
    units: tuple[StratigraphicUnit, ...]
    canonical_path: str
    collars_encoding: str | None
    lithology_encoding: str | None
    #: Every logged rock name and how many intervals carry it, before the unit map is
    #: applied.
    vocabulary: tuple[tuple[str, int], ...]
    interval_count: int
    #: Intervals dropped, and why, so a count that does not add up can be explained
    #: without re-reading the file.
    dropped: tuple[tuple[str, str], ...]
    collar_elevation_source: str

    @property
    def borehole_count(self) -> int:
        return len(self.boreholes)


class BoreholeImportService:
    """Drill core logs to `Borehole` records, in canonical SI metres."""

    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def import_drill_logs(self, request: DrillLogImportRequest) -> ImportedDrillLogs:
        collar_table = read_table(request.collars_path, encoding=request.encoding)
        interval_table = read_table(request.lithology_path, encoding=request.encoding)
        collars, intervals = list(collar_table.rows), list(interval_table.rows)
        if not collars:
            raise ValueError(f"{request.collars_path} has no collar rows")
        if not intervals:
            raise ValueError(f"{request.lithology_path} has no interval rows")

        _require_columns(collar_table.columns, _collar_columns(request), request.collars_path)
        _require_columns(interval_table.columns, _interval_columns(request), request.lithology_path)
        _agree_on_crs(collar_table, request)

        units, unit_of, vocabulary = _units_from(intervals, request)
        by_hole, dropped = _intervals_by_hole(intervals, request, unit_of)
        boreholes, collar_dropped, elevation_source = _boreholes_from(collars, request, by_hole)

        dataset_id, destination = self._store.new_dataset()
        canonical = destination / "boreholes.json"
        canonical.write_text(
            json.dumps(
                {
                    "units": [unit.model_dump(mode="json") for unit in units],
                    "boreholes": [hole.model_dump(mode="json") for hole in boreholes],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return ImportedDrillLogs(
            dataset_id=dataset_id,
            boreholes=boreholes,
            units=units,
            canonical_path=canonical.as_posix(),
            collars_encoding=collar_table.encoding,
            lithology_encoding=interval_table.encoding,
            vocabulary=vocabulary,
            interval_count=sum(len(hole.intervals) for hole in boreholes),
            dropped=tuple(dropped) + tuple(collar_dropped),
            collar_elevation_source=elevation_source,
        )


# -- reading ---------------------------------------------------------------


def _collar_columns(request: DrillLogImportRequest) -> tuple[str, ...]:
    named = [
        request.hole_id_column,
        request.x_column,
        request.y_column,
        request.total_depth_column,
    ]
    for optional in (request.z_column, request.azimuth_column, request.inclination_column):
        if optional is not None:
            named.append(optional)
    return tuple(named)


def _interval_columns(request: DrillLogImportRequest) -> tuple[str, ...]:
    return (
        request.interval_hole_id_column,
        request.from_column,
        request.to_column,
        request.unit_column,
    )


def _require_columns(present: tuple[str, ...], columns: tuple[str, ...], where: str) -> None:
    missing = sorted(set(columns) - set(present))
    if missing:
        raise ValueError(f"{where} is missing mapped columns: {', '.join(missing)}")


def _agree_on_crs(table: Table, request: DrillLogImportRequest) -> None:
    """A file that states its own system is not overruled in silence."""
    declared = request.source_crs or request.coordinate_convention.crs
    if table.crs is not None and table.crs != declared:
        raise ValueError(
            f"{request.collars_path} declares {table.crs} and the request says {declared}; "
            "they cannot both be where the collars are"
        )


# -- units -----------------------------------------------------------------


def _units_from(
    intervals: list[dict[str, str]], request: DrillLogImportRequest
) -> tuple[tuple[StratigraphicUnit, ...], dict[str, UUID], tuple[tuple[str, int], ...]]:
    counts = Counter(
        (row.get(request.unit_column) or "").strip()
        for row in intervals
        if (row.get(request.unit_column) or "").strip()
    )
    vocabulary = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    mapping = request.unit_map or {}
    names: dict[str, UUID] = {unit.name: unit.unit_id for unit in request.known_units}
    unit_of: dict[str, UUID] = {}
    for logged in counts:
        target = mapping.get(logged, logged)
        if target in request.exclude_units or logged in request.exclude_units:
            continue
        if target not in names:
            names[target] = uuid4()
        unit_of[logged] = names[target]
    _names_are_units_not_descriptions(names)
    known = {unit.name: unit for unit in request.known_units}
    units = tuple(
        known.get(name, StratigraphicUnit(unit_id=identifier, name=name, colour=_colour_for(name)))
        for name, identifier in names.items()
    )
    return units, unit_of, vocabulary


def _names_are_units_not_descriptions(names: dict[str, UUID]) -> None:
    """A logged rock name is a petrography, and sometimes it is a paragraph."""
    long = sorted(name for name in names if len(name) > _MAX_UNIT_NAME)
    if not long:
        return
    raise ValueError(
        f"{len(long)} logged rock names are longer than {_MAX_UNIT_NAME} characters and are "
        f"descriptions rather than unit names, the first being {long[0][:60]!r}; supply a "
        "unit_map that says which stratigraphic unit each belongs to"
    )


def _colour_for(name: str) -> str:
    """A colour a unit keeps across imports."""
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=3).hexdigest()
    return f"#{digest}"


# -- intervals -------------------------------------------------------------


def _intervals_by_hole(
    rows: list[dict[str, str]], request: DrillLogImportRequest, unit_of: dict[str, UUID]
) -> tuple[dict[str, list[BoreholeInterval]], list[tuple[str, str]]]:
    by_hole: dict[str, list[BoreholeInterval]] = {}
    dropped: list[tuple[str, str]] = []
    for index, row in enumerate(rows, start=2):
        hole = (row.get(request.interval_hole_id_column) or "").strip()
        logged = (row.get(request.unit_column) or "").strip()
        if not hole:
            dropped.append((f"{request.lithology_path}:{index}", "no hole identifier"))
            continue
        if logged not in unit_of:
            dropped.append((f"{request.lithology_path}:{index}", f"excluded unit {logged!r}"))
            continue
        try:
            top = float(row[request.from_column])
            base = float(row[request.to_column])
        except (TypeError, ValueError):
            dropped.append((f"{request.lithology_path}:{index}", "non-numeric depth"))
            continue
        if not (np.isfinite(top) and np.isfinite(base)) or base <= top:
            dropped.append((f"{request.lithology_path}:{index}", "interval does not descend"))
            continue
        top_m, base_m = (
            float(canonicalize_quantity(value, request.interval_depth_unit, QuantityType.LENGTH))
            for value in (top, base)
        )
        by_hole.setdefault(hole, []).append(
            BoreholeInterval(unit_id=unit_of[logged], from_depth_m=top_m, to_depth_m=base_m)
        )
    for hole in by_hole:
        by_hole[hole].sort(key=lambda item: item.from_depth_m)
    return by_hole, dropped


# -- collars ---------------------------------------------------------------


def _boreholes_from(
    rows: list[dict[str, str]],
    request: DrillLogImportRequest,
    by_hole: dict[str, list[BoreholeInterval]],
) -> tuple[tuple[Borehole, ...], list[tuple[str, str]], str]:
    """Collars to holes, in two passes."""
    parsed, dropped = _parsed_collars(rows, request)
    elevations, elevation_source = _collar_elevations(parsed, request)
    boreholes: list[Borehole] = []
    for collar, z_m in zip(parsed, elevations, strict=True):
        intervals = tuple(by_hole.get(collar.name, ()))
        deepest = max((item.to_depth_m for item in intervals), default=0.0)
        if deepest > collar.total_m + _DEPTH_TOLERANCE_M:
            raise ValueError(
                f"hole {collar.name} is logged to {deepest:.1f} m but its collar says "
                f"{collar.total_m:.1f} m; the two tables are not in the same unit"
            )
        boreholes.append(
            Borehole(
                name=collar.name,
                collar_x_m=collar.x_m,
                collar_y_m=collar.y_m,
                collar_z_m=float(z_m),
                total_depth_m=max(collar.total_m, deepest),
                vertical=collar.vertical,
                survey=collar.survey,
                intervals=intervals,
            )
        )
    return tuple(boreholes), dropped, elevation_source


@dataclass(frozen=True)
class _Collar:
    """One readable collar row, before it has an elevation."""

    name: str
    x_m: float
    y_m: float
    total_m: float
    vertical: bool
    survey: tuple[BoreholeSurveyStation, ...]
    stated_elevation: float | None


def _parsed_collars(
    rows: list[dict[str, str]], request: DrillLogImportRequest
) -> tuple[list[_Collar], list[tuple[str, str]]]:
    collars: list[_Collar] = []
    dropped: list[tuple[str, str]] = []
    for index, row in enumerate(rows, start=2):
        name = (row.get(request.hole_id_column) or "").strip()
        where = f"{request.collars_path}:{index}"
        if not name:
            dropped.append((where, "no hole identifier"))
            continue
        try:
            x = float(row[request.x_column])
            y = float(row[request.y_column])
            total = float(row[request.total_depth_column])
            stated = (
                None
                if request.z_column is None
                else float(
                    canonicalize_quantity(
                        float(row[request.z_column]),
                        str(request.elevation_unit),
                        QuantityType.LENGTH,
                    )
                )
            )
        except (TypeError, ValueError):
            dropped.append((where, "non-numeric collar or depth"))
            continue
        if total <= 0.0:
            dropped.append((where, "total depth is not positive"))
            continue
        x_m, y_m = _in_project_metres(x, y, request)
        vertical, survey = _attitude(row, request)
        collars.append(
            _Collar(
                name=name,
                x_m=x_m,
                y_m=y_m,
                total_m=float(
                    canonicalize_quantity(total, request.collar_depth_unit, QuantityType.LENGTH)
                ),
                vertical=vertical,
                survey=survey,
                stated_elevation=stated,
            )
        )
    return collars, dropped


def _collar_elevations(
    collars: list[_Collar], request: DrillLogImportRequest
) -> tuple[np.ndarray, str]:
    """Where the tops of the holes are, from whichever source was given."""
    if request.z_column is not None:
        return np.asarray([collar.stated_elevation for collar in collars], dtype=float), (
            "collar table"
        )
    assert request.topography_path is not None
    east = np.asarray([collar.x_m for collar in collars], dtype=float)
    north = np.asarray([collar.y_m for collar in collars], dtype=float)
    path = Path(request.topography_path)
    if path.suffix.lower() in _RASTER_SUFFIXES:
        assert request.elevation_unit is not None
        return (
            sample_elevation(
                path,
                east,
                north,
                crs=request.coordinate_convention.crs,
                elevation_unit=request.elevation_unit,
            ),
            f"raster {path.name}",
        )
    surface = _topography_points(path)
    return (
        np.asarray(
            [_nearest_elevation(surface, x, y) for x, y in zip(east, north, strict=True)],
            dtype=float,
        ),
        "topography surface",
    )


def _in_project_metres(x: float, y: float, request: DrillLogImportRequest) -> tuple[float, float]:
    """A collar in the project's own metres, however the file gave it."""
    if request.source_crs is not None:
        east, north = reproject(
            np.asarray([x]),
            np.asarray([y]),
            source_crs=request.source_crs,
            target_crs=request.coordinate_convention.crs,
        )
        return float(east[0]), float(north[0])
    assert request.coordinate_unit is not None
    return tuple(  # type: ignore[return-value]
        float(canonicalize_quantity(value, request.coordinate_unit, QuantityType.LENGTH))
        for value in (x, y)
    )


def _attitude(
    row: dict[str, str], request: DrillLogImportRequest
) -> tuple[bool, tuple[BoreholeSurveyStation, ...]]:
    """Vertical, or one station saying where the hole went."""
    if request.azimuth_column is None or request.inclination_column is None:
        return True, ()
    try:
        azimuth = float(row[request.azimuth_column])
        inclination = float(row[request.inclination_column])
    except (TypeError, ValueError):
        return True, ()
    from_vertical = _from_vertical(inclination, request.inclination_reference)
    if from_vertical <= 0.0:
        return True, ()
    return False, (
        BoreholeSurveyStation(
            depth_m=0.0,
            inclination_degrees=from_vertical,
            azimuth_degrees=azimuth % 360.0,
        ),
    )


def _from_vertical(value: float, reference: str | None) -> float:
    """The angle off vertical that OFAG stores, from whichever one was read."""
    if reference == "dip_negative_down":
        return 90.0 + value
    if reference == "dip_positive_down":
        return 90.0 - value
    return value


def _topography_points(path: Path) -> np.ndarray:
    if not path.is_file():
        raise ValueError(f"topography file does not exist: {path}")
    table = np.genfromtxt(path, delimiter=",", names=True)
    names = table.dtype.names
    if names is None or not {"x_m", "y_m", "z_m"} <= set(names):
        raise ValueError("topography CSV must contain x_m, y_m and z_m columns")
    surface = np.column_stack(
        [
            np.atleast_1d(np.asarray(table["x_m"], dtype=float)),
            np.atleast_1d(np.asarray(table["y_m"], dtype=float)),
            np.atleast_1d(np.asarray(table["z_m"], dtype=float)),
        ]
    )
    if not surface.size or not np.isfinite(surface).all():
        raise ValueError("topography CSV must contain finite coordinates")
    return surface


def _nearest_elevation(surface: np.ndarray, x_m: float, y_m: float) -> float:
    """The nearest sampled elevation, which is what a posted DEM offers."""
    offsets = surface[:, :2] - np.asarray([x_m, y_m])
    return float(surface[int(np.argmin(np.einsum("ij,ij->i", offsets, offsets))), 2])
