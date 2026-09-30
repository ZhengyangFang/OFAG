"""Turning recovered properties into a description of the ground."""

from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.core.schemas import (
    Borehole,
    BoreholeInterval,
    GeologicalModel,
    ModelExtent,
    PropertyClass,
    StratigraphicUnit,
    StructuralGroup,
)
from ofag.desktop.navigation import Stage
from ofag.desktop.plotting import PlotPanel
from ofag.desktop.stages.base import StagePanel
from ofag.desktop.tasks import BackgroundTask, interpolate_section
from ofag.services.result_review import ResultReview


class InterpretationStage(StagePanel):
    """Named units, logged holes, and the surfaces between them."""

    def __init__(self) -> None:
        super().__init__(Stage.INTERPRETATION)
        self._tabs = QTabWidget()
        self._preferred = QLabel()
        self._preferred.setWordWrap(True)
        self._body.addWidget(self._preferred)
        reload_geology = QPushButton("Reload saved edits")
        reload_geology.setToolTip("Replaces unsaved structural edits.")
        reload_geology.clicked.connect(self.refresh)
        self._body.addWidget(reload_geology)
        self._labelled = _LabelledModelTab()
        self._tabs.addTab(self._labelled, "Labelled model")
        self._units = _UnitsTab()
        self._boreholes = _BoreholesTab()
        self._surfaces = _SurfacesTab()
        self._tabs.addTab(self._units, "Property classes")
        self._tabs.setTabToolTip(
            1, "Separate classification settings; does not edit the displayed volume."
        )
        self._tabs.addTab(self._boreholes, "Boreholes")
        self._tabs.addTab(self._surfaces, "Surfaces")
        from ofag.desktop.model_builder import ModelBuilder

        self._builder = ModelBuilder()
        self._tabs.addTab(self._builder, "Build model")
        from ofag.desktop.coverage_view import CoverageView

        self._coverage = CoverageView()
        self._tabs.addTab(self._coverage, "Survey map")
        self._body.addWidget(self._tabs, 1)

    def refresh(self) -> None:
        self._builder.load(self.session)
        self._coverage.load(self.session)
        self._refresh_preferred()
        if self._surfaces._session is not self.session:
            self._surfaces._task.cancel()
        self._labelled.load(self.session)
        for tab in (self._units, self._boreholes, self._surfaces):
            tab.load(self.session)

    def refresh_updates(self, kind: str) -> None:
        self._builder.load(self.session)
        if self._tabs.currentWidget() is self._coverage or kind == "workspace":
            self._coverage.load(self.session)
        # Run progress and audit updates must not rebuild editable geology tables.
        self._refresh_preferred()
        self._labelled.load(self.session)
        if kind == "workspace":
            self._surfaces.reload()

    def focus_record(self, identifier: str) -> None:
        from pathlib import Path

        self._labelled.load(self.session)
        for index in range(self._labelled._models.count()):
            if Path(self._labelled._models.itemData(index)).stem == identifier:
                self._labelled._models.setCurrentIndex(index)
                self._tabs.setCurrentIndex(0)
                return

    def _refresh_preferred(self) -> None:
        if self.session is not None:
            try:
                choices = ResultReview(self.session.runs).selections()
                self._preferred.setText(
                    "Preferred results: "
                    + (
                        "; ".join(
                            f"{choice['dataset']}: {choice['run_id'][:8]} ({choice['audit']})"
                            for choice in choices
                        )
                        or "none. Select results in Results."
                    )
                )
            except (OSError, ValueError) as error:
                self._preferred.setText(f"Could not read preferred results: {error}")


#: A claimed unit's colour, in the order units are listed: distinct under the common
#: colour-vision deficiencies, and none of them grey, which is kept for what nothing
#: claimed.
_UNIT_COLOURS = (
    "#1f77b4",
    "#e6a100",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#17becf",
    "#e377c2",
)
_UNCLAIMED_COLOURS = ("#d9d9d9", "#bdbdbd", "#eeeeee")


def _model_label(path: Any) -> str:
    """"The case's model", or the name an agent's model was saved under."""
    import json

    if path.name == "geological_model.npz":
        return "The case's model"
    try:
        return f"Agent model: {json.loads(path.with_suffix('.json').read_text('utf-8'))['name']}"
    except (OSError, ValueError, KeyError):
        return f"Agent model {path.stem[:8]}"


class _LabelledModelTab(QWidget):
    """The labelled volumes the cases and the agents built, cut and looked at."""

    VIEWS = ("Section west-east", "Section south-north", "Plan")

    def __init__(self) -> None:
        super().__init__()
        from PySide6.QtWidgets import QSlider

        self._session: Any = None
        self._model: Any = None
        self._positions: Any = None
        self._models = QComboBox()
        self._models.currentIndexChanged.connect(self._load_model)
        self._view = QComboBox()
        self._view.addItems(self.VIEWS)
        self._view.currentIndexChanged.connect(self._view_changed)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.valueChanged.connect(self._draw)
        self._where = QLabel()
        top = QHBoxLayout()
        top.addWidget(QLabel("Model"))
        top.addWidget(self._models, 2)
        top.addWidget(QLabel("Cut"))
        top.addWidget(self._view)
        top.addWidget(self._slider, 2)
        top.addWidget(self._where)
        self._plot = PlotPanel()
        self._report = QTextEdit()
        self._report.setReadOnly(True)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._plot)
        split.addWidget(self._report)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)

    def load(self, session: Any) -> None:
        from ofag.services.unit_models import find_unit_models

        paths = find_unit_models(session.folder.root) if session is not None else []
        signature = (id(session), tuple((str(path), path.stat().st_mtime_ns) for path in paths))
        if getattr(self, "_signature", None) == signature:
            return
        self._signature = signature
        selected = self._models.currentData() if session is self._session else None
        self._session = session
        self._models.blockSignals(True)
        self._models.clear()
        if session is not None:
            for path in paths:
                self._models.addItem(_model_label(path), str(path))
        self._models.setCurrentIndex(max(0, self._models.findData(selected)))
        self._models.blockSignals(False)
        if self._models.count() == 0:
            self._model = None
            self._plot.clear(
                "No labelled model in this project yet. One is written when a case script "
                "builds its model, or when the modelling agent runs ofag.build_model."
            )
            self._report.clear()
            return
        self._load_model()

    def _load_model(self) -> None:
        from pathlib import Path

        from ofag.services.unit_models import load_unit_model

        path = self._models.currentData()
        if not path or self._session is None:
            return
        try:
            self._model = load_unit_model(Path(path), self._session.folder.root)
        except (OSError, ValueError, KeyError) as unreadable:
            self._model = None
            self._plot.clear(f"This model could not be read: {unreadable}")
            return
        model = self._model
        lines = [
            f"{model.cells:,} cells in the model volume"
            + (f"; cell geometry from {model.geometry_from}" if model.geometry_from else "")
        ]
        lines += [
            f"  {share * 100:5.1f}%  {name}   [{source}]" for name, source, share in model.shares()
        ]
        if model.report:
            lines += ["", model.report]
        recipe = model.path.with_suffix(".recipe.json")
        lines += [
            "",
            "Edit in Build model; each build creates a new version."
            if recipe.exists()
            else "Legacy case model: no saved recipe. Build model creates a separate version.",
        ]
        self._report.setPlainText("\n".join(lines))
        self._view_changed()

    def _legend(self) -> list[tuple[str, str]]:
        model = self._model
        shares = model.shares()
        legend = []
        claimed = unclaimed = 0
        for index, (name, _source, share) in enumerate(shares):
            if model.unclaimed(index):
                colour = _UNCLAIMED_COLOURS[unclaimed % len(_UNCLAIMED_COLOURS)]
                unclaimed += 1
            else:
                colour = _UNIT_COLOURS[claimed % len(_UNIT_COLOURS)]
                claimed += 1
            legend.append((f"{name} ({share * 100:.1f}%)", colour))
        return legend

    def _axis_values(self) -> Any:
        import numpy as np

        model = self._model
        inside = model.unit >= 0
        view = self._view.currentText()
        if view == "Plan":
            if "ground_elevation_m" in model.fields:
                return np.round(
                    model.fields["ground_elevation_m"][inside] - model.centres_m[inside, 2], 3
                )
            return np.round(model.centres_m[inside, 2], 3)
        axis = 1 if view == "Section west-east" else 0
        return np.round(model.centres_m[inside, axis], 3)

    def _view_changed(self) -> None:
        import numpy as np

        if self._model is None:
            return
        self._positions = np.unique(self._axis_values())
        self._slider.blockSignals(True)
        self._slider.setRange(0, max(0, len(self._positions) - 1))
        self._slider.setValue(
            len(self._positions) // 2
            if self._view.currentText() != "Plan"
            else min(2, len(self._positions) - 1)
        )
        self._slider.blockSignals(False)
        self._draw()

    def _draw(self) -> None:
        import numpy as np

        model = self._model
        if model is None or self._positions is None or len(self._positions) == 0:
            return
        position = float(self._positions[self._slider.value()])
        c, w = model.centres_m, model.widths_m
        inside = model.unit >= 0
        view = self._view.currentText()
        legend = self._legend()
        if view == "Plan":
            if "ground_elevation_m" in model.fields:
                depth = model.fields["ground_elevation_m"] - c[:, 2]
                on = inside & (np.abs(depth - position) <= w[:, 2] / 2 + 1e-6)
                where = f"{position:.1f} m below ground"
            else:
                on = inside & (np.abs(c[:, 2] - position) <= w[:, 2] / 2 + 1e-6)
                where = f"elevation {position:.0f} m"
            self._where.setText(where)
            self._plot.unit_cells(
                c[on, 0],
                c[on, 1],
                w[on, 0],
                w[on, 1],
                model.unit[on],
                legend=legend,
                title=f"{model.name}: plan, {where}",
                x_label="Easting (m)",
                y_label="Northing (m)",
                equal_aspect=True,
            )
            return
        axis, across = (1, 0) if view == "Section west-east" else (0, 1)
        on = inside & (np.abs(c[:, axis] - position) <= w[:, axis] / 2 + 1e-6)
        name = "northing" if axis == 1 else "easting"
        self._where.setText(f"{name} {position:.0f} m")
        self._plot.unit_cells(
            c[on, across],
            c[on, 2],
            w[on, across],
            w[on, 2],
            model.unit[on],
            legend=legend,
            title=f"{model.name}: section at {name} {position:.0f} m",
            x_label="Easting (m)" if across == 0 else "Northing (m)",
            y_label="Elevation (m)",
        )


class _ModelTab(QWidget):
    """A tab that reads and writes the project's one geological model."""

    def __init__(self) -> None:
        super().__init__()
        self._session: Any = None

    def load(self, session: Any) -> None:
        self._session = session
        if session is not None:
            self.reload()

    def reload(self) -> None:
        """Read the workspace. Overridden by every tab."""

    def model(self) -> GeologicalModel | None:
        if self._session is None:
            return None
        models = self._session.workspace().geology
        return models[0] if models else None

    def save(self, model: GeologicalModel) -> None:
        session = self._session
        workspace = session.workspace()
        session.save_workspace(workspace.model_copy(update={"geology": (model,)}))

    def ensure_model(self) -> GeologicalModel:
        existing = self.model()
        if existing is not None:
            return existing
        created = GeologicalModel(
            name=f"{self._session.record.name} structure",
            extent=ModelExtent(
                min_x_m=0.0,
                max_x_m=1000.0,
                min_y_m=-100.0,
                max_y_m=100.0,
                min_z_m=-500.0,
                max_z_m=0.0,
            ),
        )
        self.save(created)
        return created


class _UnitsTab(_ModelTab):
    """The stratigraphic pile, and what each unit is in the recovered property."""

    def __init__(self) -> None:
        super().__init__()
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Unit", "Colour", "From", "To"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Saprolite")
        self._colour = QLineEdit("#c9a227")
        add = QPushButton("Add unit")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        save = QPushButton("Save value ranges")
        save.clicked.connect(self._save_ranges)

        form = QHBoxLayout()
        form.addWidget(QLabel("Name"))
        form.addWidget(self._name, 2)
        form.addWidget(QLabel("Colour"))
        form.addWidget(self._colour)
        form.addWidget(add)
        form.addWidget(remove)
        form.addStretch(1)
        form.addWidget(save)

        self._note = QLabel(
            "A value range says which recovered values you called this unit. Nothing is "
            "classified automatically: a recovered resistivity does not say what the rock is."
        )
        self._note.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._note)
        self.setLayout(layout)

    def reload(self) -> None:
        model = self.model()
        units = model.units if model is not None else ()
        ranges = self._ranges()
        self._table.setRowCount(len(units))
        for row, unit in enumerate(units):
            name_cell = QTableWidgetItem(unit.name)
            name_cell.setData(Qt.ItemDataRole.UserRole, unit.unit_id)
            self._table.setItem(row, 0, name_cell)
            self._table.setItem(row, 1, QTableWidgetItem(unit.colour))
            low, high = ranges.get(unit.name, (None, None))
            self._table.setItem(row, 2, QTableWidgetItem("" if low is None else str(low)))
            self._table.setItem(row, 3, QTableWidgetItem("" if high is None else str(high)))

    def _ranges(self) -> dict[str, tuple[float | None, float | None]]:
        if self._session is None:
            return {}
        found: dict[str, tuple[float | None, float | None]] = {}
        for site in self._session.workspace().models:
            for source in site.sources:
                for item in source.classes:
                    found[item.name] = (item.minimum, item.maximum)
        return found

    def _add(self) -> None:
        if self._session is None:
            return
        name = self._name.text().strip()
        if not name:
            return
        model = self.ensure_model()
        unit = StratigraphicUnit(name=name, colour=self._colour.text().strip() or "#c9a227")
        units = (*model.units, unit)
        # One group holding the pile in the order units were added, which is the order
        # they were deposited unless somebody says otherwise.
        group = StructuralGroup(
            group_id=model.groups[0].group_id if model.groups else uuid4(),
            name=model.groups[0].name if model.groups else "Sequence",
            unit_ids=tuple(item.unit_id for item in units),
        )
        self.save(model.model_copy(update={"units": units, "groups": (group,)}))
        self._name.clear()
        self.reload()

    def _remove(self) -> None:
        model = self.model()
        row = self._table.currentRow()
        if model is None or row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        unit_id = item.data(Qt.ItemDataRole.UserRole)
        units = tuple(unit for unit in model.units if unit.unit_id != unit_id)
        groups = tuple(
            group.model_copy(
                update={"unit_ids": tuple(uid for uid in group.unit_ids if uid != unit_id)}
            )
            for group in model.groups
        )
        holes = tuple(
            hole.model_copy(
                update={
                    "intervals": tuple(
                        interval for interval in hole.intervals if interval.unit_id != unit_id
                    )
                }
            )
            for hole in model.boreholes
        )
        self.save(
            model.model_copy(
                update={
                    "units": units,
                    "groups": groups,
                    "boreholes": holes,
                    "surface_points": tuple(
                        point for point in model.surface_points if point.unit_id != unit_id
                    ),
                    "orientations": tuple(
                        item for item in model.orientations if item.unit_id != unit_id
                    ),
                }
            )
        )
        self.reload()

    def _save_ranges(self) -> None:
        """Store the value ranges as a site model against the project's runs."""
        session = self._session
        model = self.model()
        if session is None or model is None:
            return
        from ofag.core.schemas import ModelSource, SiteModel

        classes: list[PropertyClass] = []
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            if name_item is None:
                continue
            colour = self._table.item(row, 1)
            classes.append(
                PropertyClass(
                    name=name_item.text(),
                    colour=(colour.text() if colour else "#c9a227"),
                    minimum=_number(self._table.item(row, 2)),
                    maximum=_number(self._table.item(row, 3)),
                )
            )
        workspace = session.workspace()
        runs = session.runs.list_runs()
        if not runs:
            QMessageBox.information(
                self,
                "OFAG",
                "A value range is a reading of a specific inversion, so it is stored against "
                "one. Run an inversion first.",
            )
            return
        newest = runs[0]
        try:
            result = session.runs.result(newest.spec.run_id)
        except (KeyError, ValueError, OSError):
            result = None
        artifacts = result.artifacts if result is not None else ()
        if not artifacts:
            QMessageBox.information(self, "OFAG", "That run produced no model to classify yet.")
            return
        artifact = artifacts[0]
        site = SiteModel(
            name=f"{session.record.name} units",
            sources=(
                ModelSource(
                    run_id=newest.spec.run_id,
                    artifact_id=artifact.artifact_id,
                    physical_quantity=artifact.physical_quantity,
                    units=artifact.units,
                    classes=tuple(classes),
                ),
            ),
        )
        session.save_workspace(workspace.model_copy(update={"models": (site,)}))
        QMessageBox.information(self, "OFAG", f"Stored against run {newest.spec.run_id}.")


class _BoreholesTab(_ModelTab):
    """Holes, and what was logged in them."""

    def __init__(self) -> None:
        super().__init__()
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Hole", "Collar E", "Collar N", "Collar Z", "Depth"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._show_log)

        self._name = QLineEdit()
        self._name.setPlaceholderText("BH-1")
        self._east = _spin()
        self._north = _spin()
        self._elevation = _spin()
        self._depth = _spin(50.0, low=0.1)
        add = QPushButton("Add hole")
        add.clicked.connect(self._add_hole)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Collar easting (m)", self._east)
        form.addRow("Collar northing (m)", self._north)
        form.addRow("Collar elevation (m)", self._elevation)
        form.addRow("Total depth (m)", self._depth)
        collar = QGroupBox("A new hole")
        inner = QVBoxLayout()
        inner.addLayout(form)
        inner.addWidget(add)
        collar.setLayout(inner)

        self._unit = QComboBox()
        self._from = _spin(0.0, low=0.0)
        self._to = _spin(10.0, low=0.01)
        log = QPushButton("Add interval to the selected hole")
        log.clicked.connect(self._add_interval)
        interval_form = QFormLayout()
        interval_form.addRow("Unit", self._unit)
        interval_form.addRow("From depth (m)", self._from)
        interval_form.addRow("To depth (m)", self._to)
        interval_box = QGroupBox("Log an interval")
        interval_inner = QVBoxLayout()
        interval_inner.addLayout(interval_form)
        interval_inner.addWidget(log)
        interval_box.setLayout(interval_inner)

        self._log = QTextEdit()
        self._log.setReadOnly(True)

        left = QVBoxLayout()
        left.addWidget(collar)
        left.addWidget(interval_box)
        left.addStretch(1)
        left_holder = QWidget()
        left_holder.setLayout(left)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self._table)
        right.addWidget(self._log)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_holder)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout()
        layout.addWidget(splitter, 1)
        self.setLayout(layout)

    def reload(self) -> None:
        model = self.model()
        holes = model.boreholes if model is not None else ()
        self._table.setRowCount(len(holes))
        for row, hole in enumerate(holes):
            cells = (
                hole.name,
                f"{hole.collar_x_m:.1f}",
                f"{hole.collar_y_m:.1f}",
                f"{hole.collar_z_m:.1f}",
                f"{hole.total_depth_m:.1f}",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, hole.borehole_id)
                self._table.setItem(row, column, item)
        self._unit.clear()
        for unit in model.units if model is not None else ():
            self._unit.addItem(unit.name, unit.unit_id)
        self._show_log()

    def _selected_hole(self) -> Borehole | None:
        model = self.model()
        row = self._table.currentRow()
        if model is None or row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        borehole_id = item.data(Qt.ItemDataRole.UserRole)
        for hole in model.boreholes:
            if hole.borehole_id == borehole_id:
                return hole
        return None

    def _show_log(self) -> None:
        hole = self._selected_hole()
        model = self.model()
        if hole is None or model is None:
            self._log.clear()
            return
        names = {unit.unit_id: unit.name for unit in model.units}
        lines = [f"{hole.name}: {'vertical' if hole.vertical else 'surveyed'}", ""]
        for interval in sorted(hole.intervals, key=lambda item: item.from_depth_m):
            east, north, elevation = hole.position_at(interval.from_depth_m)
            lines.append(
                f"  {interval.from_depth_m:7.1f}–{interval.to_depth_m:<7.1f} m  "
                f"{names.get(interval.unit_id, 'unit'):<16s} "
                f"top at {elevation:.1f} m elevation ({east:.0f}, {north:.0f})"
            )
        if not hole.intervals:
            lines.append("  nothing logged yet")
        lines += [
            "",
            "The top of every interval is a contact for its unit. The bottom of the",
            "deepest one is not: the hole ended there, which says nothing about where",
            "the unit does.",
        ]
        self._log.setPlainText("\n".join(lines))

    def _add_hole(self) -> None:
        if self._session is None:
            return
        name = self._name.text().strip()
        if not name:
            return
        model = self.ensure_model()
        hole = Borehole(
            name=name,
            collar_x_m=self._east.value(),
            collar_y_m=self._north.value(),
            collar_z_m=self._elevation.value(),
            total_depth_m=self._depth.value(),
        )
        self.save(model.model_copy(update={"boreholes": (*model.boreholes, hole)}))
        self._name.clear()
        self.reload()

    def _add_interval(self) -> None:
        model = self.model()
        hole = self._selected_hole()
        unit_id = self._unit.currentData()
        if model is None or hole is None or unit_id is None:
            QMessageBox.information(self, "OFAG", "Select a hole, and add at least one unit first.")
            return
        try:
            interval = BoreholeInterval(
                unit_id=unit_id,
                from_depth_m=self._from.value(),
                to_depth_m=self._to.value(),
            )
            updated = hole.model_copy(update={"intervals": (*hole.intervals, interval)})
            # Re-validated rather than trusted: overlapping intervals and one deeper
            # than the hole are both refused, and a copy skips that.
            updated = Borehole.model_validate(updated.model_dump())
        except ValueError as error:
            QMessageBox.warning(self, "Not a log", str(error))
            return
        holes = tuple(
            updated if item.borehole_id == hole.borehole_id else item for item in model.boreholes
        )
        self.save(model.model_copy(update={"boreholes": holes}))
        self.reload()


class _SurfacesTab(_ModelTab):
    """What stops the model being interpolated, and the section when nothing does."""

    def __init__(self) -> None:
        super().__init__()
        self._readiness = QTextEdit()
        self._readiness.setReadOnly(True)
        self._plot = PlotPanel()
        draw = QPushButton("Interpolate and draw a section")
        draw.clicked.connect(self._draw)
        self._task = BackgroundTask(self)
        self._task.succeeded.connect(self._draw_finished)
        self._task.failed.connect(self._plot.clear)
        self._task.status.connect(self._readiness.setPlainText)
        self._task.busy_changed.connect(lambda busy: draw.setEnabled(not busy))
        cancel = QPushButton("Cancel interpolation")
        cancel.setEnabled(False)
        cancel.clicked.connect(self._task.cancel)
        self._task.busy_changed.connect(cancel.setEnabled)
        self._pending_model: GeologicalModel | None = None

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._readiness)
        splitter.addWidget(self._plot)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout()
        layout.addWidget(splitter, 1)
        layout.addWidget(draw)
        layout.addWidget(cancel)
        self.setLayout(layout)

    def reload(self) -> None:
        model = self.model()
        if model is None:
            self._readiness.setPlainText("No geological model yet. Add a unit to begin one.")
            return
        session = self._session
        issues = session.geology.readiness(model) if session is not None else model.readiness()
        contacts = len(model.borehole_points())
        lines = [
            f"{len(model.units)} units, {len(model.boreholes)} holes, "
            f"{contacts} logged contacts, {len(model.surface_points)} picked points",
            "",
        ]
        if issues:
            lines.append("Not ready to interpolate:")
            lines += [f"  {issue}" for issue in issues]
        else:
            lines.append("Ready to interpolate.")
        self._readiness.setPlainText("\n".join(lines))

    def _draw(self) -> None:
        session = self._session
        model = self.model()
        if session is None or model is None:
            return
        if not session.geology.dependency_available():
            self._plot.clear("Structural modelling needs the gempy extra: uv sync --extra gempy")
            return
        from ofag.core.schemas import SectionGeometry

        extent = model.extent
        geometry = SectionGeometry(
            start_m=(extent.min_x_m, 0.5 * (extent.min_y_m + extent.max_y_m)),
            end_m=(extent.max_x_m, 0.5 * (extent.min_y_m + extent.max_y_m)),
            min_z_m=extent.min_z_m,
            max_z_m=extent.max_z_m,
            samples_along=60,
            samples_vertical=40,
        )
        self._pending_model = model
        self._task.start(
            "Interpolating geological surfaces...", interpolate_section, model, geometry
        )

    def _draw_finished(self, section: Any) -> None:
        model = self._pending_model
        if model is None:
            return
        import numpy as np

        order = {unit.unit_id: index for index, unit in enumerate(model.units)}
        raster = np.array(
            [
                np.nan if unit is None else float(order.get(unit, np.nan))
                for unit in section.unit_ids
            ]
        )
        distances = np.tile(np.asarray(section.distances_m), section.samples_vertical)
        elevations = np.repeat(np.asarray(section.elevations_m), section.samples_along)
        self._plot.scatter_section(
            distances.tolist(),
            elevations.tolist(),
            raster.tolist(),
            title=f"{model.name}: {section.undecided_cells} cells left undecided",
            colour_label="unit",
        )


def _spin(value: float = 0.0, low: float = -1e9) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, 1e9)
    box.setDecimals(2)
    box.setValue(value)
    return box


def _number(item: QTableWidgetItem | None) -> float | None:
    if item is None or not item.text().strip():
        return None
    try:
        return float(item.text())
    except ValueError:
        return None
