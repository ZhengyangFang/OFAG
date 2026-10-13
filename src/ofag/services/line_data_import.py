"""Import layered-earth models delivered along flight lines."""

import math
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import Field

from ofag.core.constants import CANONICAL_UNITS, QuantityType
from ofag.core.schemas import (
    ArtifactManifest,
    CoordinateConvention,
    DatasetSpec,
    RunResult,
    RunSpec,
    StrictModel,
)
from ofag.core.units import canonicalize_quantity

#: The plugin id an imported line-data model carries.
IMPORT_PLUGIN_ID = "ofag.external.line_data_import"

#: `GET /runs/{id}/tdem-batch-section` refuses a section past this many values, so a
#: line longer than this divided by its layer count has to be decimated before it can be
#: viewed at all.
MAX_SECTION_VALUES = 250_000

#: Fields 1 to 9 of an ASEG-style row -- through easting, northing and elevation -- fit
#: comfortably in this many bytes.
_PREFIX_BYTES = 96


class LayeredLineInventoryRequest(StrictModel):
    """Ask what flight lines a delivered line-data file contains."""

    data_path: str
    header_path: str


class FlightLineSummary(StrictModel):
    """One flight line, and enough of its extent to recognise it on a map."""

    line: str
    sounding_count: int = Field(ge=1)
    easting_min_m: float
    easting_max_m: float
    northing_min_m: float
    northing_max_m: float


class LayeredLineInventory(StrictModel):
    """What is in the file, without having parsed the models in it."""

    lines: tuple[FlightLineSummary, ...]
    total_soundings: int
    layer_count: int
    columns: tuple[str, ...]


class LayeredLineImportRequest(StrictModel):
    """One flight line's layered models, as a completed run."""

    data_path: str
    header_path: str
    line: str
    name: str
    #: What the conductivity columns are in.
    conductivity_units: str = "S/m"
    coordinate_convention: CoordinateConvention
    project_id: UUID | None = None
    #: A line of sixteen thousand soundings cannot be viewed whole, so every nth is
    #: taken.
    max_soundings: int = Field(default=4_000, ge=1)


@dataclass(frozen=True)
class ImportedLineData:
    """What the workbench shows after importing one line."""

    run_id: UUID
    line: str
    sounding_count: int
    imported_sounding_count: int
    decimation: int
    layer_count: int
    bounds_m: tuple[float, float, float, float, float, float]
    deepest_layer_top_m: float
    value_minimum: float
    value_maximum: float
    #: Cells a logarithmic view cannot hold.
    non_positive_values: int
    units: str


@dataclass(frozen=True)
class LineDataHeader:
    """The column names of a delivered line-data file, in file order."""

    columns: tuple[str, ...]
    conductivity: tuple[int, ...]
    thickness: tuple[int, ...]
    line: int
    easting: int
    northing: int
    elevation: int

    @property
    def layer_count(self) -> int:
        return len(self.conductivity)


def read_header(path: Path) -> LineDataHeader:
    """Read an ASEG-style `.hdr`: one `index name` pair per line."""
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        parts = raw.split(None, 1)
        if len(parts) != 2 or not parts[0].strip().isdigit():
            continue
        names.append(parts[1].strip())
    if names and names[-1].lower().startswith("carriage"):
        names.pop()
    if not names:
        raise ValueError(f"{path} lists no columns")

    lowered = [name.lower() for name in names]

    def find(*candidates: str) -> int:
        for candidate in candidates:
            if candidate in lowered:
                return lowered.index(candidate)
        raise ValueError(f"the header names no column for {candidates[0]}")

    conductivity = tuple(
        index for index, name in enumerate(lowered) if name.startswith("conductivity:")
    )
    thickness = tuple(index for index, name in enumerate(lowered) if name.startswith("thickness:"))
    if not conductivity:
        raise ValueError("the header names no conductivity columns")
    if len(thickness) not in {len(conductivity), len(conductivity) - 1}:
        raise ValueError(
            f"{len(conductivity)} conductivity columns but {len(thickness)} thicknesses; "
            "a layered model needs one thickness per layer, or one fewer for a half-space base"
        )
    return LineDataHeader(
        columns=tuple(names),
        conductivity=conductivity,
        thickness=thickness,
        line=find("line"),
        easting=find("easting", "x"),
        northing=find("northing", "y"),
        elevation=find("elevation", "ground_elevation", "z"),
    )


class LayeredLineImportService:
    """Read one flight line out of a delivered survey, as a completed run."""

    def inventory(self, request: LayeredLineInventoryRequest) -> LayeredLineInventory:
        """List the flight lines without parsing the models."""
        header = read_header(Path(request.header_path))
        data_path = Path(request.data_path)
        if not data_path.is_file():
            raise ValueError(f"{data_path} does not exist")
        needed = max(header.line, header.easting, header.northing, header.elevation) + 1

        counts: dict[str, int] = {}
        extents: dict[str, list[float]] = {}
        total = 0
        with data_path.open("rb") as stream:
            for raw in stream:
                fields = raw[:_PREFIX_BYTES].split()
                if len(fields) < needed:
                    continue
                try:
                    line = fields[header.line].decode("ascii")
                    easting = float(fields[header.easting])
                    northing = float(fields[header.northing])
                except (UnicodeDecodeError, ValueError):
                    continue
                total += 1
                counts[line] = counts.get(line, 0) + 1
                box = extents.get(line)
                if box is None:
                    extents[line] = [easting, easting, northing, northing]
                else:
                    box[0] = min(box[0], easting)
                    box[1] = max(box[1], easting)
                    box[2] = min(box[2], northing)
                    box[3] = max(box[3], northing)
        if not total:
            raise ValueError(f"{data_path} holds no rows this header can read")

        summaries = tuple(
            FlightLineSummary(
                line=line,
                sounding_count=counts[line],
                easting_min_m=extents[line][0],
                easting_max_m=extents[line][1],
                northing_min_m=extents[line][2],
                northing_max_m=extents[line][3],
            )
            for line in sorted(counts, key=lambda item: (-counts[item], item))
        )
        return LayeredLineInventory(
            lines=summaries,
            total_soundings=total,
            layer_count=header.layer_count,
            columns=header.columns,
        )

    def import_line(
        self, request: LayeredLineImportRequest, run_id: UUID, run_dir: Path
    ) -> tuple[RunSpec, RunResult, ImportedLineData]:
        """Read one line's soundings and write them as OFAG's batch artifacts."""
        header = read_header(Path(request.header_path))
        layers = header.layer_count
        if request.max_soundings * layers > MAX_SECTION_VALUES:
            raise ValueError(
                f"{request.max_soundings} soundings of {layers} layers exceeds the "
                f"{MAX_SECTION_VALUES:,}-value section limit; ask for at most "
                f"{MAX_SECTION_VALUES // layers}"
            )
        data_path = Path(request.data_path)
        if not data_path.is_file():
            raise ValueError(f"{data_path} does not exist")

        matched, rows = _read_line(data_path, header, request.line, request.max_soundings)
        if not rows:
            raise ValueError(f"no soundings on line {request.line!r}")
        decimation = max(1, math.ceil(matched / request.max_soundings))

        locations = np.array([row[0] for row in rows], dtype=float)
        conductivity = np.array([row[1] for row in rows], dtype=float)
        thicknesses = np.array([row[2] for row in rows], dtype=float)
        # A shared depth axis is only honest if the file actually shares one.
        if not np.allclose(thicknesses, thicknesses[0]):
            raise ValueError(
                "this file's layer thicknesses vary between soundings, so its models "
                "do not share one depth axis; importing it would need resampling"
            )
        tops = np.concatenate([[0.0], np.cumsum(thicknesses[0])])[:layers]

        canonical = np.asarray(
            canonicalize_quantity(
                conductivity, request.conductivity_units, QuantityType.CONDUCTIVITY
            ),
            dtype=float,
        )
        canonical_unit = CANONICAL_UNITS[QuantityType.CONDUCTIVITY]
        sounding_ids = np.array([f"{request.line}-{index}" for index in range(len(rows))])

        run_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            run_dir / "stitched_conductivity_section.npz",
            sounding_ids=sounding_ids,
            receiver_locations_m=locations,
            layer_top_depth_m=tops,
            conductivity_s_m=canonical,
        )
        # Also as a plain model over cell centres, so the property histogram and the
        # site model read it the way they read any other result.
        centres = np.repeat(locations, layers, axis=0)
        centre_depths = np.tile(_layer_centres(tops), len(rows))
        centres[:, 2] = centres[:, 2] - centre_depths
        np.save(run_dir / "recovered_model.npy", canonical.reshape(-1))
        np.savez_compressed(
            run_dir / "mesh_geometry.npz",
            cell_centers_m=centres,
            cell_volumes_m3=np.ones(centres.shape[0]),
            active_cells=np.ones(centres.shape[0], dtype=bool),
        )

        spec = RunSpec(
            schema_version="1.1",
            run_id=run_id,
            project_id=request.project_id,
            plugin_id=IMPORT_PLUGIN_ID,
            engine="external",
            dataset=DatasetSpec(
                name=request.name,
                coordinate_convention=request.coordinate_convention,
                physical_quantity=QuantityType.CONDUCTIVITY,
                units=canonical_unit,
            ),
            physics={
                "data_path": str(data_path),
                "header_path": str(request.header_path),
                "line": request.line,
                "soundings_on_line": matched,
                "decimation": decimation,
                "layer_count": layers,
                "declared_units": request.conductivity_units,
            },
        )
        section_artifact = ArtifactManifest(
            artifact_type="stitched_conductivity_section",
            physical_quantity=QuantityType.CONDUCTIVITY,
            units=canonical_unit,
            source_run_id=run_id,
            relative_path=f"{run_id}/stitched_conductivity_section.npz",
        )
        model_artifact = ArtifactManifest(
            artifact_type="recovered_model",
            physical_quantity=QuantityType.CONDUCTIVITY,
            units=canonical_unit,
            source_run_id=run_id,
            relative_path=f"{run_id}/recovered_model.npy",
        )
        geometry_artifact = ArtifactManifest(
            artifact_type="mesh_geometry",
            physical_quantity=QuantityType.LENGTH,
            units="m",
            source_run_id=run_id,
            relative_path=f"{run_id}/mesh_geometry.npz",
        )
        result = RunResult(
            run_id=run_id,
            summary={
                "imported": True,
                "line": request.line,
                "soundings_on_line": matched,
                "soundings_imported": len(rows),
                "decimation": decimation,
                "layers": layers,
                "deepest_layer_top_m": float(tops[-1]),
                "non_positive_values": int((canonical <= 0.0).sum()),
                "units": canonical_unit,
            },
            artifacts=(section_artifact, model_artifact, geometry_artifact),
        )
        imported = ImportedLineData(
            run_id=run_id,
            line=request.line,
            sounding_count=matched,
            imported_sounding_count=len(rows),
            decimation=decimation,
            layer_count=layers,
            bounds_m=(
                float(locations[:, 0].min()),
                float(locations[:, 0].max()),
                float(locations[:, 1].min()),
                float(locations[:, 1].max()),
                float((locations[:, 2] - tops[-1]).min()),
                float(locations[:, 2].max()),
            ),
            deepest_layer_top_m=float(tops[-1]),
            value_minimum=float(canonical.min()),
            value_maximum=float(canonical.max()),
            non_positive_values=int((canonical <= 0.0).sum()),
            units=canonical_unit,
        )
        return spec, result, imported


def _layer_centres(tops: np.ndarray) -> np.ndarray:
    """Depth to the middle of each layer, the bottom one taken as its own top."""
    centres = np.empty_like(tops)
    centres[:-1] = (tops[:-1] + tops[1:]) / 2.0
    centres[-1] = tops[-1]
    return centres


def _read_line(
    data_path: Path, header: LineDataHeader, line: str, max_soundings: int
) -> tuple[int, list[tuple[list[float], list[float], list[float]]]]:
    """Every nth sounding of one flight line, and how many that line holds."""
    wanted = line.encode("ascii")
    matched = 0
    with data_path.open("rb") as stream:
        for raw in stream:
            fields = raw[:_PREFIX_BYTES].split()
            if len(fields) > header.line and fields[header.line] == wanted:
                matched += 1
    if not matched:
        return 0, []

    stride = max(1, math.ceil(matched / max_soundings))
    rows: list[tuple[list[float], list[float], list[float]]] = []
    seen = 0
    with data_path.open("rb") as stream:
        for raw in stream:
            prefix = raw[:_PREFIX_BYTES].split()
            if len(prefix) <= header.line or prefix[header.line] != wanted:
                continue
            index = seen
            seen += 1
            if index % stride:
                continue
            fields = raw.split()
            try:
                location = [
                    float(fields[header.easting]),
                    float(fields[header.northing]),
                    float(fields[header.elevation]),
                ]
                conductivity = [float(fields[index_]) for index_ in header.conductivity]
                thickness = [float(fields[index_]) for index_ in header.thickness]
            except (IndexError, ValueError) as error:
                raise ValueError(f"row {seen} of line {line} is not readable: {error}") from error
            rows.append((location, conductivity, thickness))
    return matched, rows
