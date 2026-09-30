"""Editable model recipes using the same audited operations as the agents."""

import json
from typing import Any

from pydantic import BaseModel, Field
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.agent.volumes import CellGridSpec
from ofag.core.schemas import UnitRule
from ofag.desktop.specform import SpecForm
from ofag.desktop.tasks import BackgroundTask
from ofag.services.result_review import ResultReview


class ModelRecipe(BaseModel):
    grid_id: str = ""
    rules: list[UnitRule] = Field(default_factory=list)
    surfaces: dict[str, Any] = Field(default_factory=dict)
    sections: dict[str, Any] = Field(default_factory=dict)


def model_action(root: Any, tool: str, arguments: dict[str, Any]) -> Any:
    from ofag.agent.dispatch import Dispatcher

    return Dispatcher(root, actor="desktop-modelling").call(tool, arguments)


class ModelBuilder(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.session: Any = None
        self.task = BackgroundTask(self)
        self.task.succeeded.connect(self._finished)
        self.recipe = SpecForm(ModelRecipe)
        self.grid = SpecForm(CellGridSpec)
        self._empty_grid = self.grid.value()
        self.saved = QComboBox()
        self.saved.addItem("New recipe", None)
        self.saved.currentIndexChanged.connect(self._load_recipe)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(120)
        self.task.failed.connect(self.output.setPlainText)
        self.task.status.connect(self.output.setPlainText)
        tabs = QTabWidget()
        for title, form in (("Rules & sources", self.recipe), ("New grid", self.grid)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(form)
            tabs.addTab(scroll, title)
        row = QHBoxLayout()
        for text, callback in (
            ("Create grid", self._grid),
            ("Use selected results", self._sources),
            ("Build new version", self._build),
            ("Export report", self._export),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            self.task.busy_changed.connect(lambda busy, b=button: b.setEnabled(not busy))
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Set rules and sources. Builds require diagnosed, independently audited runs.")
        )
        layout.addWidget(self.saved)
        layout.addWidget(tabs)
        layout.addLayout(row)
        layout.addWidget(self.output)

    def load(self, session: Any) -> None:
        if session is not self.session:
            self.task.cancel()
            self.recipe.set_value(ModelRecipe().model_dump())
            self.grid.set_value(self._empty_grid)
            self.output.clear()
        self.session = session
        selected = self.saved.currentData()
        self.saved.blockSignals(True)
        self.saved.clear()
        self.saved.addItem("New recipe", None)
        if session:
            for path in sorted((session.folder.runs_root / "models").glob("*.recipe.json")):
                self.saved.addItem(path.name.removesuffix(".recipe.json")[:8], str(path))
        self.saved.setCurrentIndex(max(0, self.saved.findData(selected)))
        self.saved.blockSignals(False)

    def _load_recipe(self) -> None:
        from pathlib import Path

        path = self.saved.currentData()
        if path is None:
            self.recipe.set_value(ModelRecipe().model_dump())
            return
        if path:
            try:
                self.recipe.set_value(json.loads(Path(path).read_text("utf-8")))
            except (OSError, ValueError) as error:
                self.output.setPlainText(str(error))

    def _sources(self) -> None:
        if not self.session:
            return
        choices = ResultReview(self.session.runs).selections()
        sections = {
            f"source_{index + 1}": {"run_id": choice["run_id"]}
            for index, choice in enumerate(choices)
        }
        self.recipe.set_value({"sections": sections})
        self.output.setPlainText(
            "Sources loaded. Choose rules and check method support before building."
        )

    def _start(self, tool: str, args: dict[str, Any]) -> None:
        if self.session:
            self.task.start("Working…", model_action, self.session.folder.runs_root, tool, args)

    def _grid(self) -> None:
        if self.grid.errors():
            self.output.setPlainText("\n".join(self.grid.errors()))
            return
        self._start("ofag.cell_grid", {"spec": self.grid.value()})

    def _build(self) -> None:
        if self.recipe.errors():
            self.output.setPlainText("\n".join(self.recipe.errors()))
            return
        self._start("ofag.build_model", self.recipe.value())

    def _export(self) -> None:
        self._start("ofag.export_report", {})

    def _finished(self, result: dict[str, Any]) -> None:
        self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        if "grid_id" in result and "built" not in result:
            self.recipe.set_value({"grid_id": result["grid_id"]})
        if self.session:
            self.session.events.changed.emit("models")
            self.load(self.session)
