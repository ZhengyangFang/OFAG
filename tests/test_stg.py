"""The SuperSting reader, on files whose answer is known by construction."""

import numpy as np
import pytest

from ofag.formats.stg import read_stg

HEADER = (
    "Advanced Geosciences, Inc. SuperSting R8-IP Resistivity meter. S/N: SS0201071 Type: 3D\n"
    "Firmware version: 01.23.65 Survey period: 20150417 Records: {records}\n"
    "Unit: meter\n"
)


def _record(index: int, resistance: float, error_tenths: int, xs: tuple[float, ...]) -> str:
    """One data record, with A, B, M, N at the four given x positions."""
    geometry = ",".join(f"{x: .5E}, 0.00000E+00, 0.00000E+00" for x in xs)
    return (
        f"{index:4d},USER   ,20150417,10:07:27,{resistance: .5E},{error_tenths:4d},217,"
        f" 1.00000E+02,SEMPARK  ,{geometry},Cmd=1,HV=400\n"
    )


def _write(tmp_path, records: list[str], declared: int | None = None):
    path = tmp_path / "survey.stg"
    count = len(records) if declared is None else declared
    path.write_text(HEADER.format(records=count) + "".join(records), encoding="utf-8")
    return path


def test_electrodes_are_recovered_from_the_readings_and_ordered_along_the_line(tmp_path) -> None:
    """The .cmd says what the instrument was asked to do; the .stg says what it did."""
    path = _write(
        tmp_path,
        [
            _record(1, 4.7, 2, (5.0, 0.0, 10.0, 15.0)),
            _record(2, 0.6, 1, (5.0, 0.0, 15.0, 20.0)),
        ],
    )
    survey = read_stg(path)

    assert survey.electrodes_m[:, 0].tolist() == [0.0, 5.0, 10.0, 15.0, 20.0]
    assert survey.spacing_m == pytest.approx(5.0)
    # A is at x=5 and B at x=0, so the quadrupole is not sorted -- the order in the file
    # is the order of the roles, and reordering it would negate K.
    assert survey.quadrupoles[0].tolist() == [1, 0, 2, 3]
    assert survey.quadrupoles[1].tolist() == [1, 0, 3, 4]


def test_the_measurement_is_v_over_i_and_the_error_is_a_percent(tmp_path) -> None:
    path = _write(tmp_path, [_record(1, -0.0452, 13, (0.0, 5.0, 10.0, 15.0))])
    survey = read_stg(path)

    assert survey.resistance_ohm[0] == pytest.approx(-0.0452)
    # The file writes tenths of a percent, so 13 is 1.3 per cent.
    assert survey.error_percent[0] == pytest.approx(1.3)
    assert survey.current_ma[0] == pytest.approx(217.0)
    assert survey.apparent_resistivity_ohm_m[0] == pytest.approx(100.0)


def test_a_negative_resistance_is_kept(tmp_path) -> None:
    """Not a fault, and not the reader's to judge."""
    path = _write(
        tmp_path,
        [
            _record(1, -0.0452, 1, (0.0, 5.0, 10.0, 15.0)),
            _record(2, -0.0091, 1, (0.0, 5.0, 15.0, 20.0)),
        ],
    )
    survey = read_stg(path)

    assert survey.resistance_ohm.size == 2
    assert (survey.resistance_ohm < 0).all()


def test_the_declared_record_count_is_reported_beside_what_was_parsed(tmp_path) -> None:
    """So a file that has lost readings can be noticed here and nowhere else."""
    path = _write(
        tmp_path,
        [_record(i, 1.0, 1, (0.0, 5.0, 10.0, 15.0)) for i in range(1, 4)],
        declared=3108,
    )
    survey = read_stg(path)

    assert survey.declared_records == 3108
    assert survey.resistance_ohm.size == 3
    assert survey.unparsed_records == 0


def test_a_truncated_record_is_counted_rather_than_guessed_at(tmp_path) -> None:
    path = _write(
        tmp_path,
        [
            _record(1, 1.0, 1, (0.0, 5.0, 10.0, 15.0)),
            "   2,USER   ,20150417,10:07:28, 1.0E+00,   1,217\n",
            _record(3, 2.0, 1, (0.0, 5.0, 15.0, 20.0)),
        ],
    )
    survey = read_stg(path)

    assert survey.resistance_ohm.tolist() == [1.0, 2.0]
    assert survey.unparsed_records == 1
    assert survey.quadrupoles.shape == (2, 4)


def test_a_file_with_no_records_says_so(tmp_path) -> None:
    path = tmp_path / "empty.stg"
    path.write_text(HEADER.format(records=0), encoding="utf-8")
    with pytest.raises(ValueError, match="no data records"):
        read_stg(path)


def test_the_geometric_factor_of_the_parse_matches_the_instrument(tmp_path) -> None:
    """The check that confirms A, B, M, N were read in that order."""
    # A Wenner-alpha at 5 m: K = 2*pi*a = 31.4159, so R of 3.18310 ohm is exactly 100
    # ohm.m.
    resistance = 100.0 / (2.0 * np.pi * 5.0)
    path = _write(tmp_path, [_record(1, resistance, 1, (0.0, 15.0, 5.0, 10.0))])
    survey = read_stg(path)

    e = survey.electrodes_m
    a, b, m, n = (e[survey.quadrupoles[0, i]] for i in range(4))
    gap = lambda p, q: float(np.linalg.norm(p - q))  # noqa: E731
    k = 2.0 * np.pi / (1 / gap(a, m) - 1 / gap(b, m) - 1 / gap(a, n) + 1 / gap(b, n))

    assert k == pytest.approx(2.0 * np.pi * 5.0)
    assert k * survey.resistance_ohm[0] == pytest.approx(
        survey.apparent_resistivity_ohm_m[0], rel=1e-4
    )
