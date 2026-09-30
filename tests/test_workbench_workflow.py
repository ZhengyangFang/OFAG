"""User workflows across pages and isolated background calculations."""

import os
import time

import pytest
from pydantic import BaseModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def wait(app, predicate, seconds=15):
    end = time.monotonic() + seconds
    while not predicate():
        app.processEvents()
        assert time.monotonic() < end, "Background action timed out"
        time.sleep(0.01)


def test_background_result_error_and_cancellation(app):
    from ofag.desktop.tasks import BackgroundTask

    task = BackgroundTask()
    answers, errors, states = [], [], []
    task.succeeded.connect(answers.append)
    task.failed.connect(errors.append)
    task.status.connect(states.append)
    task.start("Computing", pow, 2, 5)
    wait(app, lambda: bool(answers))
    assert answers == [32] and not task.busy
    task.start("Invalid", int, "bad")
    wait(app, lambda: bool(errors))
    assert "ValueError" in errors[0]
    task.start("Long operation", time.sleep, 30)
    task.cancel()
    assert states[-1] == "Cancelled" and not task.busy
    assert answers == [32]


def test_array_editor_roundtrips_rows_and_invalid_json(app):
    from ofag.desktop.specform import SpecForm

    class Model(BaseModel):
        values: list[float] | None = None

    form = SpecForm(Model, grouped=True)
    assert form.value() == {"values": None}
    editor = form._editors["values"]
    editor._add()
    editor._table.item(0, 0).setText("1e-8")
    assert form.parsed().values == [1e-8]
    editor._mode.setChecked(True)
    editor._raw.setPlainText("[broken")
    editor._mode.setChecked(False)
    assert editor._mode.isChecked()
    assert form.errors()
    draft = form.value()
    restored = SpecForm(Model, grouped=True)
    restored.set_value(draft)
    assert restored.value() == draft
    editor._raw.setPlainText("[2, 3]")
    editor._mode.setChecked(False)
    assert form.parsed().values == [2.0, 3.0]


def test_project_change_reaches_inversion_without_losing_draft(app, tmp_path):
    from ofag.core.schemas import CoordinateConvention, DatasetKind, ProjectCreateRequest
    from ofag.desktop.main_window import MainWindow
    from ofag.desktop.navigation import Stage

    window = MainWindow(result_root=tmp_path)
    record = window._projects.create(
        ProjectCreateRequest(
            name="Workflow",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    window.open_project(record.project_id)
    session = window._session
    stage = window._stages[Stage.INVERSION]
    stage._plugin.setCurrentIndex(stage._plugin.findData("simpeg.pf.gravity3d"))
    original = stage._form.value()
    session.projects.register_dataset(
        record.project_id,
        kind=DatasetKind.GRAVITY,
        name="New data",
        source_filename="g.csv",
        imported={},
    )
    session.events.changed.emit("workspace")
    session.events.navigate.emit("inversion")
    assert stage._dataset.count() == 2
    assert stage._form.value() == original
    window.close()


def test_knowledge_root_is_independent_of_working_directory(tmp_path, monkeypatch):
    from ofag.agent.lessons import load_lessons
    from ofag.agent.resources import DOCS_ROOT

    monkeypatch.chdir(tmp_path)
    assert DOCS_ROOT.is_absolute()
    assert load_lessons()


def test_history_reads_truncated_log_without_executing(app, tmp_path):
    from ofag.desktop.conversation_history import ConversationHistory

    (tmp_path / "one.jsonl").write_text(
        '{"kind":"user","text":"Review my run"}\n{broken', encoding="utf-8"
    )
    dialog = ConversationHistory(tmp_path)
    assert "Review my run" in dialog._text.toPlainText()
    assert "Incomplete log entry" in dialog._text.toPlainText()


def test_configuration_diff_records_actual_values():
    from ofag.services.project_changes import configuration_changes

    assert configuration_changes(
        {"physics": {"max_iterations": 10}}, {"physics": {"max_iterations": 20}}
    ) == ["/physics/max_iterations: 10 -> 20"]


def test_preferred_result_is_persistent_and_does_not_grant_audit(tmp_path):
    from types import SimpleNamespace

    from ofag.core.schemas import RunRecord, RunResult, RunState
    from ofag.services.result_review import ResultReview
    from tests.conftest import gravity_run_spec

    spec = gravity_run_spec()
    record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    runs = SimpleNamespace(
        artifact_root=tmp_path,
        get=lambda _: record,
        result=lambda _: RunResult(run_id=spec.run_id, summary={}, artifacts=()),
    )
    review = ResultReview(runs)
    review.choose(spec.run_id)
    assert ResultReview(runs).preferred(spec.run_id)
    assert review.audit_status(spec.run_id) == "Not audited"


def test_vetoed_result_cannot_be_preferred(tmp_path):
    from types import SimpleNamespace

    from ofag.agent.obligations import Ledger, Stage
    from ofag.core.schemas import RunRecord, RunState, spec_fingerprint
    from ofag.services.result_review import ResultReview
    from tests.conftest import gravity_run_spec

    spec = gravity_run_spec()
    ledger = Ledger(tmp_path / "obligations.jsonl")
    fingerprint = spec_fingerprint(spec)
    for stage in (Stage.ADOPTED, Stage.DIAGNOSED):
        ledger.discharge(stage, fingerprint, "evidence checked and recorded", by="producer")
    ledger.discharge(
        Stage.VETOED, fingerprint, "result is unsupported by observations", by="auditor"
    )
    runs = SimpleNamespace(
        artifact_root=tmp_path,
        get=lambda _: RunRecord(spec=spec, state=RunState.SUCCEEDED),
        result=lambda _: object(),
    )
    with pytest.raises(ValueError, match="vetoed"):
        ResultReview(runs).choose(spec.run_id)
    assert not (tmp_path / "preferred_results.json").exists()


def test_comparison_uses_one_colour_scale_and_reports_configuration_diff(app):
    import numpy as np

    from ofag.core.cell_model import CellModel
    from ofag.core.schemas import RunRecord, RunResult, RunState
    from ofag.desktop.plotting import PlotPanel
    from ofag.desktop.result_comparison import ResultComparison
    from tests.conftest import gravity_run_spec

    first = gravity_run_spec()
    second = first.model_copy(update={"label": "Candidate", "parameters": {"max_iterations": 20}})
    records = [RunRecord(spec=s, state=RunState.SUCCEEDED) for s in (first, second)]
    results = [
        RunResult(run_id=s.run_id, summary={"misfit": 1}, artifacts=()) for s in (first, second)
    ]
    models = [
        (
            CellModel(
                np.array(values),
                np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 2.0]]),
                np.ones(2),
                np.ones((2, 3)),
            ),
            "density",
            "g/cm^3",
        )
        for values in ([1.0, 2.0], [3.0, 4.0])
    ]
    dialog = ResultComparison(records, results, models)
    panels = dialog.findChildren(PlotPanel)
    assert [panel._figure.axes[0].collections[0].get_clim() for panel in panels] == [
        (1.0, 4.0),
        (1.0, 4.0),
    ]


def test_related_records_accept_only_real_identifiers():
    from uuid import uuid4

    from ofag.services.project_changes import related_records

    assert related_records({"model_id": "geological_model"}) == [
        {"kind": "model_id", "id": "geological_model"}
    ]
    assert related_records({"model_id": "../outside"}) == []

    run_id = str(uuid4())
    assert related_records({"run_id": run_id, "dataset_id": "not an id"}) == [
        {"kind": "run_id", "id": run_id}
    ]


def test_result_refresh_keeps_selection_and_does_not_redraw_completed_model(
    app, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from uuid import uuid4

    from PySide6.QtCore import QItemSelectionModel, Qt

    from ofag.core.schemas import RunRecord, RunResult, RunState
    from ofag.desktop.stages.results import ResultsStage
    from tests.conftest import gravity_run_spec

    specs = [gravity_run_spec().model_copy(update={"run_id": uuid4()}) for _ in range(2)]
    records = [RunRecord(spec=s, state=RunState.SUCCEEDED) for s in specs]

    def result(run_id):
        return RunResult(run_id=run_id, summary={}, artifacts=())

    runs = SimpleNamespace(
        artifact_root=tmp_path,
        list_runs=lambda: records,
        get=lambda run_id: next(r for r in records if r.spec.run_id == run_id),
        result=result,
        events=lambda _: [],
    )
    stage = ResultsStage()
    session = SimpleNamespace(runs=runs, folder=SimpleNamespace(runs_root=tmp_path))
    drawn = []
    monkeypatch.setattr(stage, "_draw_section", lambda *args: drawn.append(args[1]))
    stage.set_session(session)
    stage._table.setCurrentCell(0, 0)
    stage._table.selectRow(0)
    stage._table.selectionModel().select(
        stage._table.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    selected_id = stage._selected_run_id()
    drawn.clear()
    records.reverse()
    stage.refresh()
    assert stage._selected_run_id() == selected_id
    assert {
        str(stage._table.item(index.row(), 5).data(Qt.ItemDataRole.UserRole))
        for index in stage._table.selectionModel().selectedRows()
    } == {str(s.run_id) for s in specs}
    assert drawn == []
