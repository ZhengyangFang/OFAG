"""The agents, run from inside OFAG: a lead that delegates, and roles that work."""

import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.agent.providers import ChatModel, ProviderError, ToolCall, ToolResult, ToolSpec, Turn
from ofag.agent.roles import Role, brief, dispatcher_for, spec_for
from ofag.agent.tools import Tier
from ofag.services.project_changes import (
    configuration_changes,
    configuration_snapshot,
    related_records,
)

__all__ = ["Event", "Orchestrator", "DELEGATE", "Cancelled"]

#: The one tool the lead has that no dispatcher declares.
DELEGATE = "ofag.delegate"

#: The roles the lead may start from here.
DELEGABLE = (Role.DATA, Role.INVERSION, Role.MODELLING, Role.AUDIT, Role.LITERATURE)

#: A tool result longer than this is cut, with a note saying so.
LONGEST_RESULT = 12_000

LEAD_INSTRUCTIONS = """
## How you work here

You are talking with a person who is working on a geophysics project in
OFAG. Answer what they ask; do the work by delegating it.

- `ofag.delegate` starts one of the other roles on a task: data, inversion,
  modelling, audit or literature. Give it a task that stands alone -- the
  role sees nothing of this conversation -- naming the files, runs or
  identifiers it needs. It returns the role's report.
- A run is read into a model only after the audit role has passed it, and
  the audit role cannot be the one that ran it. Delegate the audit; never
  describe a result as audited because a worker said it looked fine.
- A question about this project is answered from ofag.project, which reads
  the project's own records. The lessons and case write-ups describe other
  field cases; quote them as lessons, never as this project's data.
- Before answering, check what the ledger and the journal record
  (ofag.owed, ofag.result, ofag.journal). Say what is verified and what is
  only reported.
- When a choice is the person's to make -- the data cannot settle it --
  ask them rather than choosing, and record the answer with
  ofag.record_decision.
- Be brief. Say what was done, what it showed, and what is still owed.
- The answer appears in a narrow desktop dock. Prefer short paragraphs or bullets
  over wide tables. Name runs by label with a short id; keep full ids in tool details.
- Before changing the project, state a short user-facing plan naming the steps
  and intended outputs. Report identifiers of the data, runs and models produced.
- Reuse historical inversions through prepare_run and saved_run, so full mesh,
  uncertainty and large station arrays stay intact. Never rebuild their specs from a summary.
- Preserve the user's requested operations when delegating. A saved draft requires
  prepare_run; reuse_run only previews an unsaved spec. owed lists outstanding gates
  and never substitutes for validate. Confirm saved outputs from tool results.
- Historical results need adopt_run, diagnosis and an independent audit before modelling.
  A selected result is not automatically audited. Never claim a refused build succeeded.
- Model builds return model_id. Use list_models and model_recipe to inspect the saved output,
  and export_report for a local deliverable. State missing capabilities explicitly.
"""

WORKER_INSTRUCTIONS = """
## This task

You were started by the lead with the task below. Do it with your tools. When
you are done, reply with a short report and no tool calls: what you did, what
it showed, the run ids or files involved, and anything owed or refused. If a
tool refuses, read what it says is owed; do not retry the same call.
Keep reads scoped to the delegated task. Reuse evidence already returned in this
task. Once the requested checks have answers, report them; do not keep searching
lessons or unrelated historical runs. Mark missing evidence explicitly.
"""


class Cancelled(RuntimeError):
    """The person stopped the conversation."""


@dataclass(frozen=True)
class Event:
    """One thing that happened, as the panel and the log both want it."""

    #: user, message (the lead's answer), note (said on the way to a tool call),
    #: thinking (the model's reasoning), delegate, tool_call, tool_result, report,
    #: approval, error.
    kind: str
    role: str
    text: str
    detail: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def _delegate_spec() -> ToolSpec:
    return ToolSpec(
        name=DELEGATE,
        description=(
            "Start another role on a task and return its report. The role begins with "
            "no knowledge of this conversation, so the task has to stand alone."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": [r.value for r in DELEGABLE]},
                "task": {"type": "string"},
            },
            "required": ["role", "task"],
            "additionalProperties": False,
        },
    )


class Orchestrator:
    """One conversation with the lead, and the workers it starts."""

    def __init__(
        self,
        artifact_root: Path,
        model_for: Callable[[Role], ChatModel],
        *,
        approve: Callable[[str, str, dict[str, Any]], bool] = lambda role, tool, args: False,
        emit: Callable[[Event], None] = lambda event: None,
        max_steps: int = 30,
        registry: Any = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self._model_for = model_for
        self._approve = approve
        self._emit = emit
        self.max_steps = max_steps
        self._registry = registry
        self._lead_turns: list[Turn] = []
        self._cancel = threading.Event()
        self.conversation_id = uuid.uuid4().hex[:12]
        self.log_path = self.artifact_root / "conversations" / f"{self.conversation_id}.jsonl"

    # -- the person's side ---------------------------------------------------

    def ask(self, text: str, *, ui_context: dict[str, Any] | None = None) -> str:
        """One message from the person; the lead's answer."""
        try:
            if self.cancelled:
                raise Cancelled("stopped by the person")
            self._record(
                Event("user", "person", text, {"ui_context": ui_context} if ui_context else {})
            )
            request = text
            if ui_context:
                request += "\n\n[Current UI selection]\n" + json.dumps(ui_context)
            self._lead_turns.append(Turn(role="user", text=request))
            lead = dispatcher_for(Role.LEAD, self.artifact_root, registry=self._registry)
            system = brief(Role.LEAD, question=text) + self._project_brief() + LEAD_INSTRUCTIONS
            tools = [*self._specs(lead), _delegate_spec()]
            answer = self._loop(Role.LEAD, lead, system, self._lead_turns, tools)
            self._record(Event("message", Role.LEAD.value, answer))
            return answer
        finally:
            # Reset only after the turn ends: Stop may arrive after the UI schedules its
            # worker but before that thread enters ask().
            self._cancel.clear()

    def cancel(self) -> None:
        """Stop at the next step. Safe to call from another thread."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- the loop every agent runs --------------------------------------------

    def _loop(
        self,
        role: Role,
        surface: Dispatcher,
        system: str,
        turns: list[Turn],
        tools: list[ToolSpec],
    ) -> str:
        model = self._model_for(role)
        summarizing = False
        for step in range(self.max_steps + 1):
            # An empty final response still gets its single summary retry.
            if step == self.max_steps and not summarizing:
                break
            if self._cancel.is_set():
                raise Cancelled("stopped by the person")
            try:
                reply = model.respond(system, turns, tools)
            except ProviderError as failed:
                self._record(Event("error", role.value, str(failed)))
                raise
            if self.cancelled:
                raise Cancelled("stopped by the person")
            truncated = reply.stop_reason in {"length", "max_tokens", "max_output_tokens"}
            if reply.tool_calls and (truncated or summarizing):
                note = "Incomplete model response; no tool calls from this response were executed."
                self._record(Event("error", role.value, note))
                raise ProviderError(note)
            if reply.text or reply.tool_calls:
                turns.append(Turn(role="assistant", text=reply.text, tool_calls=reply.tool_calls))
            if reply.reasoning:
                self._record(Event("thinking", role.value, reply.reasoning))
            if not reply.tool_calls:
                if reply.text and not truncated:
                    return reply.text
                if summarizing:
                    note = "The model did not return a complete answer after one summary retry."
                    self._record(Event("error", role.value, note))
                    raise ProviderError(note)
                summarizing = True
                tools = []
                self._record(
                    Event(
                        "note",
                        role.value,
                        "Requesting a brief summary of the completed checks.",
                        {"stop_reason": reply.stop_reason, "output_tokens": reply.output_tokens},
                    )
                )
                turns.append(
                    Turn(
                        role="user",
                        text="Your last response was empty or incomplete. Return a concise final "
                        "answer now using the tool evidence already collected. "
                        "No further tool calls. State what completed, what is still missing, "
                        "and any saved output paths.",
                    )
                )
                continue
            if reply.text:
                # Said on the way to a tool call: working, not an answer.
                self._record(Event("note", role.value, reply.text))
            results: list[ToolResult] = []
            for call in reply.tool_calls:
                try:
                    if self.cancelled:
                        raise Cancelled("stopped by the person")
                    result = self._call(role, surface, call)
                except Cancelled:
                    self.cancel()
                    result = ToolResult(
                        call.id,
                        call.name,
                        "Cancelled by the person; task not completed.",
                        is_error=True,
                    )
                results.append(result)
            # Every tool call needs a result, including cancelled delegations.
            turns.append(Turn(role="tool", results=tuple(results)))
            if self.cancelled:
                raise Cancelled("stopped by the person")
        note = f"stopped after {self.max_steps} steps without finishing"
        self._record(Event("error", role.value, note))
        raise ProviderError(note)

    def _call(self, role: Role, surface: Dispatcher, call: ToolCall) -> ToolResult:
        self._record(Event("tool_call", role.value, call.name, {"arguments": call.arguments}))
        before = None
        changes: list[str] = []
        references = related_records(call.arguments)
        try:
            if call.name == DELEGATE and role is Role.LEAD:
                return self._delegate(call)
            tool = next((t for t in surface.manifest() if t.name == call.name), None)
            if tool is not None and tool.tier is Tier.DESTRUCTIVE:
                allowed = self._approve(role.value, call.name, call.arguments)
                self._record(Event("approval", role.value, call.name, {"allowed": allowed}))
                if not allowed:
                    raise ToolError(
                        f"{call.name} removes things and the person declined it. Do not "
                        "retry; say what you wanted removed and why."
                    )
            if self.cancelled:
                raise Cancelled("stopped by the person")
            if tool is not None and tool.tier in (Tier.WRITE, Tier.COMPUTE, Tier.DESTRUCTIVE):
                before = configuration_snapshot(self.artifact_root)
            result = replace(surface, cancelled=lambda: self.cancelled).call(
                call.name, call.arguments
            )
            content, failed = _render(result), False
            references += related_records(result)
        except Cancelled:
            raise
        except ToolError as refused:
            content, failed = str(refused), True
        except Exception as crash:  # noqa: BLE001 - a crash is reported to the model, not raised
            content, failed = f"{call.name} failed: {type(crash).__name__}: {crash}", True
            self._record(Event("error", role.value, content))
        if before is not None:
            changes = configuration_changes(before, configuration_snapshot(self.artifact_root))
        self._record(
            Event(
                "tool_result",
                role.value,
                call.name,
                {
                    "is_error": failed,
                    "chars": len(content),
                    "changes": changes,
                    "project_changed": before is not None,
                    "references": references,
                },
            )
        )
        return ToolResult(call_id=call.id, name=call.name, content=content, is_error=failed)

    def _delegate(self, call: ToolCall) -> ToolResult:
        name = str(call.arguments.get("role", ""))
        task = str(call.arguments.get("task", "")).strip()
        try:
            role = Role(name)
            if role not in DELEGABLE:
                raise ValueError
        except ValueError:
            return ToolResult(
                call.id,
                DELEGATE,
                (
                    f"no role {name!r} to delegate to; the roles are "
                    + ", ".join(r.value for r in DELEGABLE)
                ),
                is_error=True,
            )
        if not task:
            return ToolResult(call.id, DELEGATE, "a delegation needs a task", is_error=True)
        self._record(Event("delegate", role.value, task))
        surface = dispatcher_for(role, self.artifact_root, registry=self._registry)
        system = brief(role, question=task) + self._project_brief() + WORKER_INSTRUCTIONS
        # A fresh conversation: the task and nothing of the lead's.
        turns = [Turn(role="user", text=task)]
        report = self._loop(role, surface, system, turns, self._specs(surface))
        self._record(Event("report", role.value, report))
        return ToolResult(call.id, DELEGATE, f"[{role.value} reports]\n{report}")

    def _project_brief(self) -> str:
        """The open project in a few lines, or a sentence saying there is none."""
        from ofag.agent.project_context import LESSONS_ARE_NOT_DATA, ProjectContext

        context = ProjectContext.find(self.artifact_root)
        if context is None:
            return "\n## The open project\n\nNone: this runs folder belongs to no project.\n"
        try:
            return "\n" + context.as_brief()
        except (OSError, ValueError) as unreadable:
            return (
                f"\n## The open project\n\nIts records could not be read ({unreadable}). "
                f"{LESSONS_ARE_NOT_DATA}\n"
            )

    def _specs(self, surface: Dispatcher) -> list[ToolSpec]:
        from ofag.agent.mcp_server import described

        return [
            ToolSpec(name=d.name, description=d.description, input_schema=d.input_schema)
            for d in (described(tool) for tool in surface.manifest())
        ]

    def _record(self, event: Event) -> None:
        self._emit(event)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.__dict__, default=str) + "\n")


def _render(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, indent=1, default=str)
    if len(text) > LONGEST_RESULT:
        cut = len(text) - LONGEST_RESULT
        text = text[:LONGEST_RESULT] + f"\n... ({cut} more characters not shown; ask for less)"
    return text


def role_titles() -> dict[str, str]:
    """A short label per role, for a panel."""
    return {role.value: spec_for(role).purpose.split(",")[0] for role in Role}
