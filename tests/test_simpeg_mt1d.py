"""The layered magnetotelluric plugin, against arithmetic that is nobody's library."""

import numpy as np
import pytest

MU0 = 4.0e-7 * np.pi


def analytic_impedance(frequency: float, thicknesses, resistivities) -> complex:
    """The layered impedance from the recursion, written surface-first."""
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
    # Negated into the quadrant the simulation answers in.
    return -complex(impedance)


def apparent_resistivity(impedance: complex, frequency: float) -> float:
    return abs(impedance) ** 2 / (2.0 * np.pi * frequency * MU0)


def _predicted(thicknesses, resistivities, frequencies):
    """What the plugin's own simulation returns for a model written surface-first."""
    from simpeg import maps
    from simpeg.electromagnetics import natural_source as nsem

    from ofag.plugins.simpeg_mt1d import SimPEGMT1DPlugin

    simulation, _ = SimPEGMT1DPlugin._simulation(
        nsem,
        maps,
        np.asarray(thicknesses, dtype=float),
        np.asarray(frequencies, dtype=float),
        len(resistivities),
    )
    values = simulation.dpred(np.log(1.0 / np.asarray(resistivities, dtype=float)))
    return values[0::2] + 1j * values[1::2]


FREQUENCIES = (0.01, 0.1, 1.0, 10.0)


class TestTheLayerOrder:
    def test_a_halfspace_reads_its_own_resistivity(self) -> None:
        """The check that passes whichever way up the model is, which is why it is not enough
        on its own and is here to catch everything else."""
        pytest.importorskip("simpeg")

        predicted = _predicted([100.0], [100.0, 100.0], FREQUENCIES)

        for frequency, impedance in zip(FREQUENCIES, predicted, strict=True):
            assert apparent_resistivity(impedance, frequency) == pytest.approx(100.0, rel=1e-6)
            assert np.degrees(np.angle(impedance)) == pytest.approx(-135.0, abs=1e-6)

    def test_a_conductor_over_a_resistor_matches_the_recursion(self) -> None:
        """Ten ohm-metres for 300 m over a thousand."""
        pytest.importorskip("simpeg")
        thicknesses, resistivities = [300.0], [10.0, 1000.0]

        predicted = _predicted(thicknesses, resistivities, FREQUENCIES)

        for frequency, impedance in zip(FREQUENCIES, predicted, strict=True):
            expected = analytic_impedance(frequency, thicknesses, resistivities)
            assert impedance == pytest.approx(expected, rel=1e-6)

    def test_the_thicknesses_are_surface_first_too(self) -> None:
        """Both arrays are reversed by the simulation, independently, so a fix that turned
        over only the model would still be modelling the wrong earth."""
        pytest.importorskip("simpeg")
        thicknesses, resistivities = [100.0, 1000.0], [10.0, 1000.0, 10.0]

        predicted = _predicted(thicknesses, resistivities, FREQUENCIES)

        for frequency, impedance in zip(FREQUENCIES, predicted, strict=True):
            expected = analytic_impedance(frequency, thicknesses, resistivities)
            assert impedance == pytest.approx(expected, rel=1e-6)
            reversed_ = analytic_impedance(frequency, thicknesses[::-1], resistivities)
            assert impedance != pytest.approx(reversed_, rel=1e-3), "the test can tell them apart"

    def test_a_three_layer_model_matches_the_recursion(self) -> None:
        pytest.importorskip("simpeg")
        thicknesses, resistivities = [200.0, 400.0], [50.0, 5.0, 500.0]

        predicted = _predicted(thicknesses, resistivities, FREQUENCIES)

        for frequency, impedance in zip(FREQUENCIES, predicted, strict=True):
            expected = analytic_impedance(frequency, thicknesses, resistivities)
            assert impedance == pytest.approx(expected, rel=1e-6)

    def test_the_surface_layer_is_the_one_the_highest_frequency_sees(self) -> None:
        """A physical statement rather than an arithmetic one, and it holds whatever the
        recursion above is doing: the shortest period cannot see past the top of the
        section."""
        pytest.importorskip("simpeg")
        # 1000 Hz, and a cover many skin depths thick either way round, so the shortest
        # period is looking only at whichever layer is written first.
        high = (1000.0,)
        conductive_cover = _predicted([5000.0], [1.0, 1000.0], high)
        resistive_cover = _predicted([5000.0], [1000.0, 1.0], high)

        assert apparent_resistivity(conductive_cover[0], high[0]) == pytest.approx(1.0, rel=0.05)
        assert apparent_resistivity(resistive_cover[0], high[0]) == pytest.approx(1000.0, rel=0.05)
