"""What has to hold about pyGIMLi before a resistivity inversion is dispatched."""

import numpy as np

from ofag.core.conventions import ConventionCheck, ConventionResult

__all__ = ["halfspace_apparent_resistivity", "electrode_order_within_a_pair", "checks"]

#: The halfspace both checks are run over.
_RESISTIVITY = 100.0
#: A Wenner-like spread: 24 electrodes, 5 m apart, which is the geometry the case this
#: was written for uses.
_ELECTRODES = 24
_SPACING = 5.0

#: How far from the halfspace a correct engine is allowed to land.
_TOLERANCE = 0.02


def _electrodes() -> np.ndarray:
    return np.column_stack(
        [np.arange(_ELECTRODES) * _SPACING, np.zeros(_ELECTRODES), np.zeros(_ELECTRODES)]
    )


def _forward(quadrupoles: np.ndarray) -> np.ndarray:
    """Transfer resistance from pyGIMLi over a uniform halfspace."""
    from pygimli.meshtools import createMesh, createWorld  # type: ignore[import-untyped]
    from pygimli.physics import ert  # type: ignore[import-untyped]

    electrodes = _electrodes()
    span = float(electrodes[:, 0].max() - electrodes[:, 0].min())
    world = createWorld(start=[-span, 0.0], end=[2.0 * span, -1.5 * span], worldMarker=True)
    for position in electrodes:
        world.createNode([position[0], 0.0])
        world.createNode([position[0], -_SPACING / 8.0])
    mesh = createMesh(world, quality=34.0, area=_SPACING**2 / 4.0)

    scheme = ert.createData(elecs=electrodes[:, 0], schemeName="dd")
    scheme.resize(quadrupoles.shape[0])
    for position, token in enumerate("abmn"):
        scheme[token] = quadrupoles[:, position]
    scheme["valid"] = np.ones(quadrupoles.shape[0], dtype=int)
    data = ert.simulate(mesh, scheme=scheme, res=_RESISTIVITY, calcOnly=True, verbose=False)
    # Whatever the engine returns, unaltered.
    return np.asarray(data["u"] / data["i"], dtype=float)


def _geometric_factor(quadrupoles: np.ndarray) -> np.ndarray:
    """K for a surface array over a halfspace, written out here on purpose."""
    e = _electrodes()
    a, b, m, n = (e[quadrupoles[:, i]] for i in range(4))

    def gap(p: np.ndarray, q: np.ndarray) -> np.ndarray:
        return np.asarray(np.linalg.norm(p - q, axis=1), dtype=float)

    return 2.0 * np.pi / (1.0 / gap(a, m) - 1.0 / gap(b, m) - 1.0 / gap(a, n) + 1.0 / gap(b, n))


def halfspace_apparent_resistivity() -> ConventionCheck:
    """Over a uniform halfspace, K times R is the halfspace, at every spacing."""

    def run() -> ConventionResult:
        # Dipole-dipole at four separations, so a convention that happens to hold at one
        # geometry cannot carry the check.
        quadrupoles = np.array([[0, 1, 1 + n, 2 + n] for n in (1, 3, 6, 10)], dtype=int)
        resistance = _forward(quadrupoles)
        recovered = _geometric_factor(quadrupoles) * resistance
        worst = float(np.max(np.abs(recovered / _RESISTIVITY - 1.0)))
        return ConventionResult(
            passed=bool(worst < _TOLERANCE),
            detail=(
                f"over a {_RESISTIVITY:.0f} ohm.m halfspace the engine's resistance times the "
                f"closed-form K gives {np.min(recovered):.2f} to {np.max(recovered):.2f} ohm.m "
                f"across {quadrupoles.shape[0]} spacings, worst departure {100 * worst:.2f}%"
            ),
        )

    return ConventionCheck(
        name="K times R is the halfspace, at every spacing",
        catches=(
            "the engine returning an apparent resistivity where the plugin expects a transfer "
            "resistance, or a geometric factor with the current and potential pairs swapped -- "
            "either of which inverts cleanly to an earth wrong by a constant factor"
        ),
        against=(
            "the closed-form geometric factor for a surface array over a halfspace, written "
            "out in this module rather than taken from the engine"
        ),
        run=run,
    )


def electrode_order_within_a_pair() -> ConventionCheck:
    """Swapping A with B flips the sign of what comes back, and nothing else."""

    def run() -> ConventionResult:
        forward = np.array([[0, 1, 5, 6], [0, 1, 11, 12]], dtype=int)
        swapped = forward[:, [1, 0, 2, 3]]
        as_given = _forward(forward)
        as_swapped = _forward(swapped)
        flipped = np.sign(as_given) != np.sign(as_swapped)
        magnitude = np.max(np.abs(np.abs(as_swapped / as_given) - 1.0))
        passed = bool(flipped.all() and magnitude < _TOLERANCE)
        return ConventionResult(
            passed=passed,
            detail=(
                f"A B M N gives {np.array2string(as_given, precision=5)} and B A M N gives "
                f"{np.array2string(as_swapped, precision=5)}: "
                f"{'sign flips' if flipped.all() else 'THE SIGN DID NOT FLIP'}, magnitude agrees "
                f"to {100 * magnitude:.2f}%"
            ),
        )

    return ConventionCheck(
        name="swapping A and B negates the resistance",
        catches=(
            "a quadrupole whose electrodes were sorted, or a file read as B A M N, which "
            "changes the sign of every measurement the array makes and inverts to an earth "
            "that fits and is wrong"
        ),
        against=(
            "the closed-form K, which negates under this swap and does not change at all "
            "under exchanging the current pair with the potential pair -- so only this "
            "permutation is observable, and the other one is a theorem, not a gap"
        ),
        run=run,
    )


def checks() -> tuple[ConventionCheck, ...]:
    return (halfspace_apparent_resistivity(), electrode_order_within_a_pair())
