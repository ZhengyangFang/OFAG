"""Reading a `.usf` written by a different instrument than Utah FORGE's."""

from pathlib import Path

import numpy as np
import pytest

from ofag.core.schemas import CoordinateConvention
from ofag.formats.usf import read_usf
from ofag.services.tem_import import TemImportRequest, TemImportService

#: A header in the Llano dialect: no LOCATION, no Z_DIRECTION, V/M2, and POINTS stated
#: once for the whole sounding.
_HEADER = """//USF: Universal Sounding Format
//SOUNDINGS: 1
//END

/ARRAY: FIXED LOOP TEM
/LENGTH_UNITS: M
/VOLTAGE_UNITS: V/M2
/SOUNDING_NAME: GG_L00S100
/POINTS: {points}
"""

_PLACE = (559150.61, 3390953.70, 291.74)


def _sweep(
    number: int, current: float, rows: list[tuple[float, float, float]], hertz: float = 285.0
) -> str:
    lines = [
        f"/SWEEP_NUMBER: {number}",
        "/LOOP_SIZE: +1.00000000E+02, +1.00000000E+02",
        f"/CURRENT: {current:+.8E}",
        f"/FREQUENCY: {hertz:+.8E}",
        "/RAMP_TIME: +5.10000000E-09",
        "/END",
        "     INDEX,            TIME,         VOLTAGE,       ERROR_BAR",
    ]
    lines += [
        f"{index + 1:10d},  {t:+.8E},  {v:+.8E},  {e:+.8E}" for index, (t, v, e) in enumerate(rows)
    ]
    return "\n".join(lines) + "\n"


def _file(tmp_path: Path, *sweeps: str, points: int) -> Path:
    directory = tmp_path / "usf"
    directory.mkdir(exist_ok=True)
    path = directory / "sounding.usf"
    path.write_text(_HEADER.format(points=points) + "".join(sweeps), encoding="utf-8")
    return path


def _two_sweeps(tmp_path: Path) -> Path:
    return _file(
        tmp_path,
        _sweep(1, 1.5, [(1e-5, 6.0e-4, 6.0e-7), (2e-5, 3.0e-4, 3.0e-7)]),
        _sweep(2, 9.5, [(4e-5, 9.5e-4, 9.5e-7), (8e-5, 1.9e-4, 1.9e-7)], hertz=75.0),
        points=4,
    )


def test_the_columns_are_read_by_the_names_the_file_gives_them(tmp_path) -> None:
    """This dialect leads with an index and ends with an error bar."""
    sounding = read_usf(_two_sweeps(tmp_path), location=_PLACE, z_direction="DOWN")

    assert [sweep.times_s.tolist() for sweep in sounding.sweeps] == [[1e-5, 2e-5], [4e-5, 8e-5]]
    assert sounding.sweeps[0].voltages.tolist() == [6.0e-4, 3.0e-4]
    assert sounding.sweeps[0].errors is not None
    assert sounding.sweeps[0].errors.tolist() == [6.0e-7, 3.0e-7]
    # No QUALITY column means no verdict was passed, which is not the same as rejecting
    # every gate.
    assert sounding.sweeps[0].accepted.all()


def test_points_stated_once_for_the_sounding_is_checked_against_the_total(tmp_path) -> None:
    """The other dialect states it per sweep; both are checked, neither assumed."""
    read_usf(_two_sweeps(tmp_path), location=_PLACE, z_direction="DOWN")

    short = _file(
        tmp_path,
        _sweep(1, 1.5, [(1e-5, 6.0e-4, 6.0e-7)]),
        points=9,
    )
    with pytest.raises(ValueError, match="declares 9 points and its 1 sweeps carry 1"):
        read_usf(short, location=_PLACE, z_direction="DOWN")


def test_a_file_that_places_itself_nowhere_is_refused_unless_told_where(tmp_path) -> None:
    """A placeless sounding inverted into a section puts the ground nowhere (F029)."""
    path = _two_sweeps(tmp_path)

    with pytest.raises(ValueError, match="pass location="):
        read_usf(path, z_direction="DOWN")

    placed = read_usf(path, location=_PLACE, z_direction="DOWN")
    assert placed.easting_m == pytest.approx(_PLACE[0])
    assert placed.location_declared is False


def test_a_file_with_no_z_convention_is_refused_unless_told_which(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not declare /Z_DIRECTION"):
        read_usf(_two_sweeps(tmp_path), location=_PLACE)


def test_the_transmitter_current_is_divided_out_of_a_v_per_m2_file(tmp_path) -> None:
    """Two sweeps at 1.5 and 9.5 amps have to become one decay."""
    _two_sweeps(tmp_path)
    imported = TemImportService(import_root=tmp_path / "imports").import_usf_directory(
        TemImportRequest(
            source_directory=str(tmp_path / "usf"),
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            default_location_m=_PLACE,
            default_z_direction="DOWN",
            minimum_repeats=1,
            # The file declares 5.1 ns and 27 ns for a 100 m loop, which is a
            # thousandfold slip of unit; without this the import refuses (F054).
            declared_ramp_time_scale=1000.0,
            # And with it the early-gate rule becomes live, which is the point of F054
            # and not the point of these two: they are about what the dialect does to a
            # datum, so the rule is stood down here.
            earliest_gate_ramp_multiples=0.0,
        )
    )

    curves = {tuple(np.round(curve.times_s, 9)): curve for curve in imported.curves}
    first = curves[(1e-5, 2e-5)]
    second = curves[(4e-5, 8e-5)]
    # Faraday's sign, then the current: 6.0e-4 / 1.5 and 9.5e-4 / 9.5.
    assert first.values.tolist() == pytest.approx([-4.0e-4, -2.0e-4])
    assert second.values.tolist() == pytest.approx([-1.0e-4, -2.0e-5])
    # The stated error bar travels with it, scaled the same way.
    assert first.uncertainty.tolist() == pytest.approx([4.0e-7, 2.0e-7])


def test_a_gate_measured_once_takes_the_error_bar_the_file_states(tmp_path) -> None:
    """There is no scatter to stack from one measurement, and there is a bar."""
    _two_sweeps(tmp_path)
    imported = TemImportService(import_root=tmp_path / "imports").import_usf_directory(
        TemImportRequest(
            source_directory=str(tmp_path / "usf"),
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            default_location_m=_PLACE,
            default_z_direction="DOWN",
            minimum_repeats=1,
            # The file declares 5.1 ns and 27 ns for a 100 m loop, which is a
            # thousandfold slip of unit; without this the import refuses (F054).
            declared_ramp_time_scale=1000.0,
            # And with it the early-gate rule becomes live, which is the point of F054
            # and not the point of these two: they are about what the dialect does to a
            # datum, so the rule is stood down here.
            earliest_gate_ramp_multiples=0.0,
        )
    )

    for curve in imported.curves:
        assert curve.repeats.tolist() == [1, 1]
        assert (curve.uncertainty > 0).all()


def test_a_voltage_normalised_by_neither_is_still_refused(tmp_path) -> None:
    """Volts alone needs the receiver effective area, which is not in the file."""
    directory = tmp_path / "usf"
    directory.mkdir()
    (directory / "a.usf").write_text(
        _HEADER.format(points=1).replace("/VOLTAGE_UNITS: V/M2", "/VOLTAGE_UNITS: V")
        + _sweep(1, 1.5, [(1e-5, 6.0e-4, 6.0e-7)]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="V/AM2 or V/M2"):
        TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(directory),
                coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
                default_location_m=_PLACE,
                default_z_direction="DOWN",
                minimum_repeats=1,
            )
        )


def test_z_up_is_refused_rather_than_silently_inflected(tmp_path) -> None:
    """Faraday's sign is applied on the assumption of z down, unconditionally."""
    _two_sweeps(tmp_path)

    with pytest.raises(ValueError, match="handles DOWN"):
        TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(tmp_path / "usf"),
                coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
                default_location_m=_PLACE,
                default_z_direction="UP",
                minimum_repeats=1,
            )
        )


def test_a_ramp_no_transmitter_could_produce_is_refused(tmp_path: Path) -> None:
    """F054, reproduced: the file's own turn-off, against the file's own loop."""
    _file(tmp_path, _sweep(1, 1.5, [(1e-5, 4e-7, 1e-9), (2e-5, 2e-7, 1e-9)]), points=2)

    with pytest.raises(ValueError, match="turn-off ramp"):
        TemImportService(import_root=tmp_path / "imports").import_usf_directory(
            TemImportRequest(
                source_directory=str(tmp_path / "usf"),
                coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
                default_location_m=_PLACE,
                default_z_direction="DOWN",
                minimum_repeats=1,
            )
        )


def test_the_corrected_ramp_makes_the_early_gate_rule_bite(tmp_path: Path) -> None:
    """And the other half: at the right value the rule reaches the gates."""
    _file(tmp_path, _sweep(1, 1.5, [(1e-5, 4e-7, 1e-9), (2e-5, 2e-7, 1e-9)]), points=2)

    imported = TemImportService(import_root=tmp_path / "imports").import_usf_directory(
        TemImportRequest(
            source_directory=str(tmp_path / "usf"),
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            default_location_m=_PLACE,
            default_z_direction="DOWN",
            minimum_repeats=1,
            declared_ramp_time_scale=1000.0,
        )
    )

    assert imported.gates_dropped_as_too_early == 1
    (curve,) = imported.curves
    assert curve.times_s.tolist() == [2e-5]
    # And the curve carries the corrected ramp, not the declared one, so whatever models
    # this waveform later gets the value that was used.
    assert curve.ramp_time_s == pytest.approx(5.1e-6)
