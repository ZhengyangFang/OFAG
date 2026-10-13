"""What has to hold about pyGIMLi before a refraction inversion is dispatched."""

from typing import Any

import numpy as np

from ofag.core.conventions import ConventionCheck, ConventionResult

__all__ = [
    "homogeneous_traveltime_is_offset_over_velocity",
    "two_layer_traveltime_follows_the_refraction_equation",
    "checks",
]

#: The spread both checks are run over: 24 geophones 4 m apart, which is the geometry of
#: the survey this was written for.
_SENSORS = 24
_SPACING = 4.0

#: Secondary nodes for the checks.
_SECONDARY_NODES = 3

#: The uniform medium of the first check, in metres per second.
_VELOCITY = 1000.0

#: The two-layer earth of the second check.
_TOP_VELOCITY = 800.0
_BOTTOM_VELOCITY = 3000.0
_INTERFACE_DEPTH = 8.0

#: How far above the closed-form time a converged solver is allowed to land.
_TOLERANCE = 0.03

#: The two-layer check compares against a formula that is itself an approximation near
#: the crossover, so it is read only well beyond it.
_CROSSOVER_MARGIN = 2.0


def _scheme() -> tuple[Any, np.ndarray]:
    """A single end shot into the whole spread, and the offsets it gives."""
    import pygimli as pg  # type: ignore[import-untyped]

    positions = np.arange(_SENSORS) * _SPACING
    data = pg.DataContainer()
    for x in positions:
        data.createSensor([float(x), 0.0])
    data.registerSensorIndex("s")
    data.registerSensorIndex("g")
    receivers = np.arange(1, _SENSORS)
    data.resize(receivers.size)
    data["s"] = np.zeros(receivers.size, dtype=int).tolist()
    data["g"] = receivers.tolist()
    return data, positions[receivers]


def _mesh(layered: bool) -> Any:
    """A box under the spread, optionally cut by a horizontal interface."""
    import pygimli as pg

    span = (_SENSORS - 1) * _SPACING
    world = pg.meshtools.createWorld(
        start=[-span * 0.2, 0.0],
        end=[span * 1.2, -span * 0.5],
        layers=[-_INTERFACE_DEPTH] if layered else None,
    )
    return pg.meshtools.createMesh(world, quality=33.0, area=span / 6.0)


def _forward(mesh: Any, scheme: Any, velocity_by_marker: dict[int, float]) -> np.ndarray:
    """Traveltimes for a per-marker velocity, in seconds."""
    import numpy as np_
    import pygimli.physics.traveltime as tt  # type: ignore[import-untyped]

    markers = [int(m) for m in mesh.cellMarkers()]
    velocity = np_.asarray([velocity_by_marker.get(m, _VELOCITY) for m in markers], dtype=float)
    data = tt.simulate(
        mesh, scheme=scheme, vel=velocity, secNodes=_SECONDARY_NODES, noiseLevel=0.0, verbose=False
    )
    return np_.asarray(data["t"], dtype=float)


def homogeneous_traveltime_is_offset_over_velocity() -> ConventionCheck:
    """In a uniform medium the first arrival is the direct wave, at every offset."""

    def run() -> ConventionResult:
        scheme, offsets = _scheme()
        modelled = _forward(_mesh(layered=False), scheme, {1: _VELOCITY, 2: _VELOCITY})
        expected = offsets / _VELOCITY
        excess = modelled / expected - 1.0
        worst = float(np.max(np.abs(excess)))
        return ConventionResult(
            passed=bool(worst < _TOLERANCE and np.all(excess > -_TOLERANCE)),
            detail=(
                f"over a {_VELOCITY:.0f} m/s halfspace at {_SECONDARY_NODES} secondary nodes the "
                f"engine returns traveltimes {100 * float(np.min(excess)):+.2f}% to "
                f"{100 * float(np.max(excess)):+.2f}% from offset over velocity, across offsets "
                f"{offsets.min():.0f} to {offsets.max():.0f} m; a shortest-path solver may be "
                f"slow but not fast"
            ),
        )

    return ConventionCheck(
        name="a direct wave takes offset over velocity",
        catches=(
            "the engine reading a velocity as a slowness or returning milliseconds, either of "
            "which inverts cleanly to a section wrong by a reciprocal or by a thousand -- and a "
            "shortest-path solver left with too few secondary nodes, which is slow everywhere "
            "and reports nothing"
        ),
        against=(
            "offset divided by velocity, which is the traveltime of a straight ray and needs no "
            "solver at all"
        ),
        run=run,
    )


def two_layer_traveltime_follows_the_refraction_equation() -> ConventionCheck:
    """Beyond the crossover the arrival is a head wave, at the textbook time."""

    def run() -> ConventionResult:
        critical = np.arcsin(_TOP_VELOCITY / _BOTTOM_VELOCITY)
        intercept = 2.0 * _INTERFACE_DEPTH * np.cos(critical) / _TOP_VELOCITY
        crossover = (
            2.0
            * _INTERFACE_DEPTH
            * np.sqrt((_BOTTOM_VELOCITY + _TOP_VELOCITY) / (_BOTTOM_VELOCITY - _TOP_VELOCITY))
        )
        scheme, offsets = _scheme()
        modelled = _forward(_mesh(layered=True), scheme, {1: _TOP_VELOCITY, 2: _BOTTOM_VELOCITY})
        far = offsets > _CROSSOVER_MARGIN * crossover
        expected = offsets[far] / _BOTTOM_VELOCITY + intercept
        excess = modelled[far] / expected - 1.0
        worst = float(np.max(np.abs(excess)))
        return ConventionResult(
            passed=bool(far.any() and worst < _TOLERANCE),
            detail=(
                f"over {_TOP_VELOCITY:.0f} m/s on {_BOTTOM_VELOCITY:.0f} m/s at "
                f"{_INTERFACE_DEPTH:.0f} m the crossover is {crossover:.1f} m and the head-wave "
                f"intercept {1e3 * intercept:.2f} ms; beyond {_CROSSOVER_MARGIN * crossover:.0f} m "
                f"the engine is {100 * float(np.min(excess)):+.2f}% to "
                f"{100 * float(np.max(excess)):+.2f}% from that line over {int(far.sum())} offsets"
            ),
        )

    return ConventionCheck(
        name="beyond the crossover the arrival is the head wave",
        catches=(
            "an engine that never refracts -- a solver confined to the top layer, or a mesh "
            "whose markers never reached the forward operator, both of which return a plausible "
            "direct-wave curve and invert to a section with no interface in it"
        ),
        against=(
            "the two-layer refraction equation, x over v2 plus twice the depth times the cosine "
            "of the critical angle over v1, written out here rather than taken from the engine"
        ),
        run=run,
    )


def checks() -> tuple[ConventionCheck, ...]:
    return (
        homogeneous_traveltime_is_offset_over_velocity(),
        two_layer_traveltime_follows_the_refraction_equation(),
    )
