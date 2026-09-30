"""Talking to the agents from the workbench."""

import html
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ofag.agent.orchestrator import Cancelled, Event, Orchestrator
from ofag.agent.providers import (
    PRESETS,
    AgentSettings,
    ChatModel,
    ProviderConfig,
    ProviderError,
    ProviderKind,
    endpoint,
    is_variable_name,
    load_settings,
    model_from,
    probe,
    resolve_key,
    save_settings,
)
from ofag.agent.roles import Role
from ofag.desktop.chat_view import ROLE_COLOURS, AgentTurn, ChatView
from ofag.desktop.conversation_history import ConversationHistory
from ofag.desktop.session import Session

__all__ = ["AgentPanel", "ProviderDialog"]


def _who(role: str) -> str:
    colour = ROLE_COLOURS.get(role, "#444")
    return f'<b style="color:{colour}">{html.escape(role)}</b>'


class _Bridge(QObject):
    """Carries events from the worker thread to the window's thread."""

    happened = Signal(object, object)
    finished = Signal(object, str)
    failed = Signal(object, str)
    approval = Signal(object)


class _Approval:
    """A question the worker waits on until the window answers it."""

    def __init__(
        self, runner: Orchestrator, role: str, tool: str, arguments: dict[str, Any]
    ) -> None:
        self.runner = runner
        self.role, self.tool, self.arguments = role, tool, arguments
        self.allowed = False
        self.answered = threading.Event()


class ProviderDialog(QDialog):
    """Which model, where, over which protocol, and the variable its key is in."""

    def __init__(
        self,
        settings: AgentSettings,
        session_key: str,
        parent: QWidget | None = None,
        *,
        prober: Callable[[ProviderConfig, str], str] = probe,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent model")
        self.setMinimumWidth(560)
        self._prober = prober
        provider = settings.provider

        self._preset = QComboBox()
        self._preset.addItem("(choose a provider to fill the fields)", None)
        for preset in PRESETS:
            self._preset.addItem(preset.label, preset)
        self._preset.currentIndexChanged.connect(self._preset_chosen)
        self._kind = QComboBox()
        self._kind.addItem("Anthropic Messages (/v1/messages)", ProviderKind.ANTHROPIC)
        self._kind.addItem(
            "OpenAI chat completions (/chat/completions)", ProviderKind.OPENAI_COMPATIBLE
        )
        self._kind.addItem("OpenAI Responses (/responses)", ProviderKind.OPENAI_RESPONSES)
        self._kind.setCurrentIndex(self._kind_index(provider.kind))
        self._base = QLineEdit(provider.base_url)
        self._base.setPlaceholderText("https://host/v1 -- a full endpoint URL also works")
        self._model = QLineEdit(provider.model)
        self._env = QLineEdit(provider.api_key_env)
        self._key = QLineEdit(session_key)
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("optional: used for this session only, never saved")
        self._audit = QLineEdit(settings.role_models.get(Role.AUDIT.value, ""))
        self._audit.setPlaceholderText("empty: the same model as the lead")
        self._endpoint = QLabel()
        self._endpoint.setObjectName("providerEndpoint")
        self._endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for field in (self._base,):
            field.textChanged.connect(self._show_endpoint)
        self._kind.currentIndexChanged.connect(self._show_endpoint)

        form = QFormLayout()
        form.addRow("Preset", self._preset)
        form.addRow("Protocol", self._kind)
        form.addRow("Base URL", self._base)
        form.addRow("Requests go to", self._endpoint)
        form.addRow("Model", self._model)
        form.addRow("Key variable", self._env)
        form.addRow("Key (this session)", self._key)
        form.addRow("Audit model", self._audit)
        note = QLabel("Use a session key or an environment variable. Session keys are never saved.")
        note.setToolTip(
            "Settings are stored in your home folder. For a relay, use its base URL "
            "and the protocol supported by the selected model."
        )
        note.setWordWrap(True)
        self._test = QPushButton("Test connection")
        self._test.clicked.connect(self._run_probe)
        self._verdict = QLabel()
        self._verdict.setObjectName("providerVerdict")
        self._verdict.setWordWrap(True)
        self._verdict.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        test_row = QHBoxLayout()
        test_row.addWidget(self._test)
        test_row.addWidget(self._verdict, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(test_row)
        layout.addWidget(buttons)
        self._show_endpoint()

    def _preset_chosen(self) -> None:
        preset = self._preset.currentData()
        if preset is None:
            return
        self._kind.setCurrentIndex(self._kind_index(preset.kind))
        self._base.setText(preset.base_url)
        self._model.setText(preset.model)
        self._env.setText(preset.api_key_env)
        self._verdict.clear()

    def _kind_index(self, kind: ProviderKind) -> int:
        # By value: Qt's findData does not match an enum member back to the member it
        # stored, and returned -1, which left the protocol unchanged.
        for index in range(self._kind.count()):
            if str(self._kind.itemData(index)) == str(kind):
                return index
        return 0

    def _chosen_kind(self) -> ProviderKind:
        return ProviderKind(str(self._kind.currentData()))

    def _show_endpoint(self) -> None:
        base = self._base.text().strip()
        self._endpoint.setText(endpoint(self._chosen_kind(), base) if base else "")

    def current_config(self) -> ProviderConfig:
        return ProviderConfig(
            kind=self._chosen_kind(),
            model=self._model.text().strip(),
            base_url=self._base.text().strip(),
            api_key_env=self._env.text().strip(),
        )

    def _catch_pasted_key(self) -> bool:
        """Move a key pasted into the variable field to the session field."""
        text = self._env.text().strip()
        if not text or is_variable_name(text):
            return False
        self._key.setText(text)
        preset = self._preset.currentData()
        self._env.setText(preset.api_key_env if preset is not None else "OFAG_API_KEY")
        self._verdict.setText(
            '<span style="color:#ad5a00">That looked like a key, not a variable name, so it '
            "was moved to 'Key (this session)', where it is used and never saved.</span>"
        )
        return True

    def accept(self) -> None:
        self._catch_pasted_key()
        super().accept()

    def _run_probe(self) -> None:
        moved = self._catch_pasted_key()
        # Short, so a relay that never answers does not hold the dialog for the five
        # minutes a real turn is allowed.
        config = replace(self.current_config(), timeout_s=30.0, max_tokens=64)
        if not moved:
            self._verdict.setText("Testing…")
        QApplication.processEvents()
        try:
            key = resolve_key(config, self._key.text())
            answer = self._prober(config, key)
        except ProviderError as failed:
            self._verdict.setText(f'<span style="color:#a33">{html.escape(str(failed))}</span>')
            return
        note = " (the key was moved to the session field)" if moved else ""
        self._verdict.setText(
            f'<span style="color:#2e7d32">Works{note}. {html.escape(config.model)} answered: '
            f"{html.escape(answer[:120])}</span>"
        )

    def result_settings(self) -> tuple[AgentSettings, str]:
        roles = {Role.AUDIT.value: self._audit.text().strip()} if self._audit.text().strip() else {}
        return AgentSettings(
            provider=self.current_config(), role_models=roles
        ), self._key.text().strip()


class AgentPanel(QDockWidget):
    """The conversation with the lead agent, and what the roles did for it."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_loader: Callable[[], AgentSettings] = load_settings,
        settings_saver: Callable[[AgentSettings], object] = save_settings,
        model_factory: Callable[[ProviderConfig, str], ChatModel] | None = None,
    ) -> None:
        super().__init__("Agents", parent)
        self.setObjectName("agentPanel")
        self._session: Session | None = None
        self._settings = settings_loader()
        self._save = settings_saver
        self._model_factory = model_factory or (
            lambda config, key: model_from(config, key, session_id=self._conversation_id())
        )
        self._session_key = ""
        self._orchestrator: Orchestrator | None = None
        self._active_runner: Orchestrator | None = None
        self._busy = False
        self._bridge = _Bridge()
        self._bridge.happened.connect(self._receive_event)
        self._bridge.finished.connect(self._receive_finished)
        self._bridge.failed.connect(self._receive_failed)
        self._bridge.approval.connect(self._ask_approval)

        self._where = QLabel()
        self._where.setWordWrap(True)
        self._where.setObjectName("agentWhere")
        settings = QPushButton("Model…")
        self._settings_button = settings
        settings.clicked.connect(self._edit_settings)
        self._new = QPushButton("New conversation")
        self._new.clicked.connect(self.new_conversation)
        history = QPushButton("History")
        history.clicked.connect(self._history)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(settings)
        top.addWidget(self._new)
        top.addWidget(history)

        self._activity = QLabel("Ready - ask for a plan or choose a task below.")
        self._activity.setWordWrap(True)
        self._changes: list[str] = []
        self._changes_button = QPushButton("Review project changes")
        self._changes_button.clicked.connect(self._review_changes)
        self._changes_button.setEnabled(False)
        results = QPushButton("View project results")
        results.clicked.connect(self._view_results)
        self._related = QComboBox()
        self._related.addItem("Related data and runs appear here", None)
        self._related.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        locate = QPushButton("Locate")
        locate.clicked.connect(self._locate)
        related_row = QHBoxLayout()
        related_row.addWidget(self._related, 1)
        related_row.addWidget(locate)
        shortcuts = QHBoxLayout()
        for title, request in (
            (
                "Check data",
                "Check the data in this project and list what must be fixed before inversion.",
            ),
            (
                "Plan next steps",
                "Give me a short plan for the next steps in this project. Do not execute it yet.",
            ),
            (
                "Review results",
                "Review completed results and explain which are ready for interpretation.",
            ),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, text=request: self._suggest(text))
            shortcuts.addWidget(button)

        self.transcript = ChatView()
        self._turn: AgentTurn | None = None
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Ask the agents about this project. Ctrl+Enter sends.")
        self.input.setFixedHeight(80)
        self.send = QPushButton("Send")
        self.send.clicked.connect(self.submit)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(self._stop)
        self.stop.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.stop)
        buttons.addWidget(self.send)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._where)
        layout.addLayout(top)
        layout.addWidget(self._activity)
        layout.addWidget(self._changes_button)
        layout.addWidget(results)
        layout.addLayout(related_row)
        layout.addWidget(self.transcript, 1)
        layout.addLayout(shortcuts)
        layout.addWidget(self.input)
        layout.addLayout(buttons)
        self.setWidget(body)
        self.setMinimumWidth(380)
        self._describe_where()
        self.set_session(None)

    # -- the project ---------------------------------------------------------

    def set_session(self, session: Session | None) -> None:
        if session is not self._session:
            # A different project is a different conversation: its runs, ledger and
            # journal are not the ones the last one talked about.
            self._stop()
            self._orchestrator = None
            self._turn = None
            self.transcript.clear()
            self._changes.clear()
            self._related.clear()
            self._related.addItem("Related data and runs appear here", None)
            self._changes_button.setEnabled(False)
            self._activity.setText("Ready")
        self._session = session
        self._set_enabled()
        if session is None:
            self.transcript.show_placeholder("Open a project to talk to the agents about it.")

    def new_conversation(self) -> None:
        if self._busy:
            return
        self._orchestrator = None
        self._turn = None
        self.transcript.clear()
        self._changes.clear()
        self._related.clear()
        self._related.addItem("Related records", None)
        self._changes_button.setEnabled(False)

    def _suggest(self, text: str) -> None:
        self.input.setPlainText(text)

    def _history(self) -> None:
        if self._session is not None:
            ConversationHistory(self._session.runs.artifact_root / "conversations", self).exec()

    def _view_results(self) -> None:
        if self._session is not None:
            self._session.events.navigate.emit("results")

    def _locate(self) -> None:
        reference = self._related.currentData()
        if self._session is not None and reference is not None:
            self._session.events.focus_requested.emit(reference["kind"], reference["id"])

    def _review_changes(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Recorded configuration changes")
        dialog.resize(850, 550)
        text = QPlainTextEdit("\n\n".join(self._changes))
        text.setReadOnly(True)
        QVBoxLayout(dialog).addWidget(text)
        dialog.exec()

    # -- sending -------------------------------------------------------------

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - Qt's name
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.submit()
            return
        super().keyPressEvent(event)

    def submit(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or self._busy or self._session is None:
            return
        try:
            runner = self._runner()
        except ProviderError as missing:
            QMessageBox.warning(self, "Agent model", str(missing))
            return
        self.input.clear()
        self._active_runner = runner
        self._busy = True
        self._activity.setText("Working...")
        self._set_enabled()
        context = {
            "stage": self._session.active_stage,
            "dataset_id": str(self._session.selected_dataset_id)
            if self._session.selected_dataset_id
            else None,
            "run_id": str(self._session.selected_run_id) if self._session.selected_run_id else None,
        }
        threading.Thread(target=self._converse, args=(runner, text, context), daemon=True).start()

    def _converse(self, runner: Orchestrator, text: str, context: dict[str, Any]) -> None:
        try:
            answer = runner.ask(text, ui_context=context)
        except Cancelled:
            self._bridge.failed.emit(runner, "Stopped.")
        except ProviderError:
            # The server's own answer is already on screen, from the error event the
            # orchestrator recorded; saying it twice buries it.
            self._bridge.failed.emit(runner, "Agent request failed. See details above.")
        except Exception as crash:  # noqa: BLE001 - shown, not swallowed
            self._bridge.failed.emit(runner, f"{type(crash).__name__}: {crash}")
        else:
            self._bridge.finished.emit(runner, answer)

    def _runner(self) -> Orchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        assert self._session is not None
        key = resolve_key(self._settings.provider, self._session_key)
        models: dict[Role, ChatModel] = {}

        def model_for(role: Role) -> ChatModel:
            if role not in models:
                models[role] = self._model_factory(self._settings.config_for(role.value), key)
            return models[role]

        runner = Orchestrator(
            self._session.runs.artifact_root,
            model_for,
            approve=self._approve_from_worker,
            emit=lambda event: self._bridge.happened.emit(runner, event),
        )
        self._orchestrator = runner
        return runner

    def _conversation_id(self) -> str:
        """The open conversation's id, which providers that route by session read."""
        runner = self._orchestrator
        return f"ofag-{runner.conversation_id}" if runner is not None else ""

    def _approve_from_worker(self, role: str, tool: str, arguments: dict[str, Any]) -> bool:
        runner = self._active_runner
        if runner is None or runner.cancelled:
            return False
        question = _Approval(runner, role, tool, arguments)
        self._bridge.approval.emit(question)
        while not question.answered.wait(timeout=0.1):
            if runner.cancelled:
                question.answered.set()
                return False
        return question.allowed and not runner.cancelled

    def _ask_approval(self, question: _Approval) -> None:
        if (
            question.answered.is_set()
            or question.runner is not self._orchestrator
            or question.runner is not self._active_runner
            or question.runner.cancelled
        ):
            question.answered.set()
            return
        answer = QMessageBox.question(
            self,
            "Allow this?",
            f"The {question.role} agent wants to call {question.tool} with\n\n"
            f"{question.arguments}\n\nThis removes something from the project.",
        )
        question.allowed = answer == QMessageBox.StandardButton.Yes
        question.answered.set()

    def _stop(self) -> None:
        if self._active_runner is not None:
            self._active_runner.cancel()
            self._activity.setText("Stop requested; waiting for the current call to return.")

    # -- showing -------------------------------------------------------------

    def _receive_event(self, runner: Orchestrator, event: Event) -> None:
        if runner is self._orchestrator:
            if event.kind == "tool_call":
                self._activity.setText(f"{event.role}: {event.text}")
            elif event.kind == "delegate":
                self._activity.setText(f"{event.role}: working")
            elif event.kind == "report":
                self._activity.setText(f"{event.role}: report ready")
            if event.kind == "approval":
                self._activity.setText(
                    "Waiting for your decision" if not event.detail else "Decision recorded"
                )
            if event.kind == "tool_result":
                for reference in event.detail.get("references", []):
                    label = f"{reference['kind']}: {reference['id']}"
                    if self._related.findText(label) < 0:
                        self._related.addItem(label, reference)
                        self._related.setCurrentIndex(self._related.count() - 1)
                self._changes.extend(event.detail.get("changes", []))
                self._changes_button.setEnabled(bool(self._changes))
                if event.detail.get("project_changed") and self._session is not None:
                    self._session.events.changed.emit("workspace")
            self._show_event(event)

    def _receive_finished(self, runner: Orchestrator, answer: str) -> None:
        if runner is self._active_runner:
            self._active_runner = None
            self._finished(answer)

    def _receive_failed(self, runner: Orchestrator, message: str) -> None:
        if runner is self._active_runner:
            self._active_runner = None
            if runner is self._orchestrator:
                self._failed(message)
            else:
                self._finished("")

    def _show_event(self, event: Event) -> None:
        """Route one event to the question bubble, the working, or the answer."""
        role = event.role
        text = event.text
        who = _who(role)
        if event.kind == "user":
            self.transcript.add_user(text)
            self._turn = self.transcript.add_turn()
            return
        turn = self._turn or self.transcript.add_turn()
        self._turn = turn
        safe = html.escape(text)
        if event.kind == "message":
            turn.finish(text)
        elif event.kind == "delegate":
            turn.activity(f"&rarr; {who} is asked: {safe}", f"-> {role}: {text}", role=role)
        elif event.kind == "report":
            short = safe if len(safe) <= 600 else safe[:600] + " …"
            turn.activity(f"&larr; {who} reports: {short}", f"<- {role}: {text}", role=role)
        elif event.kind == "note":
            turn.activity(f"{who}: {safe}", f"{role}: {text}", role=role)
        elif event.kind == "thinking":
            turn.thinking(role, text)
        elif event.kind == "tool_call":
            turn.activity(f"{who} · <code>{safe}</code>", f"{role} . {text}", role=role, tool=True)
        elif event.kind == "tool_result" and event.detail.get("is_error"):
            turn.activity(
                f'<span style="color:#a33">{who} · {safe} was refused</span>',
                f"{role} . {text} refused",
                role=role,
            )
        elif event.kind == "approval":
            verdict = "allowed" if event.detail.get("allowed") else "declined"
            turn.activity(
                f'<span style="color:#a33">{who}: {safe} {verdict} by you</span>',
                f"{role}: {text} {verdict} by you",
                role=role,
            )
        elif event.kind == "error":
            turn.activity(
                f'<span style="color:#a33">{who}: {safe}</span>', f"{role}: {text}", role=role
            )

    def _finished(self, answer: str) -> None:
        self._busy = False
        self._activity.setText(f"Completed - {len(self._changes)} recorded configuration changes.")
        self._turn = None
        self._set_enabled()

    def _failed(self, message: str) -> None:
        self._busy = False
        self._activity.setText(message)
        if self._turn is not None:
            self._turn.fail(message)
        else:
            self.transcript.note(message)
        self._turn = None
        self._set_enabled()

    def _set_enabled(self) -> None:
        ready = self._session is not None and not self._busy
        self.send.setEnabled(ready)
        self.input.setEnabled(self._session is not None)
        self.stop.setEnabled(self._busy)
        self._new.setEnabled(not self._busy)
        self._settings_button.setEnabled(not self._busy)

    # -- settings ------------------------------------------------------------

    def _edit_settings(self) -> None:
        if self._busy:
            return
        dialog = ProviderDialog(self._settings, self._session_key, self)
        if dialog.exec():
            self._settings, self._session_key = dialog.result_settings()
            try:
                self._save(self._settings)
            except ProviderError as refused:
                QMessageBox.warning(self, "Agent model", str(refused))
            self.new_conversation()
            self._describe_where()

    def _describe_where(self) -> None:
        provider = self._settings.provider
        if provider.is_local:
            place = f"on this machine ({provider.host})"
        else:
            place = f"to {provider.host}; what the tools return about your data goes with it"
        self._where.setText(f"<b>{html.escape(provider.model)}</b> · {html.escape(provider.host)}")
        self._where.setToolTip(f"The conversation is sent {place}.")
