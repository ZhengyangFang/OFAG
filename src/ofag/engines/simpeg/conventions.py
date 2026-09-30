"""Convention checks shared by the SimPEG plugins."""

from collections.abc import Callable
from typing import Any

import numpy as np

from ofag.core.conventions import ConventionCheck, ConventionResult
from ofag.engines.simpeg.units import gravity_anomaly_from_simpeg

__all__ = [
    "MU0",
    "gravity_sign",
    "potential_field_placement",
    "layered_tem_layer_order",
    "layered_mt_layer_order",
    "layered_mt_halfspace",
]

MU0 = 4.0e-7 * np.pi

#: A plugin's own forward model, as the layered checks consume it: thicknesses and
#: resistivities surface first, one frequency, one impedance.
Predict = Callable[[list[float], list[float], float], complex]

_CELL = 200.0
_COUNT = 10
#: Deliberately off-centre and off the diagonal.
_EAST, _NORTH, _DEPTH = 600.0, 200.0, 600.0


def _probe_mesh() -> Any:
    from discretize import TensorMesh  # type: ignore[import-untyped]

    return TensorMesh(
        [[(_CELL, _COUNT)], [(_CELL, _COUNT)], [(_CELL, _COUNT)]],
        origin=[-_CELL * _COUNT / 2, -_CELL * _COUNT / 2, -_CELL * _COUNT],
    )


def _stations() -> tuple[np.ndarray, np.ndarray]:
    span = np.arange(-800.0, 801.0, 200.0)
    easting, northing = (grid.ravel() for grid in np.meshgrid(span, span, indexing="ij"))
    return easting, northing


def _block(centres: np.ndarray, east: float, north: float, value: float) -> np.ndarray:
    model = np.zeros(centres.shape[0])
    inside = (
        (np.abs(centres[:, 0] - east) < _CELL)
        & (np.abs(centres[:, 1] - north) < _CELL)
        & (np.abs(centres[:, 2] + _DEPTH) < _CELL)
    )
    model[inside] = value
    return np.asarray(model, dtype=float)


def _gravity_of(east: float, north: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from simpeg import maps  # type: ignore[import-untyped]
    from simpeg.potential_fields import gravity as pf  # type: ignore[import-untyped]

    mesh = _probe_mesh()
    easting, northing = _stations()
    receivers = pf.receivers.Point(
        np.column_stack([easting, northing, np.full(easting.size, 1.0)]), components="gz"
    )
    simulation = pf.simulation.Simulation3DIntegral(
        survey=pf.survey.Survey(pf.sources.SourceField([receivers])),
        mesh=mesh,
        rhoMap=maps.IdentityMap(nP=mesh.n_cells),
        engine="geoana",
    )
    density = _block(np.asarray(mesh.cell_centers), east, north, 1.0)
    return easting, northing, np.asarray(simulation.dpred(density), dtype=float)


def _magnetics_of(east: float, north: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from simpeg import maps
    from simpeg.potential_fields import magnetics as pf

    mesh = _probe_mesh()
    easting, northing = _stations()
    receivers = pf.receivers.Point(
        np.column_stack([easting, northing, np.full(easting.size, 1.0)]), components="tmi"
    )
    # A vertical inducing field, so the anomaly sits over the body rather than displaced
    # by the inclination.
    source = pf.sources.UniformBackgroundField(
        receiver_list=[receivers], amplitude=50_000.0, inclination=90.0, declination=0.0
    )
    simulation = pf.simulation.Simulation3DIntegral(
        survey=pf.survey.Survey(source),
        mesh=mesh,
        chiMap=maps.IdentityMap(nP=mesh.n_cells),
        engine="geoana",
    )
    susceptibility = _block(np.asarray(mesh.cell_centers), east, north, 0.05)
    return easting, northing, np.asarray(simulation.dpred(susceptibility), dtype=float)


def gravity_sign() -> ConventionCheck:
    """A gravity high is more mass, all the way through the stack."""

    def run() -> ConventionResult:
        _, _, gz = _gravity_of(0.0, 0.0)
        anomaly = np.asarray(gravity_anomaly_from_simpeg(gz), dtype=float)
        passed = bool(
            gz.min() < 0.0 and anomaly.max() > 0.0 and np.isclose(anomaly.max(), -gz.min())
        )
        return ConventionResult(
            passed=passed,
            detail=(
                f"over excess mass SimPEG's gz reaches {gz.min():+.4f} mGal and the anomaly "
                f"OFAG inverts reaches {anomaly.max():+.4f}"
            ),
        )

    return ConventionCheck(
        name="a gravity high is more mass",
        catches=(
            "SimPEG's z-up gz reaching the inversion unflipped, which explains a gravity high "
            "by removing mass and leaves every number in the run looking healthy (F001)"
        ),
        against="the sign a Bouguer anomaly has by definition over a body of known excess mass",
        run=run,
    )


def potential_field_placement(physics: str = "gravity") -> ConventionCheck:
    """The anomaly peaks over its source, and not over its transpose."""
    compute = _gravity_of if physics == "gravity" else _magnetics_of

    def run() -> ConventionResult:
        easting, northing, field = compute(_EAST, _NORTH)
        signed = (
            np.asarray(gravity_anomaly_from_simpeg(field), dtype=float)
            if physics == "gravity"
            else field
        )
        peak = int(np.argmax(signed))
        passed = bool(abs(easting[peak] - _EAST) <= _CELL and abs(northing[peak] - _NORTH) <= _CELL)
        return ConventionResult(
            passed=passed,
            detail=(
                f"body at easting {_EAST:+.0f}, northing {_NORTH:+.0f}; the anomaly peaks at "
                f"{easting[peak]:+.0f}, {northing[peak]:+.0f}"
            ),
        )

    return ConventionCheck(
        name=f"the {physics} anomaly peaks over its source",
        catches=(
            "easting and northing transposed, or an axis flipped, between the model vector and "
            "the mesh -- which moves the whole model and changes nothing else"
        ),
        against="the position the body was put at, which only one convention returns",
        run=run,
    )


def layered_tem_layer_order() -> ConventionCheck:
    """Which end of the layer array the time-domain simulation calls the surface."""

    def run() -> ConventionResult:
        from simpeg import maps
        from simpeg.electromagnetics import time_domain as tdem  # type: ignore[import-untyped]

        times = np.geomspace(1e-5, 1e-2, 8)
        receiver = tdem.receivers.PointMagneticFluxTimeDerivative(
            np.array([[0.0, 0.0, 0.0]]), times, orientation="z"
        )
        source = tdem.sources.CircularLoop(
            [receiver],
            location=np.array([0.0, 0.0, 0.0]),
            radius=20.0,
            current=1.0,
            waveform=tdem.sources.StepOffWaveform(),
        )

        def decay(resistivities: list[float]) -> np.ndarray:
            simulation = tdem.Simulation1DLayered(
                survey=tdem.Survey([source]),
                thicknesses=np.array([100.0, 100.0]),
                sigmaMap=maps.IdentityMap(nP=3),
            )
            return np.asarray(
                np.abs(simulation.dpred(1.0 / np.asarray(resistivities, dtype=float))), dtype=float
            )

        uniform = decay([1000.0, 1000.0, 1000.0])
        first = decay([1.0, 1000.0, 1000.0]) / uniform
        last = decay([1000.0, 1000.0, 1.0]) / uniform
        early_first, early_last = float(first[:2].mean()), float(last[:2].mean())
        return ConventionResult(
            passed=bool(early_first > 100.0 and early_last < 10.0),
            detail=(
                f"a 1 ohm.m layer written first moves the earliest gates by x{early_first:.0f} "
                f"and written last by x{early_last:.1f}; the surface is the end that moves "
                "early time"
            ),
        )

    return ConventionCheck(
        name="the layer array is surface first",
        catches=(
            "a layered model handed to the engine upside down, which inverts a different earth, "
            "converges, and reports nothing -- as the magnetotelluric one did (F023)"
        ),
        against="diffusion: a surface conductor dominates early time and a buried one late time",
        run=run,
    )


def mt_analytic_impedance(
    frequency: float, thicknesses: list[float], resistivities: list[float]
) -> complex:
    """The layered impedance from the Wait recursion, written surface first."""
    omega = 2.0 * np.pi * frequency
    conductivities = 1.0 / np.asarray(resistivities, dtype=float)
    wavenumbers = np.sqrt(1j * omega * MU0 * conductivities)
    intrinsic = 1j * omega * MU0 / wavenumbers
    impedance = intrinsic[-1]
    for index in range(len(thicknesses) - 1, -1, -1):
        tangent = np.tanh(wavenumbers[index] * thicknesses[index])
        impedance = (
            intrinsic[index]
            * (impedance + intrinsic[index] * tangent)
            / (intrinsic[index] + impedance * tangent)
        )
    return -complex(impedance)


def layered_mt_layer_order(predict: Predict) -> ConventionCheck:
    """`predict(thicknesses, resistivities, frequency) -> complex`, from the plugin."""

    def run() -> ConventionResult:
        # Ten ohm-metres over a thousand reads 693 ohm.m at 0.01 Hz the right way up and
        # 10.4 upside down.
        thicknesses, resistivities, frequency = [300.0], [10.0, 1000.0], 0.01
        expected = mt_analytic_impedance(frequency, thicknesses, resistivities)
        actual = predict(thicknesses, resistivities, frequency)
        scale = 2.0 * np.pi * frequency * MU0
        return ConventionResult(
            passed=bool(np.isclose(actual, expected, rtol=1e-4)),
            detail=(
                f"10 ohm.m over 1000 at {frequency} Hz: the recursion says "
                f"{abs(expected) ** 2 / scale:.1f} ohm.m, the engine says "
                f"{abs(actual) ** 2 / scale:.1f}"
            ),
        )

    return ConventionCheck(
        name="the layer array is surface first",
        catches=(
            "the model and the thicknesses arriving at the simulation upside down, which is "
            "what F023 was: a whole case inverted against a 5,000 m top layer"
        ),
        against="the Wait recursion, written out in this module and owned by no library",
        run=run,
    )


def layered_mt_halfspace(predict: Predict) -> ConventionCheck:
    """A halfspace reads its own resistivity, in the engine's own quadrant."""

    def run() -> ConventionResult:
        actual = predict([100.0], [100.0, 100.0], 1.0)
        apparent = abs(actual) ** 2 / (2.0 * np.pi * MU0)
        phase = float(np.degrees(np.angle(actual)))
        return ConventionResult(
            passed=bool(
                np.isclose(apparent, 100.0, rtol=1e-4) and np.isclose(phase, -135.0, atol=0.1)
            ),
            detail=f"a 100 ohm.m halfspace reads {apparent:.2f} ohm.m at {phase:.1f} degrees",
        )

    return ConventionCheck(
        name="a halfspace reads its own resistivity",
        catches="a wrong unit chain, or a quadrant flip in the impedance",
        against="the analytic halfspace impedance, and the 45 degrees it must have",
        run=run,
    )


def _fdem_response(
    resistivities: list[float],
    thicknesses: list[float],
    *,
    frequency: float,
    height: float,
    orientation: str = "z",
    separation: float = 7.93,
) -> np.ndarray:
    """Secondary field in ppm from SimPEG's layered frequency-domain solver."""
    from simpeg import maps
    from simpeg.electromagnetics import frequency_domain as fdem

    receiver_location = np.array([[separation, 0.0, height]])
    receivers = [
        fdem.receivers.PointMagneticFieldSecondary(
            receiver_location,
            orientation=orientation,
            component=part,
            data_type="ppm",
            use_source_receiver_offset=False,
        )
        for part in ("real", "imag")
    ]
    source = fdem.sources.MagDipole(
        receivers,
        frequency=frequency,
        location=np.array([0.0, 0.0, height]),
        orientation=orientation,
    )
    simulation = fdem.Simulation1DLayered(
        survey=fdem.Survey([source]),
        thicknesses=np.asarray(thicknesses, dtype=float),
        sigmaMap=maps.IdentityMap(nP=len(resistivities)),
    )
    return np.asarray(simulation.dpred(1.0 / np.asarray(resistivities, dtype=float)), dtype=float)


def layered_fdem_layer_order() -> ConventionCheck:
    """Which end of the layer array the frequency-domain simulation calls the surface."""

    def run() -> ConventionResult:
        thicknesses = [100.0, 100.0]
        uniform = _fdem_response([1000.0] * 3, thicknesses, frequency=1820.0, height=30.0)
        shallow = _fdem_response([1.0, 1000.0, 1000.0], thicknesses, frequency=1820.0, height=30.0)
        deep = _fdem_response([1000.0, 1000.0, 1.0], thicknesses, frequency=1820.0, height=30.0)

        near = float(np.max(np.abs(shallow - uniform)))
        far = float(np.max(np.abs(deep - uniform)))
        passed = bool(near > 5.0 * far)
        return ConventionResult(
            passed=passed,
            detail=(
                f"a 1 ohm.m layer changes the 1,820 Hz response by {near:.1f} ppm at the top of "
                f"the array and {far:.1f} ppm at the bottom, a ratio of {near / max(far, 1e-9):.1f}"
            ),
        )

    return ConventionCheck(
        name="the frequency-domain layer array starts at the surface",
        catches=(
            "a layered conductivity handed to SimPEG bottom-first, which recovers every section "
            "upside down and fits the data exactly -- the error that ran a whole case in F023, in "
            "the other electromagnetics module"
        ),
        against=(
            "the physical statement that an airborne system is far more sensitive to what is "
            "directly beneath it than to what is 200 m further down"
        ),
        run=run,
    )


def fdem_halfspace_against_analytic() -> ConventionCheck:
    """The ppm response over a halfspace, against the closed form for a dipole pair."""

    def run() -> ConventionResult:
        import scipy.constants as constants  # type: ignore[import-untyped]

        separation, height, frequency = 7.93, 30.0, 383.0
        sigma = 0.01
        response = _fdem_response([1.0 / sigma], [], frequency=frequency, height=height)
        quadrature = float(response[1])
        omega = 2.0 * np.pi * frequency
        # The approximation is for a system on the ground; at 30 m the coupling falls
        # off as the cube of the distance to the image, so it is compared in order of
        # magnitude rather than to a tolerance.
        expected = sigma * constants.mu_0 * omega * separation**2 / 4.0 * 1.0e6
        ratio = quadrature / expected if expected else np.inf
        passed = bool(quadrature > 0.0 and 1.0e-4 < ratio < 1.0)
        return ConventionResult(
            passed=passed,
            detail=(
                f"over a {1.0 / sigma:.0f} ohm.m halfspace at {frequency:.0f} Hz the engine gives "
                f"{quadrature:+.3f} ppm quadrature; the on-ground low-induction-number form gives "
                f"{expected:.1f} ppm, and flying at {height:.0f} m must reduce it without "
                f"changing its sign (ratio {ratio:.4f})"
            ),
        )

    return ConventionCheck(
        name="the halfspace quadrature has the right sign and order",
        catches=(
            "a response returned as a raw field ratio where the plugin expects parts per "
            "million, or with the sign convention of the secondary field reversed -- either of "
            "which inverts cleanly to a conductivity wrong by orders of magnitude"
        ),
        against="the low-induction-number slingram form, written out in this check",
        run=run,
    )


def fdem_coaxial_signs_against_coplanar() -> ConventionCheck:
    """A coaxial pair's ppm comes back with the opposite sign to a coplanar one."""

    def run() -> ConventionResult:
        conductive = [1.0]
        coplanar = _fdem_response(
            conductive, [], frequency=3315.0, height=30.0, orientation="z", separation=9.06
        )
        coaxial = _fdem_response(
            conductive, [], frequency=3315.0, height=30.0, orientation="x", separation=9.06
        )
        opposed = bool(np.sign(coplanar[1]) != np.sign(coaxial[1]))
        return ConventionResult(
            passed=opposed,
            detail=(
                f"over a 1 ohm.m halfspace at 3,315 Hz the coplanar quadrature is "
                f"{coplanar[1]:+.1f} ppm and the coaxial is {coaxial[1]:+.1f}; they must differ "
                f"in sign, and a delivery reporting both positive has normalised by the "
                f"magnitude and needs response_sign set"
            ),
        )

    return ConventionCheck(
        name="a coaxial pair signs the opposite way to a coplanar one",
        catches=(
            "a coaxial channel read with a coplanar sign convention, which fits nothing, runs "
            "to the iteration limit and returns a model -- the best halfspace goes from "
            "chi-squared 1.1 to 32.5 on the survey this was found in"
        ),
        against=(
            "the geometry of the primary field: on-axis and broadside dipole coupling have "
            "opposite signs, so the two normalisations cannot agree"
        ),
        run=run,
    )
