"""A12: the two numbers owed before a geometry is built, flat or not."""

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.agent.gates import (
    ENOUGH_STEPS_TO_BE_TERRAIN,
    Terrain,
    UnmeasuredTerrain,
    measure_terrain,
    refuse_unmeasured_terrain,
)

FOOT_M = 0.3048

#: Llano's ERT1, as the release gives it: 48 electrodes on seven contours.
ERT1 = np.repeat(np.arange(953, 960) * FOOT_M, 7)[:48]
#: Its ERT2, which climbs 32 ft and skips the 965 ft contour entirely.
ERT2 = np.array([ft * FOOT_M for ft in (*range(938, 965), *range(966, 971))])


def _ground(**kwargs) -> Terrain:
    return measure_terrain(
        kwargs.pop("name", "ERT1"),
        kwargs.pop("elevations", ERT1),
        source=kwargs.pop("source", "the release's electrode table"),
    )


class TestTheQuantum:
    def test_a_contour_readoff_reports_its_contour_interval(self) -> None:
        assert measure_terrain("ERT1", ERT1, source="the release's table").quantum_m == (
            pytest.approx(FOOT_M)
        )

    def test_a_skipped_contour_does_not_hide_the_interval(self) -> None:
        """ERT2 jumps 964 to 966 ft."""
        assert measure_terrain("ERT2", ERT2, source="the release's table").quantum_m == (
            pytest.approx(FOOT_M)
        )

    def test_one_interpolated_point_does_not_make_a_contour_continuous(self) -> None:
        """Why this is a grid fit and not a gap."""
        with_a_point = np.append(ERT2, 938.0 * FOOT_M + 0.04)

        terrain = measure_terrain("ERT2", with_a_point, source="the release's table")

        assert terrain.quantum_m == pytest.approx(FOOT_M)
        assert min(np.diff(np.unique(with_a_point))) == pytest.approx(0.04)

    def test_a_sampled_dem_is_not_quantised(self) -> None:
        rng = np.random.default_rng(3)
        sampled = 220.0 + rng.normal(scale=4.0, size=500)

        terrain = measure_terrain("the model footprint", sampled, source="3DEP at 10 m, bilinear")

        assert terrain.quantum_m == 0.0
        assert terrain.steps == float("inf")
        assert terrain.modellable

    def test_ground_at_one_elevation_is_flat_not_unmeasured(self) -> None:
        """A floodplain really can be flat, and the gate is about silence."""
        terrain = measure_terrain("SVP_CW6", np.full(56, 220.58), source="3DEP sampled along it")

        assert terrain.relief_m == 0.0
        assert terrain.quantum_m == 0.0


class TestWhatTheNumbersMean:
    def test_llanos_first_profile_is_six_steps_of_terrain(self) -> None:
        """1.83 m of relief on a 0.3048 m quantum."""
        terrain = _ground()

        assert terrain.relief_m == pytest.approx(6 * FOOT_M)
        assert terrain.steps == pytest.approx(6.0)
        assert not terrain.modellable

    def test_llanos_second_profile_clears_the_bar_and_is_still_a_staircase(self) -> None:
        """32 steps, so the gate passes it -- and the gate is not a claim that the elevations
        are good, only that they are not mostly quantum."""
        terrain = measure_terrain("ERT2", ERT2, source="the release's electrode table")

        assert terrain.steps > ENOUGH_STEPS_TO_BE_TERRAIN
        assert terrain.modellable
        assert terrain.quantum_m == pytest.approx(FOOT_M)

    def test_the_summary_carries_both_numbers_and_where_they_came_from(self) -> None:
        summary = _ground().summary

        assert "1.83 m of relief over 48 points" in summary
        assert "quantised to 0.3048 m" in summary
        assert "6 steps of relief" in summary
        assert "the release's electrode table" in summary

    def test_measuring_nothing_is_an_error_and_not_a_flat_terrain(self) -> None:
        with pytest.raises(ValueError, match="no finite elevation"):
            measure_terrain("a line with no elevations", np.array([np.nan, np.nan]), source="x" * 9)


class TestTheGate:
    def test_ground_nobody_measured_is_refused(self) -> None:
        with pytest.raises(UnmeasuredTerrain, match="the model volume"):
            refuse_unmeasured_terrain({"the model volume": None, "ERT2": _ground()})

    def test_the_refusal_says_what_to_go_and_measure(self) -> None:
        with pytest.raises(UnmeasuredTerrain, match="quantised"):
            refuse_unmeasured_terrain({"the model volume": None})

    def test_flat_is_an_answer(self) -> None:
        """Cedar Rapids' resistivity lines, which the airborne DTM puts at 1.6 to 2.6 m over
        240 to 480 m."""
        flat = measure_terrain(
            "Ellis_CW1", np.linspace(219.61, 220.26, 96), source="3DEP DTM sampled along the line"
        )

        assert refuse_unmeasured_terrain({"Ellis_CW1": flat}) == ()

    def test_a_staircase_is_returned_to_be_printed_rather_than_refused(self) -> None:
        """The same reason an acknowledged misfit is returned: a gate that silences what it
        passes is the same as no gate."""
        flagged = refuse_unmeasured_terrain(
            {"ERT1": _ground(), "ERT2": measure_terrain("ERT2", ERT2, source="the release's table")}
        )

        assert flagged == ("ERT1",)

    def test_a_terrain_that_will_not_say_where_it_came_from_does_not_exist(self) -> None:
        with pytest.raises(ValidationError):
            measure_terrain("ERT1", ERT1, source="a file")


class TestTheRecordedFailuresItWouldHaveRefused:
    """F034 and F035, reproduced and put in front of the gate."""

    #: The box's ground as the airborne DTM has it, at the columns the model hangs on.
    #: 58.3 m of relief over 1,800 of them.
    CEDAR_RAPIDS = np.concatenate([np.full(1_330, 219.6), np.linspace(220.0, 273.3, 470)])

    def test_a_volume_whose_ground_nobody_stated_is_refused(self) -> None:
        with pytest.raises(UnmeasuredTerrain, match="the model volume"):
            refuse_unmeasured_terrain({"the model volume": None})

    def test_stating_it_is_what_exposes_the_plane(self) -> None:
        """The gate cannot see that the cells were flat."""
        ground = measure_terrain(
            "the model volume",
            self.CEDAR_RAPIDS,
            source="DTM_HEM in the EM1DFM delivery, at each column's own sounding",
        )

        assert refuse_unmeasured_terrain({"the model volume": ground}) == ()
        assert ground.relief_m == pytest.approx(53.7, abs=0.1)
        assert ground.quantum_m == 0.0

    def test_it_refuses_silence_and_cannot_refuse_a_bad_answer(self) -> None:
        """Which is why F035 is not claimed as shown."""
        gestured = measure_terrain("the model volume", self.CEDAR_RAPIDS, source="the data")

        assert refuse_unmeasured_terrain({"the model volume": gestured}) == ()

        with pytest.raises(ValidationError):
            measure_terrain("the model volume", self.CEDAR_RAPIDS, source="short")


class TestValuesOffTheQuantum:
    """Reported separately, because the grid fit tolerates them on purpose."""

    def test_a_stray_value_is_counted_and_the_quantum_survives(self) -> None:
        strayed = np.append(ERT2, ERT2[0] + 0.41 * FOOT_M)
        terrain = measure_terrain("ERT2", strayed, source="the release's electrode table")

        assert terrain.quantum_m == pytest.approx(FOOT_M)
        assert terrain.off_the_grid == 1
        assert "1 off it" in terrain.summary

    def test_a_clean_contour_list_has_none(self) -> None:
        assert measure_terrain("ERT1", ERT1, source="the release's table").off_the_grid == 0

    def test_a_continuous_terrain_has_no_grid_to_be_off(self) -> None:
        rng = np.random.default_rng(5)
        sampled = 220.0 + rng.normal(scale=4.0, size=300)

        assert measure_terrain("a DEM", sampled, source="3DEP at 1 m, bilinear").off_the_grid == 0
