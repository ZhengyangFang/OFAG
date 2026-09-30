"""Import an inversion somebody else computed, as a completed run."""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Literal
from uuid import UUID

import numpy as np

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

#: The plugin id an imported result carries.
IMPORT_PLUGIN_ID = "ofag.external.model_import"

#: Mesh and model formats this service can read.
SUPPORTED_FORMATS: tuple[str, ...] = ("ubc",)


class ExternalModelImportRequest(StrictModel):
    """One finished model, with everything the files themselves do not state."""

    mesh_path: str
    model_path: str
    name: str
    #: What the numbers are.  A UBC model file is a bare column of values.
    physical_quantity: QuantityType
    #: The unit those numbers are in.  Never inferred from their magnitude.
    units: str
    coordinate_convention: CoordinateConvention
    project_id: UUID | None = None
    model_format: Literal["ubc"] = "ubc"
    #: The value the author wrote into cells that are not ground -- air above
    #: topography, or padding.
    inactive_value: float | None = None
    #: Who produced the model, for provenance.
    produced_by: str = ""


@dataclass(frozen=True)
class ImportedExternalModel:
    """What the workbench needs to show after an import, and nothing more."""

    run_id: UUID
    source_filename: str
    cell_count: int
    active_cell_count: int
    bounds_m: tuple[float, float, float, float, float, float]
    value_minimum: float
    value_maximum: float
    physical_quantity: str
    units: str


class ExternalModelImportService:
    """Turn a third-party model file into a run the rest of OFAG can read."""

    def dependency_available(self) -> bool:
        # discretize owns UBC-GIF I/O, including the axis order and the top-down z
        # convention.
        return find_spec("discretize") is not None

    def import_model(
        self, request: ExternalModelImportRequest, run_id: UUID, run_dir: Path
    ) -> tuple[RunSpec, RunResult, ImportedExternalModel]:
        """Read the files, write OFAG's artifacts, and describe the result."""
        import discretize  # type: ignore[import-untyped]

        mesh_path = Path(request.mesh_path)
        model_path = Path(request.model_path)
        for path in (mesh_path, model_path):
            if not path.is_file():
                raise ValueError(f"{path} does not exist")

        mesh = discretize.TensorMesh.read_UBC(str(mesh_path))
        values = np.asarray(mesh.read_model_UBC(str(model_path)), dtype=float)
        if values.size != mesh.n_cells:
            raise ValueError(
                f"the model has {values.size} values but the mesh has {mesh.n_cells} cells"
            )

        centers = np.asarray(mesh.cell_centers, dtype=float)
        volumes = np.asarray(mesh.cell_volumes, dtype=float)
        active = _active_cells(values, request.inactive_value)
        if not active.any():
            raise ValueError(
                f"every cell equals the declared inactive value {request.inactive_value}"
            )
        live = values[active]
        if not np.isfinite(live).all():
            raise ValueError("the model contains non-finite values outside its inactive cells")

        canonical = np.asarray(
            canonicalize_quantity(live, request.units, request.physical_quantity), dtype=float
        )
        canonical_unit = CANONICAL_UNITS[request.physical_quantity]

        directory = run_dir
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "recovered_model.npy", canonical)
        np.savez_compressed(
            directory / "mesh_geometry.npz",
            cell_centers_m=centers,
            cell_volumes_m3=volumes,
            active_cells=active,
        )

        bounds = (
            float(mesh.nodes_x.min()),
            float(mesh.nodes_x.max()),
            float(mesh.nodes_y.min()),
            float(mesh.nodes_y.max()),
            float(mesh.nodes_z.min()),
            float(mesh.nodes_z.max()),
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
                physical_quantity=request.physical_quantity,
                units=canonical_unit,
            ),
            physics={
                "model_format": request.model_format,
                "mesh_path": str(mesh_path),
                "model_path": str(model_path),
                "produced_by": request.produced_by,
                "inactive_value": request.inactive_value,
                "declared_units": request.units,
                "mesh_shape": list(int(size) for size in mesh.shape_cells),
            },
        )
        model_artifact = ArtifactManifest(
            artifact_type="recovered_model",
            physical_quantity=request.physical_quantity,
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
                "source": model_path.name,
                "produced_by": request.produced_by or "not stated",
                "mesh_cells": int(mesh.n_cells),
                "active_cells": int(active.sum()),
                "value_minimum": float(canonical.min()),
                "value_maximum": float(canonical.max()),
                "units": canonical_unit,
            },
            artifacts=(model_artifact, geometry_artifact),
        )
        imported = ImportedExternalModel(
            run_id=run_id,
            source_filename=model_path.name,
            cell_count=int(mesh.n_cells),
            active_cell_count=int(active.sum()),
            bounds_m=bounds,
            value_minimum=float(canonical.min()),
            value_maximum=float(canonical.max()),
            physical_quantity=request.physical_quantity.value,
            units=canonical_unit,
        )
        return spec, result, imported


def _active_cells(values: np.ndarray, inactive_value: float | None) -> np.ndarray:
    """Which cells are ground, according to the value the author declared for air."""
    if inactive_value is None:
        return np.ones(values.shape, dtype=bool)
    if np.isnan(inactive_value):
        return np.asarray(~np.isnan(values), dtype=bool)
    return np.asarray(values != inactive_value, dtype=bool)
