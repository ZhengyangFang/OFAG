"""Turning EDIs into sites a layered inversion may have."""

from pathlib import Path

import numpy as np
import pytest

from ofag.core.schemas import CoordinateConvention
from ofag.formats.edi import EDI_IMPEDANCE_TO_OHM
from ofag.services.mt_import import MtImportRequest, MtImportService
from tests.test_edi import HEAD, _from_impedance, _spectra


def _site(
    directory: Path,
    name: str,
    zxy: complex = 0.0,
    zyx: complex = 0.0,
    frequency: float = 1.0,
    zxx: complex = 0.0,
    zyy: complex = 0.0,
) -> Path:
    path = directory / f"{name}.edi"
    head = HEAD.replace('SECTID="SITE01"', f'SECTID="{name}"')
    spectra = _spectra(_from_impedance(zxy, zyx, zxx, zyy), frequency)
    path.write_text(head + "\n" + spectra + "\n>END\n", encoding="utf-8")
    return path


#: A site whose phase tensor has 6.9 degrees of skew, which no rotation and no
#: distortion can remove, so no layered model describes it.
THREE_DIMENSIONAL = dict(
    zxx=1.0 + 1.2j,
    zxy=2.0 * np.exp(1j * np.radians(20.0)),
    zyx=-3.0 * np.exp(1j * np.radians(70.0)),
    zyy=0.8 + 0.2j,
)


def _import(directory: Path, root: Path, **options: object):
    return MtImportService(import_root=root).import_edi_directory(
        MtImportRequest(
            source_directory=str(directory),
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            **options,  # type: ignore[arg-type]
        )
    )


class TestChoosingSites:
    def test_a_layered_site_is_kept(self, tmp_path) -> None:
        """Zxy = -Zyx is what a layered earth gives: the phase tensor is the identity times a
        phase, so its skew and its ellipticity are both zero."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "LAYERED", 1.0 + 1.0j, -1.0 - 1.0j)

        result = _import(source, tmp_path / "imports")

        assert [site.sounding_id for site in result.soundings] == ["LAYERED"]
        assert result.refused_as_three_dimensional == ()
        assert float(result.soundings[0].skew_degrees[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(result.soundings[0].ellipticity[0]) == pytest.approx(0.0, abs=1e-9)

    def test_a_two_dimensional_site_is_kept_and_says_so(self, tmp_path) -> None:
        """A 2D site has no skew, so it passes -- and its ellipticity records that a layered
        model of it is a model of one mode, not of the ground."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(
            source,
            "TWODEE",
            2.0 * np.exp(1j * np.radians(30.0)),
            -3.0 * np.exp(1j * np.radians(60.0)),
        )

        (site,) = _import(source, tmp_path / "imports").soundings

        assert float(site.skew_degrees[0]) == pytest.approx(0.0, abs=1e-9)
        assert float(site.ellipticity[0]) > 0.4

    def test_a_three_dimensional_site_is_refused(self, tmp_path) -> None:
        """Skew is the one thing no rotation removes and no distortion creates, so it is the
        one honest reason to refuse a site outright."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "THREEDEE", **THREE_DIMENSIONAL)

        result = _import(source, tmp_path / "imports")

        assert result.soundings == ()
        assert result.refused_as_three_dimensional == ("THREEDEE",)

    def test_the_cutoff_is_the_callers_and_is_reported(self, tmp_path) -> None:
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "MARGINAL", **THREE_DIMENSIONAL)

        strict = _import(source, tmp_path / "a", maximum_phase_tensor_skew_degrees=3.0)
        loose = _import(source, tmp_path / "b", maximum_phase_tensor_skew_degrees=10.0)

        assert strict.refused_as_three_dimensional == ("MARGINAL",)
        assert [site.sounding_id for site in loose.soundings] == ["MARGINAL"]

    def test_distortion_does_not_change_which_sites_are_kept(self, tmp_path) -> None:
        """The reason the screen moved to the phase tensor."""
        source = tmp_path / "edi"
        source.mkdir()
        # C @ Z for C = [[2.4, 0.7], [-0.3, 1.9]] acting on a layered tensor.
        value = 1.0 + 1.0j
        _site(
            source,
            "DISTORTED",
            zxx=-0.7 * value,
            zxy=2.4 * value,
            zyx=-1.9 * value,
            zyy=-0.3 * value,
        )

        (site,) = _import(source, tmp_path / "imports").soundings

        # Invariant through the whole round trip -- written to a file, read back, solved
        # out of cross-powers -- to one part in a hundred million.
        assert float(site.skew_degrees[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(site.ellipticity[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(np.median(site.one_dimensionality)) > 0.1, "the old index moved"

    def test_the_second_processing_of_a_site_is_not_a_second_site(self, tmp_path) -> None:
        """The delivery holds every site twice, plain and `_bvv`."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "FRG19001", 1.0, -1.0)
        _site(source, "FRG19001_bvv", 1.0, -1.0)

        result = _import(source, tmp_path / "imports")

        assert result.files_read == 1
        assert len(result.soundings) == 1


class TestWhereTheSiteIs:
    def test_the_position_is_projected_into_the_project_grid(self, tmp_path) -> None:
        """An EDI states degrees and the project works in metres, so the conversion happens
        once, here, rather than wherever it is next needed."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 1.0, -1.0)

        (site,) = _import(source, tmp_path / "imports").soundings

        # 39.0233 N, 112.3171 W in UTM zone 12N, whose central meridian is 111 W: 1.32
        # degrees west of it is about 114 km west of the 500,000 false easting.
        assert site.easting_m == pytest.approx(386_000, abs=2_000)
        assert site.northing_m == pytest.approx(4_320_000, abs=5_000)
        assert site.elevation_m == pytest.approx(1595.0)


class TestTheObservationFile:
    def test_it_carries_the_impedance_in_ohms_with_a_measured_uncertainty(self, tmp_path) -> None:
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 2.0 + 0.0j, -2.0 + 0.0j)

        (site,) = _import(source, tmp_path / "imports").soundings

        table = np.genfromtxt(site.observations_path, delimiter=",", names=True)
        assert table["frequency_hz"] == pytest.approx(1.0)
        assert float(table["uncertainty_ohm"]) > 0.0
        assert float(table["impedance_real_ohm"]) == pytest.approx(site.impedance_ohm[0].real)
        # Measured from the residual power, so it does not track the floor.
        assert site.uncertainty_ohm[0] > 0.0

    def test_frequencies_come_out_ascending(self, tmp_path) -> None:
        """An EDI writes its highest frequency first, and a reader that assumes an order will
        assume this one."""
        source = tmp_path / "edi"
        source.mkdir()
        path = source / "SITE.edi"
        blocks = "".join(
            _spectra(_from_impedance(1.0, -1.0), frequency) for frequency in (100.0, 1.0, 0.01)
        )
        path.write_text(HEAD + "\n" + blocks + "\n>END\n", encoding="utf-8")

        (site,) = _import(source, tmp_path / "imports").soundings

        table = np.genfromtxt(site.observations_path, delimiter=",", names=True)
        assert list(table["frequency_hz"]) == pytest.approx([0.01, 1.0, 100.0])

    def test_the_floor_binds_only_where_the_measurement_is_smaller(self, tmp_path) -> None:
        """The measurement leads and the floor catches the tail: a frequency whose residual
        power happens to be tiny would otherwise be given something close to infinite
        weight."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 2.0, -2.0)

        measured = _import(source, tmp_path / "a", minimum_relative_uncertainty=1e-6).soundings[0]
        floored = _import(source, tmp_path / "b", minimum_relative_uncertainty=0.9).soundings[0]

        magnitude = float(np.abs(measured.impedance_ohm[0]))
        assert float(measured.uncertainty_ohm[0]) > 1e-6 * magnitude, "the measurement leads"
        assert float(floored.uncertainty_ohm[0]) == pytest.approx(0.9 * magnitude)
        assert floored.uncertainty_ohm[0] > measured.uncertainty_ohm[0]


class TestRefusals:
    def test_a_directory_with_no_edis_is_refused(self, tmp_path) -> None:
        (tmp_path / "empty").mkdir()

        with pytest.raises(ValueError, match="holds no .edi files"):
            _import(tmp_path / "empty", tmp_path / "imports")

    def test_two_sites_that_would_share_a_file_are_refused(self, tmp_path) -> None:
        """A site is named from its `SECTID`, and two files can carry one."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "a", 1.0, -1.0)
        _site(source, "b", 1.0, -1.0)
        for name in ("a", "b"):
            path = source / f"{name}.edi"
            path.write_text(path.read_text().replace(f'SECTID="{name}"', 'SECTID="SAME"'))

        with pytest.raises(ValueError, match="would be written to the same file: SAME"):
            _import(source, tmp_path / "imports")


class TestWhichImpedanceTheInversionIsGiven:
    def test_the_default_is_one_polarisation_and_not_the_average(self, tmp_path) -> None:
        """Averaging two polarisations that structure has pulled apart makes a curve neither
        of them is, and no layered model need be able to fit it."""
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 1.0 + 1.0j, -1.5 - 1.5j)

        (site,) = _import(source, tmp_path / "imports").soundings

        assert site.impedance_ohm[0] == pytest.approx(-(1.0 + 1.0j) * EDI_IMPEDANCE_TO_OHM)

    def test_the_choice_is_the_callers_and_travels_with_the_result(self, tmp_path) -> None:
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 1.0 + 1.0j, -1.5 - 1.5j)

        averaged = _import(source, tmp_path / "a", impedance_component="average")
        other = _import(source, tmp_path / "b", impedance_component="yx")

        assert averaged.impedance_component == "average"
        assert averaged.soundings[0].impedance_ohm[0] == pytest.approx(
            -(1.25 + 1.25j) * EDI_IMPEDANCE_TO_OHM
        )
        assert other.soundings[0].impedance_ohm[0] == pytest.approx(
            -(1.5 + 1.5j) * EDI_IMPEDANCE_TO_OHM
        )

    def test_a_scalar_nobody_defined_is_refused_before_anything_is_read(self, tmp_path) -> None:
        source = tmp_path / "edi"
        source.mkdir()
        _site(source, "SITE", 1.0, -1.0)

        with pytest.raises(ValueError, match="impedance_component must be one of"):
            _import(source, tmp_path / "imports", impedance_component="tm")
