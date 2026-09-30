"""Unstructured mesh construction and portable export for pyGIMLi runs."""

from typing import Any

import numpy as np


def build_parameter_mesh(
    electrodes_m: np.ndarray,
    *,
    dimension: int,
    node_spacing_fraction: float,
    depth_m: float | None,
    boundary_fraction: float,
    quality: float,
    max_cell_area_m2: float | None,
) -> Any:
    """Create the inversion mesh from electrode geometry."""
    # Imported here so `ofag plugins` works without pyGIMLi installed.
    import pygimli as pg  # type: ignore[import-untyped]

    if dimension == 2:
        sensors = np.column_stack([electrodes_m[:, 0], electrodes_m[:, 2]])
    else:
        sensors = electrodes_m
    outline = pg.meshtools.createParaMeshPLC(
        sensors,
        paraDX=node_spacing_fraction,
        paraDepth=depth_m if depth_m is not None else 0.0,
        paraBoundary=boundary_fraction,
        paraMaxCellSize=max_cell_area_m2 if max_cell_area_m2 is not None else 0.0,
    )
    return pg.meshtools.createMesh(
        outline, quality=quality, area=max_cell_area_m2 if max_cell_area_m2 is not None else 0.0
    )


def build_traveltime_mesh(
    sensors_m: np.ndarray,
    *,
    node_spacing_fraction: float,
    depth_m: float | None,
    quality: float,
    max_cell_area_m2: float | None,
) -> Any:
    """Create the inversion mesh for a refraction survey."""
    import pygimli as pg

    return pg.meshtools.createParaMesh(
        np.column_stack([sensors_m[:, 0], sensors_m[:, 2]]),
        paraDX=node_spacing_fraction,
        paraDepth=depth_m if depth_m is not None else 0.0,
        paraMaxCellSize=max_cell_area_m2 if max_cell_area_m2 is not None else 0.0,
        quality=quality,
        # No cell outside the parameter domain, so every cell has a model index.
        paraBoundary=0,
        boundary=0,
    )


#: Elevation spread, in metres, below which a line counts as flat.
FLAT_TOLERANCE_M = 0.05


def geometric_factors(ert: Any, data: Any, electrodes_m: np.ndarray) -> np.ndarray:
    """K for the quadrupoles the container currently holds."""
    relief = float(np.ptp(electrodes_m[:, 2])) if len(electrodes_m) else 0.0
    numerical = relief > FLAT_TOLERANCE_M
    return np.asarray(ert.createGeometricFactors(data, numerical=numerical), dtype=float)


def mesh_geometry(mesh: Any) -> dict[str, np.ndarray]:
    """Export a pyGIMLi mesh as engine-neutral arrays."""
    nodes = np.asarray([[node.x(), node.y(), node.z()] for node in mesh.nodes()], dtype=float)
    cells = np.asarray(
        [[node.id() for node in cell.nodes()] for cell in mesh.cells()], dtype=np.int64
    )
    centers = np.asarray(mesh.cellCenters(), dtype=float)
    return {
        "nodes_m": nodes,
        "cell_nodes": cells,
        "cell_centers_m": centers,
        "cell_sizes": np.asarray(mesh.cellSizes(), dtype=float),
    }
