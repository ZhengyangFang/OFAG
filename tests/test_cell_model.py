"""The three mistakes a graded mesh invites, each held closed by a test."""

import numpy as np
import pytest

from ofag.core.cell_model import CellModel

# A mesh in miniature with the shape that causes the trouble: fine cells at the top,
# coarse ones below, and air cells that carry no model.
CENTRES = np.array(
    [
        [0.0, 0.0, 10.0],  # air
        [1.0, 0.0, 10.0],  # air
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.5, 0.0, -4.0],
    ]
)
VOLUMES = np.array([1.0, 1.0, 1.0, 1.0, 8.0])
ACTIVE = np.array([False, False, True, True, True])


VALUES = np.array([1.0, 2.0, 3.0])


def _model(values: np.ndarray | None = None) -> CellModel:
    chosen = VALUES if values is None else values
    return CellModel.on_active_cells(chosen, CENTRES, VOLUMES, ACTIVE)


class TestPairingAModelWithItsCells:
    def test_a_model_shorter_than_the_mesh_takes_the_active_cells(self) -> None:
        """The Results page compared 145,062 against 271,181 and drew nothing."""
        model = _model()

        assert len(model.values) == 3
        assert np.array_equal(model.centres, CENTRES[ACTIVE])
        assert np.array_equal(model.volumes, VOLUMES[ACTIVE])

    def test_a_model_as_long_as_the_mesh_is_used_whole(self) -> None:
        """A plugin that solved on every cell is not wrong to say so, and the mask must not
        be applied to it just because one was supplied."""
        model = CellModel.on_active_cells(np.arange(5.0), CENTRES, VOLUMES, ACTIVE)

        assert len(model.values) == 5

    def test_a_length_that_fits_neither_is_refused_with_both_numbers(self) -> None:
        with pytest.raises(ValueError, match="4-value model does not fit 3 active cells"):
            CellModel.on_active_cells(np.arange(4.0), CENTRES, VOLUMES, ACTIVE)

    def test_a_mismatch_with_no_mask_says_that_is_what_is_missing(self) -> None:
        with pytest.raises(ValueError, match="no active-cell mask was given"):
            CellModel.on_active_cells(np.arange(3.0), CENTRES, VOLUMES)

    def test_a_mask_for_a_different_mesh_is_refused(self) -> None:
        with pytest.raises(ValueError, match="mask has 4 entries for a 5-cell mesh"):
            CellModel.on_active_cells(np.arange(3.0), CENTRES, VOLUMES, np.ones(4, dtype=bool))


class TestPuttingItBack:
    def test_the_values_land_on_the_cells_they_came_from(self) -> None:
        whole = _model().on_mesh(ACTIVE)

        assert np.array_equal(whole[ACTIVE], np.array([1.0, 2.0, 3.0]))

    def test_cells_with_no_value_are_absent_rather_than_zero(self) -> None:
        """Zero is a recovered value -- a density contrast of zero says the rock matches the
        background -- so it cannot also mean 'no model here'."""
        whole = _model().on_mesh(ACTIVE)

        assert np.isnan(whole[~ACTIVE]).all()

    def test_a_fill_can_be_asked_for_explicitly(self) -> None:
        whole = _model().on_mesh(ACTIVE, fill=-999.0)

        assert (whole[~ACTIVE] == -999.0).all()


class TestVolumeAgainstCount:
    def test_a_share_is_measured_by_volume_and_not_by_counting(self) -> None:
        """The number this guards: on the FORGE octree, cells run 42 m to 5,398 m, so one
        deep cell is worth two million shallow ones and a share computed by counting is a
        different quantity."""
        model = _model()
        deep = np.array([False, False, True])

        # One cell of three, but eight units of volume out of ten.
        assert float(deep.mean()) == pytest.approx(1 / 3)
        assert model.volume_share(deep) == pytest.approx(0.8)

    def test_selecting_everything_is_the_whole_volume(self) -> None:
        assert _model().volume_share(np.ones(3, dtype=bool)) == pytest.approx(1.0)

    def test_selecting_nothing_is_none_of_it(self) -> None:
        assert _model().volume_share(np.zeros(3, dtype=bool)) == pytest.approx(0.0)

    def test_a_selection_of_the_wrong_length_is_refused(self) -> None:
        with pytest.raises(ValueError, match="5 entries for 3 cells"):
            _model().volume_share(np.ones(5, dtype=bool))


class TestSlicing:
    def test_a_plane_keeps_the_coarse_cells_as_well_as_the_fine_ones(self) -> None:
        """A single slab thickness cannot do both, and the version that was thin enough for
        the surface cut the deep model full of holes."""
        model = _model()

        # z = -4 passes through the one coarse cell, whose side is 2.
        assert model.slice_at(2, -4.0).tolist() == [False, False, True]
        # z = -3 still does: the cell spans -5 to -3.
        assert model.slice_at(2, -3.0).tolist() == [False, False, True]
        # z = 0 catches the two fine cells, whose sides are 1.
        assert model.slice_at(2, 0.0).tolist() == [True, True, False]

    def test_the_planes_cells_sit_on_are_reported_in_order(self) -> None:
        assert _model().planes(2).tolist() == [-4.0, 0.0]

    def test_a_plane_off_every_cell_selects_nothing(self) -> None:
        """Which is why a slider steps by plane rather than by distance."""
        assert not _model().slice_at(2, 5.0).any()


class TestTheInvariants:
    def test_arrays_of_different_lengths_are_refused(self) -> None:
        with pytest.raises(ValueError, match="one value, one centre and one volume"):
            CellModel(np.arange(3.0), CENTRES, VOLUMES)

    def test_centres_must_be_three_dimensional(self) -> None:
        with pytest.raises(ValueError, match=r"must be \(cells, 3\)"):
            CellModel(np.arange(2.0), np.zeros((2, 2)), np.ones(2))

    def test_a_cell_with_no_volume_is_refused(self) -> None:
        """It would contribute nothing to a share and divide by zero in a mean."""
        with pytest.raises(ValueError, match="volumes must be positive"):
            CellModel(np.arange(2.0), np.zeros((2, 3)), np.array([1.0, 0.0]))


class TestDrawingExtents:
    """What a viewer needs to draw a cell at its own size."""

    def test_recorded_widths_are_used_as_given(self) -> None:
        """The FORGE base cell is 50 x 50 x 30 m, so the three axes differ and no single
        number stands for them."""
        widths = np.tile(np.array([50.0, 50.0, 30.0]), (5, 1))
        model = CellModel.on_active_cells(np.arange(3.0), CENTRES, VOLUMES, ACTIVE, widths=widths)

        assert model.widths_or_cubes.tolist() == [[50.0, 50.0, 30.0]] * 3

    def test_a_run_without_widths_falls_back_to_the_cube_of_equal_volume(self) -> None:
        """Runs written before the widths were recorded still have to draw."""
        model = _model()

        assert model.widths_or_cubes.shape == (3, 3)
        assert model.widths_or_cubes[:, 0] == pytest.approx(np.cbrt(VOLUMES[ACTIVE]))

    def test_widths_of_the_wrong_shape_are_refused(self) -> None:
        with pytest.raises(ValueError, match="widths must match the centres"):
            CellModel(np.arange(2.0), np.zeros((2, 3)), np.ones(2), np.ones((2, 2)))

    def test_a_slice_uses_the_width_along_the_axis_it_cuts(self) -> None:
        """Not the cube root. A 30 m tall cell straddles a plane 14 m away and a 50 m wide
        one does not, and the cube root of the two says neither."""
        centres = np.array([[0.0, 0.0, 0.0]])
        widths = np.array([[50.0, 50.0, 30.0]])
        model = CellModel(np.array([1.0]), centres, np.array([75_000.0]), widths)

        assert model.slice_at(2, 14.0).tolist() == [True]
        assert model.slice_at(2, 16.0).tolist() == [False]
        assert model.slice_at(0, 24.0).tolist() == [True]
