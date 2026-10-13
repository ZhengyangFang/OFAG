"""The window: a project, six stages, and the folder everything lands in."""

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ofag.desktop.agent_panel import AgentPanel
from ofag.desktop.launcher import ProjectLauncher
from ofag.desktop.navigation import STAGES, Stage
from ofag.desktop.session import Session
from ofag.desktop.stages.base import StagePanel
from ofag.desktop.stages.data import DataStage
from ofag.desktop.stages.interpretation import InterpretationStage
from ofag.desktop.stages.inversion import InversionStage
from ofag.desktop.stages.lineage import LineageStage
from ofag.desktop.stages.results import ResultsStage
from ofag.desktop.stages.setup import SetupStage
from ofag.services.project_folder import DEFAULT_RESULT_ROOT
from ofag.services.project_service import ProjectService


class MainWindow(QMainWindow):
    """One project open at a time, six stages of work on it."""

    def __init__(self, result_root: Path = DEFAULT_RESULT_ROOT) -> None:
        super().__init__()
        self.setWindowTitle("OFAG")
        self.resize(1360, 900)
        self._projects = ProjectService(root=result_root)
        self._session: Session | None = None

        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(210)
        self._sidebar.setObjectName("stageList")
        for info in STAGES:
            item = QListWidgetItem(info.title)
            item.setData(Qt.ItemDataRole.UserRole, info.stage)
            item.setToolTip(info.purpose)
            self._sidebar.addItem(item)
        self._sidebar.currentRowChanged.connect(self._show_stage)

        self._pages = QStackedWidget()
        self._stages: dict[Stage, StagePanel] = {}
        for info in STAGES:
            panel = _build_stage(info.stage)
            self._stages[info.stage] = panel
            self._pages.addWidget(panel)

        self._project_label = QLabel("No project open")
        self._project_label.setObjectName("projectName")
        self._folder_label = QLabel("")
        self._folder_label.setObjectName("projectFolder")
        self._folder_label.setMaximumWidth(300)
        self._folder_label.setMinimumWidth(180)
        self._folder_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        reveal = QPushButton("Open folder")
        reveal.clicked.connect(self._reveal_folder)
        switch = QPushButton("Switch project…")
        switch.clicked.connect(self.choose_project)
        # The agents work across every stage, so they sit beside the stages in a dock
        # rather than being a seventh one.
        self._agents = AgentPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._agents)
        self._agents.hide()
        agents = QPushButton("Agents")
        agents.setCheckable(True)
        agents.toggled.connect(self._agents.setVisible)
        self._agents.visibilityChanged.connect(agents.setChecked)

        header = QHBoxLayout()
        header.addWidget(self._project_label)
        header.addWidget(self._folder_label)
        header.addStretch(1)
        header.addWidget(reveal)
        header.addWidget(switch)
        header.addWidget(agents)

        body = QHBoxLayout()
        body.addWidget(self._sidebar)
        body.addWidget(self._pages, 1)

        layout = QVBoxLayout()
        layout.addLayout(header)
        layout.addLayout(body, 1)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self._sidebar.setCurrentRow(0)
        self._apply_session()
        self._revision: tuple[object, ...] = ()
        self._watch = QTimer(self)
        self._watch.setInterval(1500)
        self._watch.timeout.connect(self._poll_project)
        self._watch.start()

    # -- the open project ---------------------------------------------------

    def choose_project(self) -> None:
        """Ask which project to work on, creating one if there is none."""
        launcher = ProjectLauncher(self._projects, self)
        if launcher.exec() and launcher.chosen is not None:
            self.open_project(launcher.chosen)

    def open_project(self, project_id: object) -> None:
        assert isinstance(project_id, UUID)
        if self._session is not None:
            self._session.events.changed.disconnect(self._project_changed)
            self._session.events.navigate.disconnect(self._navigate)
            self._session.events.focus_requested.disconnect(self._focus_record)
        self._session = Session.open(self._projects, project_id)
        self._session.events.changed.connect(self._project_changed)
        self._session.events.navigate.connect(self._navigate)
        self._session.events.focus_requested.connect(self._focus_record)
        self._revision = ()
        self._apply_session()

    def _apply_session(self) -> None:
        session = self._session
        if session is None:
            self._project_label.setText("No project open")
            self._folder_label.setText("")
        else:
            self._project_label.setText(session.record.name)
            self._folder_label.setText(f"Result / {session.folder.root.name}")
            self._folder_label.setToolTip(str(session.folder.root.resolve()))
        for panel in self._stages.values():
            panel.set_session(session)
        self._agents.set_session(session)
        self._show_stage(self._sidebar.currentRow())

    def _reveal_folder(self) -> None:
        if self._session is None:
            QMessageBox.information(self, "OFAG", "Open a project first.")
            return
        folder = self._session.folder.root.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -- navigation ---------------------------------------------------------

    def _show_stage(self, row: int) -> None:
        if 0 <= row < self._pages.count():
            if self._session:
                self._session.active_stage = STAGES[row].stage.value
            self._pages.setCurrentIndex(row)
            panel = self._stages[STAGES[row].stage]
            if isinstance(panel, InversionStage):
                panel.follow_selection()
            if panel.property("projectDirty"):
                kind = str(panel.property("projectDirty"))
                panel.setProperty("projectDirty", False)
                panel.refresh_updates(kind)

    def _navigate(self, stage: str) -> None:
        self._sidebar.setCurrentRow(next(i for i, item in enumerate(STAGES) if item.stage == stage))

    def _project_changed(self, kind: str) -> None:
        for stage, panel in self._stages.items():
            if kind == "runs" and stage not in (Stage.RESULTS, Stage.LINEAGE, Stage.INTERPRETATION):
                continue
            panel.setProperty("projectDirty", kind)
        self._show_stage(self._sidebar.currentRow())
        session = self._session
        if session is not None:
            from ofag.core.schemas import RunState
            from ofag.execution.state import IN_FLIGHT_STATES

            datasets = len(session.workspace().datasets)
            runs = session.runs.list_runs()
            active = sum(record.state in IN_FLIGHT_STATES for record in runs)
            next_step = "configure a run in Inversion"
            if not datasets:
                next_step = "import a survey in Data"
            elif active:
                next_step = f"follow {active} active run(s) in Results"
            elif any(record.state is RunState.SUCCEEDED for record in runs):
                next_step = "compare and review completed results"
            self.statusBar().showMessage(f"{datasets} datasets - Next: {next_step}")

    def _focus_record(self, kind: str, identifier: str) -> None:
        stage = {"run_id": Stage.RESULTS, "model_id": Stage.INTERPRETATION}.get(kind, Stage.DATA)
        if kind == "run_id" and self._session is not None:
            try:
                run_id = UUID(identifier)
            except ValueError:
                self.statusBar().showMessage("Invalid run reference.")
                return
            root = self._session.folder.runs_root
            if (root / "drafts" / f"{run_id}.json").is_file() and not (
                root / str(run_id) / "run_record.json"
            ).is_file():
                stage = Stage.INVERSION
        self._navigate(stage.value)
        panel = self._stages[stage]
        focus = getattr(panel, "focus_record", None)
        if focus is not None:
            focus(identifier)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        from ofag.desktop.tasks import BackgroundTask

        for task in self.findChildren(BackgroundTask):
            task.cancel()
        self._agents._stop()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _poll_project(self) -> None:
        session = self._session
        if session is None:
            return
        try:
            workspace_path = session.folder.workspace_path
            workspace = workspace_path.stat().st_mtime_ns if workspace_path.is_file() else 0
            paths = [
                path
                for pattern in (
                    "*/run_record.json",
                    "*/progress.jsonl",
                    "models/*.npz",
                    "obligations.jsonl",
                    "preferred_results.json",
                )
                for path in session.folder.runs_root.glob(pattern)
            ]
            revision = (
                workspace,
                tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)),
            )
            if revision != self._revision:
                kind = (
                    "workspace" if not self._revision or workspace != self._revision[0] else "runs"
                )
                self._revision = revision
                self._project_changed(kind)
        except (OSError, ValueError) as error:
            self.statusBar().showMessage(f"Could not refresh project: {error}")


def _build_stage(stage: Stage) -> StagePanel:
    """The panel for a stage. A `match` rather than a registry: six cases that the type
    checker can see are exhaustive is clearer than a lookup table that cannot fail
    visibly."""
    match stage:
        case Stage.DATA:
            return DataStage()
        case Stage.SETUP:
            return SetupStage()
        case Stage.INVERSION:
            return InversionStage()
        case Stage.RESULTS:
            return ResultsStage()
        case Stage.INTERPRETATION:
            return InterpretationStage()
        case Stage.LINEAGE:
            return LineageStage()
