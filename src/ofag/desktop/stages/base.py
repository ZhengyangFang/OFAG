"""What every stage has in common."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ofag.desktop.navigation import Stage, stage_info
from ofag.desktop.session import Session


class StagePanel(QWidget):
    """One stage of work on the open project."""

    def __init__(self, stage: Stage) -> None:
        super().__init__()
        self._stage = stage
        self._session: Session | None = None
        info = stage_info(stage)

        self._heading = QLabel(info.title)
        self._heading.setObjectName("stageHeading")
        self._purpose = QLabel(info.purpose)
        self._purpose.setObjectName("stagePurpose")
        self._purpose.setWordWrap(True)

        self._layout = QVBoxLayout()
        self._layout.addWidget(self._heading)
        self._layout.addWidget(self._purpose)
        self._body = QVBoxLayout()
        self._layout.addLayout(self._body, 1)
        self.setLayout(self._layout)

        self._empty = QLabel("Open a project to begin.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setObjectName("stageEmpty")
        self._body.addWidget(self._empty)
        following = {
            Stage.DATA: (Stage.SETUP, "Next: Setup"),
            Stage.SETUP: (Stage.INVERSION, "Next: Inversion"),
            Stage.INVERSION: (Stage.RESULTS, "View results"),
            Stage.RESULTS: (Stage.INTERPRETATION, "Next: Interpretation"),
            Stage.INTERPRETATION: (Stage.LINEAGE, "View lineage"),
        }
        self._next = QPushButton(following.get(stage, (stage, "Back to Data"))[1])
        target = following.get(stage, (Stage.DATA, ""))[0]
        self._next.clicked.connect(lambda: self._go(target))
        self._layout.addWidget(self._next)

    def _go(self, target: Stage) -> None:
        if self.session is not None:
            self.session.events.navigate.emit(target.value)

    @property
    def session(self) -> Session | None:
        return self._session

    def set_session(self, session: Session | None) -> None:
        """Called by the window whenever the open project changes."""
        if session is not self._session:
            from ofag.desktop.tasks import BackgroundTask

            for task in self.findChildren(BackgroundTask):
                task.cancel()
        self._session = session
        self._next.setEnabled(session is not None)
        self._empty.setVisible(session is None)
        if session is not None:
            self.refresh()

    def refresh(self) -> None:
        """Read the open project. Overridden by every stage that shows data."""

    def refresh_updates(self, kind: str) -> None:
        self.refresh()
