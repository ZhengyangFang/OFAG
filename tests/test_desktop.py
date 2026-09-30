"""The desktop workbench: its structure, and where it puts things."""

import os
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ofag.core.schemas import (
    CoordinateConvention,
    DatasetKind,
    ProjectCreateRequest,
    ProjectDataset,
)
from ofag.desktop.navigation import STAGES, Stage, stage_info
from ofag.services.project_service import ProjectService

needs_qt = pytest.mark.skipif(
    find_spec("PySide6") is None, reason="the desktop extra is not installed"
)

# Offscreen before Qt is imported anywhere, so a test run never needs a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _project(root: Path) -> tuple[ProjectService, object]:
    projects = ProjectService(root=root)
    record = projects.create(
        ProjectCreateRequest(
            name="Soda Lake geothermal",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            elevation_reference="NAVD88",
            enabled_methods=("seismic", "ert"),
        )
    )
    return projects, record.project_id


def test_work_divides_into_stages_rather_than_method_by_stage() -> None:
    """The browser workbench had twenty-six places, fifteen of them one method crossed with
    one stage."""
    assert len(STAGES) == 6
    assert [info.stage for info in STAGES] == list(Stage)
    for info in STAGES:
        assert info.title.strip()
        # The purpose is shown under the heading rather than left to documentation
        # nobody opens while working.
        assert info.purpose.strip() and len(info.purpose) <= 80


def test_every_stage_has_an_entry_and_a_missing_one_is_loud() -> None:
    for stage in Stage:
        assert stage_info(stage).stage is stage
    with pytest.raises(KeyError, match="missing from STAGES"):
        stage_info("nonsense")  # type: ignore[arg-type]


@needs_qt
def test_lineage_never_guesses_between_same_named_datasets() -> None:
    from ofag.desktop.stages.lineage import _source_datasets

    first = ProjectDataset(
        dataset_id=uuid4(),
        name="survey",
        kind=DatasetKind.GRAVITY,
        source_filename="one.csv",
        payload={},
    )
    second = ProjectDataset(
        dataset_id=uuid4(),
        name="survey",
        kind=DatasetKind.GRAVITY,
        source_filename="two.csv",
        payload={},
    )
    old = SimpleNamespace(
        spec=SimpleNamespace(
            dataset=SimpleNamespace(name="survey"), datasets=(), source_dataset_ids=()
        )
    )
    assert _source_datasets(old, (first, second)) == ()

    channel = SimpleNamespace(source_dataset_id=second.dataset_id)
    linked = SimpleNamespace(
        spec=SimpleNamespace(dataset=old.spec.dataset, datasets=(channel,), source_dataset_ids=())
    )
    assert _source_datasets(linked, (first, second)) == (second,)


@needs_qt
def test_joint_inversion_can_select_both_observation_channels() -> None:
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.stages.inversion import InversionStage

    application = QApplication.instance() or QApplication([])
    assert application is not None
    gravity = ProjectDataset(
        dataset_id=uuid4(),
        name="gravity",
        kind=DatasetKind.GRAVITY,
        source_filename="gravity.csv",
        payload={"canonical_observations_path": "g.csv"},
    )
    magnetic = ProjectDataset(
        dataset_id=uuid4(),
        name="magnetic",
        kind=DatasetKind.MAGNETICS,
        source_filename="magnetic.csv",
        payload={"canonical_observations_path": "m.csv"},
    )
    session = SimpleNamespace(
        workspace=lambda: SimpleNamespace(datasets=(gravity, magnetic)),
        record=SimpleNamespace(coordinate_convention=CoordinateConvention(crs="EPSG:32109")),
    )
    stage = InversionStage()
    stage._plugin.addItem("joint", "simpeg.joint.gravmag.cross_gradient")
    stage._dataset.addItem("gravity", gravity.dataset_id)
    stage._second_dataset.addItem("magnetic", magnetic.dataset_id)

    channels = stage._channels(session)

    assert [item.channel_id for item in channels] == ["gravity", "tmi"]
    assert [item.source_dataset_id for item in channels] == [
        gravity.dataset_id,
        magnetic.dataset_id,
    ]


@needs_qt
def test_mt_directory_import_registers_site_paths_without_array_dumps(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.dialogs.importers import ImportDialog

    application = QApplication.instance() or QApplication([])
    assert application is not None
    source = tmp_path / "edi"
    source.mkdir()
    (source / "one.edi").write_text("placeholder", encoding="utf-8")
    site = SimpleNamespace(
        sounding_id="one",
        observations_path="Result/site.csv",
        easting_m=100.0,
        northing_m=200.0,
        elevation_m=30.0,
    )
    imported = SimpleNamespace(
        dataset_id=uuid4(),
        directory="Result/imports/one",
        files_read=1,
        impedance_component="xy",
        refused_as_three_dimensional=(),
        soundings=(site,),
    )
    from ofag.services.mt_import import ImportedMtSoundings

    imported.catalog_payload = lambda: ImportedMtSoundings.catalog_payload(imported)
    service = SimpleNamespace(import_edi_directory=lambda request: imported)
    session = SimpleNamespace(
        record=SimpleNamespace(coordinate_convention=CoordinateConvention(crs="EPSG:32109")),
        mt_imports=service,
    )

    payload = ImportDialog(DatasetKind.MT, source).run(session)

    assert payload["soundings"] == [
        {
            "site_id": "one",
            "observations_path": "Result/site.csv",
            "easting_m": 100.0,
            "northing_m": 200.0,
            "elevation_m": 30.0,
        }
    ]


@needs_qt
def test_the_window_builds_every_stage_and_names_the_project_folder(tmp_path: Path) -> None:
    """The folder is on screen because a workbench that writes files somewhere a person
    cannot name is one they cannot back up."""
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.main_window import MainWindow

    root = tmp_path / "Result"
    projects, project_id = _project(root)
    application = QApplication.instance() or QApplication([])
    assert application is not None

    window = MainWindow(result_root=root)
    window.open_project(project_id)

    folder = projects.folder(project_id)
    assert not folder.workspace_path.exists()
    window._poll_project()
    assert window._revision is not None
    assert "Could not refresh" not in window.statusBar().currentMessage()
    assert window._folder_label.text() == f"Result / {folder.root.name}"
    assert window._folder_label.toolTip() == str(folder.root.resolve())
    assert window._pages.count() == len(STAGES)
    for row, info in enumerate(STAGES):
        window._sidebar.setCurrentRow(row)
        assert window._pages.currentIndex() == row
        assert window._pages.currentWidget().session is not None, info.title
    window.open_project(project_id)
    assert window._session.active_stage == STAGES[-1].stage.value


@needs_qt
def test_a_session_roots_every_service_in_the_open_project(tmp_path: Path) -> None:
    """The reason nothing else has to know where anything is kept."""
    from ofag.desktop.session import Session

    root = tmp_path / "Result"
    projects, project_id = _project(root)
    session = Session.open(projects, project_id)
    folder = projects.folder(project_id)

    assert session.runs.artifact_root == folder.runs_root
    assert session.imports.import_root == folder.imports_root
    assert session.segy_imports.import_root == folder.imports_root
    assert session.seismic.import_root == folder.imports_root
    assert session.ert_imports.import_root == folder.imports_root
    # Everything is inside the one directory, which is the whole point.
    for path in (folder.imports_root, folder.runs_root, folder.record_path):
        assert folder.root in path.parents or path.parent == folder.root


@needs_qt
def test_the_workspace_survives_a_round_trip_through_the_session(tmp_path: Path) -> None:
    from ofag.desktop.session import Session

    root = tmp_path / "Result"
    projects, project_id = _project(root)
    session = Session.open(projects, project_id)

    workspace = session.workspace()
    saved = session.save_workspace(workspace.model_copy(update={"active_dataset_ids": {}}))

    assert saved.project_id == project_id
    assert projects.folder(project_id).workspace_path.is_file()


@needs_qt
def test_a_form_exists_for_every_plugin_that_declares_a_model() -> None:
    """A method registered tomorrow is configurable the moment it is registered."""
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.specform import SpecForm
    from ofag.plugins.registry import default_registry

    application = QApplication.instance() or QApplication([])
    assert application is not None

    declared = 0
    for plugin in default_registry().all():
        model = plugin.physics_model()
        if model is None:
            continue
        declared += 1
        form = SpecForm(model)
        # Every field in the model has an editor, and reading them back gives the
        # model's own JSON shape.
        assert set(form.value()) == set(model.model_fields)
    assert declared >= 3


@needs_qt
def test_an_optional_number_can_be_absent_rather_than_zero() -> None:
    """A spin box cannot express absence, and zero is not absence."""
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.specform import SpecForm
    from ofag.plugins.pygimli_ert import ERTInversionSpec

    application = QApplication.instance() or QApplication([])
    assert application is not None

    form = SpecForm(ERTInversionSpec)

    # An untouched form is missing exactly what the person has not supplied yet, and
    # nothing else.
    assert form.errors() == [
        "array.electrodes_path: Input should be a valid string",
        "array.quadrupoles_path: Input should be a valid string",
    ]

    form.set_value({"array": {"electrodes_path": "e.npy", "quadrupoles_path": "q.npy"}})

    assert form.errors() == []
    quality = form.value()["quality"]
    assert isinstance(quality, dict)
    assert quality["maximum_geometric_factor"] is None


@needs_qt
def test_a_quantity_is_edited_with_its_unit_and_never_as_a_bare_number() -> None:
    """The whole point of the type is that the unit travels with the value."""
    from pydantic import BaseModel
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import QuantitySpec
    from ofag.desktop.specform import SpecForm

    application = QApplication.instance() or QApplication([])
    assert application is not None

    class Holds(BaseModel):
        depth: QuantitySpec

    form = SpecForm(Holds)
    form.set_value({"depth": {"value": 12.0, "quantity_type": "length", "unit": "m"}})

    assert form.value()["depth"] == {"value": 12.0, "quantity_type": "length", "unit": "m"}
    assert form.errors() == []


@needs_qt
def test_units_boreholes_and_readiness_work_through_the_interpretation_stage(
    tmp_path: Path,
) -> None:
    """The differentiating stage, driven as a person would drive it."""
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.session import Session
    from ofag.desktop.stages.interpretation import InterpretationStage

    root = tmp_path / "Result"
    projects, project_id = _project(root)
    application = QApplication.instance() or QApplication([])
    assert application is not None

    stage = InterpretationStage()
    stage.set_session(Session.open(projects, project_id))

    units = stage._units
    for name in ("Cover", "Bedrock"):
        units._name.setText(name)
        units._add()

    holes = stage._boreholes
    holes._name.setText("BH-1")
    holes._east.setValue(100.0)
    holes._elevation.setValue(350.0)
    holes._depth.setValue(60.0)
    holes._add_hole()
    holes._table.selectRow(0)
    holes._unit.setCurrentIndex(0)
    holes._from.setValue(0.0)
    holes._to.setValue(20.0)
    holes._add_interval()

    model = units.model()
    assert model is not None
    assert [unit.name for unit in model.units] == ["Cover", "Bedrock"]
    assert len(model.boreholes) == 1
    # The logged contact reaches the interpolation as a surface point, which is the
    # reason a borehole is in the geological model at all.
    assert len(model.borehole_points()) == 1

    stage._surfaces.reload()
    said = stage._surfaces._readiness.toPlainText()
    assert "1 logged contacts" in said
    assert "Not ready to interpolate" in said


@needs_qt
def test_a_section_is_read_from_the_run_folder_whatever_the_manifest_path_says(
    tmp_path: Path,
) -> None:
    """An artifact path is relative to the artifact root, not to the run."""
    import numpy as np

    from ofag.core.constants import QuantityType
    from ofag.core.schemas import ArtifactManifest, RunResult
    from ofag.desktop.stages.results import _artifact, _geometry, _quantity_of

    run_id = uuid4()
    centers = np.column_stack([np.arange(5.0), np.linspace(0.0, -4.0, 5), np.zeros(5)])
    np.savez(tmp_path / "mesh_geometry.npz", cell_centers_m=centers)
    np.save(tmp_path / "recovered_model.npy", np.full(5, 42.0))
    result = RunResult(
        run_id=run_id,
        summary={},
        artifacts=(
            ArtifactManifest(
                artifact_id=uuid4(),
                artifact_type="recovered_model",
                physical_quantity=QuantityType.RESISTIVITY,
                units="ohm*m",
                source_run_id=run_id,
                relative_path=f"{run_id}/recovered_model.npy",
            ),
            ArtifactManifest(
                artifact_id=uuid4(),
                artifact_type="mesh_geometry",
                physical_quantity=QuantityType.LENGTH,
                units="m",
                source_run_id=run_id,
                relative_path="mesh_geometry.npz",
            ),
        ),
    )

    geometry = _geometry(tmp_path, result)
    model = _artifact(tmp_path, result, "recovered_model")

    assert geometry is not None
    read_centers, _volumes, _active, _widths = geometry
    assert read_centers.shape == (5, 3)
    assert model is not None and model.tolist() == [42.0] * 5
    # The colour bar is labelled from the manifest, so a section never shows a number
    # without saying what it is.
    assert _quantity_of(result, "recovered_model") == ("resistivity", "ohm*m")
    assert _artifact(tmp_path, result, "not_produced") is None


@needs_qt
def test_an_untouched_form_is_valid_exactly_when_the_model_needs_no_input() -> None:
    """The invariant that makes a generated form usable rather than decorative."""
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.specform import SpecForm
    from ofag.plugins.registry import default_registry

    application = QApplication.instance() or QApplication([])
    assert application is not None

    checked = 0
    for plugin in default_registry().all():
        model = plugin.physics_model()
        if model is None:
            continue
        checked += 1
        try:
            model()
        except ValidationError:
            # Required fields with no default: the form must say which, and naming them
            # is the whole job.
            assert SpecForm(model).errors(), plugin.plugin_id
        else:
            assert SpecForm(model).errors() == [], plugin.plugin_id
    # Every method that declares a model, not a sample of them.
    assert checked >= 8


@needs_qt
def test_a_small_default_survives_the_form_it_is_shown_in() -> None:
    """A spin box at six decimals turned 1e-08 into zero, and the model refuses zero."""
    from pydantic import BaseModel, Field
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.specform import SpecForm

    application = QApplication.instance() or QApplication([])
    assert application is not None

    class Thresholds(BaseModel):
        irls: float = Field(default=1e-08, gt=0)
        sensitivity: float = Field(default=1e-12, gt=0)

    form = SpecForm(Thresholds)

    assert form.errors() == []
    assert form.value() == {"irls": 1e-08, "sensitivity": 1e-12}


@needs_qt
def test_an_optional_sub_model_can_be_absent_rather_than_blank() -> None:
    """`ArrayInputSpec | None` is not an ArrayInputSpec with empty strings in it."""
    from pydantic import BaseModel
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import ArrayInputSpec
    from ofag.desktop.specform import SpecForm

    application = QApplication.instance() or QApplication([])
    assert application is not None

    class Holds(BaseModel):
        initial_model: ArrayInputSpec | None = None

    form = SpecForm(Holds)

    assert form.errors() == []
    assert form.value()["initial_model"] is None
    # And setting one turns it back on, so the absence is a state and not a dead end.
    form.set_value(
        {"initial_model": {"path": "m.npy", "quantity_type": "density_contrast", "unit": "g/cm^3"}}
    )
    assert form.value()["initial_model"] == {
        "path": "m.npy",
        "quantity_type": "density_contrast",
        "unit": "g/cm^3",
    }


def test_a_section_is_drawn_for_a_model_on_the_active_cells_alone(tmp_path) -> None:
    """A potential-field model is shorter than its mesh, and the page has to know."""
    import numpy as np

    from ofag.core.cell_model import CellModel
    from ofag.core.constants import QuantityType
    from ofag.core.schemas import ArtifactManifest, RunResult
    from ofag.desktop.stages.results import _geometry

    run_id = uuid4()
    centres = np.column_stack(
        [np.arange(6.0), np.zeros(6), np.array([2.0, 1.0, 0.0, 2.0, 1.0, 0.0])]
    )
    active = np.array([False, True, True, False, True, True])
    np.savez(
        tmp_path / "mesh_geometry.npz",
        cell_centers_m=centres,
        cell_volumes_m3=np.full(6, 8.0),
        active_cells=active,
    )
    result = RunResult(
        run_id=run_id,
        summary={},
        artifacts=(
            ArtifactManifest(
                artifact_id=uuid4(),
                artifact_type="mesh_geometry",
                physical_quantity=QuantityType.LENGTH,
                units="m",
                source_run_id=run_id,
                relative_path="mesh_geometry.npz",
            ),
        ),
    )

    geometry = _geometry(tmp_path, result)

    assert geometry is not None
    read_centres, volumes, read_active, widths = geometry
    assert read_centres.shape == (6, 3)
    model = CellModel.on_active_cells(np.arange(4.0), read_centres, volumes, read_active, widths)
    assert model.centres.shape == (4, 3), "the section must be drawn on the active cells"
    assert np.array_equal(model.centres, centres[active])


def test_the_geometry_reader_fills_in_what_an_older_run_did_not_publish(tmp_path) -> None:
    """A run written before volumes and the mask were saved still has to draw."""
    import numpy as np

    from ofag.core.constants import QuantityType
    from ofag.core.schemas import ArtifactManifest, RunResult
    from ofag.desktop.stages.results import _geometry

    run_id = uuid4()
    centres = np.column_stack([np.arange(4.0), np.zeros(4), np.zeros(4)])
    np.savez(tmp_path / "mesh_geometry.npz", cell_centers_m=centres)
    result = RunResult(
        run_id=run_id,
        summary={},
        artifacts=(
            ArtifactManifest(
                artifact_id=uuid4(),
                artifact_type="mesh_geometry",
                physical_quantity=QuantityType.LENGTH,
                units="m",
                source_run_id=run_id,
                relative_path="mesh_geometry.npz",
            ),
        ),
    )

    geometry = _geometry(tmp_path, result)

    assert geometry is not None
    read_centres, volumes, active, widths = geometry
    assert read_centres.shape == (4, 3)
    assert volumes.tolist() == [1.0, 1.0, 1.0, 1.0]
    assert active.all()
    assert widths is None, "an older run has no widths, and the model falls back to cubes"


def test_the_section_frame_does_not_move_between_slices() -> None:
    """Sliding through a model must not reframe the picture at every step."""
    import numpy as np

    from ofag.core.cell_model import CellModel
    from ofag.desktop.stages.results import _refined_limits

    # A model wider at the bottom than at the top, so a frame fitted to the visible
    # cells would be a different width at every elevation.
    centres = np.array([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0], [900.0, 0.0, 0.0], [0.0, 0.0, 100.0]])
    model = CellModel(
        np.arange(4.0), centres, np.full(4, 1000.0), np.tile(np.array([10.0, 10.0, 10.0]), (4, 1))
    )

    frames = {_refined_limits(model, [0, 2]) for _ in range(3)}

    assert len(frames) == 1
    (x_span, _z_span) = frames.pop()
    assert x_span[0] < -4.0 and x_span[1] > 904.0, "the frame spans the whole model"


def test_a_plan_view_is_drawn_undistorted_and_a_cross_section_is_not() -> None:
    """Both axes of a depth slice are horizontal distance, so a round body has to come out
    round."""
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from ofag.core.cell_model import CellModel
    from ofag.desktop.stages.results import ResultsStage

    QApplication.instance() or QApplication([])
    grid = np.array([[x, y, z] for x in (0.0, 50.0) for y in (0.0, 50.0) for z in (0.0, 50.0)])
    model = CellModel(
        np.arange(len(grid)),
        grid,
        np.full(len(grid), 1.0e5),
        np.tile(np.array([50.0, 50.0, 50.0]), (len(grid), 1)),
    )
    stage = ResultsStage()
    stage._sliced = (model, "density", "g/cm^3", False)
    stage._reset_colour_limits()

    stage._slice_axis.setCurrentIndex(2)
    stage._draw_slice()
    assert stage._section._figure.axes[0].get_aspect() == 1.0

    stage._slice_axis.setCurrentIndex(1)
    stage._draw_slice()
    assert stage._section._figure.axes[0].get_aspect() == "auto"
