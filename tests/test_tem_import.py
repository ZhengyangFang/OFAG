"""Turning repeated TEM sweeps into one decay, and the ways that goes wrong."""

from pathlib import Path

import numpy as np
import pytest

from ofag.core.schemas import CoordinateConvention
from ofag.formats.usf import read_usf
from ofag.services.tem_import import (
    TemImportRequest,
    TemImportService,
    equal_area_radius_m,
)

HEADER = """//USF: Universal Sounding Format
//END

/ARRAY: FIXED LOOP TEM
/LOOP_SIZE: 40,40
/SOUNDING_NAME: Station1
/LOCATION: 332737.0000, 4259906.0000, 1624.74
/Z_DIRECTION: DOWN
/LENGTH_UNITS: M
/VOLTAGE_UNITS: V/AM2
"""


def _sweep(number: int, rows: list[tuple[float, float, int]], **tags: object) -> str:
    settings = {
        "CURRENT": "7.63",
        "FREQUENCY": "30.0",
        "SWEEP_IS_NOISE": "0",
        "COIL_SIZE": "35",
        # Small enough that the gate-rejection rule does not reach the gates the
        # stacking tests use -- 3 x 1.5 us is 4.5 us and they start at 10 us -- but not
        # smaller than a 40 m loop at 7.63 A can switch off in, which is 1 us even at 2
        # kV.
        "RAMP_TIME": "1.5E-6",
        "CHANNEL": "1",
    }
    settings.update({key: str(value) for key, value in tags.items()})
    lines = [f"\n/SWEEP_NUMBER: {number}"]
    lines += [f"/{key}: {value}" for key, value in settings.items()]
    lines += [f"/POINTS: {len(rows)}", "/END", "          TIME,         VOLTAGE    ,QUALITY"]
    lines += [f"    {t:.5E},     {v:.5E}           {q}" for t, v, q in rows]
    return "\n".join(lines) + "\n"


def _file(tmp_path: Path, *sweeps: str, name: str = "a.usf") -> Path:
    path = tmp_path / name
    path.write_text(HEADER + "".join(sweeps), encoding="utf-8")
    return path


def _stacked(tmp_path: Path, *sweeps: str, **options: object):
    source = tmp_path / "usf"
    source.mkdir()
    _file(source, *sweeps)
    return TemImportService(import_root=tmp_path / "imports").import_usf_directory(
        TemImportRequest(
            source_directory=str(source),
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            **options,  # type: ignore[arg-type]
        )
    )


class TestReadingTheFile:
    def test_the_declarations_and_the_samples_come_back(self, tmp_path) -> None:
        path = _file(tmp_path, _sweep(1, [(1e-5, 4.0e-7, 0), (2e-5, 2.0e-7, 1)]))

        sounding = read_usf(path)

        assert sounding.name == "Station1"
        assert (sounding.easting_m, sounding.northing_m) == (332737.0, 4259906.0)
        assert sounding.elevation_m == pytest.approx(1624.74)
        assert sounding.voltage_unit == "V/AM2"
        (sweep,) = sounding.sweeps
        assert sweep.times_s.tolist() == [1e-5, 2e-5]
        assert sweep.accepted.tolist() == [False, True]
        assert sweep.current_a == pytest.approx(7.63)

    def test_a_sweep_that_lost_samples_is_refused(self, tmp_path) -> None:
        """`/POINTS` is the instrument's own count, so a mismatch means the block was
        truncated and stacking it would quietly shorten a curve."""
        broken = _sweep(1, [(1e-5, 4.0e-7, 1)]).replace("/POINTS: 1", "/POINTS: 2")
        path = _file(tmp_path, broken)

        with pytest.raises(ValueError, match="declares 2 points and carries 1"):
            read_usf(path)

    def test_a_file_that_states_no_location_is_refused(self, tmp_path) -> None:
        path = tmp_path / "b.usf"
        path.write_text(HEADER.replace("/LOCATION: 332737.0000, 4259906.0000, 1624.74\n", ""))

        with pytest.raises(ValueError, match="does not declare /LOCATION"):
            read_usf(path)

    def test_lengths_in_another_unit_are_refused_rather_than_assumed(self, tmp_path) -> None:
        path = tmp_path / "c.usf"
        path.write_text(HEADER.replace("/LENGTH_UNITS: M", "/LENGTH_UNITS: FT"))

        with pytest.raises(ValueError, match="states lengths in FT"):
            read_usf(path)

    def test_tags_belong_to_the_sweep_they_are_written_under(self, tmp_path) -> None:
        """The per-sweep settings repeat down the file, and reading them from the file as a
        whole would give every sweep the first one's current."""
        path = _file(
            tmp_path,
            _sweep(1, [(1e-5, 1.0e-7, 1)], CURRENT="7.63", FREQUENCY="240.0"),
            _sweep(2, [(1e-5, 2.0e-7, 1)], CURRENT="0.97", FREQUENCY="30.0"),
        )

        first, second = read_usf(path).sweeps

        assert (first.current_a, first.frequency_hz) == (7.63, 240.0)
        assert (second.current_a, second.frequency_hz) == (0.97, 30.0)


class TestTheLoop:
    def test_a_square_loop_becomes_the_circle_of_equal_area(self) -> None:
        """40 m square is 1,600 m², and the circle of that area has radius 22.57 m."""
        assert equal_area_radius_m(40.0, 40.0) == pytest.approx(22.5676, abs=1e-4)
        assert equal_area_radius_m(100.0, 100.0) == pytest.approx(56.4190, abs=1e-4)

    def test_a_loop_with_no_area_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot have sides"):
            equal_area_radius_m(40.0, 0.0)


class TestStacking:
    @staticmethod
    def _import(tmp_path: Path, *sweeps: str, **options: object):
        source = tmp_path / "usf"
        source.mkdir()
        _file(source, *sweeps)
        return TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(source),
                coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
                **options,  # type: ignore[arg-type]
            )
        )

    def test_repeats_average_and_their_scatter_becomes_the_uncertainty(self, tmp_path) -> None:
        """The reason this service exists: every other case in this project had to argue a
        data uncertainty into being, and fifty repeats give it."""
        sweeps = [
            _sweep(index, [(1e-5, value, 1)]) for index, value in enumerate([1.0, 2.0, 3.0], 1)
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.values.tolist() == pytest.approx([-2.0])
        # Standard error of the mean of 1, 2, 3 is 1/sqrt(3).
        assert curve.uncertainty.tolist() == pytest.approx([1.0 / np.sqrt(3.0)])
        assert curve.repeats.tolist() == [3]

    def test_faradays_sign_is_applied_once_at_the_boundary(self, tmp_path) -> None:
        """A recorded voltage is minus the rate of change of the field."""
        sweeps = [_sweep(index, [(1e-5, 4.0e-7, 1)]) for index in (1, 2)]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.values.tolist() == pytest.approx([-4.0e-7])

    def test_gates_the_instrument_rejected_are_not_averaged_in(self, tmp_path) -> None:
        sweeps = [
            _sweep(1, [(1e-5, 1.0, 1)]),
            _sweep(2, [(1e-5, 1.0, 1)]),
            _sweep(3, [(1e-5, 99.0, 0)]),
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.values.tolist() == pytest.approx([-1.0])
        assert curve.repeats.tolist() == [2]
        assert result.gates_rejected_by_instrument == 1

    def test_a_gate_with_too_few_repeats_is_dropped_and_counted(self, tmp_path) -> None:
        sweeps = [
            _sweep(1, [(1e-5, 1.0, 1), (2e-5, 1.0, 1)]),
            _sweep(2, [(1e-5, 1.0, 1), (2e-5, 1.0, 0)]),
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.times_s.tolist() == [1e-5]
        assert result.gates_dropped_for_too_few_repeats == 1

    def test_sweeps_taken_with_the_transmitter_off_are_left_out(self, tmp_path) -> None:
        """They measure the noise floor."""
        sweeps = [
            _sweep(1, [(1e-5, 1.0, 1)]),
            _sweep(2, [(1e-5, 1.0, 1)]),
            _sweep(3, [(1e-5, 500.0, 1)], SWEEP_IS_NOISE="1", CURRENT="0.00"),
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.values.tolist() == pytest.approx([-1.0])
        assert result.sweeps_rejected_as_noise == 1

    def test_different_configurations_are_kept_apart(self, tmp_path) -> None:
        """Two receiver coils and two transmitter moments see the ground through four
        instruments, and averaging them would be averaging apples."""
        sweeps = [
            _sweep(1, [(1e-5, 1.0, 1)], COIL_SIZE="35"),
            _sweep(2, [(1e-5, 1.0, 1)], COIL_SIZE="35"),
            _sweep(3, [(1e-5, 8.0, 1)], COIL_SIZE="1400"),
            _sweep(4, [(1e-5, 8.0, 1)], COIL_SIZE="1400"),
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        assert len(result.curves) == 2
        assert {curve.receiver_area_m2 for curve in result.curves} == {35.0, 1400.0}
        assert sorted(float(curve.values[0]) for curve in result.curves) == pytest.approx(
            [-8.0, -1.0]
        )

    def test_gates_are_matched_on_their_own_time_not_their_position(self, tmp_path) -> None:
        """A sweep that recorded fewer points is not a sweep whose first gate is later, and
        lining them up by index averages different moments."""
        sweeps = [
            _sweep(1, [(1e-5, 1.0, 1), (2e-5, 2.0, 1)]),
            _sweep(2, [(2e-5, 2.0, 1)]),
        ]
        result = self._import(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.times_s.tolist() == [2e-5]
        assert curve.values.tolist() == pytest.approx([-2.0])

    def test_an_unnormalised_voltage_is_refused(self, tmp_path) -> None:
        """Volts alone would need the transmitter current and the receiver area to become a
        field rate, and both vary sweep to sweep."""
        source = tmp_path / "usf"
        source.mkdir()
        (source / "a.usf").write_text(
            HEADER.replace("/VOLTAGE_UNITS: V/AM2", "/VOLTAGE_UNITS: V")
            + _sweep(1, [(1e-5, 1.0, 1)]),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="records V, and this service reads V/AM2"):
            TemImportService(import_root=tmp_path / "imports").import_usf_directory(
                TemImportRequest(
                    source_directory=str(source),
                    coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
                )
            )


class TestNaming:
    def test_two_files_with_the_same_declared_name_do_not_overwrite_each_other(
        self, tmp_path
    ) -> None:
        """Four Utah FORGE soundings share a `/SOUNDING_NAME` with another, and they are not
        repeat occupations -- the two called Station1 are 4.2 km apart, because the second
        campaign restarted its numbering."""
        source = tmp_path / "usf"
        source.mkdir()
        for stem, easting in (
            ("20151028_152940_Station01", 332737.0),
            ("20170509_191149_Station1", 335486.0),
        ):
            (source / f"{stem}.usf").write_text(
                HEADER.replace("332737.0000", f"{easting:.4f}")
                + _sweep(1, [(1e-5, 1.0, 1)])
                + _sweep(2, [(1e-5, 1.0, 1)]),
                encoding="utf-8",
            )

        result = TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(source),
                coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
                minimum_repeats=2,
            )
        )

        assert len(result.curves) == 2, "both occupations must survive the import"
        assert len({curve.sounding_id for curve in result.curves}) == 2
        assert len({curve.observations_path for curve in result.curves}) == 2
        assert sorted(curve.easting_m for curve in result.curves) == [332737.0, 335486.0]

    def test_the_identifier_comes_from_the_file_and_carries_its_timestamp(self, tmp_path) -> None:
        source = tmp_path / "usf"
        source.mkdir()
        _file(
            source,
            _sweep(1, [(1e-5, 1.0, 1)]),
            _sweep(2, [(1e-5, 1.0, 1)]),
            name="20151028_152940_109_Station01.usf",
        )

        result = TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(source),
                coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
                minimum_repeats=2,
            )
        )

        (curve,) = result.curves
        assert curve.sounding_id.startswith("20151028-152940-109-Station01")


class TestWhatTheInstrumentSaysAboutItself:
    """Three acquisition parameters this survey declares per sweep."""

    def test_the_declared_time_delay_moves_the_gates(self, tmp_path) -> None:
        rows = [(1e-5, 4.0e-7, 1), (2e-5, 2.0e-7, 1)]
        sweeps = [_sweep(n, rows, TIME_DELAY="-1.7E-6") for n in range(1, 4)]

        (curve,) = _stacked(tmp_path, *sweeps, minimum_repeats=2).curves

        assert curve.times_s.tolist() == pytest.approx([1e-5 - 1.7e-6, 2e-5 - 1.7e-6])

    def test_the_declared_field_shift_scales_the_values(self, tmp_path) -> None:
        rows = [(1e-5, 4.0e-7, 1), (2e-5, 2.0e-7, 1)]
        sweeps = [_sweep(n, rows, FIELD_SHIFT_FACTOR="1.04") for n in range(1, 4)]

        (curve,) = _stacked(tmp_path, *sweeps, minimum_repeats=2).curves

        # Faraday's sign and the instrument's own factor, both applied once.
        assert curve.values[0] == pytest.approx(-4.0e-7 * 1.04)

    def test_the_calibration_can_be_declined_to_reproduce_someone_else(self, tmp_path) -> None:
        rows = [(1e-5, 4.0e-7, 1)]
        sweeps = [
            _sweep(n, rows, TIME_DELAY="-1.7E-6", FIELD_SHIFT_FACTOR="1.04") for n in range(1, 4)
        ]

        (curve,) = _stacked(
            tmp_path, *sweeps, minimum_repeats=2, apply_instrument_calibration=False
        ).curves

        assert curve.times_s.tolist() == pytest.approx([1e-5])
        assert curve.values[0] == pytest.approx(-4.0e-7)

    def test_gates_inside_the_turn_off_are_rejected_and_counted(self, tmp_path) -> None:
        """A gate recorded while the current is still falling is not a measurement of the
        ground, and a layered model misses it by most of its value however free the model
        is."""
        rows = [(2e-6, 9.0e-7, 1), (1e-5, 4.0e-7, 1), (2e-5, 2.0e-7, 1)]
        sweeps = [_sweep(n, rows, RAMP_TIME="3E-6") for n in range(1, 4)]

        result = _stacked(tmp_path, *sweeps, minimum_repeats=2)

        (curve,) = result.curves
        assert curve.times_s.tolist() == pytest.approx([1e-5, 2e-5])
        assert result.gates_dropped_as_too_early == 1

    def test_the_multiple_is_the_callers_and_zero_keeps_everything(self, tmp_path) -> None:
        rows = [(2e-6, 9.0e-7, 1), (1e-5, 4.0e-7, 1)]
        sweeps = [_sweep(n, rows, RAMP_TIME="3E-6") for n in range(1, 4)]

        kept = _stacked(tmp_path, *sweeps, minimum_repeats=2, earliest_gate_ramp_multiples=0.0)

        assert kept.curves[0].times_s.size == 2
        assert kept.gates_dropped_as_too_early == 0
