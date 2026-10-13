"""Turning declared rock classes into the Gaussian mixture SimPEG's PGI wants."""

import warnings
from typing import Any

import numpy as np

__all__ = ["declared_mixture"]


def declared_mixture(
    mesh: Any,
    active_cells: np.ndarray,
    means: np.ndarray,
    standard_deviations: np.ndarray,
    proportions: np.ndarray,
) -> Any:
    """Build a `WeightedGaussianMixture` holding exactly the declared classes."""
    from simpeg.utils import WeightedGaussianMixture  # type: ignore[import-untyped]
    from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]

    means = np.atleast_2d(np.asarray(means, dtype=float).T).T
    standard_deviations = np.atleast_2d(np.asarray(standard_deviations, dtype=float).T).T
    proportions = np.asarray(proportions, dtype=float).reshape(-1)
    count, properties = means.shape
    if standard_deviations.shape != means.shape:
        raise ValueError(
            "petrophysical means and standard deviations must have the same shape, got "
            f"{means.shape} and {standard_deviations.shape}"
        )
    if proportions.size != count:
        raise ValueError(
            f"{count} petrophysical classes need {count} proportions, got {proportions.size}"
        )
    if np.any(standard_deviations <= 0):
        raise ValueError("petrophysical standard deviations must be positive")
    active_count = int(np.count_nonzero(active_cells))
    if active_count < count:
        raise ValueError(
            f"a {count}-class mixture needs at least {count} active cells, mesh has {active_count}"
        )

    mixture = WeightedGaussianMixture(
        n_components=count,
        mesh=mesh,
        actv=active_cells,
        covariance_type="full",
        means_init=means,
        n_init=1,
        max_iter=1,
        random_state=0,
    )
    # The single iteration does not converge, and scikit-learn says so.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        mixture.fit(_scaffold_sample(means, proportions, active_count))

    covariances = np.zeros((count, properties, properties))
    diagonal = np.arange(properties)
    covariances[:, diagonal, diagonal] = np.square(standard_deviations)

    mixture.means_ = means
    mixture.covariances_ = covariances
    mixture.weights_ = proportions
    # Last, and nothing after it.
    mixture.compute_clusters_precisions()
    return mixture


def _scaffold_sample(means: np.ndarray, proportions: np.ndarray, count: int) -> np.ndarray:
    """Data for the throwaway fit: the declared means in the declared shares."""
    edges = np.cumsum(proportions) / proportions.sum()
    position = (np.arange(count, dtype=float) + 0.5) / count
    chosen = np.minimum(np.searchsorted(edges, position), means.shape[0] - 1)
    return np.asarray(means[chosen], dtype=float)
