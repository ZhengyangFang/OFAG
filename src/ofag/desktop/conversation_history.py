"""Read saved project conversations without replaying their tool calls."""

import json
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QTextEdit, QVBoxLayout, QWidget


class ConversationHistory(QDialog):
    def __init__(self, root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project conversation history")
        self.resize(850, 650)
        self._list = QComboBox()
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saved conversations (read-only). Tool calls are never replayed."))
        layout.addWidget(self._list)
        layout.addWidget(self._text, 1)
        for path in sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            title = path.stem
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    event = json.loads(line)
                    if event.get("kind") == "user":
                        title = f"{event.get('at', '')} - {str(event.get('text', ''))[:65]}"
                        break
            except (OSError, ValueError, AttributeError):
                pass
            self._list.addItem(title, str(path))
        self._list.currentIndexChanged.connect(self._load)
        self._load()

    def _load(self) -> None:
        path = self._list.currentData()
        if not path:
            self._text.setPlainText("No saved conversations yet.")
            return
        lines = []
        try:
            for raw in Path(path).read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(raw)
                    if event.get("kind") == "thinking":
                        continue
                    lines.append(
                        f"{event.get('at', '')} | {event.get('role', '')} | "
                        f"{event.get('kind', '')}\n{event.get('text', '')}"
                    )
                    lines.extend(event.get("detail", {}).get("changes", []))
                except (ValueError, AttributeError, TypeError):
                    lines.append("[Incomplete log entry]")
        except OSError as error:
            lines.append(str(error))
        self._text.setPlainText("\n\n".join(lines))
