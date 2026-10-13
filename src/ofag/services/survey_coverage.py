"""Measured station positions in the project's declared coordinate system."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ofag.services.project_service import ProjectService
from ofag.services.run_configuration import uses_dataset
from ofag.services.run_service import RunService


@dataclass(frozen=True)
class Coverage:
    crs: str
    stations: dict[str, np.ndarray]
    unavailable: dict[str, str]


def project_coverage(folder: Path) -> Coverage:
    from ofag.core.schemas import ProjectRecord, RunState

    record = ProjectRecord.model_validate_json((folder / "project.json").read_text("utf-8"))
    workspace = ProjectService(folder.parent).workspace(record.project_id)
    runs = RunService(artifact_root=folder / "runs")
    records = runs.list_runs()
    stations, unavailable = {}, {}
    names = [dataset.name for dataset in workspace.datasets]
    for dataset in workspace.datasets:
        if dataset.kind.value == "topography":
            continue
        label = (
            dataset.name
            if names.count(dataset.name) == 1
            else (f"{dataset.name} ({str(dataset.dataset_id)[:8]})")
        )
        try:
            points = None
            path = dataset.payload.get("canonical_observations_path")
            if isinstance(path, str) and dataset.kind.value in {"gravity", "magnetics"}:
                data = np.genfromtxt(path, delimiter=",", names=True, dtype=float)
                if {"x_m", "y_m"}.issubset(data.dtype.names or ()):
                    points = np.column_stack(
                        [np.atleast_1d(data["x_m"]), np.atleast_1d(data["y_m"])]
                    )
            if points is None:
                for run in records:
                    if run.state is not RunState.SUCCEEDED or not uses_dataset(run.spec, dataset):
                        continue
                    if (
                        run.spec.dataset.coordinate_convention.crs
                        != record.coordinate_convention.crs
                    ):
                        continue
                    section = runs.run_dir(run.spec.run_id) / "stitched_conductivity_section.npz"
                    if section.is_file():
                        with np.load(section, allow_pickle=False) as arrays:
                            points = (
                                arrays["receiver_locations_m"][:, :2].copy()
                                if ("receiver_locations_m" in arrays.files)
                                else np.column_stack([arrays["easting_m"], arrays["northing_m"]])
                            )
                        break
            if points is None:
                unavailable[label] = "No project map coordinates; profile alignment required."
                continue
            points = points[np.isfinite(points).all(axis=1)]
            if not len(points):
                unavailable[label] = "No finite station positions."
                continue
            stations[label] = points
        except (OSError, ValueError, KeyError) as error:
            unavailable[label] = str(error)
    return Coverage(record.coordinate_convention.crs, stations, unavailable)
