"""The cell grid a geological model is written on, hung on measured ground."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from pydantic import Field, model_validator

from ofag.agent.gates import Terrain, measure_terrain, refuse_unmeasured_terrain
from ofag.core.schemas import StrictModel

__all__ = ["CellGridSpec", "CellGrid", "build_cell_grid", "save_grid", "load_grid"]

#: The lowest and highest the solid surface of the Earth reaches, in metres: the
#: Challenger Deep and the summit of Everest.
EARTH_SURFACE_M = (-11_034.0, 8_849.0)

#: Values rasters and tables write where they have nothing to write. -9999 sits inside
#: the range above, so the range alone does not catch the commonest one; a surface is
#: never measured to exactly one of these.
NODATA_SENTINELS = (-9999.0, -99999.0, -999999.0, -32768.0, -32767.0)


class CellGridSpec(StrictModel):
    """A box, a cell size, and where the ground is."""

    name: str = Field(min_length=1, max_length=120)
    min_x_m: float
    max_x_m: float
    min_y_m: float
    max_y_m: float
    #: Easting, northing and vertical cell size, in metres.
    cell_m: tuple[float, float, float]
    #: How far down the box goes, below the ground rather than below a datum.
    depth_m: float = Field(gt=0.0)

    #: Ground elevations at scattered points, in project coordinates.
    ground_easting_m: tuple[float, ...] = ()
    ground_northing_m: tuple[float, ...] = ()
    ground_elevation_m: tuple[float, ...] = ()
    #: Where those elevations came from.
    ground_source: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def the_box_and_the_ground_are_usable(self) -> "CellGridSpec":
        if self.max_x_m <= self.min_x_m or self.max_y_m <= self.min_y_m:
            raise ValueError(
                f"{self.name} has an extent of "
                f"{self.max_x_m - self.min_x_m} by {self.max_y_m - self.min_y_m} m"
            )
        if any(size <= 0 for size in self.cell_m):
            raise ValueError(f"{self.name} has a cell of {self.cell_m}")
        counts = {
            len(self.ground_easting_m),
            len(self.ground_northing_m),
            len(self.ground_elevation_m),
        }
        if len(counts) != 1:
            raise ValueError(
                f"{self.name} gives {len(self.ground_easting_m)} eastings, "
                f"{len(self.ground_northing_m)} northings and "
                f"{len(self.ground_elevation_m)} elevations for its ground"
            )
        if not self.ground_elevation_m:
            raise ValueError(
                f"{self.name} says nothing about where the ground is. A volume on a plane "
                "renders, reports unit shares and is read as geology exactly like one that is "
                "not (F034). Give an elevation -- one point means flat, which is an answer."
            )
        # F031 in the ground.
        low, high = EARTH_SURFACE_M
        bad = [
            (i, z)
            for i, z in enumerate(self.ground_elevation_m)
            if not np.isfinite(z) or not low <= z <= high or z in NODATA_SENTINELS
        ]
        if bad:
            shown = ", ".join(f"point {i} at {z}" for i, z in bad[:5])
            raise ValueError(
                f"{self.name} has {len(bad)} ground elevation(s) that are not a surface: "
                f"{shown}. A value outside {low:g} to {high:g} m, or one of the conventional "
                "nodata values, is a null written as a number (F031) -- drop those points or "
                "resample them from somewhere the source has data."
            )
        return self


@dataclass(frozen=True)
class CellGrid:
    """A built grid, and what its ground was measured to be."""

    grid_id: UUID
    name: str
    #: (n, 3) easting, northing, elevation. Elevation, not depth.
    cell_centres_m: np.ndarray
    cell_volume_m3: np.ndarray
    #: Positive downward from the ground above each cell. The other quantity.
    depth_below_ground_m: np.ndarray
    ground_elevation_m: np.ndarray
    #: How far each cell's column was from the ground point it used (F006).
    ground_distance_m: np.ndarray
    terrain: Terrain
    axes: tuple[int, int, int]

    @property
    def cells(self) -> int:
        return int(self.cell_centres_m.shape[0])

    def summary(self) -> dict[str, object]:
        """What a reader needs to know before building anything on it."""
        return {
            "grid_id": str(self.grid_id),
            "name": self.name,
            "cells": self.cells,
            "axes": {"easting": self.axes[0], "northing": self.axes[1], "depth": self.axes[2]},
            "ground": {
                "source": self.terrain.source,
                "relief_m": self.terrain.relief_m,
                "quantum_m": self.terrain.quantum_m,
                "distinct": self.terrain.distinct,
                # None for continuous ground, which has no steps to count.
                "steps_of_relief": None if self.terrain.quantum_m == 0 else self.terrain.steps,
                "mostly_its_own_quantisation": not self.terrain.modellable,
                "lowest_m": float(self.ground_elevation_m.min()),
                "highest_m": float(self.ground_elevation_m.max()),
            },
            "furthest_column_from_a_ground_point_m": float(self.ground_distance_m.max()),
            "depth_below_ground_m": {
                "shallowest": float(self.depth_below_ground_m.min()),
                "deepest": float(self.depth_below_ground_m.max()),
            },
        }


def build_cell_grid(spec: CellGridSpec) -> CellGrid:
    """Lay the cells out, hang them on the ground, and measure the ground."""
    dx, dy, dz = spec.cell_m
    east = np.arange(spec.min_x_m, spec.max_x_m, dx) + dx / 2.0
    north = np.arange(spec.min_y_m, spec.max_y_m, dy) + dy / 2.0
    down = np.arange(0.0, spec.depth_m, dz) + dz / 2.0
    # Not `size == 0`: `arange(0, 1000, 2000)` returns one element, and that single
    # cell's centre lands outside the box it is meant to fill.
    width, height = spec.max_x_m - spec.min_x_m, spec.max_y_m - spec.min_y_m
    if dx > width or dy > height or dz > spec.depth_m:
        raise ValueError(
            f"{spec.name} has a cell larger than the box it is meant to fill: "
            f"{spec.cell_m} into {width} by {height} by {spec.depth_m} m"
        )

    columns = np.column_stack([grid.ravel() for grid in np.meshgrid(east, north, indexing="ij")])
    points = np.column_stack(
        [np.asarray(spec.ground_easting_m, float), np.asarray(spec.ground_northing_m, float)]
    )
    elevations = np.asarray(spec.ground_elevation_m, float)
    if len(elevations) == 1:
        # One point is a declared flat surface, and a KD-tree over a single point would
        # report a distance that means nothing.
        column_ground = np.full(columns.shape[0], float(elevations[0]))
        column_distance = np.zeros(columns.shape[0])
    else:
        from scipy.spatial import cKDTree  # type: ignore[import-untyped]

        distance, index = cKDTree(points).query(columns)
        column_ground = elevations[index]
        column_distance = np.asarray(distance, float)

    # A12 before anything is built on it.
    terrain = measure_terrain(spec.name, column_ground, source=spec.ground_source)
    # What the gate returns is a staircase -- ground that is mostly its own quantisation
    # -- to be printed, not refused, and it is printed in the summary.
    refuse_unmeasured_terrain({spec.name: terrain})

    depth = np.tile(down, columns.shape[0])
    repeated = np.repeat(np.arange(columns.shape[0]), down.size)
    centres = np.column_stack(
        [
            columns[repeated, 0],
            columns[repeated, 1],
            column_ground[repeated] - depth,
        ]
    )
    return CellGrid(
        grid_id=uuid4(),
        name=spec.name,
        cell_centres_m=centres,
        cell_volume_m3=np.full(centres.shape[0], float(dx * dy * dz)),
        depth_below_ground_m=depth,
        ground_elevation_m=column_ground[repeated],
        ground_distance_m=column_distance[repeated],
        terrain=terrain,
        axes=(int(east.size), int(north.size), int(down.size)),
    )


def save_grid(grid: CellGrid, root: Path) -> Path:
    """Write the arrays where a later call can find them by id."""
    directory = root / "grids"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{grid.grid_id}.npz"
    np.savez(
        path,
        name=grid.name,
        cell_centres_m=grid.cell_centres_m,
        cell_volume_m3=grid.cell_volume_m3,
        depth_below_ground_m=grid.depth_below_ground_m,
        ground_elevation_m=grid.ground_elevation_m,
        ground_distance_m=grid.ground_distance_m,
        axes=np.asarray(grid.axes),
        terrain_source=grid.terrain.source,
        terrain_relief_m=grid.terrain.relief_m,
        terrain_quantum_m=grid.terrain.quantum_m,
        terrain_count=grid.terrain.count,
        terrain_distinct=grid.terrain.distinct,
        terrain_off_the_grid=grid.terrain.off_the_grid,
    )
    return path


def load_grid(grid_id: UUID, root: Path) -> CellGrid:
    """Read one back, or say plainly that it is not there."""
    path = root / "grids" / f"{grid_id}.npz"
    if not path.exists():
        raise FileNotFoundError(f"no grid {grid_id} under {root}; build one with ofag.cell_grid")
    data = np.load(path, allow_pickle=False)
    return CellGrid(
        grid_id=grid_id,
        name=str(data["name"]),
        cell_centres_m=data["cell_centres_m"],
        cell_volume_m3=data["cell_volume_m3"],
        depth_below_ground_m=data["depth_below_ground_m"],
        ground_elevation_m=data["ground_elevation_m"],
        ground_distance_m=data["ground_distance_m"],
        terrain=Terrain(
            name=str(data["name"]),
            source=str(data["terrain_source"]),
            relief_m=float(data["terrain_relief_m"]),
            quantum_m=float(data["terrain_quantum_m"]),
            count=int(data["terrain_count"]),
            distinct=int(data["terrain_distinct"]),
            off_the_grid=int(data["terrain_off_the_grid"]),
        ),
        axes=tuple(int(value) for value in data["axes"]),  # type: ignore[arg-type]
    )
