"""The RES2DINV general-array reader."""

from pathlib import Path

import numpy as np
import pytest

from ofag.formats.res2dinv import read_res2dinv

#: A Wenner alpha spread with a = 10 m: A at 0, M at 10, N at 20, B at 30.
_WENNER_K = 2.0 * np.pi * 10.0


def _write(
    tmp_path: Path,
    *,
    array_type: int = 11,
    kind_flag: int = 1,
    declared: int | None = None,
    measurements: tuple[tuple[tuple[float, ...], float], ...] = (((0.0, 10.0, 20.0, 30.0), 1.0),),
    prose: bool = True,
    topography: tuple[int, tuple[tuple[float, float], ...]] | None = None,
    topography_count: int | None = None,
) -> Path:
    """One RES2DINV file, assembled a line at a time."""
    lines = ["Synthetic line", "4.00", str(array_type), "7"]
    if prose:
        lines.append("Type of measurement (0=app. resistivity,1=resistance)")
    lines += [str(kind_flag), str(len(measurements) if declared is None else declared), " 2", "0"]
    for (a, b, m, n), value in measurements:
        lines.append(f"4  {a:.2f}  0.00 {b:.2f}  0.00 {m:.2f}  0.00 {n:.2f}  0.00 {value:.5f} ")
    if topography is not None:
        kind, points = topography
        count = len(points) if topography_count is None else topography_count
        lines += ["Topography in separate list", str(kind), str(count)]
        lines += [f"{x:.2f},{z:.2f}" for x, z in points]
    lines += ["1", "0", "0", "0", "0"]
    path = tmp_path / "survey.dat"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_general_array_file_yields_its_own_quadrupoles(tmp_path) -> None:
    """The geometry comes out of the file, with no scheme reconstructed."""
    survey = read_res2dinv(
        _write(
            tmp_path,
            measurements=(
                ((0.0, 30.0, 10.0, 20.0), 1.5),
                ((10.0, 40.0, 20.0, 30.0), 2.5),
            ),
        )
    )

    assert survey.title == "Synthetic line"
    assert survey.electrode_spacing_m == pytest.approx(4.0)
    assert survey.array_type == 11
    assert survey.declared_measurements == 2
    assert survey.value_kind == "resistance"
    # Five distinct positions across the two quadrupoles, ordered along the line.
    assert survey.electrodes_m[:, 0].tolist() == [0.0, 10.0, 20.0, 30.0, 40.0]
    assert survey.quadrupoles.tolist() == [[0, 3, 1, 2], [1, 4, 2, 3]]
    assert survey.values.tolist() == [1.5, 2.5]


def test_the_geometric_factor_is_computed_from_the_files_own_positions(tmp_path) -> None:
    survey = read_res2dinv(_write(tmp_path, measurements=(((0.0, 30.0, 10.0, 20.0), 1.0),)))

    assert survey.geometric_factor[0] == pytest.approx(_WENNER_K, rel=1e-9)


def test_an_apparent_resistivity_becomes_a_resistance_without_a_scheme_name(tmp_path) -> None:
    """The header says which column it wrote, so the conversion never guesses."""
    survey = read_res2dinv(
        _write(tmp_path, kind_flag=0, measurements=(((0.0, 30.0, 10.0, 20.0), 100.0),))
    )

    assert survey.value_kind == "apparent_resistivity"
    assert survey.resistance_ohm[0] == pytest.approx(100.0 / _WENNER_K, rel=1e-9)


def test_a_resistance_file_is_returned_unconverted(tmp_path) -> None:
    survey = read_res2dinv(
        _write(tmp_path, kind_flag=1, measurements=(((0.0, 30.0, 10.0, 20.0), 1.5),))
    )

    assert survey.resistance_ohm.tolist() == [1.5]


def test_a_named_scheme_is_refused_rather_than_reconstructed(tmp_path) -> None:
    """A file that names an array writes a midpoint and a separation instead."""
    with pytest.raises(ValueError, match="array type 1"):
        read_res2dinv(_write(tmp_path, array_type=1))


def test_the_measurement_type_line_is_found_without_the_prose_above_it(tmp_path) -> None:
    """Whether the naming line is present is the one thing the format is loose about."""
    survey = read_res2dinv(_write(tmp_path, prose=False, kind_flag=0))

    assert survey.value_kind == "apparent_resistivity"
    assert survey.declared_measurements == 1


def test_the_declared_count_is_kept_so_a_short_file_can_be_caught(tmp_path) -> None:
    """The reader reports both numbers rather than trusting either."""
    survey = read_res2dinv(
        _write(
            tmp_path,
            declared=9,
            measurements=(((0.0, 30.0, 10.0, 20.0), 1.0), ((10.0, 40.0, 20.0, 30.0), 2.0)),
        )
    )

    assert survey.declared_measurements == 9
    assert survey.values.size == 2


def test_the_trailing_topography_block_is_read(tmp_path) -> None:
    """The data lines' z is zero in every file seen; the surface is down here."""
    survey = read_res2dinv(
        _write(tmp_path, topography=(2, ((0.0, 291.69), (10.0, 291.08), (20.0, 290.47))))
    )

    assert survey.topography_m is not None
    assert survey.topography_m.tolist() == [[0.0, 291.69], [10.0, 291.08], [20.0, 290.47]]
    # The electrodes themselves still carry the file's z, which is not the surface.
    assert survey.electrodes_m[:, 1].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_a_file_without_topography_says_so_rather_than_inventing_a_surface(tmp_path) -> None:
    assert read_res2dinv(_write(tmp_path)).topography_m is None


def test_a_short_topography_block_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="declares 5 topography points and carries 2"):
        read_res2dinv(
            _write(tmp_path, topography=(2, ((0.0, 291.7), (10.0, 291.1))), topography_count=5)
        )


def test_an_unknown_topography_format_is_refused_rather_than_read_as_pairs(tmp_path) -> None:
    """Format 1 numbers the points by electrode instead of giving x, so reading it as
    `x,elevation` would put the surface at the wrong places quietly."""
    with pytest.raises(ValueError, match="topography format 1"):
        read_res2dinv(_write(tmp_path, topography=(1, ((1.0, 291.7), (2.0, 291.1)))))


def test_a_file_with_no_measurements_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="no parsable measurements"):
        read_res2dinv(_write(tmp_path, measurements=()))
