"""Read individual soundings or mesh results for audited interpretation."""

from typing import Any
from uuid import UUID

import numpy as np

from ofag.services.interpretation_service import CellSection, LayeredSection


def read_section(runs: Any, run_id: UUID, request: dict[str, Any]) -> CellSection | LayeredSection:
    result = runs.result(run_id)
    if result is None:
        raise ValueError("The source run has no result.")
    bar = request.get("chi_squared_at_most")
    if bar is not None:
        chi = result.summary.get("chi_squared")
        if chi is None or not np.isfinite(float(chi)) or float(chi) > float(bar):
            raise ValueError("The source has no measured fit within the requested limit.")

    def artifact(kind: str) -> Any:
        item = next((a for a in result.artifacts if a.artifact_type == kind), None)
        if item is None:
            return None
        path = (runs.artifact_root / item.relative_path).resolve()
        if not path.is_relative_to(runs.artifact_root.resolve()):
            raise ValueError("Artifact is outside the project.")
        return path

    root = runs.run_dir(run_id)
    tops = root / "layer_top_depth_m.npy"
    conductivity = root / "recovered_conductivity_s_m.npy"
    if tops.exists() and conductivity.exists():
        location = request.get("location_m")
        if not isinstance(location, list) or len(location) != 2:
            raise ValueError(
                "A single sounding needs location_m: [easting, northing] in project coordinates."
            )
        sigma = np.load(conductivity, allow_pickle=False)
        values = (
            np.where(sigma > 0, 1 / sigma, np.nan) if request.get("as_resistivity", True) else sigma
        )
        return LayeredSection(
            np.array([location[0]]),
            np.array([location[1]]),
            values.reshape(1, -1),
            np.load(tops, allow_pickle=False),
        )
    geometry, recovered = artifact("mesh_geometry"), artifact("recovered_model")
    packed = None
    if geometry is None:
        packed = artifact("model")
        if packed is not None and packed.suffix == ".npz":
            geometry = packed
    if geometry is None or (recovered is None and packed is None):
        raise ValueError("The run has no supported layered or mesh model artifact.")
    with np.load(geometry, allow_pickle=False) as data:
        if "cell_centers_m" not in data.files:
            raise ValueError("The model artifact does not contain mesh coordinates.")
        centres = data["cell_centers_m"].copy()
        active = (
            data["active_cells"].astype(bool)
            if "active_cells" in data.files
            else np.ones(len(centres), dtype=bool)
        )
        values = data["conductivity_s_m"].ravel(order="F").copy() if packed else None
    if recovered is not None:
        values = np.load(recovered, allow_pickle=False).ravel()
    if values is None:
        raise ValueError("The mesh has no recovered values.")
    if len(values) == len(centres):
        values = values[active]
    centres = centres[active]
    if len(values) != len(centres):
        raise ValueError("Recovered values do not match the active mesh.")
    if not len(centres) or centres.ndim != 2 or centres.shape[1] not in (2, 3):
        raise ValueError("The mesh needs finite 2D or 3D cell centres.")
    if centres.shape[1] == 2:
        centres = np.column_stack([centres, np.zeros(len(centres))])
    if np.ptp(centres[:, 2]) == 0:
        profile = request.get("profile")
        fields = ("origin_easting_m", "origin_northing_m", "azimuth_degrees", "elevation_offset_m")
        if not isinstance(profile, dict) or not all(key in profile for key in fields):
            raise ValueError(
                "A 2D mesh needs profile origin_easting_m, origin_northing_m, "
                "azimuth_degrees (clockwise from north), and elevation_offset_m."
            )
        angle = np.deg2rad(float(profile["azimuth_degrees"]))
        x, z = centres[:, 0].copy(), centres[:, 1].copy()
        centres = np.column_stack(
            [
                float(profile["origin_easting_m"]) + x * np.sin(angle),
                float(profile["origin_northing_m"]) + x * np.cos(angle),
                z + float(profile["elevation_offset_m"]),
            ]
        )
    if not np.isfinite(centres).all():
        raise ValueError("Model coordinates must be finite.")
    return CellSection(centres, values)
