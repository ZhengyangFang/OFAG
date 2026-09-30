"""The agents' dock in the workbench, driven offscreen with a scripted model."""

import os
import threading
import time
from importlib.util import find_spec

import pytest

from ofag.agent.providers import AgentSettings, ProviderConfig, ProviderKind, Reply, ToolCall

pytestmark = pytest.mark.skipif(
    find_spec("PySide6") is None, reason="the desktop extra is not installed"
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)

    def respond(self, system, turns, tools):
        return self.replies.pop(0) if self.replies else Reply(text="done")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _session(tmp_path):
    from ofag.core.schemas import CoordinateConvention, ProjectCreateRequest
    from ofag.desktop.session import Session
    from ofag.services.project_service import ProjectService

    projects = ProjectService(root=tmp_path / "Result")
    record = projects.create(
        ProjectCreateRequest(
            name="Llano",
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            elevation_reference="NAVD88",
            enabled_methods=("ert",),
        )
    )
    return Session.open(projects, record.project_id)


def _panel(replies, saved=None):
    from ofag.desktop.agent_panel import AgentPanel

    local = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key_env="",
    )
    model = Scripted(replies)
    return AgentPanel(
        settings_loader=lambda: AgentSettings(provider=local),
        settings_saver=(saved.append if saved is not None else lambda s: None),
        model_factory=lambda config, key: model,
    )


def _wait_until(condition, seconds=10.0):
    app = _app()
    deadline = time.monotonic() + seconds
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


def test_nothing_can_be_sent_without_a_project() -> None:
    _app()
    panel = _panel([])

    assert not panel.send.isEnabled()
    assert "Open a project" in panel.transcript.toPlainText()


def test_it_says_where_the_conversation_goes() -> None:
    _app()
    panel = _panel([])

    assert "localhost:11434" in panel._where.text()
    assert "on this machine" in panel._where.toolTip()


def test_a_question_is_answered_on_a_worker_thread_and_logged_in_the_project(tmp_path) -> None:
    _app()
    session = _session(tmp_path)
    panel = _panel(
        [
            Reply(text="", tool_calls=(ToolCall("c1", "ofag.journal", {}),)),
            Reply(text="Nothing is owed in this project."),
        ]
    )
    panel.set_session(session)
    panel.input.setPlainText("What is still owed?")

    panel.submit()
    _wait_until(lambda: panel.send.isEnabled())

    text = panel.transcript.toPlainText()
    assert "What is still owed?" in text and "Nothing is owed in this project." in text
    assert "Open a project" not in text
    logs = list((session.runs.artifact_root / "conversations").glob("*.jsonl"))
    assert len(logs) == 1


def test_a_destructive_call_is_put_to_the_person(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    _app()
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No),
    )
    panel = _panel(
        [
            Reply(
                text="",
                tool_calls=(
                    ToolCall(
                        "c1", "ofag.delete_run", {"run_id": "00000000-0000-0000-0000-000000000000"}
                    ),
                ),
            ),
            Reply(text="You declined, so nothing was removed."),
        ]
    )
    panel.set_session(_session(tmp_path))
    panel.input.setPlainText("delete the old run")

    panel.submit()
    _wait_until(lambda: panel.send.isEnabled())

    assert asked and "ofag.delete_run" in asked[0]
    assert "declined by you" in panel.transcript.toPlainText()


def test_the_window_keeps_six_stages_and_gains_a_dock(tmp_path) -> None:
    from ofag.desktop.agent_panel import AgentPanel
    from ofag.desktop.main_window import MainWindow

    _app()
    window = MainWindow(result_root=tmp_path / "Result")

    assert window._pages.count() == 6
    assert isinstance(window.findChild(AgentPanel, "agentPanel"), AgentPanel)


def test_switching_projects_cancels_the_old_task_and_ignores_its_events(tmp_path) -> None:
    _app()
    entered, release = threading.Event(), threading.Event()

    class Blocking:
        def respond(self, system, turns, tools):
            entered.set()
            assert release.wait(5)
            return Reply(text="old project's answer")

    panel = _panel([])
    panel._model_factory = lambda config, key: Blocking()
    panel.set_session(_session(tmp_path / "first"))
    panel.input.setPlainText("old project's question")
    panel.submit()
    try:
        assert entered.wait(5)
        old = panel._active_runner
        assert old is not None
        panel.set_session(_session(tmp_path / "second"))
        assert old.cancelled
        assert not panel.send.isEnabled()
    finally:
        release.set()
    _wait_until(lambda: panel.send.isEnabled())
    assert "old project's" not in panel.transcript.toPlainText()
    assert "Stopped." not in panel.transcript.toPlainText()
    assert panel._turn is None


def test_stop_releases_a_worker_waiting_for_approval(tmp_path) -> None:
    _app()
    panel = _panel([])
    panel.set_session(_session(tmp_path))
    panel._active_runner = panel._runner()
    answers = []
    worker = threading.Thread(
        target=lambda: answers.append(panel._approve_from_worker("lead", "ofag.delete_run", {})),
        daemon=True,
    )
    worker.start()
    panel._stop()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert answers == [False]
    _app().processEvents()
