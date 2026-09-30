"""A keep-mask that still holds something a picker wrote rather than measured."""

from pathlib import Path

import numpy as np
import pytest

from ofag.agent.picks import (
    GATHER_TOLERANCE_M,
    REPEATS_ARE_A_DEFAULT,
    UnsoundPicks,
    inspect_picks,
    refuse_unsound_picks,
)
from ofag.formats.seisimager import read_first_arrivals

#: Two sound gathers: the earliest arrival is at the shot in both, and the only repeated
#: value is a pair of traces at the same offset either side of one source, which is the
#: coincidence a survey produces.
SOUND = (
    (4.0, ((0.0, 11.5), (4.0, 2.0), (8.0, 11.5), (12.0, 19.0))),
    (12.0, ((0.0, 24.0), (4.0, 18.5), (8.0, 10.5), (12.0, 2.5))),
)


def _write(tmp_path: Path, shots, name: str = "picks.txt") -> Path:
    lines = ["1996 0 3.000000", f"0 {len(shots)} 4.000000"]
    for source, traces in shots:
        lines.append(f"{source:.6f} {len(traces)} 0.000000")
        for receiver, milliseconds in traces:
            lines.append(f"{receiver:.6f} {milliseconds:.6f} 1")
    lines += ["0 0", "0", "0 0"]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _read(tmp_path: Path, shots):
    return read_first_arrivals(_write(tmp_path, shots))


class TestASoundFile:
    def test_nothing_is_wrong_with_the_file(self, tmp_path: Path) -> None:
        """`sound` is about the file."""
        found = inspect_picks(_read(tmp_path, SOUND))

        assert found.sound
        assert found.zero_offset == 2
        assert "zero offset" in found.summary

    def test_a_value_repeated_twice_is_a_coincidence(self, tmp_path: Path) -> None:
        """11.5 ms appears at 4 m either side of the shot at x = 4."""
        arrivals = _read(tmp_path, SOUND)

        assert arrivals.repeated_traveltimes == {0.0115: 2}
        assert inspect_picks(arrivals).defaults == {}
        assert REPEATS_ARE_A_DEFAULT == 2

    def test_keeping_everything_is_refused_for_the_two_at_the_source(self, tmp_path: Path) -> None:
        arrivals = _read(tmp_path, SOUND)

        with pytest.raises(UnsoundPicks, match="zero offset"):
            refuse_unsound_picks(arrivals, np.ones(arrivals.traveltime_s.size, dtype=bool))

    def test_dropping_those_two_is_allowed(self, tmp_path: Path) -> None:
        arrivals = _read(tmp_path, SOUND)

        assert refuse_unsound_picks(arrivals, arrivals.offset_m != 0).sound


class TestTheThreeItRefuses:
    def test_a_gather_whose_earliest_arrival_is_not_at_its_shot(self, tmp_path: Path) -> None:
        """F044's gather, at the release's own 16 m."""
        misplaced = ((20.0, ((0.0, 14.5), (8.0, 20.0), (16.0, 26.0), (20.0, 31.0))),)
        arrivals = _read(tmp_path, misplaced)

        assert inspect_picks(arrivals).misplaced == {20.0: 20.0}
        with pytest.raises(UnsoundPicks, match="labelled x = 20 m"):
            refuse_unsound_picks(arrivals, np.ones(4, dtype=bool))

    def test_one_station_interval_is_still_sound(self, tmp_path: Path) -> None:
        """A gather whose nearest trace was defaulted has its earliest arrival one interval
        out, and it is not a bad gather."""
        near = ((8.0, ((0.0, 19.0), (4.0, 11.0), (8.0, 12.0), (12.0, 15.0))),)

        assert inspect_picks(_read(tmp_path, near)).misplaced == {}
        assert GATHER_TOLERANCE_M == 8.0

    def test_a_value_repeated_past_coincidence(self, tmp_path: Path) -> None:
        """F043. The release writes 10.000 ms five times in one file and fourteen in the
        other, always within a few stations of the shot."""
        defaulted = (
            (4.0, ((0.0, 10.0), (4.0, 10.0), (8.0, 10.0), (12.0, 19.0))),
            (12.0, ((0.0, 24.0), (4.0, 18.5), (8.0, 10.0), (12.0, 2.5))),
        )
        arrivals = _read(tmp_path, defaulted)

        assert inspect_picks(arrivals).defaults == {0.01: 4}
        with pytest.raises(UnsoundPicks, match="10.000 ms, which is the picker's default"):
            refuse_unsound_picks(arrivals, np.ones(8, dtype=bool))

    def test_a_pick_at_zero_offset(self, tmp_path: Path) -> None:
        """The ray has no length, so the predicted time is zero in every model and the
        residual is unfittable."""
        arrivals = _read(tmp_path, SOUND)
        keep = arrivals.offset_m == 0

        with pytest.raises(UnsoundPicks, match="zero offset"):
            refuse_unsound_picks(arrivals, keep)


class TestItRefusesTheDecisionAndNotTheFile:
    def test_a_file_may_hold_what_an_inversion_may_not_be_given(self, tmp_path: Path) -> None:
        """The reader is right to surface all three rather than drop them, so the gate has to
        be on the keep-mask."""
        mixed = (
            (4.0, ((0.0, 10.0), (4.0, 10.0), (8.0, 10.0), (12.0, 19.0))),
            (12.0, ((0.0, 24.0), (4.0, 18.5), (8.0, 10.5), (12.0, 2.5))),
        )
        arrivals = _read(tmp_path, mixed)
        found = inspect_picks(arrivals)

        assert not found.sound
        keep = (arrivals.offset_m != 0) & ~np.isclose(arrivals.traveltime_s, 0.01, atol=1e-9)
        assert refuse_unsound_picks(arrivals, keep) is not None
        assert keep.sum() == 4

    def test_a_mask_of_the_wrong_length_is_an_error(self, tmp_path: Path) -> None:
        arrivals = _read(tmp_path, SOUND)

        with pytest.raises(ValueError, match="the file has 8 picks"):
            refuse_unsound_picks(arrivals, np.ones(3, dtype=bool))

    def test_the_refusal_says_it_is_about_the_handing_over(self, tmp_path: Path) -> None:
        arrivals = _read(tmp_path, SOUND)

        with pytest.raises(UnsoundPicks, match="the file is not at fault"):
            refuse_unsound_picks(arrivals, arrivals.offset_m == 0)
