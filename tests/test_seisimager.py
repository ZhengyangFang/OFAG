"""The SeisImager/2D first-arrival reader."""

from pathlib import Path

import pytest

from ofag.formats.seisimager import read_first_arrivals

#: What a shot block looks like: (shot position, ((receiver, milliseconds), ...)).
_TWO_SHOTS = (
    (0.0, ((0.0, 10.0), (4.0, 12.5), (8.0, 20.0))),
    (8.0, ((0.0, 21.0), (4.0, 13.0), (8.0, 10.0))),
)


def _write(
    tmp_path: Path,
    *,
    shots: tuple[tuple[float, tuple[tuple[float, float], ...]], ...] = _TWO_SHOTS,
    declared_shots: int | None = None,
    spacing: float = 4.0,
    trailer: bool = True,
    short_trace: bool = False,
) -> Path:
    lines = [
        "1996 0 3.000000",
        f"0 {len(shots) if declared_shots is None else declared_shots} {spacing:.6f}",
    ]
    for source, traces in shots:
        lines.append(f"{source:.6f} {len(traces)} 0.000000")
        for receiver, milliseconds in traces:
            lines.append(f"{receiver:.6f} " + ("" if short_trace else f"{milliseconds:.6f} 1"))
    if trailer:
        lines += ["0 0", "0", "0 0"]
    path = tmp_path / "picks.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_traveltimes_come_back_in_seconds(tmp_path) -> None:
    """The file writes milliseconds and OFAG stores SI."""
    arrivals = read_first_arrivals(_write(tmp_path))

    assert arrivals.traveltime_s[0] == pytest.approx(0.010)
    assert arrivals.traveltime_s[1] == pytest.approx(0.0125)
    assert arrivals.geophone_spacing_m == pytest.approx(4.0)


def test_every_pick_keeps_the_shot_it_came_from(tmp_path) -> None:
    """Flattening the gathers would destroy the only error estimate there is."""
    arrivals = read_first_arrivals(_write(tmp_path))

    assert arrivals.shot_x_m.tolist() == [0.0, 0.0, 0.0, 8.0, 8.0, 8.0]
    assert arrivals.receiver_x_m.tolist() == [0.0, 4.0, 8.0, 0.0, 4.0, 8.0]
    assert arrivals.offset_m.tolist() == [0.0, 4.0, 8.0, 8.0, 4.0, 0.0]


def test_the_trailer_is_not_read_as_a_shot_at_the_origin(tmp_path) -> None:
    """`0 0` closes the file and has the shape of a shot block with no traces."""
    with_trailer = read_first_arrivals(_write(tmp_path, trailer=True))
    without = read_first_arrivals(_write(tmp_path, trailer=False))

    assert with_trailer.parsed_shots == 2
    assert with_trailer.traveltime_s.size == without.traveltime_s.size == 6


def test_the_declared_shot_count_is_kept_beside_what_was_parsed(tmp_path) -> None:
    arrivals = read_first_arrivals(_write(tmp_path, declared_shots=9))

    assert arrivals.declared_shots == 9
    assert arrivals.parsed_shots == 2


def test_reciprocal_pairs_are_found_and_zero_offset_is_not_one(tmp_path) -> None:
    """A to B against B to A is a theorem, so the difference is measurement error."""
    arrivals = read_first_arrivals(_write(tmp_path))
    left, right = arrivals.reciprocal_pairs()

    assert left.size == 1
    # 0 -> 8 at 20.0 ms against 8 -> 0 at 21.0 ms.
    assert arrivals.shot_x_m[left[0]] == 0.0
    assert arrivals.receiver_x_m[left[0]] == 8.0
    assert arrivals.shot_x_m[right[0]] == 8.0
    assert arrivals.receiver_x_m[right[0]] == 0.0
    difference = abs(arrivals.traveltime_s[left[0]] - arrivals.traveltime_s[right[0]])
    assert difference == pytest.approx(0.001)


def test_a_repeated_traveltime_is_reported_but_not_named(tmp_path) -> None:
    """A picking floor looks like one value repeated at the short offsets."""
    arrivals = read_first_arrivals(
        _write(
            tmp_path,
            shots=((0.0, ((0.0, 10.0), (4.0, 10.0), (8.0, 10.0), (12.0, 22.0))),),
        )
    )

    repeated = arrivals.repeated_traveltimes
    assert list(repeated.values()) == [3]
    assert next(iter(repeated)) == pytest.approx(0.010)


def test_apparent_velocity_survives_a_zero_offset_rather_than_raising(tmp_path) -> None:
    """Both zero offset and zero time occur in real files and have to be seen."""
    arrivals = read_first_arrivals(_write(tmp_path))
    velocity = arrivals.apparent_velocity_m_s

    assert velocity[0] == pytest.approx(0.0)
    assert velocity[1] == pytest.approx(320.0)


def test_a_file_with_no_gathers_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="no parsable shot gathers"):
        read_first_arrivals(_write(tmp_path, shots=()))


def test_a_file_too_short_to_hold_a_header_is_refused(tmp_path) -> None:
    path = tmp_path / "stub.txt"
    path.write_text("1996 0 3.000000\n", encoding="utf-8")

    with pytest.raises(ValueError, match="too short"):
        read_first_arrivals(path)


def test_a_trace_line_missing_its_traveltime_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="fewer than two numbers"):
        read_first_arrivals(_write(tmp_path, short_trace=True))


def test_a_second_line_without_a_spacing_is_refused(tmp_path) -> None:
    path = tmp_path / "stub.txt"
    path.write_text("1996 0 3.000000\n0 2\n0.0 1 0.0\n0.0 10.0 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="shot count and geophone spacing"):
        read_first_arrivals(path)
