"""A recovered model, and the cells it is actually defined on."""

from dataclasses import dataclass

import numpy as np

__all__ = ["CellModel"]


@dataclass(frozen=True)
class CellModel:
    """Values on cells, with each cell's centre and volume beside them."""

    values: np.ndarray
    centres: np.ndarray
    volumes: np.ndarray
    #: Each cell's width along each axis, when the run recorded them.
    widths: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not (len(self.values) == len(self.centres) == len(self.volumes)):
            raise ValueError(
                "a cell model needs one value, one centre and one volume per cell, got "
                f"{len(self.values)}, {len(self.centres)} and {len(self.volumes)}"
            )
        if self.centres.ndim != 2 or self.centres.shape[1] != 3:
            raise ValueError(f"cell centres must be (cells, 3), got {self.centres.shape}")
        if np.any(self.volumes <= 0):
            raise ValueError("cell volumes must be positive")
        if self.widths is not None and self.widths.shape != self.centres.shape:
            raise ValueError(
                f"cell widths must match the centres at {self.centres.shape}, "
                f"got {self.widths.shape}"
            )

    @classmethod
    def on_active_cells(
        cls,
        values: np.ndarray,
        centres: np.ndarray,
        volumes: np.ndarray,
        active_cells: np.ndarray | None = None,
        widths: np.ndarray | None = None,
    ) -> "CellModel":
        """Pair a recovered model with its cells, whichever length it came in."""
        values = np.asarray(values, dtype=float).reshape(-1)
        centres = np.asarray(centres, dtype=float)
        volumes = np.asarray(volumes, dtype=float).reshape(-1)
        widths = None if widths is None else np.asarray(widths, dtype=float)
        if len(values) == len(centres):
            return cls(values, centres, volumes, widths)
        if active_cells is None:
            raise ValueError(
                f"a {len(values)}-value model does not fit a {len(centres)}-cell mesh, "
                "and no active-cell mask was given to explain the difference"
            )
        mask = np.asarray(active_cells, dtype=bool).reshape(-1)
        if len(mask) != len(centres):
            raise ValueError(
                f"the active-cell mask has {len(mask)} entries for a {len(centres)}-cell mesh"
            )
        if int(mask.sum()) != len(values):
            raise ValueError(
                f"a {len(values)}-value model does not fit {int(mask.sum())} active cells "
                f"of a {len(centres)}-cell mesh"
            )
        return cls(values, centres[mask], volumes[mask], None if widths is None else widths[mask])

    def on_mesh(self, active_cells: np.ndarray, fill: float = float("nan")) -> np.ndarray:
        """The values put back on the whole mesh, with `fill` where the model is absent."""
        mask = np.asarray(active_cells, dtype=bool).reshape(-1)
        if int(mask.sum()) != len(self.values):
            raise ValueError(
                f"this model covers {len(self.values)} cells and the mask marks {int(mask.sum())}"
            )
        whole = np.full(len(mask), fill, dtype=float)
        whole[mask] = self.values
        return whole

    @property
    def total_volume(self) -> float:
        return float(self.volumes.sum())

    def volume_share(self, selected: np.ndarray) -> float:
        """The share of the modelled *volume* the selected cells hold."""
        chosen = np.asarray(selected, dtype=bool).reshape(-1)
        if len(chosen) != len(self.values):
            raise ValueError(
                f"the selection has {len(chosen)} entries for {len(self.values)} cells"
            )
        total = self.total_volume
        return float(self.volumes[chosen].sum() / total) if total > 0 else 0.0

    @property
    def cell_sizes(self) -> np.ndarray:
        """One representative side length per cell, from its volume."""
        return np.asarray(np.cbrt(self.volumes), dtype=float)

    @property
    def widths_or_cubes(self) -> np.ndarray:
        """Per-axis cell widths, falling back to the cube of equal volume."""
        if self.widths is not None:
            return self.widths
        return np.repeat(self.cell_sizes[:, None], self.centres.shape[1], axis=1)

    def refined(self, factor: float = 2.0) -> np.ndarray:
        """Cells at or near the finest refinement, which is where the survey is."""
        largest = self.widths_or_cubes.max(axis=1)
        return np.asarray(largest <= float(factor) * float(largest.min()), dtype=bool)

    def planes(self, axis: int) -> np.ndarray:
        """The distinct coordinates cells sit on along one axis, ascending."""
        return np.asarray(np.unique(self.centres[:, axis]), dtype=float)

    def slice_at(self, axis: int, position: float) -> np.ndarray:
        """Which cells a plane at `position` passes through."""
        distance = np.abs(self.centres[:, axis] - float(position))
        return np.asarray(distance <= self.widths_or_cubes[:, axis] / 2.0, dtype=bool)
