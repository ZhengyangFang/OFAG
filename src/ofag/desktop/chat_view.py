"""A conversation drawn as one: the person's messages, and each answer with its working."""

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["ChatView", "AgentTurn"]

#: A role's colour, always beside its name, so identity is never colour alone.
ROLE_COLOURS = {
    "person": "#1f4e79",
    "lead": "#2e7d32",
    "data": "#6a1b9a",
    "inversion": "#ad5a00",
    "modelling": "#00695c",
    "audit": "#b71c1c",
    "literature": "#37474f",
}

_STYLE = """
QFrame#userBubble { background: #e3edf9; border-radius: 10px; }
QFrame#answerBubble { background: #eef6ea; border-radius: 10px; }
QFrame#failedBubble { background: #fbeaea; border-radius: 10px; }
QLabel#activity { color: #666; font-size: 9pt; }
QToolButton#workingToggle { border: none; color: #555; text-align: left; }
"""

#: Longer reasoning is cut in the view; the conversation log keeps all of it.
_LONGEST_THOUGHT = 700


def _who(role: str) -> str:
    colour = ROLE_COLOURS.get(role, "#444")
    return f'<b style="color:{colour}">{html.escape(role)}</b>'


def _label(text: str, *, rich: bool = True, markdown: bool = False, name: str = "") -> QLabel:
    label = QLabel()
    if markdown:
        label.setTextFormat(Qt.TextFormat.MarkdownText)
    elif rich:
        label.setTextFormat(Qt.TextFormat.RichText)
    else:
        label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
    )
    label.setOpenExternalLinks(False)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    if name:
        label.setObjectName(name)
    return label


def _bubble(body: QLabel, name: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 7, 10, 7)
    layout.addWidget(body)
    return frame


class AgentTurn(QWidget):
    """One reply: the working, folding away once the answer is in."""

    def __init__(self) -> None:
        super().__init__()
        self._started = time.monotonic()
        self._roles: set[str] = set()
        self._tools = 0
        self.plain: list[str] = []

        self.toggle = QToolButton()
        self.toggle.setObjectName("workingToggle")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.toggled.connect(self._show_working)
        self.working = QWidget()
        self.working.hide()
        self._working_layout = QVBoxLayout(self.working)
        self._working_layout.setContentsMargins(14, 0, 0, 0)
        self._working_layout.setSpacing(1)
        self.answer: QFrame | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.working)
        self._layout = layout
        self.toggle.setChecked(False)
        self._update_toggle(done=False)

    # -- the working ---------------------------------------------------------

    def activity(self, fragment: str, plain: str, *, role: str = "", tool: bool = False) -> None:
        if role:
            self._roles.add(role)
        if tool:
            self._tools += 1
        self._working_layout.addWidget(_label(fragment, name="activity"))
        self.plain.append(plain)
        self._update_toggle(done=False)

    def thinking(self, role: str, text: str) -> None:
        shown = text if len(text) <= _LONGEST_THOUGHT else text[:_LONGEST_THOUGHT] + " …"
        self.activity(
            f'{_who(role)} <i style="color:#777">thinks: {html.escape(shown)}</i>',
            f"{role} thinks: {text}",
            role=role,
        )

    # -- the end -------------------------------------------------------------

    def finish(self, answer: str) -> None:
        self.answer = _bubble(_label(answer, markdown=True), "answerBubble")
        self._layout.addWidget(self.answer)
        self.plain.append(answer)
        self.toggle.setChecked(False)
        self._update_toggle(done=True)

    def fail(self, message: str) -> None:
        self.answer = _bubble(_label(message, rich=False), "failedBubble")
        self._layout.addWidget(self.answer)
        self.plain.append(message)
        self.toggle.setChecked(True)
        self._update_toggle(done=True, failed=True)

    def _show_working(self, shown: bool) -> None:
        self.working.setVisible(shown)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def _update_toggle(self, *, done: bool, failed: bool = False) -> None:
        seconds = time.monotonic() - self._started
        roles = len(self._roles - {"lead"})
        parts = [
            f"{roles} role{'s' if roles != 1 else ''}" if roles else "",
            f"{self._tools} tool call{'s' if self._tools != 1 else ''}" if self._tools else "",
        ]
        detail = " · ".join(p for p in parts if p)
        if not done:
            head = "Working…"
        elif failed:
            head = f"Stopped after {seconds:.0f} s"
        else:
            head = f"Worked for {seconds:.0f} s"
        self.toggle.setText(f"{head}{' · ' + detail if detail else ''}")


class ChatView(QScrollArea):
    """The whole conversation, newest at the bottom, following it as it grows."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("agentTranscript")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._inner = QWidget()
        self._inner.setStyleSheet(_STYLE)
        self._rows = QVBoxLayout(self._inner)
        self._rows.setContentsMargins(8, 8, 8, 8)
        self._rows.setSpacing(10)
        self._rows.addStretch(1)
        self.setWidget(self._inner)
        self._placeholder: QLabel | None = None
        #: What was said, in order: a line of text, or a turn read when asked.
        self._entries: list[str | AgentTurn] = []
        self.verticalScrollBar().rangeChanged.connect(self._follow)

    # -- building ------------------------------------------------------------

    def add_user(self, text: str) -> None:
        """The person's message, on the left."""
        self._clear_placeholder()
        bubble = _bubble(_label(text, rich=False), "userBubble")
        row = QHBoxLayout()
        row.addWidget(bubble, 5)
        row.addStretch(1)
        self._add_row(row)
        self._entries.append(f"person: {text}")

    def add_turn(self) -> AgentTurn:
        """A reply, on the right, filled in as the agents work."""
        self._clear_placeholder()
        turn = AgentTurn()
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(turn, 5)
        self._add_row(row)
        self._entries.append(turn)
        return turn

    def note(self, text: str) -> None:
        """A line that belongs to no turn: stopped, a model changed."""
        self._clear_placeholder()
        row = QHBoxLayout()
        row.addWidget(_label(f'<i style="color:#888">{html.escape(text)}</i>'), 1)
        self._add_row(row)
        self._entries.append(text)

    def show_placeholder(self, text: str) -> None:
        self.clear()
        self._placeholder = _label(f'<i style="color:#888">{html.escape(text)}</i>')
        self._rows.insertWidget(self._rows.count() - 1, self._placeholder)

    def clear(self) -> None:
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            _discard(item)
        self._placeholder = None
        self._entries.clear()

    def toPlainText(self) -> str:  # noqa: N802 - the name QTextBrowser used, for callers
        """Everything said, in order, as text: for tests and for copying out."""
        parts = [self._placeholder.text()] if self._placeholder is not None else []
        for entry in self._entries:
            parts += entry.plain if isinstance(entry, AgentTurn) else [entry]
        return "\n".join(parts)

    # -- helpers ---------------------------------------------------------------

    def _add_row(self, row: QHBoxLayout) -> None:
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self._rows.insertWidget(self._rows.count() - 1, holder)

    def _clear_placeholder(self) -> None:
        if self._placeholder is not None:
            _gone(self._placeholder)
            self._placeholder = None

    def _follow(self, _minimum: int, maximum: int) -> None:
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(maximum))


def _discard(item: object) -> None:
    widget = getattr(item, "widget", lambda: None)()
    if widget is not None:
        _gone(widget)


def _gone(widget: QWidget) -> None:
    # Hidden and unparented first: taken out of a layout, a widget stays where it was
    # drawn until the event loop gets round to deleting it, and the placeholder sat on
    # top of the first answer until it did.
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()
