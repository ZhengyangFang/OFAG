"""Convert between OFAG's elastic parameters and Deepwave's, and propagate."""

from dataclasses import dataclass
from typing import Any

import numpy as np

ENGINE = "deepwave"

#: Deepwave's 2D plane is (y, x) with `y` running downwards into the ground.
VERTICAL_AXIS = "y"
ALONG_LINE_AXIS = "x"

#: Below this shear velocity a solid is not one.
MINIMUM_SHEAR_VELOCITY_M_S = 1.0


@dataclass(frozen=True)
class LameModel:
    """An elastic model in the parameters Deepwave actually takes."""

    lamb: np.ndarray
    mu: np.ndarray
    buoyancy: np.ndarray

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self.lamb.shape)


def to_lame(vp_m_s: np.ndarray, vs_m_s: np.ndarray, density_kg_m3: np.ndarray) -> LameModel:
    """OFAG's velocities and density as Lamé parameters and buoyancy."""
    if not (vp_m_s.shape == vs_m_s.shape == density_kg_m3.shape):
        raise ValueError(
            "vp, vs and density must share a shape, got "
            f"{vp_m_s.shape}, {vs_m_s.shape} and {density_kg_m3.shape}"
        )
    for name, values in (
        ("vp", vp_m_s),
        ("vs", vs_m_s),
        ("density", density_kg_m3),
    ):
        if not np.isfinite(values).all():
            raise ValueError(f"{name} contains non-finite values")
    if float(vs_m_s.min()) < MINIMUM_SHEAR_VELOCITY_M_S:
        raise ValueError(
            f"the model reaches a shear velocity of {float(vs_m_s.min()):g} m/s; the elastic "
            "solver's free surface is unstable in a fluid, so give every cell a solid vs"
        )
    if float(density_kg_m3.min()) <= 0.0:
        raise ValueError("density must be positive everywhere")

    mu = density_kg_m3 * vs_m_s**2
    lamb = density_kg_m3 * vp_m_s**2 - 2.0 * mu
    # lamb < 0 means vp < sqrt(2) vs, a Poisson ratio below zero.
    if float(lamb.min()) <= 0.0:
        raise ValueError(
            "the model implies a non-positive first Lame parameter somewhere, which means "
            "vp is below sqrt(2) times vs; check that vp and vs were not exchanged"
        )
    return LameModel(
        lamb=np.asarray(lamb, dtype=float),
        mu=np.asarray(mu, dtype=float),
        buoyancy=np.asarray(1.0 / density_kg_m3, dtype=float),
    )


def from_lame(model: LameModel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lamé parameters back to velocities and density, for publishing a result."""
    density = 1.0 / model.buoyancy
    vs = np.sqrt(np.maximum(model.mu, 0.0) / density)
    vp = np.sqrt(np.maximum(model.lamb + 2.0 * model.mu, 0.0) / density)
    return (
        np.asarray(vp, dtype=float),
        np.asarray(vs, dtype=float),
        np.asarray(density, dtype=float),
    )


def grid_indices(
    positions_m: np.ndarray, origin_m: tuple[float, float], spacing_m: float, shape: tuple[int, int]
) -> np.ndarray:
    """Source or receiver positions as (depth, along-line) grid indices."""
    if positions_m.ndim != 2 or positions_m.shape[1] != 2:
        raise ValueError("positions must be an (n, 2) array of along-line distance and depth")
    along = (positions_m[:, 0] - origin_m[0]) / spacing_m
    down = (positions_m[:, 1] - origin_m[1]) / spacing_m
    indices = np.column_stack([np.rint(down), np.rint(along)]).astype(np.int64)
    outside = (
        (indices[:, 0] < 0)
        | (indices[:, 0] >= shape[0])
        | (indices[:, 1] < 0)
        | (indices[:, 1] >= shape[1])
    )
    if outside.any():
        first = int(np.flatnonzero(outside)[0])
        raise ValueError(
            f"position {first} at {positions_m[first, 0]:g} m along and "
            f"{positions_m[first, 1]:g} m deep falls outside a "
            f"{shape[0]} by {shape[1]} grid; extend the model rather than moving the station"
        )
    return indices


def propagate(
    lamb: Any,
    mu: Any,
    buoyancy: Any,
    *,
    spacing_m: float,
    time_step_s: float,
    wavelet: Any,
    source_indices: Any,
    receiver_indices: Any,
    peak_frequency_hz: float,
    pml_cells: int = 20,
    free_surface: bool = True,
) -> Any:
    """One elastic shot, as the vertical particle velocity at the receivers."""
    from deepwave import elastic  # type: ignore[import-untyped]

    top = 0 if free_surface else pml_cells
    outputs = elastic(
        lamb,
        mu,
        buoyancy,
        spacing_m,
        time_step_s,
        source_amplitudes_y=wavelet,
        source_locations_y=source_indices,
        receiver_locations_y=receiver_indices,
        pml_freq=peak_frequency_hz,
        pml_width=[top, pml_cells, pml_cells, pml_cells],
    )
    # Deepwave returns its wavefield state followed by one record per receiver
    # component, and the empty ones for components nobody asked for.
    nt = int(wavelet.shape[-1])
    records = [
        tensor
        for tensor in outputs
        if getattr(tensor, "ndim", 0) == 3 and tensor.numel() and int(tensor.shape[-1]) == nt
    ]
    if len(records) != 1:
        raise ValueError(
            f"expected one receiver record from the solver, got {len(records)}; "
            "the engine's output layout has changed"
        )
    return records[0]
