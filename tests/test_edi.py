"""Reading a magnetotelluric EDI that carries spectra instead of an impedance."""

from pathlib import Path

import numpy as np
import pytest

from ofag.formats.edi import (
    EDI_IMPEDANCE_TO_OHM,
    SCALAR_IMPEDANCES,
    apparent_resistivity_ohm_m,
    effective_impedance,
    impedance_phase_degrees,
    one_dimensionality,
    phase_tensor,
    phase_tensor_invariants,
    read_edi,
    rotate,
    scalar_impedance,
    scalar_uncertainty_ohm,
)

HEAD = """>HEAD

  DATAID="Test"
  LAT= 39:01:23.94
  LONG=-112:19:1.50
  ELEV=1595
  UNITS=M

>=DEFINEMEAS
  MAXCHAN=7

>HMEAS ID=11.001 CHTYPE=HX X=2 Y=-1 AZM=0
>HMEAS ID=12.001 CHTYPE=HY X=2 Y=-1 AZM=90
>HMEAS ID=13.001 CHTYPE=HZ X=2 Y=-1 AZM=0
>EMEAS ID=14.001 CHTYPE=EX X=2 Y=-1 X2=102 Y2=-1
>EMEAS ID=15.001 CHTYPE=EY X=2 Y=-1 X2=2 Y2=99
>HMEAS ID=16.001 CHTYPE=HX X=-14675 Y=-82019 AZM=0
>HMEAS ID=17.001 CHTYPE=HY X=-14675 Y=-82019 AZM=90

>=SPECTRASECT
  SECTID="SITE01"
  NCHAN=7
  NFREQ=1
"""


def _spectra(matrix: np.ndarray, frequency: float = 1.0) -> str:
    """Write a complex Hermitian matrix the way an EDI stores one."""
    raw = np.zeros(matrix.shape, dtype=float)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            raw[i, j] = matrix[i, j].real if i >= j else matrix[j, i].imag
    rows = "\n".join("  " + "  ".join(f"{value: .8E}" for value in row) for row in raw)
    return f">SPECTRA  FREQ={frequency:.4E} ROTSPEC=0.000 //49\n{rows}\n"


def _station(tmp_path: Path, matrix: np.ndarray, frequency: float = 1.0) -> Path:
    path = tmp_path / "site.edi"
    path.write_text(HEAD + "\n" + _spectra(matrix, frequency) + "\n>END\n", encoding="utf-8")
    return path


def _from_impedance(
    zxy: complex, zyx: complex, zxx: complex = 0.0, zyy: complex = 0.0
) -> np.ndarray:
    """A spectral matrix a known impedance would produce."""
    hx, hy, _hz, ex, ey, rx, ry = range(7)
    matrix = np.eye(7, dtype=complex)
    for row, column, value in (
        (hx, rx, 1.0 + 0.0j),
        (hy, ry, 1.0 + 0.0j),
        (ex, rx, zxx),
        (ex, ry, zxy),
        (ey, rx, zyx),
        (ey, ry, zyy),
    ):
        matrix[row, column] = value
        matrix[column, row] = np.conjugate(value)
    return matrix


class TestReadingTheFile:
    def test_the_header_and_the_channel_order_come_back(self, tmp_path) -> None:
        path = _station(tmp_path, _from_impedance(1.0, -1.0))

        station = read_edi(path)

        assert station.name == "SITE01"
        assert station.elevation_m == pytest.approx(1595.0)
        assert station.channels == ("HX", "HY", "HZ", "EX", "EY", "HX", "HY")
        assert station.spectra.shape == (1, 7, 7)

    def test_a_negative_angle_is_negative_all_the_way_down(self, tmp_path) -> None:
        """`-112:19:1.50` is 112 degrees west and nineteen minutes further west."""
        station = read_edi(_station(tmp_path, _from_impedance(1.0, -1.0)))

        assert station.longitude_deg == pytest.approx(-(112 + 19 / 60 + 1.50 / 3600))
        assert station.latitude_deg == pytest.approx(39 + 1 / 60 + 23.94 / 3600)

    def test_the_spectral_matrix_comes_back_hermitian(self, tmp_path) -> None:
        """Half of each cross-power is stored above the diagonal and half below, so a matrix
        read as written is two numbers where there is one."""
        station = read_edi(_station(tmp_path, _from_impedance(2.0 + 1.0j, -3.0j)))

        matrix = station.spectra[0]
        assert np.allclose(matrix, np.conjugate(matrix.T))
        assert np.allclose(np.diagonal(matrix).imag, 0.0), "an auto-power is real"

    def test_a_block_with_the_wrong_number_of_values_is_refused(self, tmp_path) -> None:
        path = tmp_path / "short.edi"
        path.write_text(
            HEAD + "\n>SPECTRA  FREQ=1.0E+00 //4\n  1.0 2.0 3.0 4.0\n", encoding="utf-8"
        )

        with pytest.raises(ValueError, match="carries 4 numbers for 7 channels"):
            read_edi(path)

    def test_an_edi_with_no_spectra_says_so(self, tmp_path) -> None:
        """An EDI carrying an impedance directly is a different form, and returning nothing
        for it would look like a station with no data."""
        path = tmp_path / "impedance.edi"
        path.write_text(HEAD + "\n>ZXYR ROT=ZROT // 1\n  1.0\n", encoding="utf-8")

        with pytest.raises(ValueError, match="holds no >SPECTRA blocks"):
            read_edi(path)


class TestTheImpedance:
    def test_it_recovers_an_impedance_chosen_in_advance(self, tmp_path) -> None:
        station = read_edi(_station(tmp_path, _from_impedance(4.0 + 3.0j, -2.0 + 1.0j)))

        tensor = station.impedance(remote=True)

        # In ohms, because the reader converts once and nowhere else.
        assert tensor[0, 0, 1] == pytest.approx((4.0 + 3.0j) * EDI_IMPEDANCE_TO_OHM)
        assert tensor[0, 1, 0] == pytest.approx((-2.0 + 1.0j) * EDI_IMPEDANCE_TO_OHM)

    def test_the_second_hx_is_the_reference_and_not_the_first(self, tmp_path) -> None:
        """A remote-reference file lists HX and HY twice."""
        station = read_edi(_station(tmp_path, _from_impedance(1.0, -1.0)))

        assert station.channel("HX", 0) == 0
        assert station.channel("HX", 1) == 5
        assert station.channel("HY", 1) == 6

    def test_asking_for_a_reference_a_site_does_not_have_is_refused(self, tmp_path) -> None:
        """A single-station recording has five channels, and silently falling back to the
        local field would report a remote-reference estimate that no remote site
        contributed to."""
        path = tmp_path / "local.edi"
        text = HEAD
        for line in (
            ">HMEAS ID=16.001 CHTYPE=HX X=-14675 Y=-82019 AZM=0\n",
            ">HMEAS ID=17.001 CHTYPE=HY X=-14675 Y=-82019 AZM=90\n",
        ):
            text = text.replace(line, "")
        matrix = np.eye(5, dtype=complex)
        raw = "\n".join("  " + "  ".join(f"{v: .8E}" for v in row) for row in matrix.real)
        path.write_text(text + f"\n>SPECTRA  FREQ=1.0E+00 //25\n{raw}\n", encoding="utf-8")

        with pytest.raises(ValueError, match="has 1 HX channels"):
            read_edi(path).impedance(remote=True)


class TestTheUnits:
    def test_the_conversion_carries_mu_nought(self, tmp_path) -> None:
        """The magnetic channel records B and an impedance is E over H, so the conversion is
        1e3 times mu0 and not 1e3."""
        assert EDI_IMPEDANCE_TO_OHM == pytest.approx(1.0e3 * 4.0e-7 * np.pi)

    def test_apparent_resistivity_matches_the_practical_formula(self, tmp_path) -> None:
        """Two independent routes to the same number: the SI chain written out in the module,
        and `rho = 0.2 * T * |Z|^2` with Z in the EDI's own units, as it is used in the
        field."""
        frequencies = np.array([0.01, 1.0, 100.0])
        in_edi_units = np.full((3, 2, 2), 4.0 + 3.0j)

        computed = apparent_resistivity_ohm_m(in_edi_units * EDI_IMPEDANCE_TO_OHM, frequencies)
        practical = 0.2 / frequencies[:, None, None] * np.abs(in_edi_units) ** 2

        assert computed == pytest.approx(practical)

    def test_a_uniform_earth_gives_a_phase_of_forty_five_degrees(self) -> None:
        """Which is the check a scale error cannot reach, and the reason the missing mu0 had
        to be caught on the resistivity instead."""
        impedance = np.array([[[0.0, 1.0 + 1.0j], [-1.0 - 1.0j, 0.0]]])

        assert impedance_phase_degrees(impedance)[0, 0, 1] == pytest.approx(45.0)


class TestReducingTheTensorToOneNumber:
    """A layered earth has one impedance and a tensor has four numbers."""

    def test_a_layered_tensor_gives_every_candidate_the_same_answer(self) -> None:
        # This survey's Zyx is the one in the simulation's quadrant and its Zxy is the
        # same quantity turned around, so the tensor is written that way.
        tensor = np.array([[[0.0, 1.0 + 1.0j], [-1.0 - 1.0j, 0.0]]])

        answers = [scalar_impedance(tensor, kind)[0] for kind in SCALAR_IMPEDANCES]

        for answer in answers:
            assert answer == pytest.approx(-1.0 - 1.0j)

    def test_every_candidate_answers_in_the_simulation_s_quadrant(self) -> None:
        """SimPEG's layered simulation returns -135 degrees over a halfspace, so a candidate
        that answered +45 would be the same ground upside down and no model could fit it."""
        tensor = np.array([[[0.0, 1.0 + 1.0j], [-1.0 - 1.0j, 0.0]]])

        for kind in SCALAR_IMPEDANCES:
            assert impedance_phase_degrees(scalar_impedance(tensor, kind))[0] == pytest.approx(
                -135.0
            )

    def test_a_distorted_tensor_pulls_them_apart(self) -> None:
        """The two polarisations see different structure, and their average is a curve
        neither of them is."""
        tensor = np.array([[[0.0, 1.0 + 1.0j], [-4.0 - 4.0j, 0.0]]])

        xy = scalar_impedance(tensor, "xy")[0]
        yx = scalar_impedance(tensor, "yx")[0]
        average = scalar_impedance(tensor, "average")[0]

        assert abs(xy) == pytest.approx(np.sqrt(2.0))
        assert abs(yx) == pytest.approx(4.0 * np.sqrt(2.0))
        assert abs(average) == pytest.approx(2.5 * np.sqrt(2.0))

    def test_the_determinant_uses_the_diagonal_the_others_ignore(self) -> None:
        tensor = np.array([[[0.5, -2.0], [2.0, 0.5]]], dtype=complex)

        determinant = scalar_impedance(tensor, "determinant")[0]

        assert determinant == pytest.approx(-np.sqrt(0.25 + 4.0))

    def test_a_single_component_carries_its_own_error_and_a_pair_carries_half(self) -> None:
        deviation = np.array([[[0.0, 3.0], [4.0, 0.0]]])

        assert scalar_uncertainty_ohm(deviation, "xy")[0] == pytest.approx(3.0)
        assert scalar_uncertainty_ohm(deviation, "yx")[0] == pytest.approx(4.0)
        assert scalar_uncertainty_ohm(deviation, "average")[0] == pytest.approx(2.5)

    def test_an_unknown_candidate_is_refused(self) -> None:
        tensor = np.zeros((1, 2, 2), dtype=complex)

        with pytest.raises(ValueError, match="unknown scalar impedance"):
            scalar_impedance(tensor, "tm")
        with pytest.raises(ValueError, match="unknown scalar impedance"):
            scalar_uncertainty_ohm(np.zeros((1, 2, 2)), "tm")

    def test_the_old_name_still_means_the_average(self) -> None:
        tensor = np.array([[[0.0, -1.0], [3.0, 0.0]]], dtype=complex)

        assert effective_impedance(tensor)[0] == pytest.approx(
            scalar_impedance(tensor, "average")[0]
        )


class TestThePhaseTensor:
    """The one thing about a site that galvanic distortion cannot reach."""

    @staticmethod
    def _layered(phase_degrees: float = 45.0, magnitude: float = 2.0) -> np.ndarray:
        radians = np.radians(phase_degrees)
        value = magnitude * (np.cos(radians) + 1j * np.sin(radians))
        return np.array([[[0.0, value], [-value, 0.0]]])

    def test_a_layered_earth_gives_the_identity_times_the_phase_tangent(self) -> None:
        phi = phase_tensor(self._layered(30.0))

        assert phi[0] == pytest.approx(np.eye(2) * np.tan(np.radians(30.0)))

    def test_a_layered_earth_has_no_skew_and_no_ellipticity(self) -> None:
        answer = phase_tensor_invariants(self._layered(30.0))

        assert float(answer.skew_degrees[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(answer.ellipticity[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(answer.minimum[0]) == pytest.approx(float(answer.maximum[0]))

    def test_distortion_changes_the_impedance_and_not_the_phase_tensor(self) -> None:
        """The property the whole thing rests on."""
        tensor = self._layered(30.0)
        distortion = np.array([[2.4, 0.7], [-0.3, 1.9]])
        distorted = distortion @ tensor

        assert not np.allclose(distorted, tensor)
        assert phase_tensor(distorted)[0] == pytest.approx(phase_tensor(tensor)[0])

    def test_distortion_does_change_the_index_it_replaces(self) -> None:
        """Which is the point. `one_dimensionality` reads a perfectly layered site as partly
        two-dimensional as soon as it is distorted, and a screen built on it is measuring
        the near surface of the site."""
        tensor = self._layered(30.0)
        distorted = np.array([[2.4, 0.7], [-0.3, 1.9]]) @ tensor

        assert float(one_dimensionality(tensor)[0]) == pytest.approx(0.0, abs=1e-12)
        assert float(one_dimensionality(distorted)[0]) > 0.1
        # And it invents a diagonal, which the index does not look at at all.
        assert abs(complex(distorted[0, 0, 0])) > 0.0

    def test_a_two_dimensional_earth_has_ellipticity_and_still_no_skew(self) -> None:
        """Two modes with different phases, and no rotation is needed to see that: skew is
        what separates 2D from 3D, not ellipticity."""
        along = 2.0 * np.exp(1j * np.radians(30.0))
        across = 3.0 * np.exp(1j * np.radians(60.0))
        tensor = np.array([[[0.0, along], [-across, 0.0]]])

        answer = phase_tensor_invariants(tensor)

        assert float(answer.skew_degrees[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(answer.ellipticity[0]) > 0.2

    def test_the_skew_survives_rotation_and_the_strike_follows_it(self) -> None:
        along = 2.0 * np.exp(1j * np.radians(30.0))
        across = 3.0 * np.exp(1j * np.radians(60.0))
        tensor = np.array([[[0.0, along], [-across, 0.0]]])
        angle = np.radians(20.0)
        rotation = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
        rotated = rotation @ tensor @ rotation.T

        before = phase_tensor_invariants(tensor)
        after = phase_tensor_invariants(rotated)

        assert float(after.skew_degrees[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(after.ellipticity[0]) == pytest.approx(float(before.ellipticity[0]))
        # Rotating the frame by 20 degrees moves the strike measured in it by -20,
        # modulo the 90 the tensor cannot resolve.
        turned = (float(before.strike_degrees[0]) - float(after.strike_degrees[0])) % 90.0
        assert turned == pytest.approx(20.0, abs=1e-6)

    def test_a_three_dimensional_tensor_has_a_skew_no_rotation_removes(self) -> None:
        tensor = np.array(
            [
                [
                    [0.4 + 0.5j, 2.0 * np.exp(1j * np.radians(30.0))],
                    [-3.0 * np.exp(1j * np.radians(65.0)), 0.2 + 0.1j],
                ]
            ]
        )

        skews = []
        for degrees in range(0, 90, 10):
            angle = np.radians(degrees)
            rotation = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
            skews.append(
                abs(float(phase_tensor_invariants(rotation @ tensor @ rotation.T).skew_degrees[0]))
            )

        assert min(skews) > 1.0
        assert max(skews) - min(skews) < 1e-6, "skew is a rotational invariant"


class TestRotatingIntoStrike:
    """A 2D inversion solves for a section whose strike is the x axis, so the data has to be
    brought into that frame before it can be fitted."""

    def test_a_layered_tensor_is_the_same_at_every_angle(self) -> None:
        value = 1.0 + 1.0j
        tensor = np.array([[[0.0, value], [-value, 0.0]]])

        for degrees in (0.0, 17.0, 45.0, 90.0):
            assert rotate(tensor, degrees)[0] == pytest.approx(tensor[0])

    def test_rotating_a_2d_tensor_by_its_strike_empties_the_diagonal(self) -> None:
        along = 2.0 * np.exp(1j * np.radians(30.0))
        across = 3.0 * np.exp(1j * np.radians(60.0))
        principal = np.array([[[0.0, along], [-across, 0.0]]])
        observed = rotate(principal, -25.0)

        assert abs(complex(observed[0, 0, 0])) > 0.1, "off strike, the diagonal is not empty"

        strike = float(phase_tensor_invariants(observed).strike_degrees[0])
        back = rotate(observed, strike)

        assert abs(complex(back[0, 0, 0])) == pytest.approx(0.0, abs=1e-9)
        assert abs(complex(back[0, 1, 1])) == pytest.approx(0.0, abs=1e-9)

    def test_rotating_there_and_back_returns_the_tensor(self) -> None:
        tensor = np.array([[[0.4 + 0.5j, 2.0 - 1.0j], [-3.0 + 0.5j, 0.2 + 0.1j]]])

        assert rotate(rotate(tensor, 33.0), -33.0)[0] == pytest.approx(tensor[0])
