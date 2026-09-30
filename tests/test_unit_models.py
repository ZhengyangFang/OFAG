"""Labelled models: read back, drawn, and the agents' saved rather than summarised."""

import os
from importlib.util import find_spec

import numpy as np
import pytest

from ofag.services.unit_models import find_unit_models, load_unit_model, save_unit_model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _column_grid():
    """Two columns of three 2 m cells under ground at 100 m."""
    centres = np.array([[x, 0.0, z] for x in (0.0, 10.0) for z in (99.0, 97.0, 95.0)])
    return centres, np.array([0, 0, 1, 0, 1, 2])


@pytest.mark.parametrize(
    "change",
    [
        {"unit": [0.5, 0]},
        {"unit": [0, 2]},
        {"unit": [[0, 0]]},
        {"unit_sources": []},
        {"cell_centres_m": [[0, 0, 0]]},
        {"cell_widths_m": [[1, 1, -1], [1, 1, 1]]},
        {"cell_centres_m": [[0, 0, float("nan")], [0, 0, 1]]},
    ],
)
def test_invalid_model_is_refused_on_read_and_write(tmp_path, change):
    data = dict(
        unit=[0, 0],
        unit_names=["rock"],
        unit_sources=["gravity"],
        cell_centres_m=[[0, 0, 0], [0, 0, 1]],
        cell_widths_m=np.ones((2, 3)),
    )
    data.update(change)
    path = tmp_path / "invalid.npz"
    np.savez(path, **data)
    with pytest.raises(ValueError):
        load_unit_model(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_unit_model(
            path,
            unit=data["unit"],
            unit_names=data["unit_names"],
            unit_sources=data["unit_sources"],
            centres_m=data["cell_centres_m"],
            widths_m=data["cell_widths_m"],
        )
    assert path.read_bytes() == before


def test_save_returns_actual_path_without_truncating_large_labels(tmp_path):
    path = save_unit_model(
        tmp_path / "model",
        unit=[32768],
        unit_names=[str(i) for i in range(32769)],
        unit_sources=[""] * 32769,
        centres_m=[[0, 0, 0]],
    )
    assert path.is_file()
    assert load_unit_model(path).unit.tolist() == [32768]


def test_non_object_metadata_does_not_prevent_loading(tmp_path):
    path = save_unit_model(
        tmp_path / "model.npz",
        unit=[0],
        unit_names=["rock"],
        unit_sources=[""],
        centres_m=[[0, 0, 0]],
    )
    path.with_suffix(".json").write_text("[]", encoding="utf-8")
    assert load_unit_model(path).cells == 1


class TestReadingBack:
    def test_a_grid_model_gets_its_cell_sizes_from_its_own_centres(self, tmp_path) -> None:
        centres, unit = _column_grid()
        path = save_unit_model(
            tmp_path / "imports" / "geological_model.npz",
            unit=unit,
            unit_names=["fill", "granite", "nothing measured here"],
            unit_sources=["ERT", "TDEM", "no method"],
            centres_m=centres,
        )

        model = load_unit_model(path, tmp_path)

        assert model.widths_m[0].tolist() == [10.0, 1.0, 2.0]
        assert [round(s, 3) for _, _, s in model.shares()] == [0.5, 0.333, 0.167]
        assert model.unclaimed(2) and not model.unclaimed(0)

    def test_cells_outside_the_volume_are_no_part_of_its_shares(self, tmp_path) -> None:
        centres, unit = _column_grid()
        unit = unit.copy()
        unit[:2] = -1  # the inversion mesh's padding
        path = save_unit_model(
            tmp_path / "m.npz",
            unit=unit,
            unit_names=["fill", "granite", "rest"],
            unit_sources=["", "", ""],
            centres_m=centres,
        )

        model = load_unit_model(path, tmp_path)

        assert model.cells == 4 and sum(s for _, _, s in model.shares()) == pytest.approx(1.0)

    def test_a_model_without_geometry_takes_the_one_run_mesh_that_fits(self, tmp_path) -> None:
        centres, unit = _column_grid()
        mesh = tmp_path / "runs" / "abc" / "mesh_geometry.npz"
        mesh.parent.mkdir(parents=True)
        np.savez(mesh, cell_centers_m=centres, cell_widths_m=np.full((6, 3), 2.0))
        path = tmp_path / "imports" / "geological_model.npz"
        path.parent.mkdir()
        np.savez(
            path,
            unit=unit,
            unit_names=np.array(["a", "b", "c"]),
            unit_sources=np.array(["", "", ""]),
        )

        model = load_unit_model(path, tmp_path)

        assert model.geometry_from == "the mesh of run abc" and model.widths_m[0].tolist() == [
            2.0,
            2.0,
            2.0,
        ]

    def test_no_mesh_that_fits_is_refused_rather_than_guessed(self, tmp_path) -> None:
        path = tmp_path / "m.npz"
        np.savez(path, unit=np.zeros(5, dtype=int), unit_names=np.array(["a"]))

        with pytest.raises(ValueError, match="nothing honest to draw it on"):
            load_unit_model(path, tmp_path)

    @pytest.mark.parametrize("difference", ["position", "width"])
    def test_same_cell_count_does_not_make_two_meshes_equivalent(self, tmp_path, difference):
        centres, unit = _column_grid()
        centres += np.array([600_000.0, 4_600_000.0, 0.0])
        widths = np.full((len(unit), 3), 2.0)
        for index in range(2):
            mesh = tmp_path / "runs" / str(index) / "mesh_geometry.npz"
            mesh.parent.mkdir(parents=True)
            xy, sizes = centres.copy(), widths.copy()
            if index == 1:
                if difference == "position":
                    xy[:, 0] += 1.0
                else:
                    sizes[:, 2] *= 2.0
            np.savez(mesh, cell_centers_m=xy, cell_widths_m=sizes)
        path = tmp_path / "m.npz"
        np.savez(path, unit=unit, unit_names=np.array(["a", "b", "c"]))
        with pytest.raises(ValueError, match="ambiguous"):
            load_unit_model(path, tmp_path)


class TestTheAgentsModelIsKept:
    def test_build_model_saves_the_labels_where_the_view_finds_them(self, tmp_path) -> None:
        from ofag.agent.dispatch import Dispatcher
        from ofag.agent.tools import Tier

        runs = tmp_path / "runs"
        dispatcher = Dispatcher(artifact_root=runs, granted=(Tier.READ, Tier.COMPUTE, Tier.WRITE))
        grid = dispatcher.call(
            "ofag.cell_grid",
            {
                "spec": {
                    "name": "box",
                    "min_x_m": 0.0,
                    "max_x_m": 20.0,
                    "min_y_m": 0.0,
                    "max_y_m": 20.0,
                    "cell_m": [10.0, 10.0, 2.0],
                    "depth_m": 10.0,
                    "ground_easting_m": [10.0],
                    "ground_northing_m": [10.0],
                    "ground_elevation_m": [100.0],
                    "ground_source": "a flat surface, declared",
                }
            },
        )
        answer = dispatcher.call(
            "ofag.build_model",
            {
                "grid_id": grid["grid_id"],
                "rules": [
                    {
                        "name": "shallow",
                        "source": "a depth rule",
                        "kind": "above_surface",
                        "surface": "base",
                    }
                ],
                "surfaces": {"base": 4.0},
            },
        )

        (path,) = find_unit_models(tmp_path)
        assert answer["saved_to"] == path.as_posix()
        model = load_unit_model(path, tmp_path)
        assert model.cells == grid["cells"]
        assert "nothing claimed" in model.unit_names  # inside the volume, so drawn grey
        assert model.unclaimed(model.unit_names.index("nothing claimed"))


@pytest.mark.skipif(find_spec("PySide6") is None, reason="the desktop extra is not installed")
def test_the_interpretation_stage_draws_the_case_model(tmp_path) -> None:
    from matplotlib.collections import PatchCollection
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import CoordinateConvention, ProjectCreateRequest
    from ofag.desktop.session import Session
    from ofag.desktop.stages.interpretation import InterpretationStage
    from ofag.services.project_service import ProjectService

    QApplication.instance() or QApplication([])
    projects = ProjectService(root=tmp_path / "Result")
    record = projects.create(
        ProjectCreateRequest(
            name="p",
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            elevation_reference="NAVD88",
            enabled_methods=("ert",),
        )
    )
    folder = projects.folder(record.project_id)
    centres, unit = _column_grid()
    save_unit_model(
        folder.root / "imports" / "geological_model.npz",
        unit=unit,
        unit_names=["fill", "granite", "nothing measured here"],
        unit_sources=["ERT", "TDEM", "no method"],
        centres_m=centres,
    )

    stage = InterpretationStage()
    stage.set_session(Session.open(projects, record.project_id))

    tab = stage._labelled
    assert tab._models.itemText(0) == "The case's model"
    axes = tab._plot._figure.axes[0]
    (cells,) = [c for c in axes.collections if isinstance(c, PatchCollection)]
    colours = {tuple(np.round(c, 3)) for c in cells.get_facecolor()}
    assert (0.851, 0.851, 0.851, 1.0) in colours  # the unclaimed unit, grey
    assert "nothing measured here" in "\n".join(t.get_text() for t in axes.get_legend().get_texts())
