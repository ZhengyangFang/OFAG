"""The runner: a lead that delegates, workers that start from nothing."""

import json

import pytest

from ofag.agent.orchestrator import DELEGATE, Cancelled, Orchestrator
from ofag.agent.providers import ProviderError, Reply, ToolCall
from ofag.agent.roles import Role


class Scripted:
    """A model that answers from a list, and remembers what it was shown."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)
        self.seen: list[tuple[str, list, list]] = []

    def respond(self, system, turns, tools):
        self.seen.append((system, list(turns), [t.name for t in tools]))
        if not self.replies:
            return Reply(text="done")
        return self.replies.pop(0)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(id=f"id-{name}", name=name, arguments=arguments)


def orchestrator(tmp_path, models: dict[Role, Scripted], **kwargs) -> tuple[Orchestrator, list]:
    events: list = []
    runner = Orchestrator(tmp_path, lambda role: models[role], emit=events.append, **kwargs)
    return runner, events


def test_the_lead_answers_and_the_conversation_is_kept(tmp_path) -> None:
    lead = Scripted([Reply(text="Hello."), Reply(text="Still here.")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead})

    assert runner.ask("hi") == "Hello."
    assert runner.ask("again?") == "Still here."
    # The second question arrives with the first exchange before it.
    assert [t.text for t in lead.seen[1][1] if t.role == "user"] == ["hi", "again?"]


def test_ui_selection_reaches_model_without_expanding_the_user_bubble(tmp_path) -> None:
    lead = Scripted([Reply(text="ok")])
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead})
    context = {"stage": "results", "run_id": "selected"}
    runner.ask("Review this result", ui_context=context)
    assert "selected" in lead.seen[0][1][0].text
    user = next(event for event in events if event.kind == "user")
    assert user.text == "Review this result"
    assert user.detail["ui_context"] == context


def test_the_lead_holds_delegate_and_its_own_tools_only(tmp_path) -> None:
    lead = Scripted([Reply(text="ok")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead})
    runner.ask("hi")

    tools = lead.seen[0][2]
    assert DELEGATE in tools and "ofag.journal" in tools
    assert "ofag.execute" not in tools and "ofag.audit" not in tools


def test_empty_response_retries_summary_with_evidence_and_without_tools(tmp_path) -> None:
    lead = Scripted(
        [
            Reply(text="", tool_calls=(call("ofag.journal"),)),
            Reply(text="", reasoning="still considering", stop_reason="length"),
            Reply(text="The journal has no pending entries."),
        ]
    )
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead})
    assert runner.ask("Check journal") == "The journal has no pending entries."
    assert lead.seen[-1][2] == []
    assert any(t.role == "tool" for t in lead.seen[-1][1])
    assert sum(e.kind == "tool_call" for e in events) == 1


def test_repeated_empty_response_is_an_error_not_a_success(tmp_path) -> None:
    runner, _ = orchestrator(tmp_path, {Role.LEAD: Scripted([Reply(text=""), Reply(text="")])})
    with pytest.raises(ProviderError, match="complete answer"):
        runner.ask("Check")


def test_truncated_tool_response_cannot_execute(tmp_path) -> None:
    lead = Scripted([Reply(text="", tool_calls=(call("ofag.journal"),), stop_reason="length")])
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead})
    with pytest.raises(ProviderError, match="no tool calls"):
        runner.ask("Check")
    assert not any(e.kind == "tool_call" for e in events)


def test_empty_last_step_still_gets_one_summary_retry(tmp_path) -> None:
    lead = Scripted([Reply(text=""), Reply(text="Summary recovered.")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead}, max_steps=1)
    assert runner.ask("Check") == "Summary recovered."
    assert len(lead.seen) == 2 and lead.seen[-1][2] == []


def test_exhausted_steps_are_not_reported_as_completed(tmp_path) -> None:
    lead = Scripted(
        [
            Reply(text="", tool_calls=(call("ofag.journal"),)),
            Reply(text="Ready again."),
        ]
    )
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead}, max_steps=1)
    with pytest.raises(ProviderError, match="without finishing"):
        runner.ask("Check")
    assert not any(e.kind == "message" for e in events)
    assert runner.ask("Continue") == "Ready again."


def test_a_worker_starts_from_nothing_and_returns_only_its_report(tmp_path) -> None:
    lead = Scripted(
        [
            Reply(text="", tool_calls=(call(DELEGATE, role="audit", task="audit run R"),)),
            Reply(text="The auditor says R is unaudited."),
        ]
    )
    auditor = Scripted(
        [
            Reply(text="", tool_calls=(call("ofag.journal"),)),
            Reply(text="R has no diagnosis yet; nothing to pass."),
        ]
    )
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead, Role.AUDIT: auditor})

    runner.ask("secret detail only the lead knows: XYZZY. Is R audited?")

    system, turns, tools = auditor.seen[0]
    assert system.startswith("# You are the audit role")
    assert [t.text for t in turns] == ["audit run R"]
    assert "XYZZY" not in system + json.dumps([t.text for t in turns])
    assert "ofag.audit" in tools and DELEGATE not in tools
    # The lead got the report, not the auditor's tool calls.
    returned = lead.seen[1][1][-1].results[0]
    assert returned.content.startswith("[audit reports]") and "nothing to pass" in returned.content
    assert [e.kind for e in events if e.role == "audit"][:2] == ["delegate", "tool_call"]


def test_each_delegation_is_a_new_worker(tmp_path) -> None:
    lead = Scripted(
        [
            Reply(text="", tool_calls=(call(DELEGATE, role="audit", task="first"),)),
            Reply(text="", tool_calls=(call(DELEGATE, role="audit", task="second"),)),
            Reply(text="both done"),
        ]
    )
    auditor = Scripted([Reply(text="one"), Reply(text="two")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead, Role.AUDIT: auditor})
    runner.ask("audit twice")

    assert [t.text for t in auditor.seen[1][1]] == ["second"]


@pytest.mark.parametrize(
    ("arguments", "complaint"),
    [
        ({"role": "developer", "task": "x"}, "no role"),
        ({"role": "critic", "task": "x"}, "no role"),
        ({"role": "audit", "task": " "}, "needs a task"),
    ],
)
def test_a_bad_delegation_is_an_answer_to_the_lead(tmp_path, arguments, complaint) -> None:
    lead = Scripted([Reply(text="", tool_calls=(call(DELEGATE, **arguments),)), Reply(text="ok")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead})
    runner.ask("go")

    result = lead.seen[1][1][-1].results[0]
    assert result.is_error and complaint in result.content


def test_a_tool_the_role_does_not_hold_is_refused_not_raised(tmp_path) -> None:
    lead = Scripted([Reply(text="", tool_calls=(call("ofag.execute", spec={}),)), Reply(text="ok")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead})
    runner.ask("run it yourself")

    result = lead.seen[1][1][-1].results[0]
    assert result.is_error and "not a tool of lead" in result.content


def test_a_destructive_call_waits_for_the_person(tmp_path) -> None:
    lead = Scripted(
        [
            Reply(
                text="",
                tool_calls=(
                    call("ofag.delete_run", run_id="00000000-0000-0000-0000-000000000000"),
                ),
            ),
            Reply(text="declined"),
        ]
    )
    asked: list = []
    runner, events = orchestrator(
        tmp_path, {Role.LEAD: lead}, approve=lambda role, tool, args: asked.append(tool) or False
    )
    runner.ask("delete that run")

    assert asked == ["ofag.delete_run"]
    result = lead.seen[1][1][-1].results[0]
    assert result.is_error and "declined" in result.content
    assert any(e.kind == "approval" and e.detail == {"allowed": False} for e in events)


def test_a_worker_that_never_finishes_is_stopped(tmp_path) -> None:
    lead = Scripted([Reply(text="", tool_calls=(call("ofag.journal"),))] * 5)
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead}, max_steps=3)

    with pytest.raises(ProviderError, match="stopped after 3 steps"):
        runner.ask("loop")


def test_cancel_stops_at_the_next_step(tmp_path) -> None:
    runner: Orchestrator

    class CancelsItself(Scripted):
        def respond(self, system, turns, tools):
            runner.cancel()
            return Reply(text="", tool_calls=(call("ofag.journal"),))

    runner, _ = orchestrator(tmp_path, {Role.LEAD: CancelsItself([])})
    with pytest.raises(Cancelled):
        runner.ask("go")


def test_a_provider_failure_is_raised_and_logged(tmp_path) -> None:
    class Down(Scripted):
        def respond(self, system, turns, tools):
            raise ProviderError("could not reach the model")

    runner, events = orchestrator(tmp_path, {Role.LEAD: Down([])})
    with pytest.raises(ProviderError):
        runner.ask("hi")
    assert events[-1].kind == "error"


def test_every_event_is_written_to_the_project(tmp_path) -> None:
    lead = Scripted(
        [Reply(text="", tool_calls=(call("ofag.journal"),)), Reply(text="nothing owed")]
    )
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead})
    runner.ask("what is owed?")

    lines = [json.loads(line) for line in runner.log_path.read_text("utf-8").splitlines()]
    assert runner.log_path.parent == tmp_path / "conversations"
    assert [line["kind"] for line in lines] == [e.kind for e in events]
    assert lines[0]["text"] == "what is owed?" and lines[-1]["text"] == "nothing owed"


def test_cancelling_during_a_model_request_does_not_execute_its_tools(tmp_path) -> None:
    class CancelsBeforeReturning(Scripted):
        def respond(self, system, turns, tools):
            runner.cancel()
            return Reply(text="", tool_calls=(call("ofag.journal"),))

    runner, events = orchestrator(tmp_path, {Role.LEAD: CancelsBeforeReturning([])})
    with pytest.raises(Cancelled):
        runner.ask("stop while waiting for the model")
    assert not any(event.kind == "tool_call" for event in events)


def test_stop_before_the_worker_starts_is_not_cleared_by_ask(tmp_path) -> None:
    lead = Scripted([Reply(text="next question")])
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead})
    runner.cancel()
    with pytest.raises(Cancelled):
        runner.ask("cancelled before the thread started")
    assert not lead.seen
    assert runner.ask("a new question") == "next question"


def test_failed_worker_returns_a_tool_error_and_the_lead_can_continue(tmp_path) -> None:
    class Down(Scripted):
        def respond(self, system, turns, tools):
            raise ProviderError("worker unavailable")

    lead = Scripted(
        [
            Reply(text="", tool_calls=(call(DELEGATE, role="audit", task="audit R"),)),
            Reply(text="The audit could not run."),
            Reply(text="We can try again."),
        ]
    )
    runner, _ = orchestrator(tmp_path, {Role.LEAD: lead, Role.AUDIT: Down([])})
    assert runner.ask("audit") == "The audit could not run."
    returned = lead.seen[1][1][-1].results[0]
    assert returned.is_error and "worker unavailable" in returned.content
    assert runner.ask("continue") == "We can try again."


def test_cancelled_worker_closes_pending_calls_before_the_next_question(tmp_path) -> None:
    class Cancels(Scripted):
        def respond(self, system, turns, tools):
            runner.cancel()
            return Reply(text="late worker answer")

    lead = Scripted(
        [
            Reply(
                text="",
                tool_calls=(
                    call(DELEGATE, role="audit", task="audit R"),
                    call("ofag.journal"),
                ),
            ),
            Reply(text="Ready for a new request."),
        ]
    )
    runner, events = orchestrator(tmp_path, {Role.LEAD: lead, Role.AUDIT: Cancels([])})
    with pytest.raises(Cancelled):
        runner.ask("audit")
    assert not any(event.kind == "tool_call" and event.text == "ofag.journal" for event in events)
    assert runner.ask("continue") == "Ready for a new request."
    results = lead.seen[1][1][-2].results
    assert len(results) == 2 and all(result.is_error for result in results)
