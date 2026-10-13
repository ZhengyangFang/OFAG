"""Pydantic contracts persisted independently of any numerical engine."""

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, TypeVar
from uuid import UUID, uuid4, uuid5

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ofag.core.constants import ProjectMethod, QuantityType
from ofag.core.crs import validate_metric_crs
from ofag.core.units import canonicalize_quantity, validate_unit_dimension

_PhysicsModelT = TypeVar("_PhysicsModelT", bound=BaseModel)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class QuantitySpec(StrictModel):
    value: float | list[float]
    quantity_type: QuantityType
    unit: str = Field(min_length=1)

    @field_validator("unit")
    @classmethod
    def unit_matches_quantity(cls, unit: str, info: ValidationInfo) -> str:
        quantity_type = info.data.get("quantity_type")
        if quantity_type is not None:
            validate_unit_dimension(unit, quantity_type)
        return unit


class CoordinateConvention(StrictModel):
    crs: str = Field(min_length=1)
    vertical_positive: Literal["up"] = "up"
    depth_positive: Literal["down"] = "down"

    @field_validator("crs")
    @classmethod
    def metric_crs_required(cls, value: str) -> str:
        validate_metric_crs(value)
        return value


class DatasetSpec(StrictModel):
    dataset_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    coordinate_convention: CoordinateConvention
    physical_quantity: QuantityType
    units: str = Field(min_length=1)

    @field_validator("units")
    @classmethod
    def data_unit_matches_quantity(cls, value: str, info: ValidationInfo) -> str:
        quantity_type = info.data.get("physical_quantity")
        if quantity_type is not None:
            validate_unit_dimension(value, quantity_type)
        return value


class ProjectCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    coordinate_convention: CoordinateConvention
    elevation_reference: str = Field(default="Local elevation datum", min_length=1, max_length=160)
    enabled_methods: tuple[ProjectMethod, ...] = Field(min_length=1)

    @field_validator("enabled_methods")
    @classmethod
    def enabled_methods_are_unique(
        cls, value: tuple[ProjectMethod, ...]
    ) -> tuple[ProjectMethod, ...]:
        if len(set(value)) != len(value):
            raise ValueError("enabled_methods must not contain duplicates")
        return value


class ProjectMethodsUpdate(StrictModel):
    enabled_methods: tuple[ProjectMethod, ...] = Field(min_length=1)

    @field_validator("enabled_methods")
    @classmethod
    def methods_are_unique(cls, value: tuple[ProjectMethod, ...]) -> tuple[ProjectMethod, ...]:
        if len(set(value)) != len(value):
            raise ValueError("enabled_methods must not contain duplicates")
        return value


class ProjectRecord(ProjectCreateRequest):
    project_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


#: A request body is a poor way to move a survey.
MAX_INLINE_CSV_CHARACTERS = 20_000_000


class CsvImportRequest(StrictModel):
    """Observations offered either inline or as a file on this machine."""

    filename: str = Field(min_length=1, max_length=255)
    csv_text: str | None = Field(default=None, min_length=1, max_length=MAX_INLINE_CSV_CHARACTERS)
    #: A path the service can open, for data too large to send inline.
    source_path: str | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> "CsvImportRequest":
        if (self.csv_text is None) == (self.source_path is None):
            raise ValueError("give either csv_text or source_path, not both and not neither")
        return self


class CsvPreviewRequest(StrictModel):
    """Ask the service what is in a CSV it can see and the browser cannot."""

    source_path: str = Field(min_length=1)
    max_rows: int = Field(default=2_000, ge=1, le=200_000)


class CsvPreview(StrictModel):
    """A CSV's header and enough of its rows to map its columns."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    #: Every data row in the file, not just the ones returned.
    total_rows: int = Field(ge=0)
    truncated: bool


class GravityCsvImportRequest(CsvImportRequest):
    """Gravity observations and their explicit column mapping."""

    x_column: str = Field(min_length=1)
    y_column: str = Field(min_length=1)
    z_column: str = Field(min_length=1)
    gravity_column: str = Field(min_length=1)
    uncertainty_column: str | None = None
    default_uncertainty_percent: float = Field(default=1.0, gt=0, le=100)
    coordinate_unit: str = Field(min_length=1)
    gravity_unit: str = Field(min_length=1)
    uncertainty_unit: str | None = None
    coordinate_convention: CoordinateConvention

    @field_validator("coordinate_unit")
    @classmethod
    def coordinates_are_lengths(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.LENGTH)
        return value

    @field_validator("gravity_unit")
    @classmethod
    def gravity_is_acceleration(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.GRAVITY_ACCELERATION)
        return value

    @model_validator(mode="after")
    def mapping_is_distinct_and_complete(self) -> "GravityCsvImportRequest":
        columns = [self.x_column, self.y_column, self.z_column, self.gravity_column]
        if self.uncertainty_column is not None:
            columns.append(self.uncertainty_column)
            if self.uncertainty_unit is None:
                raise ValueError("uncertainty_unit is required when uncertainty_column is set")
            validate_unit_dimension(self.uncertainty_unit, QuantityType.GRAVITY_ACCELERATION)
        if len(columns) != len(set(columns)):
            raise ValueError("each mapped CSV column must be distinct")
        return self


class ImportedGravityDataset(StrictModel):
    dataset_id: UUID
    source_filename: str
    canonical_observations_path: str
    coordinate_convention: CoordinateConvention
    row_count: int = Field(ge=1)
    bounds_m: tuple[float, float, float, float, float, float]
    gravity_min_mgal: float
    gravity_max_mgal: float
    recommended_uncertainty_mgal: float = Field(gt=0)


class MagneticCsvImportRequest(CsvImportRequest):
    """Total magnetic intensity observations and column mapping."""

    x_column: str = Field(min_length=1)
    y_column: str = Field(min_length=1)
    z_column: str = Field(min_length=1)
    tmi_column: str = Field(min_length=1)
    uncertainty_column: str | None = None
    default_uncertainty_percent: float = Field(default=1.0, gt=0, le=100)
    coordinate_unit: str = Field(min_length=1)
    tmi_unit: str = Field(min_length=1)
    uncertainty_unit: str | None = None
    coordinate_convention: CoordinateConvention

    @field_validator("coordinate_unit")
    @classmethod
    def coordinates_are_lengths(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.LENGTH)
        return value

    @field_validator("tmi_unit")
    @classmethod
    def tmi_is_magnetic_anomaly(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.MAGNETIC_ANOMALY)
        return value

    @model_validator(mode="after")
    def mapping_is_distinct_and_complete(self) -> "MagneticCsvImportRequest":
        columns = [self.x_column, self.y_column, self.z_column, self.tmi_column]
        if self.uncertainty_column is not None:
            columns.append(self.uncertainty_column)
            if self.uncertainty_unit is None:
                raise ValueError("uncertainty_unit is required when uncertainty_column is set")
            validate_unit_dimension(self.uncertainty_unit, QuantityType.MAGNETIC_ANOMALY)
        if len(columns) != len(set(columns)):
            raise ValueError("each mapped CSV column must be distinct")
        return self


class ImportedMagneticDataset(StrictModel):
    dataset_id: UUID
    source_filename: str
    canonical_observations_path: str
    coordinate_convention: CoordinateConvention
    row_count: int = Field(ge=1)
    bounds_m: tuple[float, float, float, float, float, float]
    tmi_min_nt: float
    tmi_max_nt: float
    recommended_uncertainty_nt: float = Field(gt=0)


class TDEMCsvImportRequest(CsvImportRequest):
    """B-field TDEM channels, for one or many soundings."""

    time_column: str = Field(min_length=1)
    response_column: str = Field(min_length=1)
    uncertainty_column: str | None = None
    default_uncertainty_percent: float = Field(default=5.0, gt=0, le=100)
    time_unit: str = Field(min_length=1)
    response_unit: str = Field(min_length=1)
    uncertainty_unit: str | None = None
    import_mode: Literal["single", "batch"] = "single"
    sounding_id_column: str | None = None
    x_column: str | None = None
    y_column: str | None = None
    z_column: str | None = None
    coordinate_unit: str | None = None
    coordinate_convention: CoordinateConvention

    @field_validator("time_unit")
    @classmethod
    def time_is_time(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.TIME)
        return value

    @field_validator("response_unit")
    @classmethod
    def response_is_magnetic_flux_density(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.MAGNETIC_FLUX_DENSITY)
        return value

    @model_validator(mode="after")
    def mapping_is_distinct_and_complete(self) -> "TDEMCsvImportRequest":
        columns = [self.time_column, self.response_column]
        if self.uncertainty_column is not None:
            columns.append(self.uncertainty_column)
            if self.uncertainty_unit is None:
                raise ValueError("uncertainty_unit is required when uncertainty_column is set")
            validate_unit_dimension(self.uncertainty_unit, QuantityType.MAGNETIC_FLUX_DENSITY)
        if self.import_mode == "batch":
            batch_columns = {
                "sounding_id_column": self.sounding_id_column,
                "x_column": self.x_column,
                "y_column": self.y_column,
                "z_column": self.z_column,
                "coordinate_unit": self.coordinate_unit,
            }
            missing = [name for name, value in batch_columns.items() if value is None]
            if missing:
                raise ValueError("batch TDEM import requires " + ", ".join(missing))
            assert self.sounding_id_column is not None
            assert self.x_column is not None
            assert self.y_column is not None
            assert self.z_column is not None
            assert self.coordinate_unit is not None
            columns.extend([self.sounding_id_column, self.x_column, self.y_column, self.z_column])
            validate_unit_dimension(self.coordinate_unit, QuantityType.LENGTH)
        if len(columns) != len(set(columns)):
            raise ValueError("each mapped CSV column must be distinct")
        return self


class ImportedTDEMSounding(StrictModel):
    sounding_id: str
    canonical_observations_path: str
    location_m: tuple[float, float, float]
    channel_count: int = Field(ge=1)
    times_s: tuple[float, ...] = Field(min_length=1)
    recommended_uncertainty_t: float = Field(gt=0)


class ImportedTDEMDataset(StrictModel):
    dataset_id: UUID
    source_filename: str
    canonical_observations_path: str
    coordinate_convention: CoordinateConvention
    row_count: int = Field(ge=1)
    times_s: tuple[float, ...] = Field(min_length=1)
    time_min_s: float = Field(gt=0)
    time_max_s: float = Field(gt=0)
    response_min_t: float
    response_max_t: float
    recommended_uncertainty_t: float = Field(gt=0)
    import_mode: Literal["single", "batch"] = "single"
    sounding_count: int = Field(default=1, ge=1)
    soundings: tuple[ImportedTDEMSounding, ...] = ()
    batch_manifest_path: str | None = None


class TopographyCsvImportRequest(CsvImportRequest):
    """Surface elevations with explicit coordinate mapping."""

    x_column: str = Field(min_length=1)
    y_column: str = Field(min_length=1)
    z_column: str = Field(min_length=1)
    coordinate_unit: str = Field(min_length=1)
    coordinate_convention: CoordinateConvention

    @field_validator("coordinate_unit")
    @classmethod
    def coordinates_are_lengths(cls, value: str) -> str:
        validate_unit_dimension(value, QuantityType.LENGTH)
        return value

    @model_validator(mode="after")
    def mapping_is_distinct(self) -> "TopographyCsvImportRequest":
        if len({self.x_column, self.y_column, self.z_column}) != 3:
            raise ValueError("each mapped CSV column must be distinct")
        return self


class ImportedTopographyDataset(StrictModel):
    dataset_id: UUID
    source_filename: str
    canonical_topography_path: str
    coordinate_convention: CoordinateConvention
    row_count: int = Field(ge=1)
    bounds_m: tuple[float, float, float, float, float, float]


class ProjectMeshAsset(StrictModel):
    """A named, reusable survey discretization stored with a project."""

    mesh_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    source_method: Literal["gravity", "magnetics"]
    mesh_kind: Literal["tensor", "tree"]
    cell_size_m: float = Field(gt=0)
    horizontal_padding_m: float = Field(ge=0)
    depth_m: float = Field(gt=0)
    topography_path: str | None = None
    topography_filename: str | None = None
    topography_point_count: int | None = Field(default=None, ge=1)
    mesh_top_elevation_m: float | None = None


class DatasetKind(StrEnum):
    """What a registered dataset is, including the inputs shared by methods."""

    GRAVITY = "gravity"
    MAGNETICS = "magnetics"
    AEM = "aem"
    MT = "mt"
    ERT = "ert"
    SEISMIC = "seismic"
    TOPOGRAPHY = "topography"


class ProjectDataset(StrictModel):
    """One imported dataset registered in a project."""

    dataset_id: UUID
    name: str = Field(min_length=1, max_length=120)
    kind: DatasetKind
    source_filename: str = Field(min_length=1)
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, JsonValue]


class PropertyClass(StrictModel):
    """One named unit of a site model, defined by a range of property values."""

    class_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    minimum: float | None = None
    maximum: float | None = None
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def bounds_are_usable(self) -> "PropertyClass":
        if self.minimum is None and self.maximum is None:
            raise ValueError(f"unit {self.name!r} must bound at least one side of its range")
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError(f"unit {self.name!r} has minimum >= maximum")
        return self

    def contains(self, value: float) -> bool:
        """Half-open on the upper bound, so adjacent units cannot both claim a value."""
        if self.minimum is not None and value < self.minimum:
            return False
        return not (self.maximum is not None and value >= self.maximum)


class ModelSource(StrictModel):
    """One inversion result contributing to a site model, and how it is read."""

    source_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    artifact_id: UUID
    #: Carried so a model still describes itself when a run has been deleted.
    physical_quantity: QuantityType
    units: str = Field(min_length=1)
    classes: tuple[PropertyClass, ...] = ()

    @field_validator("units")
    @classmethod
    def units_match_quantity(cls, value: str, info: ValidationInfo) -> str:
        quantity_type = info.data.get("physical_quantity")
        if quantity_type is not None:
            validate_unit_dimension(value, quantity_type)
        return value

    @model_validator(mode="after")
    def classes_do_not_overlap(self) -> "ModelSource":
        identifiers = [item.class_id for item in self.classes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("class_id values must be unique within a source")
        # Classification has to be single-valued: if two units claim the same
        # resistivity, which one a cell belongs to would depend on iteration order.
        ordered = sorted(
            self.classes, key=lambda item: (item.minimum is not None, item.minimum or 0.0)
        )
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if earlier.maximum is None or (
                later.minimum is not None and later.minimum < earlier.maximum
            ):
                raise ValueError(f"units {earlier.name!r} and {later.name!r} overlap")
        return self

    def classify(self, value: float) -> "PropertyClass | None":
        """The unit a value belongs to, or None where no unit claims it."""
        for item in self.classes:
            if item.contains(value):
                return item
        return None


class SiteModel(StrictModel):
    """A description of the place, assembled from the project's inversions."""

    site_model_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=2000)
    sources: tuple[ModelSource, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def sources_are_distinct(self) -> "SiteModel":
        identifiers = [item.source_id for item in self.sources]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("source_id values must be unique within a model")
        artifacts = [(item.run_id, item.artifact_id) for item in self.sources]
        if len(set(artifacts)) != len(artifacts):
            raise ValueError("a model must not read the same run artifact twice")
        return self


class StratigraphicUnit(StrictModel):
    """One rock unit in the pile, in the order it is deposited."""

    unit_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    notes: str = Field(default="", max_length=500)


class SurfacePoint(StrictModel):
    """A point the analyst says lies on the **base** of a unit."""

    point_id: UUID = Field(default_factory=uuid4)
    unit_id: UUID
    x_m: float
    y_m: float
    z_m: float
    #: Local relaxation of the interpolation constraint.
    nugget: float = Field(default=0.0, ge=0.0)


class SurfaceOrientation(StrictModel):
    """A measured or inferred attitude of a unit's basal surface."""

    orientation_id: UUID = Field(default_factory=uuid4)
    unit_id: UUID
    x_m: float
    y_m: float
    z_m: float
    dip_degrees: float = Field(ge=0.0, le=90.0)
    dip_azimuth_degrees: float = Field(ge=0.0, lt=360.0)
    #: -1 flips the younging direction, for an overturned bed.
    polarity: Literal[1, -1] = 1
    nugget: float = Field(default=0.0, ge=0.0)


class StratigraphicRelation(StrEnum):
    """How a group of units meets the ones below it."""

    ERODE = "erode"
    ONLAP = "onlap"
    FAULT = "fault"


class BoreholeInterval(StrictModel):
    """A logged depth range assigned to a unit."""

    interval_id: UUID = Field(default_factory=uuid4)
    unit_id: UUID
    #: Along-hole depth of the top of the interval, in metres from the collar.
    from_depth_m: float = Field(ge=0.0)
    to_depth_m: float = Field(gt=0.0)
    notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def the_interval_has_thickness(self) -> "BoreholeInterval":
        if self.to_depth_m <= self.from_depth_m:
            raise ValueError(
                f"an interval from {self.from_depth_m} m to {self.to_depth_m} m has no thickness; "
                "depths are measured downwards along the hole"
            )
        return self


class BoreholeSurveyStation(StrictModel):
    """One measurement of where the hole actually goes."""

    depth_m: float = Field(ge=0.0)
    inclination_degrees: float = Field(ge=0.0, le=180.0)
    azimuth_degrees: float = Field(ge=0.0, lt=360.0)


class LogKind(StrEnum):
    """What a borehole log is a log *of*, which decides what its tops mean."""

    #: A pile. Interval tops are surface points.
    STRATIGRAPHIC = "stratigraphic"
    #: Rock types, which may repeat. Interval tops are lithological changes.
    LITHOLOGICAL = "lithological"


class Borehole(StrictModel):
    """A hole, what was logged in it, and where it went."""

    borehole_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    #: The collar, in the project's own coordinates: x Easting, y Northing, z Elevation,
    #: metres.
    collar_x_m: float
    collar_y_m: float
    collar_z_m: float
    total_depth_m: float = Field(gt=0.0)
    #: Stated, never inferred from an absent survey.
    vertical: bool = True
    #: Deviation stations, when the hole was surveyed.
    survey: tuple[BoreholeSurveyStation, ...] = ()
    intervals: tuple[BoreholeInterval, ...] = ()
    #: What the log is a log of.
    log_kind: LogKind = LogKind.STRATIGRAPHIC
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def the_log_is_a_log(self) -> "Borehole":
        ordered = sorted(self.intervals, key=lambda item: item.from_depth_m)
        previous: BoreholeInterval | None = None
        for interval in ordered:
            if interval.to_depth_m > self.total_depth_m:
                raise ValueError(
                    f"an interval reaches {interval.to_depth_m} m in a hole "
                    f"{self.total_depth_m} m deep"
                )
            if previous is not None and interval.from_depth_m < previous.to_depth_m:
                raise ValueError(
                    f"intervals overlap between {interval.from_depth_m} m and "
                    f"{previous.to_depth_m} m; a depth belongs to one unit"
                )
            previous = interval
        # A unit is crossed again only when a different unit came between.
        returns: tuple[UUID, float, float] | None = None
        first_top: dict[UUID, float] = {}
        previous_unit: UUID | None = None
        for interval in ordered:
            unit = interval.unit_id
            if unit != previous_unit and unit in first_top and returns is None:
                returns = (unit, first_top[unit], interval.from_depth_m)
            first_top.setdefault(unit, interval.from_depth_m)
            previous_unit = unit
        if returns is not None and self.log_kind is LogKind.STRATIGRAPHIC:
            if "log_kind" in self.model_fields_set:
                unit, first, again = returns
                raise ValueError(
                    f"unit {unit} is logged at {first} m and again at {again} m with another "
                    "unit between; a pile crosses a unit once, so this is a lithological log "
                    "and has to say so -- read as a pile it gives the interpolation two tops "
                    "for one surface. A section repeated across a reverse fault is the one "
                    "genuine stratigraphic case this refuses, and it needs the fault modelled."
                )
            # Declared nothing, and the intervals say rock types.
            object.__setattr__(self, "log_kind", LogKind.LITHOLOGICAL)
        if self.survey:
            depths = [station.depth_m for station in self.survey]
            if depths != sorted(depths):
                raise ValueError("survey stations must be ordered by depth")
            if depths[-1] > self.total_depth_m:
                raise ValueError("a survey station is deeper than the hole")
        if self.survey and self.vertical:
            raise ValueError(
                "a hole with a deviation survey is not declared vertical; "
                "drop the flag and let the survey say where it goes"
            )
        return self

    def position_at(self, depth_m: float) -> tuple[float, float, float]:
        """Where a given along-hole depth is, in project coordinates."""
        if not self.survey:
            return (self.collar_x_m, self.collar_y_m, self.collar_z_m - depth_m)
        east, north, elevation = self.collar_x_m, self.collar_y_m, self.collar_z_m
        walked = 0.0
        stations = list(self.survey)
        if stations[0].depth_m > 0.0:
            # Above the first station the hole is taken as that station's attitude,
            # which is what a survey that starts below the collar leaves unsaid.
            stations.insert(
                0,
                BoreholeSurveyStation(
                    depth_m=0.0,
                    inclination_degrees=stations[0].inclination_degrees,
                    azimuth_degrees=stations[0].azimuth_degrees,
                ),
            )
        for start, end in zip(stations, stations[1:], strict=False):
            segment = min(end.depth_m, depth_m) - start.depth_m
            if segment <= 0.0:
                break
            east, north, elevation = _advance(start, end, segment, east, north, elevation)
            walked = start.depth_m + segment
            if walked >= depth_m:
                return (east, north, elevation)
        remaining = depth_m - walked
        if remaining > 0.0:
            last = stations[-1]
            east, north, elevation = _advance(last, last, remaining, east, north, elevation)
        return (east, north, elevation)

    def contacts(self) -> tuple[tuple[UUID, UUID, float], ...]:
        """Unit tops the log records, as (unit, along-hole depth) pairs."""
        ordered = sorted(self.intervals, key=lambda item: item.from_depth_m)
        return tuple(
            (interval.interval_id, interval.unit_id, interval.from_depth_m) for interval in ordered
        )


def _advance(
    start: BoreholeSurveyStation,
    end: BoreholeSurveyStation,
    length_m: float,
    east: float,
    north: float,
    elevation: float,
) -> tuple[float, float, float]:
    """One survey segment, walked with the average of its two attitudes."""
    import math

    inclination = math.radians(0.5 * (start.inclination_degrees + end.inclination_degrees))
    azimuth = math.radians(0.5 * (start.azimuth_degrees + end.azimuth_degrees))
    horizontal = length_m * math.sin(inclination)
    return (
        east + horizontal * math.sin(azimuth),
        north + horizontal * math.cos(azimuth),
        elevation - length_m * math.cos(inclination),
    )


class StructuralGroup(StrictModel):
    """A conformable set of units, and how the set truncates what is beneath."""

    group_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    relation: StratigraphicRelation = StratigraphicRelation.ERODE
    #: Unit ids in this group, youngest first, matching the engine's ordering.
    unit_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("unit_ids")
    @classmethod
    def units_are_distinct(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("a unit must not appear twice in one group")
        return value


class ModelExtent(StrictModel):
    """The volume the geological model is defined over, in project metres."""

    min_x_m: float
    max_x_m: float
    min_y_m: float
    max_y_m: float
    min_z_m: float
    max_z_m: float

    @model_validator(mode="after")
    def extent_is_positive(self) -> "ModelExtent":
        for low, high, axis in (
            (self.min_x_m, self.max_x_m, "x"),
            (self.min_y_m, self.max_y_m, "y"),
            (self.min_z_m, self.max_z_m, "z"),
        ):
            if not high > low:
                raise ValueError(f"the {axis} extent must be positive, got {low} to {high}")
        return self

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (
            self.min_x_m,
            self.max_x_m,
            self.min_y_m,
            self.max_y_m,
            self.min_z_m,
            self.max_z_m,
        )


class GeologicalModel(StrictModel):
    """An implicit geological model of the project's ground."""

    geological_model_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=2000)
    extent: ModelExtent
    units: tuple[StratigraphicUnit, ...] = ()
    groups: tuple[StructuralGroup, ...] = ()
    surface_points: tuple[SurfacePoint, ...] = ()
    orientations: tuple[SurfaceOrientation, ...] = ()
    #: Holes logged in this ground.
    boreholes: tuple[Borehole, ...] = ()
    #: Runs whose sections this interpretation was digitised on, for lineage.
    interpreted_from_run_ids: tuple[UUID, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def unit(self, unit_id: UUID) -> "StratigraphicUnit | None":
        for item in self.units:
            if item.unit_id == unit_id:
                return item
        return None

    def pile(self) -> tuple[UUID, ...]:
        """Unit ids from the top down, in the order the groups declare them."""
        return tuple(unit_id for group in self.groups for unit_id in group.unit_ids)

    def basement_unit_id(self) -> "UUID | None":
        """The unit under everything else, which needs no surface of its own."""
        pile = self.pile()
        return pile[-1] if pile else None

    @model_validator(mode="after")
    def references_resolve(self) -> "GeologicalModel":
        unit_ids = [item.unit_id for item in self.units]
        if len(set(unit_ids)) != len(unit_ids):
            raise ValueError("unit_id values must be unique within a model")
        known = set(unit_ids)
        placed: set[UUID] = set()
        for group in self.groups:
            for unit_id in group.unit_ids:
                if unit_id not in known:
                    raise ValueError(f"group {group.name!r} lists unknown unit {unit_id}")
                if unit_id in placed:
                    raise ValueError(f"unit {unit_id} appears in more than one group")
                placed.add(unit_id)
        for point in self.surface_points:
            if point.unit_id not in known:
                raise ValueError(f"a surface point references unknown unit {point.unit_id}")
        for hole in self.boreholes:
            for interval in hole.intervals:
                if interval.unit_id not in known:
                    raise ValueError(f"borehole {hole.name!r} logs unknown unit {interval.unit_id}")
        for orientation in self.orientations:
            if orientation.unit_id not in known:
                raise ValueError(f"an orientation references unknown unit {orientation.unit_id}")
        group_ids = [group.group_id for group in self.groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("group_id values must be unique within a model")
        return self

    def borehole_points(self) -> tuple[SurfacePoint, ...]:
        """The logged contacts, as surface points in project coordinates."""
        points: list[SurfacePoint] = []
        for hole in self.boreholes:
            if hole.log_kind is not LogKind.STRATIGRAPHIC:
                continue
            for interval_id, unit_id, depth_m in hole.contacts():
                east, north, elevation = hole.position_at(depth_m)
                points.append(
                    SurfacePoint(
                        # Keep cell IDs stable across repeated reads.
                        point_id=uuid5(interval_id, "borehole-contact"),
                        unit_id=unit_id,
                        x_m=east,
                        y_m=north,
                        z_m=elevation,
                        nugget=0.0,
                    )
                )
        return tuple(points)

    def all_surface_points(self) -> tuple[SurfacePoint, ...]:
        """Everything the interpolation is constrained by, picks and holes."""
        return self.surface_points + self.borehole_points()

    def readiness(self) -> tuple[str, ...]:
        """What still stops this model from being interpolated."""
        issues: list[str] = []
        # Said first and regardless of the rest, because it is the one line here that
        # reports a constraint the model *has* and is not using.
        lithological = [h.name for h in self.boreholes if h.log_kind is not LogKind.STRATIGRAPHIC]
        if lithological:
            issues.append(
                f"{len(lithological)} hole(s) are logged lithologically and contribute no "
                f"surface points: {', '.join(sorted(lithological))}. Their tops are rock "
                f"changes, not surfaces."
            )
        if not self.groups:
            return tuple(issues) + ("Add at least one structural group.",)
        basement = self.basement_unit_id()
        if len(self.pile()) < 2:
            issues.append("A model needs at least two units: one surface and what lies under it.")
        for group in self.groups:
            # The basement carries no surface of its own, so a group holding only the
            # basement contributes nothing to interpolate and needs no attitude either.
            interpolated = [unit_id for unit_id in group.unit_ids if unit_id != basement]
            if not interpolated:
                continue
            oriented = any(orientation.unit_id in interpolated for orientation in self.orientations)
            if not oriented:
                issues.append(f"Group {group.name!r} needs at least one orientation.")
            # Counted over picks and logged contacts together, because the interpolation
            # is given both and a unit constrained entirely by boreholes is better
            # constrained, not worse.
            available = self.all_surface_points()
            for unit_id in interpolated:
                unit = self.unit(unit_id)
                count = sum(1 for point in available if point.unit_id == unit_id)
                if count < 2 and unit is not None:
                    issues.append(
                        f"Unit {unit.name!r} has {count} surface point"
                        f"{'' if count == 1 else 's'} on its base; at least two are needed."
                    )
        return tuple(issues)


class ProjectWorkspace(StrictModel):
    """Persistent project inputs that must survive an application restart."""

    project_id: UUID
    datasets: tuple[ProjectDataset, ...] = ()
    #: Which dataset each workflow currently works on, by kind.
    active_dataset_ids: dict[DatasetKind, UUID] = Field(default_factory=dict)
    meshes: tuple[ProjectMeshAsset, ...] = ()
    #: What the project concluded about the place, built from its runs.
    models: tuple[SiteModel, ...] = ()
    #: Structural interpretations of the same ground.
    geology: tuple[GeologicalModel, ...] = ()
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def dataset(self, dataset_id: UUID) -> "ProjectDataset | None":
        for item in self.datasets:
            if item.dataset_id == dataset_id:
                return item
        return None

    def active(self, kind: DatasetKind) -> "ProjectDataset | None":
        dataset_id = self.active_dataset_ids.get(kind)
        return self.dataset(dataset_id) if dataset_id is not None else None

    def mesh(self, source_method: str) -> "ProjectMeshAsset | None":
        for item in self.meshes:
            if item.source_method == source_method:
                return item
        return None

    @model_validator(mode="after")
    def registrations_are_consistent(self) -> "ProjectWorkspace":
        identifiers = [item.dataset_id for item in self.datasets]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("dataset_id values must be unique within a project")
        known = set(identifiers)
        for kind, dataset_id in self.active_dataset_ids.items():
            if dataset_id not in known:
                raise ValueError(f"the active {kind.value} dataset {dataset_id} is not registered")
            registered = self.dataset(dataset_id)
            if registered is not None and registered.kind is not kind:
                raise ValueError(
                    f"dataset {dataset_id} is {registered.kind.value}, not {kind.value}"
                )
        model_ids = [item.site_model_id for item in self.models]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("site_model_id values must be unique within a project")
        geology_ids = [item.geological_model_id for item in self.geology]
        if len(set(geology_ids)) != len(geology_ids):
            raise ValueError("geological_model_id values must be unique within a project")
        return self

    def site_model(self, site_model_id: UUID) -> "SiteModel | None":
        for item in self.models:
            if item.site_model_id == site_model_id:
                return item
        return None

    def geological_model(self, geological_model_id: UUID) -> "GeologicalModel | None":
        for item in self.geology:
            if item.geological_model_id == geological_model_id:
                return item
        return None


class ProjectWorkspaceUpdate(StrictModel):
    datasets: tuple[ProjectDataset, ...] = ()
    active_dataset_ids: dict[DatasetKind, UUID] = Field(default_factory=dict)
    meshes: tuple[ProjectMeshAsset, ...] = ()
    models: tuple[SiteModel, ...] = ()
    geology: tuple[GeologicalModel, ...] = ()


class TensorMeshSpec(StrictModel):
    """A metric rectilinear mesh in two or three dimensions."""

    cell_size: QuantitySpec
    shape: tuple[int, int] | tuple[int, int, int]
    origin: tuple[float, float] | tuple[float, float, float]
    cell_widths: (
        tuple[QuantitySpec, QuantitySpec] | tuple[QuantitySpec, QuantitySpec, QuantitySpec] | None
    ) = None
    active_cells: int | None = Field(default=None, ge=1)

    @field_validator("cell_size")
    @classmethod
    def cell_size_is_length(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH:
            raise ValueError("cell_size must use quantity_type='length'")
        return value

    @property
    def dimension(self) -> int:
        """2 for an along-profile section, 3 for a volume."""
        return len(self.shape)

    @field_validator("shape")
    @classmethod
    def positive_shape(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(size <= 0 for size in value):
            raise ValueError("all mesh dimensions must be positive")
        return value

    @field_validator("cell_widths")
    @classmethod
    def widths_are_lengths(
        cls, value: tuple[QuantitySpec, ...] | None
    ) -> tuple[QuantitySpec, ...] | None:
        if value is not None and any(
            item.quantity_type is not QuantityType.LENGTH for item in value
        ):
            raise ValueError("cell_widths must use quantity_type='length' on every axis")
        return value

    @model_validator(mode="after")
    def axes_agree_on_dimension(self) -> "TensorMeshSpec":
        if len(self.origin) != self.dimension:
            raise ValueError(
                f"origin must have {self.dimension} components to match shape {self.shape}"
            )
        sizes = self.cell_size.value
        if isinstance(sizes, list) and len(sizes) != self.dimension:
            raise ValueError(
                f"cell_size must have {self.dimension} components to match shape {self.shape}"
            )
        if self.cell_widths is not None and len(self.cell_widths) != self.dimension:
            raise ValueError(
                f"cell_widths must have {self.dimension} axes to match shape {self.shape}"
            )
        return self

    @model_validator(mode="after")
    def widths_match_shape(self) -> "TensorMeshSpec":
        if self.cell_widths is None:
            return self
        for axis, (widths, axis_size) in enumerate(zip(self.cell_widths, self.shape, strict=True)):
            if not isinstance(widths.value, list) or len(widths.value) != axis_size:
                raise ValueError(f"cell_widths axis {axis} must contain exactly {axis_size} values")
            if any(width <= 0 for width in widths.value):
                raise ValueError(f"cell_widths axis {axis} must contain positive lengths")
        return self


class TreeMeshSpec(StrictModel):
    """A metric octree mesh built from survey or topography geometry at run time."""

    cell_size: QuantitySpec
    padding_distance: tuple[QuantitySpec, QuantitySpec, QuantitySpec]
    depth_core: QuantitySpec
    surface_padding_cells: tuple[int, ...] = (2, 1)
    receiver_padding_cells: tuple[int, ...] = (2, 1)
    diagonal_balance: bool = True
    active_cells: int | None = Field(default=None, ge=1)

    @field_validator("cell_size")
    @classmethod
    def cell_size_is_three_lengths(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH or not isinstance(value.value, list):
            raise ValueError("cell_size must contain three length values")
        if len(value.value) != 3 or any(item <= 0 for item in value.value):
            raise ValueError("cell_size must contain three positive length values")
        return value

    @field_validator("padding_distance")
    @classmethod
    def padding_is_two_lengths_per_axis(
        cls, value: tuple[QuantitySpec, QuantitySpec, QuantitySpec]
    ) -> tuple[QuantitySpec, QuantitySpec, QuantitySpec]:
        for axis, item in enumerate(value):
            if item.quantity_type is not QuantityType.LENGTH or not isinstance(item.value, list):
                raise ValueError("padding_distance must contain length pairs for every axis")
            if len(item.value) != 2 or any(width < 0 for width in item.value):
                raise ValueError(
                    f"padding_distance axis {axis} must contain two non-negative lengths"
                )
        return value

    @field_validator("depth_core")
    @classmethod
    def depth_core_is_positive_length(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.LENGTH
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("depth_core must be a positive scalar length")
        return value

    @field_validator("surface_padding_cells", "receiver_padding_cells")
    @classmethod
    def refinement_padding_is_non_negative(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or any(item < 0 for item in value):
            raise ValueError("refinement padding must contain one or more non-negative integers")
        return value


class ExecutorKind(StrEnum):
    LOCAL_PROCESS = "local_process"
    DASK = "dask"
    SLURM = "slurm"
    REMOTE = "remote"


class ExecutorSpec(StrictModel):
    kind: ExecutorKind = ExecutorKind.LOCAL_PROCESS
    max_workers: int = Field(default=1, ge=1, le=64)


class GravityRegularizationKind(StrEnum):
    L2 = "l2"
    SPARSE_IRLS = "sparse_irls"
    # Petrophysically guided: the model is pulled towards a set of declared rock classes
    # rather than towards a single reference value.
    PETROPHYSICAL = "petrophysical"


class GravityOptimizerKind(StrEnum):
    PROJECTED_GNCG = "projected_gncg"
    INEXACT_GAUSS_NEWTON = "inexact_gauss_newton"


class BetaEstimationKind(StrEnum):
    FIXED = "fixed"
    BY_EIG = "by_eig"
    MAX_DERIVATIVE = "max_derivative"


class SensitivityWeightingSpec(StrictModel):
    enabled: bool = True
    every_iteration: bool = False
    threshold_value: float = Field(default=1e-12, gt=0)
    threshold_method: Literal["amplitude", "global", "percentile"] = "amplitude"
    normalization_method: Literal["maximum", "minimum"] = "maximum"

    @model_validator(mode="after")
    def threshold_matches_method(self) -> "SensitivityWeightingSpec":
        if self.threshold_method == "amplitude" and self.threshold_value > 1:
            raise ValueError("amplitude sensitivity threshold_value must be in (0, 1]")
        if self.threshold_method == "percentile" and self.threshold_value > 100:
            raise ValueError("percentile sensitivity threshold_value must be in (0, 100]")
        return self


class GravityTilingSpec(StrictModel):
    """Controls SimPEG's TileMap-based gravity inversion workflow."""

    enabled: bool = False
    tile_count: int = Field(default=2, ge=1, le=64)
    partition_axis: Literal["x", "y"] = "x"
    sensitivity_storage: Literal["ram", "disk"] = "disk"

    @model_validator(mode="after")
    def enabled_tiling_uses_multiple_tiles(self) -> "GravityTilingSpec":
        if self.enabled and self.tile_count < 2:
            raise ValueError("enabled tiling requires tile_count of at least 2")
        return self


class GravitySimulationSpec(StrictModel):
    engine: Literal["geoana", "choclo"] = "geoana"
    n_processes: int = Field(default=1, ge=1, le=64)
    numba_parallel: bool = True
    sensitivity_dtype: Literal["float32", "float64"] = "float32"
    tiling: GravityTilingSpec = Field(default_factory=GravityTilingSpec)


class ArrayInputSpec(StrictModel):
    """A numeric array path with an explicit physical unit."""

    path: str = Field(min_length=1)
    quantity_type: QuantityType
    unit: str = Field(min_length=1)

    @field_validator("unit")
    @classmethod
    def unit_matches_quantity(cls, value: str, info: ValidationInfo) -> str:
        quantity_type = info.data.get("quantity_type")
        if quantity_type is not None:
            validate_unit_dimension(value, quantity_type)
        return value


class GravityModelSpec(StrictModel):
    initial_density_contrast: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=0.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
        )
    )
    lower_bound: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=-10.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
        )
    )
    upper_bound: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=10.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
        )
    )
    reference_model_in_smooth: bool = False
    initial_model: ArrayInputSpec | None = None
    reference_model: ArrayInputSpec | None = None

    @field_validator("initial_density_contrast", "lower_bound", "upper_bound")
    @classmethod
    def density_quantity_is_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.DENSITY_CONTRAST or isinstance(
            value.value, list
        ):
            raise ValueError("gravity model values must be scalar density_contrast quantities")
        return value

    @field_validator("initial_model", "reference_model")
    @classmethod
    def model_arrays_are_density(cls, value: ArrayInputSpec | None) -> ArrayInputSpec | None:
        if value is not None and value.quantity_type is not QuantityType.DENSITY_CONTRAST:
            raise ValueError("gravity model arrays must be density_contrast")
        return value


class PetrophysicalClassSpec(StrictModel):
    """One rock class a petrophysically guided inversion is told to expect."""

    name: str = Field(min_length=1, max_length=80)
    value: QuantitySpec
    standard_deviation: QuantitySpec
    source: str = Field(min_length=1, max_length=200)
    proportion: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def spread_is_positive_and_in_the_same_quantity(self) -> "PetrophysicalClassSpec":
        for field, spec in (("value", self.value), ("standard_deviation", self.standard_deviation)):
            if isinstance(spec.value, list):
                raise ValueError(f"petrophysical class {field} must be scalar")
        if self.standard_deviation.quantity_type is not self.value.quantity_type:
            raise ValueError(
                "petrophysical class standard_deviation must measure the same quantity "
                f"as its value, got {self.standard_deviation.quantity_type} "
                f"against {self.value.quantity_type}"
            )
        if float(self.standard_deviation.value) <= 0:  # type: ignore[arg-type]
            raise ValueError("petrophysical class standard_deviation must be positive")
        return self


class GravityRegularizationSpec(StrictModel):
    kind: GravityRegularizationKind = GravityRegularizationKind.L2
    alpha_s: float = Field(default=1.0, ge=0)
    alpha_x: float | None = Field(default=None, ge=0)
    alpha_y: float | None = Field(default=None, ge=0)
    alpha_z: float | None = Field(default=None, ge=0)
    alpha_xx: float = Field(default=0.0, ge=0)
    alpha_yy: float = Field(default=0.0, ge=0)
    alpha_zz: float = Field(default=0.0, ge=0)
    length_scale_x: float | None = Field(default=None, gt=0)
    length_scale_y: float | None = Field(default=None, gt=0)
    length_scale_z: float | None = Field(default=None, gt=0)
    norms: tuple[float, float, float, float] = (2.0, 2.0, 2.0, 2.0)
    gradient_type: Literal["total", "components"] = "total"
    irls_scaled: bool = True
    irls_threshold: float = Field(default=1e-8, gt=0)
    cell_weights: dict[str, ArrayInputSpec] = Field(default_factory=dict)
    petrophysical_classes: tuple[PetrophysicalClassSpec, ...] = ()
    # Weight on the petrophysical term, in the place `alpha_s` holds for the other
    # kinds.
    alpha_pgi: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def petrophysical_classes_accompany_the_kind_that_uses_them(
        self,
    ) -> "GravityRegularizationSpec":
        classes = self.petrophysical_classes
        if self.kind is not GravityRegularizationKind.PETROPHYSICAL:
            if classes:
                raise ValueError(
                    "petrophysical_classes apply only to 'petrophysical' regularization"
                )
            return self
        if len(classes) < 2:
            raise ValueError(
                "petrophysical regularization needs at least two rock classes; "
                "one class is a reference model, which is what 'l2' already does"
            )
        names = [item.name for item in classes]
        if len(set(names)) != len(names):
            raise ValueError("petrophysical class names must be distinct")
        quantities = {item.value.quantity_type for item in classes}
        if len(quantities) > 1:
            raise ValueError(
                "petrophysical classes must all measure the same quantity, got "
                + ", ".join(sorted(str(item) for item in quantities))
            )
        declared = [item.proportion for item in classes if item.proportion is not None]
        # All or none: a mixture in which two classes claim shares and the rest do not
        # has no reading, and silently splitting the remainder would be this framework
        # inventing a number the analyst did not state.
        if declared and len(declared) != len(classes):
            raise ValueError(
                "either every petrophysical class states a proportion or none does; "
                f"{len(declared)} of {len(classes)} state one"
            )
        if declared and abs(sum(declared) - 1.0) > 1e-6:
            raise ValueError(f"petrophysical class proportions must sum to 1, got {sum(declared)}")
        return self

    @field_validator("norms")
    @classmethod
    def sparse_norms_are_supported(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, ...]:
        if any(norm < 0 or norm > 2 for norm in value):
            raise ValueError("regularization norms must each be in [0, 2]")
        return value

    @field_validator("cell_weights")
    @classmethod
    def weights_are_dimensionless(
        cls, value: dict[str, ArrayInputSpec]
    ) -> dict[str, ArrayInputSpec]:
        if any(not key.strip() for key in value):
            raise ValueError("regularization cell weight names cannot be blank")
        if any(item.quantity_type is not QuantityType.DIMENSIONLESS for item in value.values()):
            raise ValueError("regularization cell weights must be dimensionless")
        return value


class GravityOptimizerSpec(StrictModel):
    kind: GravityOptimizerKind = GravityOptimizerKind.PROJECTED_GNCG
    max_iterations: int = Field(default=10, ge=1, le=200)
    max_line_search_iterations: int = Field(default=20, ge=1, le=200)
    cg_max_iterations: int = Field(default=20, ge=1, le=10_000)
    cg_relative_tolerance: float = Field(default=1e-3, ge=0, le=1)
    cg_absolute_tolerance: float = Field(default=1e-3, ge=0)
    tolerance_f: float = Field(default=1e-5, gt=0)
    tolerance_x: float = Field(default=1e-4, gt=0)
    tolerance_g: float = Field(default=1e-4, gt=0)
    step_active_set: bool = True
    active_set_gradient_scale: float = Field(default=0.01, gt=0)


class GravityBetaSpec(StrictModel):
    estimation: BetaEstimationKind = BetaEstimationKind.BY_EIG
    fixed_beta: float | None = Field(default=None, gt=0)
    beta0_ratio: float = Field(default=1.0, gt=0)
    n_power_iterations: int = Field(default=4, ge=1, le=100)
    cooling_factor: float = Field(default=2.0, gt=1)
    cooling_rate: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def fixed_beta_is_supplied_when_requested(self) -> "GravityBetaSpec":
        if self.estimation is BetaEstimationKind.FIXED and self.fixed_beta is None:
            raise ValueError("fixed_beta is required when beta estimation is 'fixed'")
        return self


class GravityIRLSSpec(StrictModel):
    enabled: bool = False
    cooling_factor: float = Field(default=2.0, gt=1)
    cooling_rate: int = Field(default=1, ge=1, le=100)
    chi_factor_start: float = Field(default=1.0, gt=0)
    chi_factor_target: float = Field(default=1.0, gt=0)
    threshold_cooling_factor: float = Field(default=1.2, gt=1)
    minimum_phi_model_change: float = Field(default=0.01, gt=0)
    max_iterations: int = Field(default=20, ge=1, le=200)
    misfit_tolerance: float = Field(default=0.1, gt=0)
    percentile: float = Field(default=100.0, gt=0, le=100)


class PetrophysicalDirectivesSpec(StrictModel):
    """What the inversion is allowed to do with the rock classes as it runs."""

    #: Re-point the smallness at each cell's current class mean every iteration.
    update_reference: bool = True
    #: Once the data is fit, let the class means also be the reference the smoothness
    #: measures against, so a contact between two classes stops costing what a gradient
    #: within one class costs.
    reference_in_smoothness: bool = True
    #: Let the mixture itself move towards the recovered model.
    learn_classes: bool = False


class GravityDirectivesSpec(StrictModel):
    sensitivity_weighting: SensitivityWeightingSpec = Field(
        default_factory=SensitivityWeightingSpec
    )
    update_preconditioner: bool = True
    target_chi_factor: float | None = Field(default=None, gt=0)
    save_iteration_metrics: bool = True
    irls: GravityIRLSSpec = Field(default_factory=GravityIRLSSpec)
    petrophysical: PetrophysicalDirectivesSpec = Field(default_factory=PetrophysicalDirectivesSpec)


class GravityInversionSpec(StrictModel):
    simulation: GravitySimulationSpec = Field(default_factory=GravitySimulationSpec)
    model: GravityModelSpec = Field(default_factory=GravityModelSpec)
    regularization: GravityRegularizationSpec = Field(default_factory=GravityRegularizationSpec)
    optimizer: GravityOptimizerSpec = Field(default_factory=GravityOptimizerSpec)
    beta: GravityBetaSpec = Field(default_factory=GravityBetaSpec)
    directives: GravityDirectivesSpec = Field(default_factory=GravityDirectivesSpec)

    @model_validator(mode="after")
    def sparse_regularization_requires_irls(self) -> "GravityInversionSpec":
        if (
            self.regularization.kind is GravityRegularizationKind.SPARSE_IRLS
            and not self.directives.irls.enabled
        ):
            raise ValueError("sparse_irls regularization requires directives.irls.enabled=true")
        return self


class MagneticsInducingFieldSpec(StrictModel):
    """Uniform inducing field for total-magnetic-intensity modelling."""

    amplitude: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=50_000.0,
            quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY,
            unit="nT",
        )
    )
    inclination: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=90.0, quantity_type=QuantityType.ANGLE, unit="degree"
        )
    )
    declination: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=0.0, quantity_type=QuantityType.ANGLE, unit="degree"
        )
    )

    @field_validator("amplitude")
    @classmethod
    def amplitude_is_positive_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.MAGNETIC_FLUX_DENSITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError(
                "magnetic inducing-field amplitude must be positive scalar flux density"
            )
        return value

    @field_validator("inclination", "declination")
    @classmethod
    def direction_is_scalar_angle(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.ANGLE or isinstance(value.value, list):
            raise ValueError("magnetic inducing-field direction must be a scalar angle")
        return value


class MagneticsModelSpec(StrictModel):
    """Scalar induced susceptibility model and optional active-cell arrays."""

    initial_susceptibility: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=1e-4, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )
    )
    lower_bound: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=0.0, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )
    )
    upper_bound: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=1.0, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )
    )
    reference_model_in_smooth: bool = False
    initial_model: ArrayInputSpec | None = None
    reference_model: ArrayInputSpec | None = None

    @field_validator("initial_susceptibility", "lower_bound", "upper_bound")
    @classmethod
    def susceptibility_is_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.SUSCEPTIBILITY or isinstance(value.value, list):
            raise ValueError("magnetic model values must be scalar susceptibility quantities")
        return value

    @field_validator("initial_model", "reference_model")
    @classmethod
    def model_arrays_are_susceptibility(cls, value: ArrayInputSpec | None) -> ArrayInputSpec | None:
        if value is not None and value.quantity_type is not QuantityType.SUSCEPTIBILITY:
            raise ValueError("magnetic model arrays must be susceptibility")
        return value


class MagneticsInversionSpec(StrictModel):
    """TMI scalar-susceptibility inversion controls backed by SimPEG."""

    inducing_field: MagneticsInducingFieldSpec = Field(default_factory=MagneticsInducingFieldSpec)
    simulation: GravitySimulationSpec = Field(default_factory=GravitySimulationSpec)
    model: MagneticsModelSpec = Field(default_factory=MagneticsModelSpec)
    regularization: GravityRegularizationSpec = Field(default_factory=GravityRegularizationSpec)
    optimizer: GravityOptimizerSpec = Field(default_factory=GravityOptimizerSpec)
    beta: GravityBetaSpec = Field(default_factory=GravityBetaSpec)
    directives: GravityDirectivesSpec = Field(default_factory=GravityDirectivesSpec)

    @model_validator(mode="after")
    def supported_magnetics_controls_are_consistent(self) -> "MagneticsInversionSpec":
        if self.simulation.tiling.enabled:
            raise ValueError("TMI magnetics inversion does not yet support tiling")
        if (
            self.regularization.kind is GravityRegularizationKind.SPARSE_IRLS
            and not self.directives.irls.enabled
        ):
            raise ValueError("sparse_irls regularization requires directives.irls.enabled=true")
        lower = canonicalize_quantity(
            self.model.lower_bound.value,
            self.model.lower_bound.unit,
            QuantityType.SUSCEPTIBILITY,
        )
        upper = canonicalize_quantity(
            self.model.upper_bound.value,
            self.model.upper_bound.unit,
            QuantityType.SUSCEPTIBILITY,
        )
        assert isinstance(lower, float)
        assert isinstance(upper, float)
        if lower >= upper:
            raise ValueError("magnetic model lower_bound must be smaller than upper_bound")
        return self


class DataChannelSpec(StrictModel):
    """One observation set a run inverts, with its own quantity, unit and errors."""

    channel_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    # Stable link to the project register.
    source_dataset_id: UUID | None = None
    dataset: DatasetSpec
    observations_path: str = Field(min_length=1)
    data_uncertainty: QuantitySpec

    @model_validator(mode="after")
    def uncertainty_matches_observations(self) -> "DataChannelSpec":
        if self.data_uncertainty.quantity_type is not self.dataset.physical_quantity:
            raise ValueError(
                f"channel {self.channel_id!r} declares "
                f"{self.dataset.physical_quantity.value} observations but "
                f"{self.data_uncertainty.quantity_type.value} uncertainty"
            )
        return self


class JointGravityPropertySpec(StrictModel):
    """Gravity-only controls within a shared gravimetry/magnetics solve."""

    simulation: GravitySimulationSpec = Field(default_factory=GravitySimulationSpec)
    model: GravityModelSpec = Field(default_factory=GravityModelSpec)
    regularization: GravityRegularizationSpec = Field(default_factory=GravityRegularizationSpec)


class JointMagneticsPropertySpec(StrictModel):
    """TMI-only controls within a shared gravimetry/magnetics solve."""

    inducing_field: MagneticsInducingFieldSpec = Field(default_factory=MagneticsInducingFieldSpec)
    simulation: GravitySimulationSpec = Field(default_factory=GravitySimulationSpec)
    model: MagneticsModelSpec = Field(default_factory=MagneticsModelSpec)
    regularization: GravityRegularizationSpec = Field(default_factory=GravityRegularizationSpec)


class JointPetrophysicalClassSpec(StrictModel):
    """One rock, stated in both properties a joint inversion recovers."""

    name: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=200)
    proportion: float | None = Field(default=None, gt=0, lt=1)
    density_contrast: QuantitySpec
    density_standard_deviation: QuantitySpec
    susceptibility: QuantitySpec
    susceptibility_standard_deviation: QuantitySpec

    @model_validator(mode="after")
    def properties_are_scalar_positive_and_the_right_quantity(
        self,
    ) -> "JointPetrophysicalClassSpec":
        expected = (
            ("density_contrast", self.density_contrast, QuantityType.DENSITY_CONTRAST, False),
            (
                "density_standard_deviation",
                self.density_standard_deviation,
                QuantityType.DENSITY_CONTRAST,
                True,
            ),
            ("susceptibility", self.susceptibility, QuantityType.SUSCEPTIBILITY, False),
            (
                "susceptibility_standard_deviation",
                self.susceptibility_standard_deviation,
                QuantityType.SUSCEPTIBILITY,
                True,
            ),
        )
        for field, spec, quantity, positive in expected:
            if isinstance(spec.value, list):
                raise ValueError(f"joint petrophysical class {field} must be scalar")
            if spec.quantity_type is not quantity:
                raise ValueError(
                    f"joint petrophysical class {field} must be a {quantity}, got "
                    f"{spec.quantity_type}"
                )
            if positive and float(spec.value) <= 0:
                raise ValueError(f"joint petrophysical class {field} must be positive")
        return self


class JointPetrophysicalSpec(StrictModel):
    """The rocks a joint gravity/magnetics inversion is told to expect."""

    classes: tuple[JointPetrophysicalClassSpec, ...] = ()
    alpha_pgi: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def the_mixture_is_usable(self) -> "JointPetrophysicalSpec":
        if len(self.classes) < 2:
            raise ValueError(
                "joint petrophysical regularization needs at least two rock classes; "
                "one class is a reference model"
            )
        names = [item.name for item in self.classes]
        if len(set(names)) != len(names):
            raise ValueError("joint petrophysical class names must be distinct")
        declared = [item.proportion for item in self.classes if item.proportion is not None]
        if declared and len(declared) != len(self.classes):
            raise ValueError(
                "either every joint petrophysical class states a proportion or none does; "
                f"{len(declared)} of {len(self.classes)} state one"
            )
        if declared and abs(sum(declared) - 1.0) > 1e-6:
            raise ValueError(
                f"joint petrophysical class proportions must sum to 1, got {sum(declared)}"
            )
        return self


class CrossGradientCouplingSpec(StrictModel):
    """Dimensionless-property scales and weight for SimPEG cross-gradient coupling."""

    weight: float = Field(default=1.0, ge=0)
    density_scale: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=0.1, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
        )
    )
    susceptibility_scale: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=0.01, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )
    )
    normalize_models: bool = True
    approximate_hessian: bool = True

    @field_validator("density_scale")
    @classmethod
    def density_scale_is_positive_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.DENSITY_CONTRAST
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError(
                "cross-gradient density_scale must be positive scalar density_contrast"
            )
        return value

    @field_validator("susceptibility_scale")
    @classmethod
    def susceptibility_scale_is_positive_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.SUSCEPTIBILITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError(
                "cross-gradient susceptibility_scale must be positive scalar susceptibility"
            )
        return value


class GravMagJointInversionSpec(StrictModel):
    """One shared-mesh SimPEG gravity/TMI inversion with cross-gradient coupling."""

    # Channel ids resolved against `RunSpec.datasets`.
    gravity_channel: str = "gravity"
    magnetics_channel: str = "tmi"
    gravity: JointGravityPropertySpec = Field(default_factory=JointGravityPropertySpec)
    magnetics: JointMagneticsPropertySpec = Field(default_factory=JointMagneticsPropertySpec)
    coupling: CrossGradientCouplingSpec = Field(default_factory=CrossGradientCouplingSpec)
    #: Rocks spanning both properties.
    petrophysical: JointPetrophysicalSpec | None = None
    optimizer: GravityOptimizerSpec = Field(default_factory=GravityOptimizerSpec)
    beta: GravityBetaSpec = Field(default_factory=GravityBetaSpec)
    directives: GravityDirectivesSpec = Field(default_factory=GravityDirectivesSpec)
    directive_strategy: Literal["standard", "simpeg_cross_gradient_tutorial"] = "standard"
    topography_path: str | None = None

    @model_validator(mode="after")
    def shared_mesh_controls_are_consistent(self) -> "GravMagJointInversionSpec":
        # Per-channel quantity and uncertainty agreement is now a DataChannelSpec
        # invariant, and one shared coordinate convention is a RunSpec one.
        if self.gravity_channel == self.magnetics_channel:
            raise ValueError("gravity_channel and magnetics_channel must differ")
        if self.gravity.simulation.tiling.enabled or self.magnetics.simulation.tiling.enabled:
            raise ValueError("joint gravity/magnetics inversion does not yet support tiling")
        if any(
            regularization.kind is GravityRegularizationKind.SPARSE_IRLS
            for regularization in (self.gravity.regularization, self.magnetics.regularization)
        ):
            raise ValueError(
                "joint gravity/magnetics inversion currently supports l2 regularization"
            )
        # There are two places a joint inversion could be told about rocks and only one
        # of them means anything.
        if any(
            regularization.kind is GravityRegularizationKind.PETROPHYSICAL
            for regularization in (self.gravity.regularization, self.magnetics.regularization)
        ):
            raise ValueError(
                "set petrophysical classes on the joint spec rather than on one property: "
                "a joint mixture spans density and susceptibility together, and a class "
                "declared for one property alone is not a rock"
            )
        # Two couplings, one question.
        if self.petrophysical is not None and self.coupling.weight > 0:
            raise ValueError(
                "a joint petrophysical inversion couples through the rock classes, so "
                "coupling.weight must be 0; set it to zero to use the mixture, or drop "
                "`petrophysical` to use cross-gradient coupling instead"
            )
        return self


class LayeredEarthSpec(StrictModel):
    """One-dimensional earth discretization, ordered from surface downward."""

    layer_thicknesses: QuantitySpec

    @field_validator("layer_thicknesses")
    @classmethod
    def layer_thicknesses_are_positive_lengths(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH or not isinstance(value.value, list):
            raise ValueError("layer_thicknesses must be a list of length values")
        if not value.value or any(thickness <= 0 for thickness in value.value):
            raise ValueError("layer_thicknesses must contain positive values")
        return value


class TDEMSystemSpec(StrictModel):
    """Explicit circular-loop TDEM system geometry and time channels in SI."""

    times: QuantitySpec
    source_location: QuantitySpec
    receiver_location: QuantitySpec
    source_radius: QuantitySpec
    source_current: QuantitySpec
    source_turns: int = Field(default=1, ge=1, le=1_000)
    source_orientation: Literal["x", "y", "z"] = "z"
    receiver_orientation: Literal["x", "y", "z"] = "z"
    receiver_quantity: Literal["magnetic_flux_density", "magnetic_flux_density_time_derivative"] = (
        "magnetic_flux_density"
    )
    waveform: Literal["step_off", "piecewise_linear"] = "step_off"
    waveform_times: QuantitySpec | None = None
    waveform_current_fractions: tuple[float, ...] | None = None
    source_locations: ArrayInputSpec | None = None
    receiver_locations: ArrayInputSpec | None = None
    source_kind: Literal["circular_loop", "magnetic_dipole"] = "circular_loop"
    source_moment: QuantitySpec | None = None
    time_gates: tuple["TDEMTimeGateSpec", ...] = ()

    @field_validator("times")
    @classmethod
    def times_are_increasing_positive_seconds(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.TIME or not isinstance(value.value, list):
            raise ValueError("times must be a list of time values")
        if any(time <= 0 for time in value.value):
            raise ValueError("times must contain positive values")
        if any(right <= left for left, right in zip(value.value, value.value[1:], strict=False)):
            raise ValueError("times must be strictly increasing")
        return value

    @field_validator("source_location", "receiver_location")
    @classmethod
    def locations_are_three_lengths(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH or not isinstance(value.value, list):
            raise ValueError("system locations must contain three length values")
        if len(value.value) != 3:
            raise ValueError("system locations must contain exactly three values")
        return value

    @field_validator("source_radius")
    @classmethod
    def source_radius_is_positive_length(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.LENGTH
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("source_radius must be a positive scalar length")
        return value

    @field_validator("source_current")
    @classmethod
    def source_current_is_scalar_current(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.ELECTRIC_CURRENT
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("source_current must be a positive scalar electric_current")
        return value

    @field_validator("source_locations", "receiver_locations")
    @classmethod
    def survey_locations_are_length_arrays(
        cls, value: ArrayInputSpec | None
    ) -> ArrayInputSpec | None:
        if value is not None and value.quantity_type is not QuantityType.LENGTH:
            raise ValueError("survey location arrays must have quantity_type='length'")
        return value

    @field_validator("source_moment")
    @classmethod
    def source_moment_is_positive(cls, value: QuantitySpec | None) -> QuantitySpec | None:
        if value is None:
            return value
        if (
            value.quantity_type is not QuantityType.MAGNETIC_DIPOLE_MOMENT
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("source_moment must be a positive scalar magnetic_dipole_moment")
        return value

    @field_validator("waveform_times")
    @classmethod
    def waveform_times_are_increasing_seconds(
        cls, value: QuantitySpec | None
    ) -> QuantitySpec | None:
        if value is None:
            return value
        if value.quantity_type is not QuantityType.TIME or not isinstance(value.value, list):
            raise ValueError("waveform_times must be a list of time values")
        if len(value.value) < 2 or any(
            right <= left for left, right in zip(value.value, value.value[1:], strict=False)
        ):
            raise ValueError("waveform_times must contain at least two strictly increasing values")
        return value

    @model_validator(mode="after")
    def waveform_configuration_is_complete(self) -> "TDEMSystemSpec":
        if self.waveform == "step_off":
            if self.waveform_times is not None or self.waveform_current_fractions is not None:
                raise ValueError("step_off waveform does not accept waveform_times or fractions")
            return self
        if self.waveform_times is None or self.waveform_current_fractions is None:
            raise ValueError("piecewise_linear waveform requires waveform_times and fractions")
        assert isinstance(self.waveform_times.value, list)
        if len(self.waveform_times.value) != len(self.waveform_current_fractions):
            raise ValueError("waveform_times and waveform_current_fractions must have equal length")
        if not all(
            float("-inf") < value < float("inf") for value in self.waveform_current_fractions
        ):
            raise ValueError("waveform_current_fractions must contain finite values")
        return self

    @model_validator(mode="after")
    def survey_configuration_is_complete(self) -> "TDEMSystemSpec":
        assert isinstance(self.times.value, list)
        if not self.times.value and not self.time_gates:
            raise ValueError("provide one or more receiver times or time_gates")
        if (self.source_locations is None) != (self.receiver_locations is None):
            raise ValueError("source_locations and receiver_locations must be supplied together")
        if self.source_kind == "magnetic_dipole" and self.source_moment is None:
            raise ValueError("magnetic_dipole source_kind requires source_moment")
        return self


class TDEMTimeGateSpec(StrictModel):
    """A rectangular receiver gate evaluated by numerical integration in 3D TDEM."""

    start: QuantitySpec
    end: QuantitySpec
    integration_points: int = Field(default=5, ge=3, le=64)

    @field_validator("start", "end")
    @classmethod
    def gate_edges_are_positive_scalar_times(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.TIME
            or isinstance(value.value, list)
            or value.value < 0
        ):
            raise ValueError("gate edges must be non-negative scalar times")
        return value

    @model_validator(mode="after")
    def gate_has_positive_width(self) -> "TDEMTimeGateSpec":
        start = canonicalize_quantity(self.start.value, self.start.unit, QuantityType.TIME)
        end = canonicalize_quantity(self.end.value, self.end.unit, QuantityType.TIME)
        if float(end) <= float(start):
            raise ValueError("gate end must be later than gate start")
        return self


class TDEMModelSpec(StrictModel):
    initial_conductivity: QuantitySpec
    lower_bound: QuantitySpec
    upper_bound: QuantitySpec
    reference_conductivity: QuantitySpec | None = None
    reference_model_in_smooth: bool = False

    @field_validator("initial_conductivity", "lower_bound", "upper_bound", "reference_conductivity")
    @classmethod
    def conductivity_is_positive_scalar(cls, value: QuantitySpec | None) -> QuantitySpec | None:
        if value is None:
            return value
        if (
            value.quantity_type is not QuantityType.CONDUCTIVITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("TDEM conductivity values must be positive scalar conductivity")
        return value


class TDEMRegularizationSpec(StrictModel):
    alpha_s: float = Field(default=1.0, ge=0)
    alpha_z: float | None = Field(default=None, ge=0)


class TDEMOptimizerSpec(StrictModel):
    max_iterations: int = Field(default=10, ge=1, le=200)
    max_line_search_iterations: int = Field(default=20, ge=1, le=200)
    cg_max_iterations: int = Field(default=20, ge=1, le=10_000)
    cg_relative_tolerance: float = Field(default=1e-3, ge=0, le=1)
    cg_absolute_tolerance: float = Field(default=1e-3, ge=0)
    tolerance_f: float = Field(default=1e-5, gt=0)
    tolerance_x: float = Field(default=1e-4, gt=0)
    tolerance_g: float = Field(default=1e-4, gt=0)


class TDEMBetaSpec(StrictModel):
    estimation: Literal["by_eig", "fixed"] = "by_eig"
    fixed_beta: float | None = Field(default=None, gt=0)
    beta0_ratio: float = Field(default=1.0, gt=0)
    n_power_iterations: int = Field(default=4, ge=1, le=100)
    cooling_factor: float = Field(default=2.0, gt=1)
    cooling_rate: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def fixed_beta_is_supplied_when_requested(self) -> "TDEMBetaSpec":
        if self.estimation == "fixed" and self.fixed_beta is None:
            raise ValueError("fixed_beta is required when beta estimation is 'fixed'")
        return self


class TDEMDirectivesSpec(StrictModel):
    target_chi_factor: float | None = Field(default=None, gt=0)
    save_iteration_metrics: bool = True


class TDEMInversionSpec(StrictModel):
    system: TDEMSystemSpec
    earth: LayeredEarthSpec
    model: TDEMModelSpec
    regularization: TDEMRegularizationSpec = Field(default_factory=TDEMRegularizationSpec)
    optimizer: TDEMOptimizerSpec = Field(default_factory=TDEMOptimizerSpec)
    beta: TDEMBetaSpec = Field(default_factory=TDEMBetaSpec)
    directives: TDEMDirectivesSpec = Field(default_factory=TDEMDirectivesSpec)

    @model_validator(mode="after")
    def model_bounds_are_ordered(self) -> "TDEMInversionSpec":
        assert isinstance(self.system.times.value, list)
        if (
            not self.system.times.value
            or self.system.time_gates
            or self.system.source_locations is not None
            or self.system.source_kind != "circular_loop"
        ):
            raise ValueError(
                "TDEM 1D inversion supports one circular-loop sounding with time channels"
            )
        assert not isinstance(self.model.lower_bound.value, list)
        assert not isinstance(self.model.upper_bound.value, list)
        lower_bound = canonicalize_quantity(
            self.model.lower_bound.value,
            self.model.lower_bound.unit,
            QuantityType.CONDUCTIVITY,
        )
        upper_bound = canonicalize_quantity(
            self.model.upper_bound.value,
            self.model.upper_bound.unit,
            QuantityType.CONDUCTIVITY,
        )
        assert isinstance(lower_bound, float)
        assert isinstance(upper_bound, float)
        if lower_bound >= upper_bound:
            raise ValueError("TDEM lower_bound must be smaller than upper_bound")
        return self


class TDEMBatchSoundingSpec(StrictModel):
    """One sounding participating in a shared 1D batch inversion."""

    sounding_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    observations_path: str = Field(min_length=1)
    system: TDEMSystemSpec
    data_uncertainty: QuantitySpec
    #: Where this sounding stands, in project coordinates.
    station_location: QuantitySpec | None = None

    @field_validator("station_location")
    @classmethod
    def station_location_is_a_point(cls, value: QuantitySpec | None) -> QuantitySpec | None:
        if value is None:
            return value
        if value.quantity_type is not QuantityType.LENGTH:
            raise ValueError("station_location must be a length")
        if len(np.atleast_1d(np.asarray(value.value, dtype=float))) != 3:
            raise ValueError("station_location must be three coordinates: easting, northing, z")
        return value

    @field_validator("data_uncertainty")
    @classmethod
    def data_uncertainty_is_b_field(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type not in {
            QuantityType.MAGNETIC_FLUX_DENSITY,
            QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
        }:
            raise ValueError(
                "batch data_uncertainty must be magnetic flux density or its derivative"
            )
        return value


class TDEMBatchInversionSpec(StrictModel):
    """Shared earth and inversion controls for multiple independent soundings."""

    earth: LayeredEarthSpec
    model: TDEMModelSpec
    regularization: TDEMRegularizationSpec = Field(default_factory=TDEMRegularizationSpec)
    optimizer: TDEMOptimizerSpec = Field(default_factory=TDEMOptimizerSpec)
    beta: TDEMBetaSpec = Field(default_factory=TDEMBetaSpec)
    directives: TDEMDirectivesSpec = Field(default_factory=TDEMDirectivesSpec)
    soundings: tuple[TDEMBatchSoundingSpec, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def sounding_ids_are_unique(self) -> "TDEMBatchInversionSpec":
        ids = [sounding.sounding_id for sounding in self.soundings]
        if len(set(ids)) != len(ids):
            raise ValueError("batch sounding_id values must be unique")
        response_kind = self.soundings[0].system.receiver_quantity
        if any(sounding.system.receiver_quantity != response_kind for sounding in self.soundings):
            raise ValueError("all batch soundings must use the same receiver_quantity")
        expected_quantity = QuantityType(response_kind)
        if any(
            sounding.data_uncertainty.quantity_type is not expected_quantity
            for sounding in self.soundings
        ):
            raise ValueError("batch data_uncertainty must match each sounding receiver_quantity")
        assert not isinstance(self.model.lower_bound.value, list)
        assert not isinstance(self.model.upper_bound.value, list)
        lower_bound = canonicalize_quantity(
            self.model.lower_bound.value,
            self.model.lower_bound.unit,
            QuantityType.CONDUCTIVITY,
        )
        upper_bound = canonicalize_quantity(
            self.model.upper_bound.value,
            self.model.upper_bound.unit,
            QuantityType.CONDUCTIVITY,
        )
        assert isinstance(lower_bound, float)
        assert isinstance(upper_bound, float)
        if lower_bound >= upper_bound:
            raise ValueError("batch TDEM lower_bound must be smaller than upper_bound")
        return self


class MTSiteSpec(StrictModel):
    """One magnetotelluric site in a shared layered batch."""

    site_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    observations_path: str = Field(min_length=1)
    easting_m: float
    northing_m: float
    elevation_m: float = 0.0


class MTModelSpec(StrictModel):
    initial_conductivity: QuantitySpec
    lower_bound: QuantitySpec
    upper_bound: QuantitySpec
    reference_conductivity: QuantitySpec | None = None

    @field_validator("initial_conductivity", "lower_bound", "upper_bound", "reference_conductivity")
    @classmethod
    def conductivity_is_a_positive_scalar(cls, value: QuantitySpec | None) -> QuantitySpec | None:
        if value is None:
            return value
        if (
            value.quantity_type is not QuantityType.CONDUCTIVITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("magnetotelluric model bounds must be positive scalar conductivities")
        return value


class MT1DBatchInversionSpec(StrictModel):
    """Independent layered inversions of many magnetotelluric sites."""

    earth: LayeredEarthSpec
    model: MTModelSpec
    regularization: TDEMRegularizationSpec = Field(default_factory=TDEMRegularizationSpec)
    optimizer: TDEMOptimizerSpec = Field(default_factory=TDEMOptimizerSpec)
    beta: TDEMBetaSpec = Field(default_factory=TDEMBetaSpec)
    directives: TDEMDirectivesSpec = Field(default_factory=TDEMDirectivesSpec)
    sites: tuple[MTSiteSpec, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def site_ids_are_unique(self) -> "MT1DBatchInversionSpec":
        identifiers = [site.site_id for site in self.sites]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("magnetotelluric site_id values must be unique")
        assert not isinstance(self.model.lower_bound.value, list)
        assert not isinstance(self.model.upper_bound.value, list)
        lower = canonicalize_quantity(
            self.model.lower_bound.value, self.model.lower_bound.unit, QuantityType.CONDUCTIVITY
        )
        upper = canonicalize_quantity(
            self.model.upper_bound.value, self.model.upper_bound.unit, QuantityType.CONDUCTIVITY
        )
        assert isinstance(lower, float) and isinstance(upper, float)
        if lower >= upper:
            raise ValueError("magnetotelluric lower_bound must be smaller than upper_bound")
        return self


class MT2DMeshSpec(StrictModel):
    """How the 2D mesh is built, which the caller does not draw by hand."""

    #: The core cell size, used both across the profile and downward.
    core_cell: QuantitySpec
    #: How deep the uniformly-discretized core reaches.
    core_depth: QuantitySpec
    #: How far the core extends beyond the outermost site along the profile.
    core_margin: QuantitySpec
    #: How far the padding reaches, in skin depths at the lowest frequency and
    #: `padding_resistivity`.
    padding_skin_depths: float = Field(default=5.0, gt=0.0, le=100.0)
    #: The resistivity the padding reach is computed at.
    padding_resistivity: QuantitySpec | None = None
    #: How fast the padding cells grow.
    padding_factor: float = Field(default=1.5, gt=1.0, le=3.0)
    #: Air conductivity. Not zero, because the system would be singular.
    air_conductivity: QuantitySpec | None = None

    @field_validator("core_cell", "core_depth", "core_margin")
    @classmethod
    def is_a_positive_length(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH or not isinstance(
            value.value, int | float
        ):
            raise ValueError("mesh dimensions must be scalar lengths")
        if float(value.value) <= 0:
            raise ValueError("mesh dimensions must be positive")
        return value


class MT2DSiteSpec(StrictModel):
    """One site on the profile, and which mode its file carries."""

    site_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    observations_path: str = Field(min_length=1)
    #: Position along the profile in metres, increasing in one direction.
    distance_m: float
    elevation_m: float = 0.0
    #: `te` is the electric field along strike, `tm` is the magnetic field along strike.
    mode: Literal["te", "tm"] = "tm"


class MT2DRegularizationSpec(StrictModel):
    """Smallness and the two smoothnesses, none of them left unset."""

    alpha_s: float = Field(default=1e-4, ge=0)
    alpha_y: float = Field(default=1.0, ge=0)
    alpha_z: float = Field(default=1.0, ge=0)


class MT2DInversionSpec(StrictModel):
    """A two-dimensional natural-source inversion along one profile."""

    mesh: MT2DMeshSpec
    model: MTModelSpec
    regularization: MT2DRegularizationSpec = Field(default_factory=MT2DRegularizationSpec)
    optimizer: TDEMOptimizerSpec = Field(default_factory=TDEMOptimizerSpec)
    beta: TDEMBetaSpec = Field(default_factory=TDEMBetaSpec)
    directives: TDEMDirectivesSpec = Field(default_factory=TDEMDirectivesSpec)
    sites: tuple[MT2DSiteSpec, ...] = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def sites_are_distinct_and_bounds_ascend(self) -> "MT2DInversionSpec":
        keys = [(site.site_id, site.mode) for site in self.sites]
        if len(set(keys)) != len(keys):
            raise ValueError("each site_id may appear once per mode")
        assert not isinstance(self.model.lower_bound.value, list)
        assert not isinstance(self.model.upper_bound.value, list)
        lower = canonicalize_quantity(
            self.model.lower_bound.value, self.model.lower_bound.unit, QuantityType.CONDUCTIVITY
        )
        upper = canonicalize_quantity(
            self.model.upper_bound.value, self.model.upper_bound.unit, QuantityType.CONDUCTIVITY
        )
        assert isinstance(lower, float) and isinstance(upper, float)
        if lower >= upper:
            raise ValueError("lower_bound must be smaller than upper_bound")
        return self


class TDEMTimeStepSpec(StrictModel):
    step: QuantitySpec
    count: int = Field(ge=1, le=100_000)

    @field_validator("step")
    @classmethod
    def step_is_positive_time(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.TIME
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("time step must be a positive scalar time")
        return value


class TDEMConductivityBlockSpec(StrictModel):
    """An axis-aligned, constant-conductivity block applied after the background model."""

    minimum: QuantitySpec
    maximum: QuantitySpec
    conductivity: QuantitySpec

    @field_validator("minimum", "maximum")
    @classmethod
    def corners_are_three_lengths(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.LENGTH or not isinstance(value.value, list):
            raise ValueError("block corners must contain three length values")
        if len(value.value) != 3:
            raise ValueError("block corners must contain exactly three values")
        return value

    @field_validator("conductivity")
    @classmethod
    def conductivity_is_positive_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.CONDUCTIVITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("block conductivity must be positive scalar conductivity")
        return value

    @model_validator(mode="after")
    def maximum_is_later_than_minimum(self) -> "TDEMConductivityBlockSpec":
        minimum = canonicalize_quantity(self.minimum.value, self.minimum.unit, QuantityType.LENGTH)
        maximum = canonicalize_quantity(self.maximum.value, self.maximum.unit, QuantityType.LENGTH)
        if np.any(np.asarray(maximum) <= np.asarray(minimum)):
            raise ValueError("each block maximum coordinate must exceed its minimum")
        return self


class TDEM3DModelSpec(StrictModel):
    conductivity: QuantitySpec
    conductivity_model: ArrayInputSpec | None = None
    air_conductivity: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(
            value=1e-8, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
        )
    )
    conductivity_blocks: tuple[TDEMConductivityBlockSpec, ...] = ()

    @field_validator("conductivity", "air_conductivity")
    @classmethod
    def conductivity_is_positive_scalar(cls, value: QuantitySpec) -> QuantitySpec:
        if (
            value.quantity_type is not QuantityType.CONDUCTIVITY
            or isinstance(value.value, list)
            or value.value <= 0
        ):
            raise ValueError("3D conductivity values must be positive scalar conductivity")
        return value

    @field_validator("conductivity_model")
    @classmethod
    def conductivity_model_has_conductivity_units(
        cls, value: ArrayInputSpec | None
    ) -> ArrayInputSpec | None:
        if value is not None and value.quantity_type is not QuantityType.CONDUCTIVITY:
            raise ValueError("3D conductivity_model must be conductivity")
        return value


class TDEM3DForwardSpec(StrictModel):
    system: TDEMSystemSpec
    model: TDEM3DModelSpec
    time_steps: tuple[TDEMTimeStepSpec, ...] = Field(min_length=1, max_length=100)
    initial_time: QuantitySpec = Field(
        default_factory=lambda: QuantitySpec(value=0.0, quantity_type=QuantityType.TIME, unit="s")
    )

    @field_validator("initial_time")
    @classmethod
    def initial_time_is_scalar_time(cls, value: QuantitySpec) -> QuantitySpec:
        if value.quantity_type is not QuantityType.TIME or isinstance(value.value, list):
            raise ValueError("initial_time must be a scalar time")
        return value


class RunSpec(StrictModel):
    # 1.1 carries method configuration in `physics`; 1.0 carries it in a typed field per
    # method.
    schema_version: Literal["1.0", "1.1"] = "1.0"
    run_id: UUID = Field(default_factory=uuid4)
    project_id: UUID | None = None
    plugin_id: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    plugin_version: str = Field(default="0.1.0", min_length=1)
    engine: str = Field(default="ofag", min_length=1)
    # What this run was for, in the words of whoever started it.
    label: str | None = Field(default=None, max_length=120)
    seed: int = Field(default=0, ge=0)
    # The run's primary dataset.
    dataset: DatasetSpec
    # Project-register identities, including methods whose observations are a collection
    # of per-site files rather than one DataChannelSpec.
    source_dataset_ids: tuple[UUID, ...] = ()
    # Every observation set this run inverts.  Empty for single-channel methods.
    datasets: tuple[DataChannelSpec, ...] = ()
    mesh: TensorMeshSpec | TreeMeshSpec | None = None
    executor: ExecutorSpec = Field(default_factory=ExecutorSpec)
    # Method configuration owned by the selected plugin and opaque to the core.
    physics: dict[str, JsonValue] | None = None

    gravity_inversion: GravityInversionSpec | None = None
    magnetics_inversion: MagneticsInversionSpec | None = None
    gravmag_joint_inversion: GravMagJointInversionSpec | None = None
    tdem_inversion: TDEMInversionSpec | None = None
    tdem_batch_inversion: TDEMBatchInversionSpec | None = None
    tdem3d_forward: TDEM3DForwardSpec | None = None
    parameters: dict[str, QuantitySpec | float | int | str | bool] = Field(default_factory=dict)

    def physics_as(self, model: type[_PhysicsModelT]) -> _PhysicsModelT | None:
        """Parse the plugin-owned payload, or None when this run carries none."""
        if self.physics is None:
            return None
        return model.model_validate(self.physics)

    def channel(self, channel_id: str) -> "DataChannelSpec | None":
        """Resolve one declared observation channel by id."""
        for item in self.datasets:
            if item.channel_id == channel_id:
                return item
        return None

    @model_validator(mode="after")
    def one_method_configuration_form(self) -> "RunSpec":
        """A run states its method configuration once, in one of the two forms."""
        typed_fields = tuple(
            name
            for name in (
                "gravity_inversion",
                "magnetics_inversion",
                "gravmag_joint_inversion",
                "tdem_inversion",
                "tdem_batch_inversion",
                "tdem3d_forward",
            )
            if getattr(self, name) is not None
        )
        if self.physics is not None and typed_fields:
            raise ValueError(
                "physics cannot be combined with the schema 1.0 fields "
                f"{', '.join(typed_fields)}; state the method configuration once"
            )
        return self

    @model_validator(mode="after")
    def data_channels_are_addressable_and_aligned(self) -> "RunSpec":
        identifiers = [item.channel_id for item in self.datasets]
        duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
        if duplicates:
            raise ValueError(f"data channel_id values must be unique; repeated: {duplicates}")
        # A mesh is built once for the whole run, so channels cannot disagree about what
        # their coordinates mean.
        conventions = {item.dataset.coordinate_convention for item in self.datasets}
        if len(conventions) > 1:
            raise ValueError("all data channels must share one coordinate convention")
        return self

    @model_validator(mode="after")
    def tiled_gravity_requires_treemesh(self) -> "RunSpec":
        if (
            self.gravity_inversion is not None
            and self.gravity_inversion.simulation.tiling.enabled
            and not isinstance(self.mesh, TreeMeshSpec)
        ):
            raise ValueError("tiled gravity inversion requires a TreeMeshSpec")
        if self.gravmag_joint_inversion is not None and (
            self.gravity_inversion is not None or self.magnetics_inversion is not None
        ):
            raise ValueError(
                "gravmag_joint_inversion cannot be combined with independent gravity_inversion "
                "or magnetics_inversion controls"
            )
        return self


class RunState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    #: Cut off rather than gone wrong.
    INTERRUPTED = "INTERRUPTED"


class RunCheckpoint(StrictModel):
    """A plugin's own saved progress, and what it was solving when it saved."""

    plugin_id: str
    plugin_version: str
    spec_fingerprint: str = Field(min_length=1)
    written_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: How far the solve had got, for the interface to report.
    iteration: int | None = Field(default=None, ge=0)
    state: dict[str, JsonValue] = Field(default_factory=dict)


def spec_fingerprint(spec: "RunSpec") -> str:
    """A stable digest of everything a run was configured to do."""
    canonical = spec.model_dump_json()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ParameterSensitivity(StrictModel):
    """How much the misfit moves per relative change in each parameter."""

    #: Parameter name to sensitivity. Comparable to each other, nothing else.
    sensitivity: dict[str, float]
    #: Which of them this configuration would update.
    inverted: tuple[str, ...] = ()
    #: Where the measurement was taken; the answer moves as the model does.
    measured_at: str = "starting_model"

    def ratios(self) -> dict[str, float]:
        """Each parameter against the most sensitive one."""
        largest = max(self.sensitivity.values(), default=0.0)
        if largest <= 0.0:
            return dict.fromkeys(self.sensitivity, 0.0)
        return {name: value / largest for name, value in self.sensitivity.items()}


class ValidationIssue(StrictModel):
    field: str
    message: str
    remediation: str


class ValidationReport(StrictModel):
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class ResourceEstimate(StrictModel):
    cpu_cores: int = Field(ge=1)
    memory_mb: int = Field(ge=1)
    estimated_seconds: int = Field(ge=0)
    estimate_basis: Literal["heuristic_uncalibrated"] = "heuristic_uncalibrated"


class CapabilityManifest(StrictModel):
    plugin_id: str
    plugin_version: str
    supported_quantities: tuple[QuantityType, ...]
    supported_meshes: tuple[str, ...]
    supports_parallel: bool
    supports_restart: bool
    limitations: tuple[str, ...] = ()


class RunEvent(StrictModel):
    run_id: UUID
    event_type: Literal["state", "iteration", "warning", "error"]
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    iteration: int | None = Field(default=None, ge=0)
    phi_total: float | None = None
    phi_data: float | None = None
    phi_model: float | None = None
    elapsed_time_s: float | None = Field(default=None, ge=0)
    message: str | None = None

    # A solve that runs in stages -- IRLS, FWI frequency continuation, the DC and IP
    # halves of a resistivity inversion -- restarts its iteration count in each one, so
    # `iteration` alone cannot place an event.
    stage: str | None = Field(default=None, max_length=64)
    stage_index: int | None = Field(default=None, ge=0)
    stage_total: int | None = Field(default=None, ge=1)

    # Per-term data misfits for solves with more than one.
    misfits: dict[str, float] = Field(default_factory=dict)


class ArtifactManifest(StrictModel):
    artifact_id: UUID = Field(default_factory=uuid4)
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    source_run_id: UUID
    relative_path: str
    # Set when a staged solve emits the same artifact type more than once, so a per-
    # stage recovered model stays distinguishable from the final one.
    stage: str | None = Field(default=None, max_length=64)


class NumericArtifactSeries(StrictModel):
    """A bounded one-dimensional numeric artifact for browser plotting."""

    artifact_id: UUID
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    sample_indices: tuple[int, ...]
    sample_index_unit: Literal["dimensionless"] = "dimensionless"
    values: tuple[float, ...]


class TDEMBatchSection(StrictModel):
    """Bounded stitched result for a batch of independent 1D TDEM soundings."""

    sounding_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    receiver_locations_m: tuple[tuple[float, float, float], ...] = Field(min_length=1)
    layer_top_depth_m: tuple[float, ...] = Field(min_length=1, max_length=10_000)
    conductivity_s_m: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=10_000)


class TDEMBatchSoundingResult(StrictModel):
    """One selected sounding from a stitched batch result."""

    sounding_id: str
    times_s: tuple[float, ...] = Field(min_length=1, max_length=10_000)
    observed_t: tuple[float, ...] = Field(min_length=1, max_length=10_000)
    predicted_t: tuple[float, ...] = Field(min_length=1, max_length=10_000)
    layer_top_depth_m: tuple[float, ...] = Field(min_length=1, max_length=10_000)
    conductivity_s_m: tuple[float, ...] = Field(min_length=1, max_length=10_000)


class ModelPointCloud(StrictModel):
    """A bounded active-cell model view for browser-side 3-D rendering."""

    artifact_id: UUID
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    points_m: tuple[tuple[float, float, float], ...]
    cell_volumes_m3: tuple[float, ...]
    values: tuple[float, ...]


class ModelSlice(StrictModel):
    """One active-cell model slice, sized for an interactive browser view."""

    artifact_id: UUID
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    normal: Literal["x", "y", "z"]
    coordinate_positions_m: tuple[float, ...]
    selected_index: int = Field(ge=0)
    selected_position_m: float
    value_minimum: float
    value_maximum: float
    points_m: tuple[tuple[float, float, float], ...]
    values: tuple[float, ...]


class SectionGeometry(StrictModel):
    """A vertical slice through the project, in project coordinates."""

    start_m: tuple[float, float]
    end_m: tuple[float, float]
    min_z_m: float
    max_z_m: float
    samples_along: int = Field(default=160, ge=2, le=1000)
    samples_vertical: int = Field(default=80, ge=2, le=1000)

    @model_validator(mode="after")
    def section_has_length_and_height(self) -> "SectionGeometry":
        if self.start_m == self.end_m:
            raise ValueError("a section needs two distinct end points")
        if not self.max_z_m > self.min_z_m:
            raise ValueError("max_z_m must be above min_z_m")
        return self

    @property
    def length_m(self) -> float:
        return float(np.hypot(self.end_m[0] - self.start_m[0], self.end_m[1] - self.start_m[1]))

    def sample_points(self) -> np.ndarray:
        """The (n, 3) grid this section is evaluated on, row-major by elevation."""
        fractions = np.linspace(0.0, 1.0, self.samples_along)
        eastings = self.start_m[0] + fractions * (self.end_m[0] - self.start_m[0])
        northings = self.start_m[1] + fractions * (self.end_m[1] - self.start_m[1])
        elevations = np.linspace(self.min_z_m, self.max_z_m, self.samples_vertical)
        x = np.tile(eastings, self.samples_vertical)
        y = np.tile(northings, self.samples_vertical)
        z = np.repeat(elevations, self.samples_along)
        return np.column_stack([x, y, z])


class GeologicalSectionRequest(StrictModel):
    """Interpolate one geological model and read it on a section."""

    model: GeologicalModel
    section: SectionGeometry


class BoreholeOnSection(StrictModel):
    """One hole placed on a section, ready to draw beside the interpolation."""

    borehole_id: UUID
    name: str
    #: Where the collar projects onto the section line, in metres from its start; and
    #: how far off the line the hole actually is, which is what says whether it
    #: constrains this section or a different piece of ground.
    collar_distance_m: float
    collar_offline_m: float
    #: The hole's path, as (distance along section, elevation) pairs.
    path_distance_m: tuple[float, ...]
    path_elevation_m: tuple[float, ...]
    #: Logged contacts, in the same coordinates, with the unit each one tops.
    contact_distance_m: tuple[float, ...]
    contact_elevation_m: tuple[float, ...]
    contact_unit_ids: tuple[UUID, ...]


class GeologicalSection(StrictModel):
    """Which unit occupies each cell of a section, as a raster of unit ids."""

    samples_along: int = Field(ge=2)
    samples_vertical: int = Field(ge=2)
    distances_m: tuple[float, ...]
    elevations_m: tuple[float, ...]
    #: One entry per cell, naming the unit that occupies it.
    unit_ids: tuple[UUID | None, ...]
    #: Cells the interpolation left between two units.
    undecided_cells: int = Field(ge=0)
    #: The holes that constrain this ground, placed on the same axes.
    boreholes: tuple[BoreholeOnSection, ...] = ()

    @model_validator(mode="after")
    def raster_is_rectangular(self) -> "GeologicalSection":
        expected = self.samples_along * self.samples_vertical
        if len(self.unit_ids) != expected:
            raise ValueError(f"expected {expected} cells, got {len(self.unit_ids)}")
        if len(self.distances_m) != self.samples_along:
            raise ValueError("distances_m must have one entry per column")
        if len(self.elevations_m) != self.samples_vertical:
            raise ValueError("elevations_m must have one entry per row")
        return self


class PropertyDistribution(StrictModel):
    """How a recovered model's values are distributed, as a bounded histogram."""

    artifact_id: UUID
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    cell_count: int = Field(ge=1)
    minimum: float
    maximum: float
    #: Bin edges in the requested scale's linear domain; `log_scale` says whether they
    #: were spaced logarithmically.
    bin_edges: tuple[float, ...]
    counts: tuple[int, ...]
    log_scale: bool
    #: Cells left out because a logarithmic axis cannot hold them.
    excluded_non_positive: int = Field(default=0, ge=0)
    #: (fraction, value) pairs -- p05 through p95 -- for placing thresholds.
    quantiles: tuple[tuple[float, float], ...]

    @model_validator(mode="after")
    def edges_bound_the_counts(self) -> "PropertyDistribution":
        if len(self.bin_edges) != len(self.counts) + 1:
            raise ValueError("bin_edges must have exactly one more entry than counts")
        return self


class RunComparisonRequest(StrictModel):
    baseline_run_id: UUID
    candidate_run_id: UUID

    @model_validator(mode="after")
    def run_ids_are_distinct(self) -> "RunComparisonRequest":
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("baseline_run_id and candidate_run_id must be different")
        return self


class ArtifactComparison(StrictModel):
    artifact_type: str
    physical_quantity: QuantityType
    units: str
    baseline_artifact_id: UUID
    candidate_artifact_id: UUID
    sample_count: int = Field(ge=1)
    mean_delta: float
    root_mean_square_delta: float = Field(ge=0)
    maximum_absolute_delta: float = Field(ge=0)


class RunComparison(StrictModel):
    baseline_run_id: UUID
    candidate_run_id: UUID
    summary_deltas: dict[str, float]
    artifact_comparisons: tuple[ArtifactComparison, ...]


class PreparedReferenceRun(StrictModel):
    """An official reference dataset prepared as a ready-to-submit RunSpec."""

    dataset_id: str
    source_url: str
    observations_path: str
    topography_path: str
    observation_count: int = Field(ge=1)
    run_spec: RunSpec


class RunResult(StrictModel):
    run_id: UUID
    summary: dict[str, float | int | str | bool]
    artifacts: tuple[ArtifactManifest, ...] = ()


class RunRecord(StrictModel):
    spec: RunSpec
    state: RunState = RunState.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


# Define geological interpretation contracts.


class UnitRuleKind(StrEnum):
    """How a cell qualifies for a unit."""

    #: Everything at or below a surface, given as an elevation per cell.
    BELOW_SURFACE = "below_surface"
    #: Everything no deeper than a surface, given as a depth below ground.
    ABOVE_SURFACE = "above_surface"
    #: Where a layered section's property crosses a threshold at that cell.
    PROPERTY_THRESHOLD = "property_threshold"
    #: Whatever the rules above did not claim.
    REMAINDER = "remainder"


class UnitRule(StrictModel):
    """One unit, how a cell joins it, and which method says so."""

    name: str = Field(min_length=1, max_length=80)
    #: The method that resolves this unit's depth, stored per cell in the result.
    source: str = Field(min_length=1, max_length=120)
    kind: UnitRuleKind
    #: For the two surface kinds: the key of the surface in the request.
    surface: str | None = None
    #: For PROPERTY_THRESHOLD: the layered section's key, the cut, and which side of it
    #: qualifies.
    section: str | None = None
    threshold: float | None = None
    below_threshold: bool = True
    #: For PROPERTY_THRESHOLD: the depth above which the method resolves nothing, so
    #: nothing above it is claimed either way.
    resolved_from_depth_m: float = Field(default=0.0, ge=0.0)
    #: How far a cell may be from the nearest measurement and still be assigned by this
    #: rule.
    reach_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def the_rule_has_what_its_kind_needs(self) -> "UnitRule":
        if self.kind in (UnitRuleKind.BELOW_SURFACE, UnitRuleKind.ABOVE_SURFACE):
            if not self.surface:
                raise ValueError(f"a {self.kind.value} rule needs a surface")
        elif self.kind is UnitRuleKind.PROPERTY_THRESHOLD:
            if not self.section or self.threshold is None:
                raise ValueError("a property_threshold rule needs a section and a threshold")
        return self


class SurfaceFitReport(StrictModel):
    """How a surface was fitted, and how well it predicts a pick it never saw."""

    surface: str
    estimator: str
    #: Leave-one-out RMS error, in the units of the picked quantity.
    held_out_error: float = Field(ge=0.0)
    #: The picks' own spread, which is what an estimator has to beat.
    pick_spread: float = Field(ge=0.0)
    candidates: dict[str, float]
    pick_count: int = Field(ge=1)
    #: How far the furthest modelled point is from the nearest pick.
    furthest_from_a_pick_m: float = Field(ge=0.0)


class UnitReport(StrictModel):
    """One unit's share of the model, and how much of it rests on measurement."""

    name: str
    source: str
    cell_count: int = Field(ge=0)
    volume_share: float = Field(ge=0.0, le=1.0)
    #: For a rule with a reach: the share of the whole modelled volume its own guard put
    #: out of consideration.
    beyond_reach_share: float = Field(default=0.0, ge=0.0, le=1.0)


class InterpretationReport(StrictModel):
    """What an interpreted model is made of, and what it could not decide."""

    units: tuple[UnitReport, ...]
    surfaces: tuple[SurfaceFitReport, ...] = ()
    cell_count: int = Field(ge=0)
    #: Cells no rule claimed, including the remainder.
    undecided_cells: int = Field(default=0, ge=0)


# Define frequency-domain airborne EM contracts.


class FDEMCoilPairSpec(StrictModel):
    """One transmitter-receiver pair on the bar, at one frequency."""

    #: The frequency the coil actually operates at, not the one it is called.
    frequency_hz: float = Field(gt=0.0)
    #: Horizontal in-line distance between the two coils.
    separation_m: float = Field(gt=0.0)
    #: Horizontal coplanar or vertical coaxial.
    orientation: Literal["horizontal_coplanar", "vertical_coaxial"]
    #: The column this pair's in-phase and quadrature come from.
    in_phase_column: str = Field(min_length=1)
    quadrature_column: str = Field(min_length=1)
    #: Which way the delivery signs this channel against a forward model that normalises
    #: by the *signed* primary field.
    response_sign: Literal[1, -1] = 1


class FDEMSystemSpec(StrictModel):
    """The bar, its height, and what its numbers mean."""

    coil_pairs: tuple[FDEMCoilPairSpec, ...] = Field(min_length=1)
    #: Height of the bar above the ground. Per sounding, from the altimeter.
    flight_height_m: QuantitySpec
    #: The response is parts per million of the primary field, which is what the
    #: receivers are asked for directly.

    @field_validator("coil_pairs")
    @classmethod
    def frequencies_are_distinct(
        cls, value: tuple[FDEMCoilPairSpec, ...]
    ) -> tuple[FDEMCoilPairSpec, ...]:
        seen = [(pair.frequency_hz, pair.orientation) for pair in value]
        if len(set(seen)) != len(seen):
            raise ValueError("each coil pair must be a distinct frequency and orientation")
        return value


class FDEMSoundingSpec(StrictModel):
    """One sounding: where it is, how high the bar was, and its response."""

    sounding_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    observations_path: str = Field(min_length=1)
    station_location: QuantitySpec
    flight_height_m: float = Field(gt=0.0)
    data_uncertainty: QuantitySpec


class FDEM1DInversionSpec(StrictModel):
    """A layered conductivity beneath each sounding, one sounding at a time."""

    earth: LayeredEarthSpec
    system: FDEMSystemSpec
    model: TDEMModelSpec
    regularization: TDEMRegularizationSpec = Field(default_factory=TDEMRegularizationSpec)
    optimizer: TDEMOptimizerSpec = Field(default_factory=TDEMOptimizerSpec)
    beta: TDEMBetaSpec = Field(default_factory=TDEMBetaSpec)
    directives: TDEMDirectivesSpec = Field(default_factory=TDEMDirectivesSpec)
    soundings: tuple[FDEMSoundingSpec, ...] = Field(min_length=1, max_length=200_000)

    @model_validator(mode="after")
    def sounding_ids_are_unique(self) -> "FDEM1DInversionSpec":
        ids = [sounding.sounding_id for sounding in self.soundings]
        if len(set(ids)) != len(ids):
            raise ValueError("sounding_id values must be unique")
        return self
