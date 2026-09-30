"""Turn a SEG-Y line into the arrays a 2D elastic inversion consumes."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import Field, model_validator

from ofag.core.constants import QuantityType
from ofag.core.schemas import QuantitySpec, StrictModel
from ofag.core.units import canonicalize_quantity
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore
from ofag.services.segy_import import (
    SegyImportRequest,
    SegyImportService,
    coordinate_scalar,
    positioned_traces,
    read_header_field,
)
from ofag.services.seismic_preprocess import (
    SeismicPreprocessingSpec,
    apply_preprocessing,
)


class SegyExtractRequest(SegyImportRequest):
    """Which shots and channels of a line to invert, and over what window."""

    #: Take every nth shot, then at most this many of them.
    shot_stride: int = Field(default=1, ge=1)
    max_shots: int = Field(default=8, ge=1, le=512)
    #: Take every nth channel within a shot.
    receiver_stride: int = Field(default=1, ge=1)
    #: The time window, in samples from the start of the record.
    first_sample: int = Field(default=0, ge=0)
    sample_count: int | None = Field(default=None, ge=8)
    #: How many traces each station contributed -- three for the 3C records land crews
    #: now shoot as a matter of course.
    components: int = Field(default=1, ge=1, le=9)
    #: Which of them to invert, counting from zero in file order.
    component_index: int = Field(default=0, ge=0, le=8)
    #: More files holding more shots of the same line.
    additional_source_paths: tuple[str, ...] = ()
    #: The bearing of the 2D line, clockwise from north.
    line_azimuth: QuantitySpec | None = None
    #: Keep only stations within this distance of that line.
    corridor_half_width: QuantitySpec | None = None
    #: What is done to the traces before an inversion is allowed to fit them.
    preprocessing: SeismicPreprocessingSpec = Field(default_factory=SeismicPreprocessingSpec)
    #: How far below the model top the stations sit.
    station_depth_m: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def line_is_described_consistently(self) -> "SegyExtractRequest":
        if self.line_azimuth is not None and self.line_azimuth.quantity_type is not (
            QuantityType.ANGLE
        ):
            raise ValueError("line_azimuth must be an angle")
        if self.corridor_half_width is not None:
            if self.corridor_half_width.quantity_type is not QuantityType.LENGTH:
                raise ValueError("corridor_half_width must be a length")
            if float(np.asarray(self.corridor_half_width.value)) <= 0:
                raise ValueError("a corridor of zero width would keep no stations")
        return self

    @model_validator(mode="after")
    def component_exists(self) -> "SegyExtractRequest":
        if self.component_index >= self.components:
            raise ValueError(
                f"component {self.component_index} of a {self.components}-component record "
                "does not exist; they are numbered from zero"
            )
        return self


@dataclass(frozen=True)
class PreparedSeismicLine:
    """What was selected, and where the arrays for the run were written."""

    dataset_id: UUID
    source_filename: str
    #: Every file the shots came from, in the order they were read.
    source_filenames: tuple[str, ...]
    shot_count: int
    shots_available: int
    receiver_count: int
    channels_available: int
    #: Stations every selected shot recorded.
    channels_shared: int
    #: The bearing the section is measured along, whether stated or fitted.
    line_azimuth_degrees: float
    sample_count: int
    samples_available: int
    #: Along-line extent the selection covers.
    line_length_m: float
    #: How far the stations stray from the straight line they are treated as. 2D is only
    #: defensible while this is small next to a wavelength.
    maximum_offline_deviation_m: float
    observations_path: str
    sources_path: str
    receivers_path: str
    #: What preprocessing did, in the order it did it, for the interface to show and for
    #: a reader of the receipt to check against the numbers.
    preprocessing_applied: tuple[str, ...]
    #: The full selection and preprocessing specification, written beside the arrays.
    preparation_path: str
    #: Digest of the observation array as written.
    observations_sha256: str


class StartingModelRequest(StrictModel):
    """A linear-gradient starting model, on the grid a run will use."""

    #: (depth cells, along-line cells), matching the run's grid.
    shape: tuple[int, int]
    cell_size: QuantitySpec
    surface_p_velocity: QuantitySpec
    #: Increase in P velocity per metre of depth.  Zero gives a half-space.
    p_velocity_gradient_per_m: float = Field(default=0.0, ge=0.0)
    #: Vp over Vs. 1.9 is a common consolidated value; a wet weathering layer runs much
    #: higher, which is why it is a parameter and not a constant.
    vp_over_vs: float = Field(default=1.9, gt=1.4142135623730951)
    density: QuantitySpec

    @model_validator(mode="after")
    def quantities_are_right(self) -> "StartingModelRequest":
        if self.cell_size.quantity_type is not QuantityType.LENGTH:
            raise ValueError("cell_size must be a length")
        if self.surface_p_velocity.quantity_type is not QuantityType.P_WAVE_VELOCITY:
            raise ValueError("surface_p_velocity must be a P-wave velocity")
        if self.density.quantity_type is not QuantityType.BULK_DENSITY:
            raise ValueError("density must be a bulk density")
        if any(size < 8 for size in self.shape):
            raise ValueError("each grid axis needs at least eight cells")
        return self


@dataclass(frozen=True)
class PreparedStartingModel:
    """Where the starting arrays were written, and what they span."""

    dataset_id: UUID
    shape: tuple[int, int]
    p_velocity_min_m_s: float
    p_velocity_max_m_s: float
    s_velocity_min_m_s: float
    s_velocity_max_m_s: float
    density_kg_m3: float
    initial_vp_path: str
    initial_vs_path: str
    density_path: str


class SeismicPrepareService:
    """Select shots for an inversion, and build the model it starts from."""

    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)
        self._segy = SegyImportService(import_root=self._store.root)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def dependency_available(self) -> bool:
        return self._segy.dependency_available()

    @staticmethod
    def _line_of(
        request: SegyExtractRequest,
        sources_xy: np.ndarray,
        receivers_xy: np.ndarray,
        usable: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """The straight line the section is measured along."""
        if request.line_azimuth is None:
            return _line_direction(receivers_xy[usable])
        radians = float(
            np.asarray(
                canonicalize_quantity(
                    request.line_azimuth.value, request.line_azimuth.unit, QuantityType.ANGLE
                )
            )
        )
        # Clockwise from north, so east is the sine.
        return np.array([np.sin(radians), np.cos(radians)]), sources_xy[usable].mean(axis=0)

    def extract(self, request: SegyExtractRequest) -> PreparedSeismicLine:
        import segyio  # type: ignore[import-untyped]

        paths = [
            Path(request.source_path),
            *(Path(item) for item in request.additional_source_paths),
        ]
        for path in paths:
            if not path.is_file():
                raise ValueError(f"{path} does not exist")

        # One pass over the headers of every file, so the line, the corridor and the
        # shot selection are decided against the whole survey before a single trace is
        # read.
        geometry_blocks: list[np.ndarray] = []
        owners: list[np.ndarray] = []
        offsets_in_file: list[np.ndarray] = []
        samples_available = 0
        sample_interval_s = 0.0
        for file_index, path in enumerate(paths):
            with segyio.open(str(path), "r", ignore_geometry=True) as handle:
                samples = int(len(handle.samples))
                interval_us = float(handle.bin[segyio.BinField.Interval])
                if interval_us <= 0:
                    raise ValueError(
                        "the binary header states a sample interval of "
                        f"{interval_us:g} microseconds, which cannot be a rate"
                    )
                if file_index == 0:
                    samples_available = samples
                    sample_interval_s = interval_us * 1e-6
                elif samples != samples_available or interval_us * 1e-6 != sample_interval_s:
                    raise ValueError(
                        f"{path.name} holds {samples} samples at {interval_us * 1e-6:g} s and "
                        f"{paths[0].name} holds {samples_available} at {sample_interval_s:g} s; "
                        "these are not records of one line"
                    )
                keep = min(int(handle.tracecount), request.max_traces_scanned)
                scalar, _ = coordinate_scalar(handle, request, keep)
                raw = np.column_stack(
                    [
                        read_header_field(handle, request.source_x_byte, keep),
                        read_header_field(handle, request.source_y_byte, keep),
                        read_header_field(handle, request.receiver_x_byte, keep),
                        read_header_field(handle, request.receiver_y_byte, keep),
                    ]
                )
            geometry_blocks.append(
                np.asarray(
                    canonicalize_quantity(
                        raw * scalar, request.coordinate_unit, QuantityType.LENGTH
                    ),
                    dtype=float,
                )
            )
            owners.append(np.full(keep, file_index, dtype=np.int64))
            offsets_in_file.append(np.arange(keep, dtype=np.int64))

        geometry = np.vstack(geometry_blocks)
        owner = np.concatenate(owners)
        within_file = np.concatenate(offsets_in_file)
        sources_xy = geometry[:, :2]
        receivers_xy = geometry[:, 2:]

        window_start = request.first_sample
        window = (
            samples_available - window_start
            if request.sample_count is None
            else request.sample_count
        )
        if window_start + window > samples_available:
            raise ValueError(
                f"a window of {window} samples from {window_start} runs past the "
                f"{samples_available} samples each trace holds"
            )

        # The auxiliary traces sit at the map origin, and everything below is geometry:
        # a line fitted through the origin is rotated away from the spread it is meant
        # to describe, and every channel's along-line position moves with it.
        usable = positioned_traces(sources_xy, receivers_xy)
        direction, origin = self._line_of(request, sources_xy, receivers_xy, usable)

        if request.corridor_half_width is not None:
            half_width = _metres(request.corridor_half_width)
            normal = np.array([-direction[1], direction[0]])
            inside = np.abs((receivers_xy - origin) @ normal) <= half_width
            if not (usable & inside).any():
                raise ValueError(
                    f"no station lies within {half_width:g} m of the line; widen the corridor "
                    "or check the azimuth"
                )
            usable = usable & inside

        usable_index = np.flatnonzero(usable)
        # The line's own start, fixed once so every distance below is on the same axis.
        line_start = float(_along(receivers_xy[usable], direction, origin).min())
        shot_keys, first_of_shot = np.unique(sources_xy[usable], axis=0, return_index=True)
        shot_first_index = usable_index[first_of_shot]
        # Ordered along the line rather than by where they sat in the file, because a
        # shot number is not a position and a selection by stride should walk the line.
        shot_order = np.argsort(_along(shot_keys, direction, origin))
        selected = shot_order[:: request.shot_stride][: request.max_shots]
        if not selected.size:
            raise ValueError("the shot selection is empty")

        # -1 rather than 0, so an unusable trace belongs to no shot instead of
        # joining the first one.
        trace_shot = np.full(len(geometry), -1, dtype=np.int64)
        for index, key in enumerate(shot_keys):
            trace_shot[usable & np.all(sources_xy == key, axis=1)] = index

        # Each shot's channels, keyed by where they sit on the line rather than by
        # channel number: two shots of a rolling spread number the same ground
        # differently, and a 3D patch drops and adds stations between shots.
        per_shot: list[dict[int, int]] = []
        channels_available = 0
        for shot_index in selected:
            traces = _one_component(
                np.flatnonzero(trace_shot == shot_index),
                receivers_xy,
                request.components,
                request.component_index,
            )
            # Counted after the component is chosen, because what is available to a 2D
            # run is stations, not traces: a 3C record would otherwise offer three times
            # the channels it has.
            channels_available = max(channels_available, int(traces.size))
            along = _along(receivers_xy[traces], direction, origin) - line_start
            per_shot.append(
                {
                    int(round(position * 10)): int(trace)
                    for position, trace in zip(along, traces, strict=True)
                }
            )

        shared = set(per_shot[0])
        for channels in per_shot[1:]:
            shared &= set(channels)
        if len(shared) < 2:
            # Not a refusal to handle rolling data so much as a statement that these
            # shots have no common ground: nothing can be inverted on one receiver array
            # that all of them recorded.
            raise ValueError(
                f"the {len(selected)} selected shots share {len(shared)} stations, so there is "
                "no spread they all recorded; select shots from nearer one another, or widen "
                "the corridor if a line was taken out of a patch"
            )
        keys = sorted(shared)[:: request.receiver_stride]
        reference = np.array([key / 10.0 for key in keys])

        gathers: list[np.ndarray] = []
        chosen_sources: list[np.ndarray] = []
        readers = {
            index: segyio.open(str(path), "r", ignore_geometry=True)
            for index, path in enumerate(paths)
        }
        try:
            for shot_index, channels in zip(selected, per_shot, strict=True):
                gathers.append(
                    np.stack(
                        [
                            np.asarray(
                                readers[int(owner[channels[key]])].trace[
                                    int(within_file[channels[key]])
                                ],
                                dtype=float,
                            )[window_start : window_start + window]
                            for key in keys
                        ]
                    )
                )
                chosen_sources.append(sources_xy[int(shot_first_index[shot_index])])
        finally:
            for reader in readers.values():
                reader.close()

        observations = np.stack(gathers)
        # Offsets along the line the run is modelled on, not the map distance: the mute
        # follows the arrival the 2D solver will produce.
        source_along = _along(np.asarray(chosen_sources), direction, origin) - line_start
        observations, preprocessing_applied = apply_preprocessing(
            observations,
            np.abs(source_along[:, None] - reference[None, :]),
            sample_interval_s,
            request.preprocessing,
        )
        offline = _offline_deviation(
            np.vstack([receivers_xy[usable], np.asarray(chosen_sources)]), direction, origin
        )
        dataset_id, directory = self._store.new_dataset()
        written: dict[str, str] = {}
        for name, values in (
            ("observations", observations),
            (
                "sources",
                np.column_stack(
                    [source_along, np.full(source_along.size, request.station_depth_m)]
                ),
            ),
            (
                "receivers",
                np.column_stack([reference, np.full(reference.size, request.station_depth_m)]),
            ),
        ):
            target = directory / f"fwi_{name}.npy"
            np.save(target, values)
            written[name] = str(target)

        digest = hashlib.sha256(np.ascontiguousarray(observations).tobytes()).hexdigest()
        preparation = directory / "fwi_preparation.json"
        preparation.write_text(
            json.dumps(
                {
                    "request": request.model_dump(mode="json"),
                    "preprocessing_applied": list(preprocessing_applied),
                    "observations_sha256": digest,
                    "observations_shape": list(observations.shape),
                    "sample_interval_s": sample_interval_s,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return PreparedSeismicLine(
            dataset_id=dataset_id,
            source_filename=paths[0].name,
            source_filenames=tuple(item.name for item in paths),
            shot_count=int(observations.shape[0]),
            shots_available=int(shot_keys.shape[0]),
            receiver_count=int(observations.shape[1]),
            channels_available=channels_available,
            channels_shared=len(shared),
            line_azimuth_degrees=float(np.degrees(np.arctan2(direction[0], direction[1])) % 180.0),
            sample_count=int(observations.shape[2]),
            samples_available=samples_available,
            line_length_m=float(reference.max() - reference.min()),
            maximum_offline_deviation_m=float(offline),
            observations_path=written["observations"],
            sources_path=written["sources"],
            receivers_path=written["receivers"],
            preprocessing_applied=preprocessing_applied,
            preparation_path=str(preparation),
            observations_sha256=digest,
        )

    def starting_model(self, request: StartingModelRequest) -> PreparedStartingModel:
        """Write vp, vs and density on the run's grid."""
        spacing = float(np.asarray(request.cell_size.value).reshape(-1)[0])
        surface = float(np.asarray(request.surface_p_velocity.value).reshape(-1)[0])
        density_value = float(np.asarray(request.density.value).reshape(-1)[0])
        if density_value <= 0:
            raise ValueError("density must be positive")

        depth_cells, along_cells = request.shape
        depths = np.arange(depth_cells, dtype=float) * spacing
        vp_column = surface + request.p_velocity_gradient_per_m * depths
        vp = np.repeat(vp_column[:, None], along_cells, axis=1)
        vs = vp / request.vp_over_vs
        density = np.full_like(vp, density_value)

        dataset_id, directory = self._store.new_dataset()
        paths = {}
        for name, values in (("vp", vp), ("vs", vs), ("density", density)):
            target = directory / f"starting_{name}.npy"
            np.save(target, values)
            paths[name] = str(target)

        return PreparedStartingModel(
            dataset_id=dataset_id,
            shape=(depth_cells, along_cells),
            p_velocity_min_m_s=float(vp.min()),
            p_velocity_max_m_s=float(vp.max()),
            s_velocity_min_m_s=float(vs.min()),
            s_velocity_max_m_s=float(vs.max()),
            density_kg_m3=density_value,
            initial_vp_path=paths["vp"],
            initial_vs_path=paths["vs"],
            density_path=paths["density"],
        )


def _metres(spec: QuantitySpec) -> float:
    return float(np.asarray(canonicalize_quantity(spec.value, spec.unit, QuantityType.LENGTH)))


def _one_component(
    traces: np.ndarray,
    receivers_xy: np.ndarray,
    components: int,
    component_index: int,
) -> np.ndarray:
    """One component's trace at each station of a shot."""
    _, inverse = np.unique(receivers_xy[traces], axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    per_station = np.bincount(inverse)

    if components == 1:
        crowded = int((per_station > 1).sum())
        if crowded:
            raise ValueError(
                f"{crowded} of {per_station.size} stations in this shot hold more than one "
                f"trace -- up to {int(per_station.max())} -- which is what a multi-component "
                "record looks like, since no SEG-Y header distinguishes the components. "
                "State how many components each station recorded and which one to invert; "
                "read as extra channels at the same point they would be inverted as if they "
                "were different stations"
            )
        return traces

    if not np.all(per_station == components):
        counts = ", ".join(str(int(value)) for value in np.unique(per_station))
        raise ValueError(
            f"a {components}-component record was declared, but the stations of this shot "
            f"hold {counts} traces each; the components are not laid out the way this "
            "selection assumes, or some channels are missing"
        )

    # Which occurrence of its own station each trace is, in file order.
    occurrence = np.zeros(len(traces), dtype=np.int64)
    seen: dict[int, int] = {}
    for row, station in enumerate(inverse.tolist()):
        occurrence[row] = seen.get(station, 0)
        seen[station] = occurrence[row] + 1
    return np.asarray(traces[occurrence == component_index])


def _line_direction(points_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The straight line a 2D section treats the stations as lying on."""
    origin = points_xy.mean(axis=0)
    centred = points_xy - origin
    if not np.any(centred):
        raise ValueError("every station sits at the same position")
    _, _, vectors = np.linalg.svd(centred, full_matrices=False)
    direction = vectors[0]
    # Point it towards increasing Easting so "along the line" is stable between runs
    # rather than depending on the sign the decomposition happened to pick.
    if direction[0] < 0 or (direction[0] == 0 and direction[1] < 0):
        direction = -direction
    return direction, origin


def _along(points_xy: np.ndarray, direction: np.ndarray, origin: np.ndarray) -> np.ndarray:
    """Signed distance along the line from a fixed origin."""
    return np.asarray((points_xy - origin) @ direction, dtype=float)


def _offline_deviation(points_xy: np.ndarray, direction: np.ndarray, origin: np.ndarray) -> float:
    """How far the stations stray from the line they are treated as lying on."""
    perpendicular = np.array([-direction[1], direction[0]])
    return float(np.abs((points_xy - origin) @ perpendicular).max())
