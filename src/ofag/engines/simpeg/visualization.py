"""Portable figure generation through SimPEG/Discretize plotting helpers."""

from pathlib import Path
from typing import Any

import numpy as np


def _pyplot() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot

    return pyplot


def render_observation_map(
    locations_m: np.ndarray,
    values: np.ndarray,
    path: Path,
    *,
    title: str,
    unit: str,
) -> None:
    """Render an XY data map using SimPEG's interpolation-aware helper."""
    plt = _pyplot()
    from simpeg import utils  # type: ignore[import-untyped]

    figure, axis = plt.subplots(figsize=(6, 4.5), constrained_layout=True)
    try:
        contours, _ = utils.plot2Ddata(
            np.asarray(locations_m, dtype=float),
            np.asarray(values, dtype=float),
            ax=axis,
            dataloc=True,
        )
        figure.colorbar(contours, ax=axis, label=unit)
    except (ValueError, np.linalg.LinAlgError):
        scatter = axis.scatter(
            locations_m[:, 0], locations_m[:, 1], c=values, cmap="viridis", edgecolors="black"
        )
        figure.colorbar(scatter, ax=axis, label=unit)
    axis.set_title(title)
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def render_active_model_slice(
    mesh: Any,
    active_cells: np.ndarray,
    values: np.ndarray,
    path: Path,
    *,
    title: str,
    unit: str,
) -> None:
    """Render one horizontal model slice through Discretize's mesh plotting API."""
    plt = _pyplot()

    full_model = np.full(int(mesh.nC), np.nan, dtype=float)
    full_model[np.asarray(active_cells, dtype=bool)] = np.asarray(values, dtype=float)
    figure, axis = plt.subplots(figsize=(6, 4.5), constrained_layout=True)
    try:
        if hasattr(mesh, "shape_cells"):
            index = int(mesh.shape_cells[2] // 2)
            image = mesh.plot_slice(full_model, normal="Z", ind=index, ax=axis, grid=False)
            mappable = image[0] if isinstance(image, tuple) else image
            figure.colorbar(mappable, ax=axis, label=unit)
        else:
            raise ValueError("mesh does not expose slice plotting")
    except (AttributeError, IndexError, TypeError, ValueError):
        centers = np.asarray(mesh.cell_centers, dtype=float)[np.asarray(active_cells, dtype=bool)]
        scatter = axis.scatter(
            centers[:, 0], centers[:, 1], c=np.asarray(values, dtype=float), cmap="viridis"
        )
        figure.colorbar(scatter, ax=axis, label=unit)
    axis.set_title(title)
    axis.set_xlabel("Easting (m)")
    axis.set_ylabel("Northing (m)")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)
