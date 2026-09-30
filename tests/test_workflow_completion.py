"""Regressions from exercising saved runs, modelling and conversations as a user."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.core.schemas import RunRecord, RunResult, RunSpec, RunState
from ofag.services.result_review import ResultReview
from ofag.services.run_service import RunService
from tests.conftest import gravity_run_spec

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def saved(runs, spec=None):
    spec = spec or gravity_run_spec()
    record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    runs._persist_record(record)
    runs._persist_run_spec(spec)
    result = RunResult(run_id=spec.run_id, summary={"chi_squared": 1.0}, artifacts=())
    (runs.run_dir(spec.run_id) / "result.json").write_text(result.model_dump_json(), "utf-8")
    return spec


def test_preferred_results_keep_separate_lines_and_replace_only_same_line(tmp_path):
    runs = RunService(artifact_root=tmp_path)
    first = saved(runs)
    second = saved(runs)
    candidate = saved(runs, first.model_copy(update={"run_id": uuid4(), "seed": 4}))
    review = ResultReview(runs)
    review.choose(first.run_id)
    review.choose(second.run_id)
    assert len(review.selections()) == 2
    review.choose(candidate.run_id)
    assert review.preferred(second.run_id) and review.preferred(candidate.run_id)
    assert not review.preferred(first.run_id)


def test_historical_run_with_unnamed_execution_can_be_reviewed_now(tmp_path):
    from ofag.agent.obligations import Ledger, Stage
    from ofag.agent.roles import Role, dispatcher_for
    from ofag.core.schemas import spec_fingerprint

    runs = RunService(artifact_root=tmp_path)
    spec = saved(runs)
    fingerprint = spec_fingerprint(spec)
    ledger = Ledger(tmp_path / "obligations.jsonl")
    for stage in (
        Stage.SPECIFIED,
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
        Stage.EXECUTED,
    ):
        ledger.discharge(stage, fingerprint, f"Historical {stage.value} evidence was saved")

    inversion = dispatcher_for(Role.INVERSION, tmp_path)
    audit = dispatcher_for(Role.AUDIT, tmp_path)
    adopted = inversion.call(
        "ofag.adopt_run",
        {
            "run_id": str(spec.run_id),
            "evidence": "Retrospective adoption of saved run and declared artifacts inspected now",
        },
    )
    assert adopted["adopted"]
    diagnosed = inversion.call(
        "ofag.diagnose",
        {"run_id": str(spec.run_id), "evidence": "Current saved chi squared is 1.0"},
    )
    assert diagnosed["diagnosed"]
    audited = audit.call(
        "ofag.audit",
        {
            "run_id": str(spec.run_id),
            "verdict": "pass",
            "evidence": "Independently checked current saved result and its limits",
        },
    )
    assert audited["audited"]
    assert ResultReview(runs).audit_status(spec.run_id) == "Audit passed (retrospective review)"


def test_large_run_configuration_does_not_hide_quality_from_agent(tmp_path):
    from ofag.agent.orchestrator import LONGEST_RESULT, _render

    runs = RunService(artifact_root=tmp_path)
    spec = saved(
        runs,
        gravity_run_spec().model_copy(update={"parameters": {"array": "x" * LONGEST_RESULT}}),
    )
    response = Dispatcher(tmp_path).call("ofag.inspect_run", {"run_id": str(spec.run_id)})
    shown = _render(response)
    assert '"quality"' in shown and '"audit"' in shown
    assert "not shown" in shown


def test_agent_estimate_keeps_its_uncalibrated_basis(tmp_path):
    result = Dispatcher(tmp_path).call(
        "ofag.estimate", {"spec": gravity_run_spec().model_dump(mode="json")}
    )
    assert result["estimate_basis"] == "heuristic_uncalibrated"
    assert "not a wall-time" in result["note"]


def test_draft_preserves_full_spec_and_cannot_change_method(tmp_path):
    runs = RunService(artifact_root=tmp_path)
    original = saved(runs, gravity_run_spec().model_copy(update={"parameters": {"alpha": 2.0}}))
    dispatcher = Dispatcher(tmp_path, actor="inversion")
    answer = dispatcher.call(
        "ofag.prepare_run",
        {
            "source_run_id": str(original.run_id),
            "changes": {"label": "New", "seed": 7},
        },
    )
    draft = RunSpec.model_validate_json(Path(answer["saved_to"]).read_text("utf-8"))
    assert draft.mesh == original.mesh and draft.parameters == original.parameters
    assert draft.run_id != original.run_id and draft.seed == 7
    inspected = dispatcher.call("ofag.inspect_run", {"run_id": str(draft.run_id)})
    assert inspected["state"] == "draft" and inspected["artifacts"] == []
    assert inspected["spec"] == draft.model_dump(mode="json")
    preview = dispatcher.call("ofag.reuse_run", {"run_id": str(draft.run_id)})
    assert preview["spec"]["run_id"] != str(draft.run_id)
    assert preview["spec"]["parameters"] == inspected["spec"]["parameters"]
    assert not (tmp_path / "drafts" / f"{preview['spec']['run_id']}.json").exists()
    with pytest.raises((KeyError, ToolError)):
        dispatcher.call("ofag.select_result", {"run_id": str(draft.run_id)})
    checked = dispatcher.call("ofag.saved_run", {"run_id": str(draft.run_id), "action": "validate"})
    assert checked["valid"]
    dispatcher.call("ofag.saved_run", {"run_id": str(draft.run_id), "action": "estimate"})
    executed = dispatcher.call(
        "ofag.saved_run",
        {
            "run_id": str(draft.run_id),
            "action": "execute",
        },
    )
    assert executed["ran"] and runs.get(draft.run_id).state is RunState.SUCCEEDED
    assert runs.get(original.run_id).spec == original
    with pytest.raises((ValueError, ToolError), match="identity changes"):
        dispatcher.call(
            "ofag.prepare_run",
            {
                "source_run_id": str(original.run_id),
                "changes": {"plugin_id": "wrong"},
            },
        )


def test_conversation_delegates_adopts_diagnoses_audits_builds_and_exports(tmp_path):
    from ofag.agent.orchestrator import DELEGATE, Orchestrator
    from ofag.agent.providers import Reply
    from ofag.agent.roles import Role
    from tests.test_orchestrator import Scripted, call
    from tests.test_volumes import BOX, GROUND

    runs = RunService(artifact_root=tmp_path / "runs")
    spec = saved(runs)
    run_id = str(spec.run_id)
    np.savez(
        runs.run_dir(spec.run_id) / "stitched_conductivity_section.npz",
        conductivity_s_m=np.array([[0.1, 0.1]]),
        layer_top_depth_m=[0.0, 100.0],
        easting_m=[500.0],
        northing_m=[250.0],
        elevation_m=[245.0],
        chi_squared=[1.0],
    )
    grid_id = Dispatcher(runs.artifact_root).call("ofag.cell_grid", {"spec": {**BOX, **GROUND}})[
        "grid_id"
    ]
    recipe = {
        "grid_id": grid_id,
        "sections": {"aem": {"run_id": run_id}},
        "rules": [
            {
                "name": "Conductor",
                "source": "AEM",
                "kind": "property_threshold",
                "section": "aem",
                "threshold": 20.0,
                "reach_m": 600.0,
            }
        ],
    }
    models = {
        Role.LEAD: Scripted(
            [
                Reply(
                    text="",
                    tool_calls=(
                        call(
                            DELEGATE, role="inversion", task="Adopt and diagnose historical result"
                        ),
                    ),
                ),
                Reply(
                    text="",
                    tool_calls=(
                        call(DELEGATE, role="audit", task="Independently audit the measured fit"),
                    ),
                ),
                Reply(
                    text="",
                    tool_calls=(
                        call(DELEGATE, role="modelling", task="Build the declared model recipe"),
                    ),
                ),
                Reply(
                    text="",
                    tool_calls=(
                        call("ofag.select_result", run_id=run_id),
                        call("ofag.export_report"),
                    ),
                ),
                Reply(text="Model and report saved."),
            ]
        ),
        Role.INVERSION: Scripted(
            [
                Reply(
                    text="",
                    tool_calls=(
                        call(
                            "ofag.adopt_run", run_id=run_id, evidence="Historical arrays inspected"
                        ),
                    ),
                ),
                Reply(
                    text="",
                    tool_calls=(
                        call(
                            "ofag.diagnose", run_id=run_id, evidence="Measured chi squared is 1.0"
                        ),
                    ),
                ),
            ]
        ),
        Role.AUDIT: Scripted(
            [
                Reply(text="", tool_calls=(call("ofag.inspect_run", run_id=run_id),)),
                Reply(
                    text="",
                    tool_calls=(
                        call(
                            "ofag.audit",
                            run_id=run_id,
                            verdict="pass",
                            evidence="Independently read measured chi squared and coordinates",
                        ),
                    ),
                ),
            ]
        ),
        Role.MODELLING: Scripted(
            [Reply(text="", tool_calls=(call("ofag.build_model", **recipe),))]
        ),
    }
    events = []
    runner = Orchestrator(runs.artifact_root, lambda role: models[role], emit=events.append)
    assert (
        runner.ask("Build and report the declared synthetic example") == "Model and report saved."
    )
    assert not [e for e in events if e.kind == "tool_result" and e.detail.get("is_error")]
    model_paths = list((runs.artifact_root / "models").glob("*.npz"))
    assert len(model_paths) == 1
    assert json.loads(model_paths[0].with_suffix(".recipe.json").read_text("utf-8")) == recipe
    assert ResultReview(runs).preferred(spec.run_id)
    assert list((runs.artifact_root / "reports").glob("*.md"))
    refs = [ref for e in events for ref in e.detail.get("references", [])]
    assert {"kind": "model_id", "id": model_paths[0].stem} in refs
    again = Dispatcher(runs.artifact_root, actor="modelling").call("ofag.build_model", recipe)
    assert UUID(again["model_id"]) != UUID(model_paths[0].stem)
    assert model_paths[0].exists()


def test_batch_filter_requires_measured_fit(tmp_path):
    runs = RunService(artifact_root=tmp_path)
    spec = saved(runs)
    np.savez(
        runs.run_dir(spec.run_id) / "stitched_conductivity_section.npz",
        conductivity_s_m=[[0.1]],
        layer_top_depth_m=[0.0],
        easting_m=[0.0],
        northing_m=[0.0],
        elevation_m=[0.0],
    )
    with pytest.raises(ToolError, match="no per-site chi-squared"):
        Dispatcher(tmp_path)._sections_for(
            {
                "test": {
                    "run_id": str(spec.run_id),
                    "chi_squared_at_most": 2.0,
                }
            }
        )


def test_batch_controls_choose_line_depth_and_quality(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.plotting import PlotPanel
    from ofag.desktop.sounding_controls import SoundingControls

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "section.npz"
    np.savez(
        path,
        conductivity_s_m=np.ones((4, 2)),
        layer_top_depth_m=[0.0, 20.0],
        receiver_locations_m=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        sounding_ids=["L1-1", "L1-2", "L2-1", "L2-2"],
        chi_squared=[1, 4, 1, 1],
    )
    panel = PlotPanel()
    controls = SoundingControls(panel)
    controls.load(path, "Survey")
    assert controls.line.count() == 2 and controls.depth_choice.count() == 2
    controls.line.setCurrentText("L2")
    controls.depth_choice.setCurrentIndex(1)
    controls.only_fit.setChecked(True)
    app.processEvents()
    assert "3/4" in controls.note.text()
    assert panel._figure.axes


def test_cell_section_requires_explicit_support_and_does_not_fill_below_mesh():
    from ofag.services.interpretation_service import CellSection

    section = CellSection(np.array([[0, 0, -5], [0, 0, -15]]), np.array([10, 20]))
    distances, values = section.sample(np.array([[0, 0, -5], [0, 0, -25]]))
    assert distances.tolist() == [0, 10]
    assert values[0] == 10 and np.isnan(values[1])


def test_conversation_stop_cancels_its_running_numerical_job(tmp_path):
    from types import SimpleNamespace

    from ofag.agent.session import GuardedRuns

    cancelled = []
    runs = SimpleNamespace(
        artifact_root=tmp_path,
        get=lambda _: SimpleNamespace(state=RunState.RUNNING),
        cancel=cancelled.append,
    )
    guard = GuardedRuns(runs, registry=object(), cancelled=lambda: True)
    run_id = uuid4()
    guard._wait(run_id)
    assert cancelled == [run_id]


def test_mt2d_model_sections_preserve_active_cells_and_require_profile(tmp_path):
    from types import SimpleNamespace

    from ofag.services.model_sections import read_section

    path = tmp_path / "section.npz"
    np.savez(
        path,
        cell_centers_m=[[0, -5], [10, -5], [0, -15], [10, -15]],
        active_cells=[True, False, True, True],
        conductivity_s_m=[[1, 3], [2, 4]],
    )
    result = SimpleNamespace(
        summary={},
        artifacts=[
            SimpleNamespace(
                artifact_type="model",
                relative_path=path.name,
            )
        ],
    )
    runs = SimpleNamespace(
        artifact_root=tmp_path, result=lambda _: result, run_dir=lambda _: tmp_path
    )
    with pytest.raises(ValueError, match="2D mesh needs profile"):
        read_section(runs, uuid4(), {})
    section = read_section(
        runs,
        uuid4(),
        {
            "profile": {
                "origin_easting_m": 100.0,
                "origin_northing_m": 200.0,
                "azimuth_degrees": 90.0,
                "elevation_offset_m": 300.0,
            }
        },
    )
    assert section.values.tolist() == [1, 3, 4]
    np.testing.assert_allclose(
        section.centres_m, [[100, 200, 295], [100, 200, 285], [110, 200, 285]]
    )


def test_gui_reuses_complete_history_and_invalidates_checks_on_edit(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import (
        CoordinateConvention,
        DatasetKind,
        GravityInversionSpec,
        ProjectCreateRequest,
    )
    from ofag.desktop.selection import find_data
    from ofag.desktop.session import Session
    from ofag.desktop.stages.inversion import InversionStage
    from ofag.services.project_service import ProjectService

    QApplication.instance() or QApplication([])
    projects = ProjectService(root=tmp_path / "Result")
    project = projects.create(
        ProjectCreateRequest(
            name="Reuse",
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            enabled_methods=("gravity",),
        )
    )
    dataset = projects.register_dataset(
        project.project_id,
        kind=DatasetKind.GRAVITY,
        name="Survey",
        source_filename="g.csv",
        imported={},
    )
    session = Session.open(projects, project.project_id)
    source = gravity_run_spec().model_copy(
        update={
            "project_id": project.project_id,
            "plugin_id": "simpeg.pf.gravity3d",
            "engine": "simpeg",
            "schema_version": "1.1",
            "physics": GravityInversionSpec().model_dump(mode="json"),
            "source_dataset_ids": (dataset.dataset_id,),
            "parameters": {"observations_path": "g.csv"},
        }
    )
    saved(session.runs, source)
    stage = InversionStage()
    stage.set_session(session)
    # UUID value is re-read from disk; Qt's findData cannot reliably compare it.
    assert find_data(stage._dataset, UUID(str(dataset.dataset_id))) == 1
    spec = stage._spec()
    assert spec is not None
    assert spec.mesh == source.mesh and spec.parameters == source.parameters
    assert spec.dataset == source.dataset
    stage._report.setPlainText("Valid.")
    stage._inputs.set_value({"seed": 7})
    assert "Check again" in stage._report.toPlainText()
    stage.refresh()
    assert stage._inputs.value()["seed"] == 7
    stage._plugin.setCurrentIndex(stage._plugin.findData("ofag.fixture.gravity3d"))
    assert stage._form is None and stage._inputs is not None
    stage._inputs.set_value({"seed": 23, "mesh": source.mesh.model_dump(mode="json")})
    stage.refresh()
    fixture = stage._spec()
    assert fixture.seed == 23 and fixture.mesh == source.mesh
    other = projects.create(
        ProjectCreateRequest(
            name="Empty",
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            enabled_methods=("gravity",),
        )
    )
    stage._report.setPlainText("Valid.")
    stage.set_session(Session.open(projects, other.project_id))
    assert "Valid." not in stage._report.toPlainText()


@pytest.mark.parametrize("plugin_id", ["ofag.fixture.gravity3d", "simpeg.pf.gravity3d"])
def test_locate_agent_draft_preserves_config_across_refresh(tmp_path, plugin_id):
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import (
        CoordinateConvention,
        DatasetKind,
        GravityInversionSpec,
        ProjectCreateRequest,
    )
    from ofag.desktop.main_window import MainWindow
    from ofag.desktop.navigation import Stage

    QApplication.instance() or QApplication([])
    window = MainWindow(result_root=tmp_path / "Result")
    project = window._projects.create(
        ProjectCreateRequest(
            name="Drafts",
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            enabled_methods=("gravity",),
        )
    )
    data = window._projects.register_dataset(
        project.project_id,
        kind=DatasetKind.GRAVITY,
        name="Survey",
        source_filename="g.csv",
        imported={},
    )
    window.open_project(project.project_id)
    session = window._session
    source = gravity_run_spec().model_copy(
        update={
            "project_id": project.project_id,
            "plugin_id": plugin_id,
            "source_dataset_ids": (data.dataset_id,),
            "label": "Saved draft",
            "parameters": {"custom": 2.0},
            "seed": 31,
            "physics": GravityInversionSpec().model_dump(mode="json")
            if plugin_id.startswith("simpeg")
            else None,
            "schema_version": "1.1" if plugin_id.startswith("simpeg") else "1.0",
        }
    )
    path = session.folder.runs_root / "drafts" / f"{source.run_id}.json"
    path.parent.mkdir(parents=True)
    path.write_text(source.model_dump_json(), "utf-8")
    session.events.focus_requested.emit("run_id", str(source.run_id))
    assert session.active_stage == Stage.INVERSION.value
    stage = window._stages[Stage.INVERSION]
    assert "Saved draft" in stage._report.toPlainText()
    assert stage._spec().model_dump(exclude={"run_id"}) == source.model_dump(exclude={"run_id"})
    stage._inputs.set_value({"seed": 32})
    stage.refresh()
    edited = stage._spec()
    assert edited.seed == 32 and edited.label == source.label
    assert edited.dataset == source.dataset and edited.parameters == source.parameters
    assert path.read_text("utf-8") == source.model_dump_json()
    assert not session.runs.list_runs()
    # Once executed, the same reference must take the user to its result.
    saved(session.runs, source)
    session.events.focus_requested.emit("run_id", str(source.run_id))
    assert session.active_stage == Stage.RESULTS.value
    window.close()


def test_survey_map_keeps_duplicate_names_and_reports_unmapped_profiles(tmp_path):
    from ofag.core.schemas import CoordinateConvention, DatasetKind, ProjectCreateRequest
    from ofag.services.project_service import ProjectService
    from ofag.services.survey_coverage import project_coverage

    projects = ProjectService(tmp_path / "Result")
    project = projects.create(
        ProjectCreateRequest(
            name="Coverage",
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            enabled_methods=("gravity", "ert"),
        )
    )
    for index in range(2):
        path = tmp_path / f"g{index}.csv"
        path.write_text(f"x_m,y_m,z_m,gravity_mgal\n{index},2,3,0.1\n", "utf-8")
        projects.register_dataset(
            project.project_id,
            kind=DatasetKind.GRAVITY,
            name="Survey",
            source_filename=path.name,
            imported={"canonical_observations_path": str(path)},
        )
    projects.register_dataset(
        project.project_id,
        kind=DatasetKind.ERT,
        name="Local profile",
        source_filename="ert.csv",
        imported={},
    )
    coverage = project_coverage(projects.folder(project.project_id).root)
    assert len(coverage.stations) == 2
    assert sorted(p[0, 0] for p in coverage.stations.values()) == [0.0, 1.0]
    assert "Local profile" in coverage.unavailable
    result = Dispatcher(projects.folder(project.project_id).runs_root).call(
        "ofag.survey_coverage", {}
    )
    assert len(result["datasets"]) == 2 and result["crs"] == "EPSG:26912"
