"""Read a flown magnetic survey into observations an inversion can fit."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import Field, field_validator, model_validator

from ofag.core.constants import QuantityType
from ofag.core.crs import reproject
from ofag.core.geomagnetism import looks_like_a_total_field, to_anomaly_nt
from ofag.core.schemas import CoordinateConvention, StrictModel
from ofag.core.units import canonicalize_quantity, validate_unit_dimension
from ofag.formats.raster import sample_elevation
from ofag.formats.tables import read_table
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore


class AeromagneticImportRequest(StrictModel):
    """One flown survey, and everything the file does not state about itself."""

    source_path: str = Field(min_length=1)

    line_column: str = Field(min_length=1)
    x_column: str = Field(min_length=1)
    y_column: str = Field(min_length=1)
    total_field_column: str = Field(min_length=1)
    #: The sensor's height above the ground, which is what an altimeter reads.
    height_above_ground_column: str = Field(min_length=1)

    coordinate_unit: str | None = None
    source_crs: str | None = None
    height_unit: str = Field(min_length=1)
    total_field_unit: str = Field(min_length=1)
    coordinate_convention: CoordinateConvention

    #: The terrain the sensor's height is measured above.
    terrain_path: str = Field(min_length=1)
    terrain_elevation_unit: str = Field(min_length=1)

    #: When the survey was flown.
    epoch: datetime

    #: Keep about one sample per this distance along each line.
    along_line_spacing_m: float | None = Field(default=None, gt=0.0)

    #: Rows carrying this in any mapped column are the file's own no-data marker.
    dummy_value: float | None = -9_999_999.0

    encoding: str | None = None

    @field_validator("coordinate_unit", "height_unit", "terrain_elevation_unit")
    @classmethod
    def lengths_are_lengths(cls, value: str | None) -> str | None:
        if value is not None:
            validate_unit_dimension(value, QuantityType.LENGTH)
        return value

    @field_validator("total_field_unit")
    @classmethod
    def the_field_is_a_flux_density(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.MAGNETIC_FLUX_DENSITY)
        return value

    @model_validator(mode="after")
    def coordinates_are_described_once(self) -> "AeromagneticImportRequest":
        if (self.coordinate_unit is None) == (self.source_crs is None):
            raise ValueError(
                "give either coordinate_unit, for a survey already in the project's system, "
                "or source_crs, for one that has to be projected into it -- not both, "
                "because a CRS already states its own unit, and not neither"
            )
        return self


@dataclass(frozen=True)
class ImportedAeromagneticSurvey:
    """Canonical observations, and every judgement made reaching them."""

    dataset_id: UUID
    source_filename: str
    canonical_observations_path: str
    coordinate_convention: CoordinateConvention
    line_count: int
    #: Readings in the file, kept after thinning, and dropped as no-data.
    readings_in_file: int
    observation_count: int
    dropped_as_dummy: int
    #: True when the column really was a total field, which is the common case and the
    #: one a reader has to be told about.
    reduced_from_total_field: bool
    reference_field_median_nt: float
    anomaly_min_nt: float
    anomaly_max_nt: float
    anomaly_median_nt: float
    #: The along-line spacing asked for and what was achieved, because a line sampled
    #: more coarsely than the target cannot be thinned to it.
    along_line_spacing_m: float | None
    median_along_line_spacing_m: float
    sensor_height_median_m: float
    terrain_filename: str
    bounds_m: tuple[float, float, float, float, float, float]


class AeromagneticImportService:
    """A flown survey to canonical anomaly observations in project metres."""

    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def import_survey(self, request: AeromagneticImportRequest) -> ImportedAeromagneticSurvey:
        table = read_table(request.source_path, encoding=request.encoding)
        columns = (
            request.line_column,
            request.x_column,
            request.y_column,
            request.total_field_column,
            request.height_above_ground_column,
        )
        missing = sorted(set(columns) - set(table.columns))
        if missing:
            raise ValueError(
                f"{request.source_path} is missing mapped columns: {', '.join(missing)}"
            )

        line, x, y, field, height = _numeric_columns(table.rows, columns, request.source_path)
        keep = _not_dummy(request.dummy_value, x, y, field, height)
        dropped = int((~keep).sum())
        line, x, y, field, height = (values[keep] for values in (line, x, y, field, height))
        if not x.size:
            raise ValueError(f"{request.source_path} has no readings left after no-data removal")

        east, north = _in_project_metres(x, y, request)
        selected = _thin_along_lines(line, east, north, request.along_line_spacing_m)
        line, east, north, field, height = (
            values[selected] for values in (line, east, north, field, height)
        )

        terrain = sample_elevation(
            request.terrain_path,
            east,
            north,
            crs=request.coordinate_convention.crs,
            elevation_unit=request.terrain_elevation_unit,
        )
        sensor_height = np.asarray(
            canonicalize_quantity(height, request.height_unit, QuantityType.LENGTH), dtype=float
        )
        elevation = terrain + sensor_height

        was_total = looks_like_a_total_field(
            np.asarray(
                canonicalize_quantity(
                    field, request.total_field_unit, QuantityType.MAGNETIC_FLUX_DENSITY
                ),
                dtype=float,
            )
            * 1e9
        )
        if was_total:
            anomaly = to_anomaly_nt(
                field,
                east,
                north,
                elevation,
                crs=request.coordinate_convention.crs,
                epoch=request.epoch,
                total_field_unit=request.total_field_unit,
            )
            reference = (
                np.asarray(
                    canonicalize_quantity(
                        field, request.total_field_unit, QuantityType.MAGNETIC_FLUX_DENSITY
                    ),
                    dtype=float,
                )
                * 1e9
                - anomaly
            )
        else:
            anomaly = (
                np.asarray(
                    canonicalize_quantity(
                        field, request.total_field_unit, QuantityType.MAGNETIC_FLUX_DENSITY
                    ),
                    dtype=float,
                )
                * 1e9
            )
            reference = np.zeros_like(anomaly)

        dataset_id, destination = self._store.new_dataset()
        observations = destination / "magnetic_observations.csv"
        np.savetxt(
            observations,
            np.c_[east, north, elevation, anomaly],
            delimiter=",",
            header="x_m,y_m,z_m,tmi_nt",
            comments="",
            fmt="%.6f",
        )
        return ImportedAeromagneticSurvey(
            dataset_id=dataset_id,
            source_filename=Path(request.source_path).name,
            canonical_observations_path=observations.as_posix(),
            coordinate_convention=request.coordinate_convention,
            line_count=int(np.unique(line).size),
            readings_in_file=len(table),
            observation_count=int(east.size),
            dropped_as_dummy=dropped,
            reduced_from_total_field=bool(was_total),
            reference_field_median_nt=float(np.median(reference)),
            anomaly_min_nt=float(anomaly.min()),
            anomaly_max_nt=float(anomaly.max()),
            anomaly_median_nt=float(np.median(anomaly)),
            along_line_spacing_m=request.along_line_spacing_m,
            median_along_line_spacing_m=_median_spacing(line, east, north),
            sensor_height_median_m=float(np.median(sensor_height)),
            terrain_filename=Path(request.terrain_path).name,
            bounds_m=(
                float(east.min()),
                float(east.max()),
                float(north.min()),
                float(north.max()),
                float(elevation.min()),
                float(elevation.max()),
            ),
        )


def _numeric_columns(
    rows: tuple[dict[str, str], ...], columns: tuple[str, ...], where: str
) -> tuple[np.ndarray, ...]:
    try:
        return tuple(
            np.asarray([float(row[column]) for row in rows], dtype=float) for column in columns
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{where} has a non-numeric value in a mapped column: {error}") from error


def _not_dummy(dummy: float | None, *columns: np.ndarray) -> np.ndarray:
    keep = np.ones(columns[0].shape, dtype=bool)
    for values in columns:
        keep &= np.isfinite(values)
        if dummy is not None:
            keep &= values != dummy
    return keep


def _in_project_metres(
    x: np.ndarray, y: np.ndarray, request: AeromagneticImportRequest
) -> tuple[np.ndarray, np.ndarray]:
    if request.source_crs is not None:
        return reproject(
            x, y, source_crs=request.source_crs, target_crs=request.coordinate_convention.crs
        )
    assert request.coordinate_unit is not None
    return tuple(  # type: ignore[return-value]
        np.asarray(
            canonicalize_quantity(values, request.coordinate_unit, QuantityType.LENGTH),
            dtype=float,
        )
        for values in (x, y)
    )


def _thin_along_lines(
    line: np.ndarray, east: np.ndarray, north: np.ndarray, spacing_m: float | None
) -> np.ndarray:
    """Indices keeping about one reading per `spacing_m` within each line."""
    if spacing_m is None:
        return np.arange(east.size)
    kept: list[int] = []
    for identifier in np.unique(line):
        indices = np.flatnonzero(line == identifier)
        last_east, last_north = east[indices[0]], north[indices[0]]
        kept.append(int(indices[0]))
        for index in indices[1:]:
            if np.hypot(east[index] - last_east, north[index] - last_north) >= spacing_m:
                kept.append(int(index))
                last_east, last_north = east[index], north[index]
    return np.asarray(sorted(kept), dtype=int)


def _median_spacing(line: np.ndarray, east: np.ndarray, north: np.ndarray) -> float:
    """What the along-line sampling actually came out as."""
    gaps: list[float] = []
    for identifier in np.unique(line):
        indices = np.flatnonzero(line == identifier)
        if indices.size < 2:
            continue
        gaps.extend(np.hypot(np.diff(east[indices]), np.diff(north[indices])).tolist())
    return float(np.median(gaps)) if gaps else 0.0
