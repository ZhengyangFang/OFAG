"""The agents answer about the open project from the project, and show their working."""

import json
import os
from importlib.util import find_spec

import pytest

from ofag.agent.orchestrator import Orchestrator
from ofag.agent.project_context import LESSONS_ARE_NOT_DATA, ProjectContext
from ofag.agent.providers import (
    AnthropicModel,
    OpenAICompatibleModel,
    OpenAIResponsesModel,
    ProviderConfig,
    ProviderKind,
    Reply,
    ToolCall,
    Turn,
)
from ofag.agent.roles import Role, brief, dispatcher_for, spec_for

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _project(tmp_path):
    from ofag.core.schemas import CoordinateConvention, ProjectCreateRequest
    from ofag.services.project_service import ProjectService

    projects = ProjectService(root=tmp_path / "Result")
    record = projects.create(
        ProjectCreateRequest(
            name="Cedar Rapids",
            coordinate_convention=CoordinateConvention(crs="EPSG:26915"),
            elevation_reference="NAVD88",
            enabled_methods=("ert",),
        )
    )
    return projects.folder(record.project_id).runs_root


class TestTheProjectTool:
    def test_every_role_can_ask_what_the_project_holds(self, tmp_path) -> None:
        runs = _project(tmp_path)
        for role in Role:
            assert "ofag.project" in spec_for(role).holds

        facts = dispatcher_for(Role.DATA, runs).call("ofag.project", {})

        assert (facts["name"], facts["crs"], facts["methods"]) == (
            "Cedar Rapids",
            "EPSG:26915",
            ["ert"],
        )
        assert facts["datasets"] == [] and facts["runs"] == []
        assert facts["note"] == LESSONS_ARE_NOT_DATA

    def test_a_runs_folder_that_is_no_project_says_so(self, tmp_path) -> None:
        from ofag.agent.dispatch import ToolError

        with pytest.raises(ToolError, match="no project.json"):
            dispatcher_for(Role.DATA, tmp_path / "loose").call("ofag.project", {})

    def test_it_finds_the_project_from_the_runs_folder_alone(self, tmp_path) -> None:
        runs = _project(tmp_path)

        assert ProjectContext.find(runs).summary()["name"] == "Cedar Rapids"
        assert ProjectContext.find(tmp_path) is None


class TestWhatAnAgentIsTold:
    def test_every_agent_starts_knowing_the_open_project(self, tmp_path) -> None:
        runs = _project(tmp_path)
        seen: list[str] = []

        class Records:
            def respond(self, system, turns, tools):
                seen.append(system)
                if len(seen) == 1:
                    return Reply(
                        text="",
                        tool_calls=(
                            ToolCall("d", "ofag.delegate", {"role": "data", "task": "list it"}),
                        ),
                    )
                return Reply(text="done")

        Orchestrator(runs, lambda role: Records()).ask("what data does this project have?")

        lead, worker = seen[0], seen[1]
        for system in (lead, worker):
            assert "## The open project" in system and "**Cedar Rapids**" in system
            assert "not data in the open project" in system

    def test_the_lessons_in_a_brief_are_labelled_as_lessons(self) -> None:
        text = brief("data", question="elevations stated twice", k=2)

        assert "not data in the open project" in text
        assert "Call ofag.project first" in text

    def test_retrieved_passages_say_they_are_not_the_projects_data(self, tmp_path) -> None:
        answer = dispatcher_for(Role.DATA, tmp_path).call(
            "ofag.retrieve", {"query": "ramp", "k": 1}
        )

        assert LESSONS_ARE_NOT_DATA in answer["note"]


class Recorder:
    def __init__(self, answer):
        self.answer = answer

    def __call__(self, url, headers, body, timeout):
        return json.dumps(self.answer).encode()


class TestReasoningIsShownNotSent:
    TURNS = [Turn(role="user", text="hi")]

    def test_each_protocols_reasoning_is_read(self) -> None:
        chat = OpenAICompatibleModel(
            ProviderConfig.default_for(ProviderKind.OPENAI_COMPATIBLE),
            "k",
            Recorder(
                {"choices": [{"message": {"content": "Hi.", "reasoning_content": "Greet back."}}]}
            ),
        )
        anthropic = AnthropicModel(
            ProviderConfig(),
            "k",
            Recorder(
                {
                    "content": [
                        {"type": "thinking", "thinking": "Greet back."},
                        {"type": "text", "text": "Hi."},
                    ]
                }
            ),
        )
        responses = OpenAIResponsesModel(
            ProviderConfig.default_for(ProviderKind.OPENAI_RESPONSES),
            "k",
            Recorder(
                {
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "Greet back."}],
                        },
                        {"type": "message", "content": [{"type": "output_text", "text": "Hi."}]},
                    ]
                }
            ),
        )
        for model in (chat, anthropic, responses):
            reply = model.respond("s", self.TURNS, [])
            assert (reply.text, reply.reasoning) == ("Hi.", "Greet back.")

    def test_reasoning_becomes_a_thinking_event_and_text_before_a_tool_call_a_note(
        self, tmp_path
    ) -> None:
        replies = iter(
            [
                Reply(
                    text="Looking first.",
                    reasoning="Check the journal.",
                    tool_calls=(ToolCall("j", "ofag.journal", {}),),
                ),
                Reply(text="Nothing owed."),
            ]
        )

        class Model:
            def respond(self, system, turns, tools):
                return next(replies)

        events: list = []
        Orchestrator(tmp_path, lambda role: Model(), emit=events.append).ask("owed?")

        kinds = [(e.kind, e.text) for e in events]
        assert ("thinking", "Check the journal.") in kinds and ("note", "Looking first.") in kinds
        assert kinds[-1] == ("message", "Nothing owed.")


@pytest.mark.skipif(find_spec("PySide6") is None, reason="the desktop extra is not installed")
class TestTheChat:
    @staticmethod
    def _app():
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    def test_the_person_is_on_the_left_and_the_agent_on_the_right(self) -> None:
        from ofag.desktop.chat_view import AgentTurn, ChatView

        self._app()
        chat = ChatView()
        chat.add_user("what is here?")
        chat.add_turn()

        rows = [chat._rows.itemAt(i).widget() for i in range(chat._rows.count() - 1)]
        user_row, turn_row = rows[0].layout(), rows[1].layout()
        assert user_row.itemAt(0).widget().objectName() == "userBubble"  # bubble first, then space
        assert isinstance(turn_row.itemAt(1).widget(), AgentTurn)  # space first, then the turn

    def test_the_working_folds_away_when_the_answer_arrives(self) -> None:
        from ofag.desktop.chat_view import ChatView

        self._app()
        chat = ChatView()
        chat.add_user("q")
        turn = chat.add_turn()
        turn.activity("lead · ofag.project", "lead . ofag.project", role="lead", tool=True)
        turn.thinking("audit", "check the ledger")
        assert not turn.toggle.isChecked() and turn.toggle.text().startswith("Working")
        turn.toggle.setChecked(True)

        turn.finish("**Two runs.**")

        assert not turn.toggle.isChecked() and turn.working.isHidden()
        assert turn.toggle.text().startswith("Worked for") and "1 tool call" in turn.toggle.text()
        turn.toggle.setChecked(True)
        assert not turn.working.isHidden()
        assert chat.toPlainText().splitlines()[0] == "person: q"

    def test_a_failure_leaves_the_working_open_to_read(self) -> None:
        from ofag.desktop.chat_view import ChatView

        self._app()
        chat = ChatView()  # held: Qt deletes a turn with the view that owns it
        turn = chat.add_turn()
        turn.fail("The model refused the request; its answer is above.")

        assert turn.toggle.isChecked() and turn.toggle.text().startswith("Stopped")

    def test_long_paths_wrap_inside_a_narrow_chat_dock(self) -> None:
        from ofag.desktop.chat_view import ChatView

        app = self._app()
        chat = ChatView()
        chat.resize(380, 600)
        answer = "Report: `D:/project/" + "long_directory_" * 30 + "/review.md`"
        chat.add_turn().finish(answer)
        chat.show()
        app.processEvents()
        assert chat.horizontalScrollBar().maximum() == 0
        assert answer in chat.toPlainText()
        chat.close()
