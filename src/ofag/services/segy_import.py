"""Read the geometry out of a SEG-Y file, in units somebody stated."""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import numpy as np
from pydantic import Field, model_validator

from ofag.core.constants import QuantityType
from ofag.core.schemas import CoordinateConvention, StrictModel
from ofag.core.units import canonicalize_quantity
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore

#: The SEG-Y standard positions, one-based, as the revision 1 specification fixes them.
STANDARD_HEADER_BYTES: dict[str, int] = {
    "source_x": 73,
    "source_y": 77,
    "receiver_x": 81,
    "receiver_y": 85,
    "source_elevation": 45,
    "receiver_elevation": 41,
    "coordinate_scalar": 71,
    "elevation_scalar": 69,
}

#: Reading every trace header of a very large survey is a minute of work, and the
#: geometry is usually clear long before then.
DEFAULT_MAX_TRACES_SCANNED = 2_000_000


class SegyImportRequest(StrictModel):
    """One SEG-Y file, and everything its headers do not reliably state."""

    source_path: str
    name: str
    coordinate_convention: CoordinateConvention
    project_id: UUID | None = None
    #: One-based byte positions of the coordinate fields.
    source_x_byte: int = Field(default=STANDARD_HEADER_BYTES["source_x"], ge=1, le=233)
    source_y_byte: int = Field(default=STANDARD_HEADER_BYTES["source_y"], ge=1, le=233)
    receiver_x_byte: int = Field(default=STANDARD_HEADER_BYTES["receiver_x"], ge=1, le=233)
    receiver_y_byte: int = Field(default=STANDARD_HEADER_BYTES["receiver_y"], ge=1, le=233)
    #: How to scale the raw coordinate integers. "header" reads byte 71 and applies the
    #: SEG-Y rule, where a positive value multiplies and a negative one divides.
    coordinate_scalar: Literal["header"] | float = "header"
    #: The unit of the scaled coordinates.
    coordinate_unit: str = "m"
    max_traces_scanned: int = Field(default=DEFAULT_MAX_TRACES_SCANNED, ge=1)

    @model_validator(mode="after")
    def scalar_is_usable(self) -> "SegyImportRequest":
        if isinstance(self.coordinate_scalar, float) and self.coordinate_scalar == 0:
            raise ValueError("a coordinate scalar of zero would collapse every coordinate to zero")
        return self


@dataclass(frozen=True)
class ImportedSegyDataset:
    """The geometry a SEG-Y file describes, in canonical metres."""

    dataset_id: UUID
    source_filename: str
    source_path: str
    trace_count: int
    scanned_trace_count: int
    #: Scanned traces whose coordinate headers were left at zero -- the auxiliary
    #: channels every land record carries.
    unpositioned_trace_count: int
    truncated: bool
    sample_count: int
    sample_interval_s: float
    record_length_s: float
    #: Distinct source positions, which is the shot count for a land line.
    shot_count: int
    receiver_count: int
    #: Traces per source-receiver pair, when every pair holds the same number.
    traces_per_station: int | None
    bounds_m: tuple[float, float, float, float, float, float]
    #: Source-receiver offsets, which is what says whether the geometry read.
    offset_min_m: float
    offset_max_m: float
    #: Set when the mapped bytes cannot describe an acquisition geometry, with the
    #: reason.
    geometry_warning: str | None
    #: The mapping this file was read with, echoed back so the steps after the import
    #: read it the same way.
    source_x_byte: int
    source_y_byte: int
    receiver_x_byte: int
    receiver_y_byte: int
    coordinate_unit: str
    #: The scalar actually applied, after the SEG-Y sign rule.
    coordinate_scalar_applied: float
    #: Whether it came from the file or from the request.
    coordinate_scalar_source: Literal["header", "declared"]
    geometry_path: str


class SegyImportService:
    """Describe a SEG-Y survey without copying it."""

    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def dependency_available(self) -> bool:
        return find_spec("segyio") is not None

    def import_file(self, request: SegyImportRequest) -> ImportedSegyDataset:
        import segyio  # type: ignore[import-untyped]

        path = Path(request.source_path)
        if not path.is_file():
            raise ValueError(f"{path} does not exist")

        # `ignore_geometry` because a shot-gather land line is not the regular
        # inline/crossline cube segyio otherwise tries to infer, and failing to infer
        # one must not stop the file being read.
        with segyio.open(str(path), "r", ignore_geometry=True) as handle:
            trace_count = int(handle.tracecount)
            if not trace_count:
                raise ValueError(f"{path} holds no traces")
            sample_count = int(len(handle.samples))
            # The binary header states the interval in microseconds.
            interval_us = float(handle.bin[segyio.BinField.Interval])
            if interval_us <= 0:
                raise ValueError(
                    "the binary header states a sample interval of "
                    f"{interval_us:g} microseconds, which cannot be a rate"
                )
            sample_interval_s = interval_us * 1e-6

            keep = min(trace_count, request.max_traces_scanned)
            scalar, scalar_source = coordinate_scalar(handle, request, keep)
            raw = np.column_stack(
                [
                    read_header_field(handle, request.source_x_byte, keep),
                    read_header_field(handle, request.source_y_byte, keep),
                    read_header_field(handle, request.receiver_x_byte, keep),
                    read_header_field(handle, request.receiver_y_byte, keep),
                ]
            )

        scaled = raw * scalar
        geometry_m = np.asarray(
            canonicalize_quantity(scaled, request.coordinate_unit, QuantityType.LENGTH),
            dtype=float,
        )
        if not np.isfinite(geometry_m).all():
            raise ValueError("the mapped coordinate headers contain non-finite values")

        # Saved full length, so a row index stays a trace index for whoever reads a
        # trace back out of the file.
        positioned = positioned_traces(geometry_m[:, :2], geometry_m[:, 2:])
        sources = geometry_m[positioned, :2]
        receivers = geometry_m[positioned, 2:]
        offsets = np.hypot(sources[:, 0] - receivers[:, 0], sources[:, 1] - receivers[:, 1])
        _, per_station = np.unique(
            np.column_stack([sources, receivers]), axis=0, return_counts=True
        )
        uniform = bool(per_station.size) and bool(np.all(per_station == per_station[0]))

        dataset_id, directory = self._store.new_dataset()
        geometry_path = directory / "segy_geometry.npy"
        np.save(geometry_path, geometry_m)

        return ImportedSegyDataset(
            dataset_id=dataset_id,
            source_filename=path.name,
            source_path=str(path),
            trace_count=trace_count,
            scanned_trace_count=int(keep),
            unpositioned_trace_count=int(keep - int(positioned.sum())),
            truncated=bool(keep < trace_count),
            sample_count=sample_count,
            sample_interval_s=sample_interval_s,
            record_length_s=sample_interval_s * max(sample_count - 1, 0),
            shot_count=int(len(np.unique(sources, axis=0))),
            receiver_count=int(len(np.unique(receivers, axis=0))),
            traces_per_station=int(per_station[0]) if uniform else None,
            bounds_m=(
                float(min(sources[:, 0].min(), receivers[:, 0].min())),
                float(max(sources[:, 0].max(), receivers[:, 0].max())),
                float(min(sources[:, 1].min(), receivers[:, 1].min())),
                float(max(sources[:, 1].max(), receivers[:, 1].max())),
                0.0,
                0.0,
            ),
            offset_min_m=float(offsets.min()),
            offset_max_m=float(offsets.max()),
            geometry_warning=_geometry_warning(sources, receivers, offsets),
            source_x_byte=request.source_x_byte,
            source_y_byte=request.source_y_byte,
            receiver_x_byte=request.receiver_x_byte,
            receiver_y_byte=request.receiver_y_byte,
            coordinate_unit=request.coordinate_unit,
            coordinate_scalar_applied=float(scalar),
            coordinate_scalar_source=scalar_source,
            geometry_path=str(geometry_path),
        )


#: An offset larger than this is not a land or marine acquisition offset; it is what an
#: unpopulated coordinate field looks like against a populated one.
IMPLAUSIBLE_OFFSET_M = 100_000.0


def positioned_traces(sources: np.ndarray, receivers: np.ndarray) -> np.ndarray:
    """Which traces carry a position at all."""
    keep = np.ones(len(sources), dtype=bool)
    for role in (sources, receivers):
        unset = ~role.any(axis=1)
        if not unset.all():
            keep &= ~unset
    # Disjoint gaps in the two roles could in principle empty the survey; the geometry
    # as read is more useful to look at than nothing.
    return keep if keep.any() else np.ones(len(sources), dtype=bool)


def _geometry_warning(
    sources: np.ndarray, receivers: np.ndarray, offsets: np.ndarray
) -> str | None:
    """Whether the mapped bytes can describe an acquisition at all."""
    if not np.any(sources) and not np.any(receivers):
        return "every mapped coordinate is zero, so these bytes hold no geometry"
    if not np.any(sources):
        return (
            "every source coordinate is zero, so the source position is not in the "
            "mapped bytes; the offsets below are measured from the origin"
        )
    distinct_sources = len(np.unique(sources, axis=0))
    distinct_receivers = len(np.unique(receivers, axis=0))
    if distinct_sources == 1 and distinct_receivers == 1 and len(offsets) > 1:
        return (
            f"all {len(offsets)} traces share one source and one receiver position, so the "
            "mapped bytes do not distinguish the channels"
        )
    if float(offsets.max()) > IMPLAUSIBLE_OFFSET_M:
        return (
            f"the largest source-receiver offset is {float(offsets.max()):,.0f} m, which is "
            "not an acquisition offset; check the byte positions and the scalar"
        )
    return None


def read_header_field(handle: Any, byte_position: int, keep: int) -> np.ndarray:
    """One trace-header field across the scanned traces."""
    values = np.asarray(handle.attributes(byte_position)[:keep], dtype=float)
    if values.size != keep:
        raise ValueError(f"header byte {byte_position} yielded {values.size} of {keep} values")
    return values


def coordinate_scalar(
    handle: Any, request: "SegyImportRequest", keep: int
) -> tuple[float, Literal["header", "declared"]]:
    """The coordinate multiplier, under the SEG-Y sign rule."""
    if not isinstance(request.coordinate_scalar, str):
        return float(request.coordinate_scalar), "declared"
    raw = np.asarray(
        handle.attributes(STANDARD_HEADER_BYTES["coordinate_scalar"])[:keep], dtype=float
    )
    distinct = np.unique(raw)
    if distinct.size > 1:
        listed = ", ".join(f"{value:g}" for value in distinct[:5])
        raise ValueError(
            f"the traces state {distinct.size} different coordinate scalars ({listed}), "
            "so their coordinates are not in one unit; declare the scalar to override"
        )
    stated = float(distinct[0])
    if stated == 0:
        # Zero means "not set" in practice; the standard says unity.
        return 1.0, "header"
    return (stated if stated > 0 else 1.0 / abs(stated)), "header"
