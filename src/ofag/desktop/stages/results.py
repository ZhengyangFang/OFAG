"""Every run in the project, and what it produced."""

from typing import Any
from uuid import UUID

import numpy as np
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.core.cell_model import CellModel
from ofag.core.schemas import RunState
from ofag.desktop.navigation import Stage
from ofag.desktop.plotting import PlotPanel
from ofag.desktop.stages.base import StagePanel
from ofag.services.method_catalog import method_info
from ofag.services.result_review import ResultReview

#: Quantities a section is worth drawing on a logarithmic colour scale.
_LOGARITHMIC_QUANTITIES = frozenset({"resistivity", "apparent_resistivity", "conductivity"})

#: Colour maps offered, and why these.
_COLORMAPS: tuple[str, ...] = ("viridis", "magma", "cividis", "seismic", "RdBu_r", "turbo")

#: Summary keys worth a column of their own, because they say what a result rests on
#: rather than what it is.
_EVIDENCE_KEYS: tuple[str, ...] = (
    "observation_count",
    "quadrupoles",
    "shots",
    "channels",
    "measurements_removed",
)


class ResultsStage(StagePanel):
    """One list of runs, whatever method produced them."""

    def __init__(self) -> None:
        super().__init__(Stage.RESULTS)

        # Label first, because it is the only column that says what a run was for.
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Run", "Started", "Method", "State", "Quality", "Run id"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setColumnHidden(5, True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._show_selected)
        self._table.cellClicked.connect(lambda *_: self._show_selected())

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setObjectName("runDetail")

        self._section = PlotPanel()
        # A three-dimensional model has to be cut before it can be looked at, and where
        # to cut it is the operator's decision rather than a default worth guessing.
        self._sliced: tuple[CellModel, str, str, bool] | None = None
        self._slice_axis = QComboBox()
        self._slice_axis.addItems(["Cut across Easting", "Cut across Northing", "Depth slice"])
        self._slice_axis.setCurrentIndex(1)
        self._slice_axis.currentIndexChanged.connect(self._draw_slice)
        self._slice_where = QSlider(Qt.Orientation.Horizontal)
        self._slice_where.setRange(0, 100)
        self._slice_where.setValue(50)
        self._slice_where.valueChanged.connect(self._draw_slice)
        self._slice_at = QLabel("")
        slice_row = QHBoxLayout()
        slice_row.addWidget(self._slice_axis)
        slice_row.addWidget(self._slice_where, 1)
        slice_row.addWidget(self._slice_at)

        # The colour scale is held still while the slider moves, and stated so it can be
        # changed.
        self._colormap = QComboBox()
        self._colormap.addItems(_COLORMAPS)
        self._colormap.currentIndexChanged.connect(self._draw_slice)
        self._colour_low = QLineEdit()
        self._colour_high = QLineEdit()
        for box in (self._colour_low, self._colour_high):
            box.setMaximumWidth(90)
            box.setValidator(QDoubleValidator())
            box.editingFinished.connect(self._draw_slice)
        reset_colours = QPushButton("Fit to model")
        reset_colours.setToolTip(
            "Set the range from the whole recovered model, so every slice is on one scale."
        )
        reset_colours.clicked.connect(self._reset_colour_limits)
        colour_row = QHBoxLayout()
        colour_row.addWidget(QLabel("Colour"))
        colour_row.addWidget(self._colormap)
        colour_row.addWidget(QLabel("from"))
        colour_row.addWidget(self._colour_low)
        colour_row.addWidget(QLabel("to"))
        colour_row.addWidget(self._colour_high)
        colour_row.addWidget(reset_colours)
        colour_row.addStretch(1)

        controls_column = QVBoxLayout()
        controls_column.setContentsMargins(0, 0, 0, 0)
        controls_column.addLayout(slice_row)
        controls_column.addLayout(colour_row)
        self._slice_controls = QWidget()
        self._slice_controls.setLayout(controls_column)
        self._slice_controls.setVisible(False)

        section_holder = QWidget()
        section_layout = QVBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.addWidget(self._slice_controls)
        from ofag.desktop.sounding_controls import SoundingControls

        self._soundings = SoundingControls(self._section)
        self._soundings.hide()
        section_layout.addWidget(self._soundings)
        section_layout.addWidget(self._section, 1)
        section_holder.setLayout(section_layout)

        self._convergence = PlotPanel()
        self._views = QTabWidget()
        self._views.addTab(section_holder, "Section")
        self._views.addTab(self._convergence, "Convergence")
        self._views.addTab(self._detail, "Summary and artifacts")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._views)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.refresh)
        resume_button = QPushButton("Resume interrupted run")
        resume_button.clicked.connect(self._resume)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self._cancel)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete)

        controls = QGridLayout()
        controls.addWidget(reload_button, 0, 0)
        controls.addWidget(resume_button, 0, 1)
        controls.addWidget(cancel_button, 0, 2)
        controls.addWidget(delete_button, 1, 0)
        compare = QPushButton("Compare")
        compare.clicked.connect(self._compare)
        choose = QPushButton("Use for this dataset")
        choose.setToolTip("Select this dataset's result; scientific audit remains separate.")
        choose.clicked.connect(self._choose)
        controls.addWidget(compare, 1, 1)
        controls.addWidget(choose, 1, 2)
        self._where = QLabel("")
        self._where.setWordWrap(True)
        controls.addWidget(self._where, 2, 0, 1, 3)

        holder = QWidget()
        inner = QVBoxLayout()
        inner.addLayout(controls)
        inner.addWidget(splitter, 1)
        holder.setLayout(inner)
        self._body.addWidget(holder, 1)

    # -- the list -----------------------------------------------------------

    def refresh(self) -> None:
        from ofag.services.result_quality import quality_summary

        session = self.session
        if session is None:
            return
        same = getattr(self, "_catalog_session", None) is session
        selected = self._selected_run_id() if same else None
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in self._table.selectionModel().selectedRows()
            if same and (item := self._table.item(index.row(), 5)) is not None
        }
        self._catalog_session = session
        records = session.runs.list_runs()
        self._table.blockSignals(True)
        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            run_id = record.spec.run_id
            summary = self._summary_of(run_id)
            cells = (
                record.spec.label or "",
                record.created_at.strftime("%Y-%m-%d %H:%M"),
                method_info(record.spec.plugin_id).name,
                str(record.state),
                quality_summary(summary),
                str(run_id),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if column == 5:
                    item.setData(Qt.ItemDataRole.UserRole, run_id)
                self._table.setItem(row, column, item)
        self._table.blockSignals(False)
        self._where.setText(str(session.folder.runs_root))
        matching = next(
            (i for i, record in enumerate(records) if record.spec.run_id == selected), None
        )
        if matching is not None:
            self._table.blockSignals(True)
            self._table.selectionModel().setCurrentIndex(
                self._table.model().index(matching, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
            self._table.clearSelection()
            for row, record in enumerate(records):
                if str(record.spec.run_id) in selected_ids:
                    self._table.selectionModel().select(
                        self._table.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select
                        | QItemSelectionModel.SelectionFlag.Rows,
                    )
            self._table.blockSignals(False)
            # Completed model plots need no redraw during progress polling.
            record = records[matching]
            self._show_selected(redraw_model=getattr(self, "_shown_state", None) != record.state)
            self._shown_state = record.state
        else:
            self._sliced = None
            self._detail.clear()
            self._section.clear("Select a run.")
            self._convergence.clear("Select a run.")

    def _summary_of(self, run_id: UUID) -> dict[str, object]:
        session = self.session
        if session is None:
            return {}
        try:
            result = session.runs.result(run_id)
        except (KeyError, ValueError, OSError):
            return {}
        return dict(result.summary) if result is not None else {}

    # -- one run ------------------------------------------------------------

    def focus_record(self, identifier: str) -> None:
        self.refresh()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 5)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == identifier:
                self._table.setCurrentCell(row, 0)
                self._table.selectRow(row)
                break

    def _choose(self) -> None:
        run_id, session = self._selected_run_id(), self.session
        if session is None or run_id is None:
            return
        try:
            ResultReview(session.runs).choose(run_id)
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Cannot select result", str(error))
            return
        self._show_selected()

    def _compare(self) -> None:
        from ofag.desktop.result_comparison import ResultComparison

        session = self.session
        if session is None:
            return
        rows = sorted({item.row() for item in self._table.selectedItems()})
        if len(rows) != 2:
            QMessageBox.information(self, "Compare results", "Select two rows using Ctrl or Shift.")
            return
        try:
            items = [self._table.item(row, 5) for row in rows]
            ids = [
                UUID(str(item.data(Qt.ItemDataRole.UserRole))) for item in items if item is not None
            ]
            records = [session.runs.get(run_id) for run_id in ids]
            results = [session.runs.result(run_id) for run_id in ids]
            if any(result is None for result in results):
                raise ValueError("Both runs need a completed result.")
            models: list[tuple[CellModel, str, str] | None] = []
            for run_id, result in zip(ids, results, strict=True):
                root = session.runs.run_dir(run_id)
                geometry = _geometry(root, result)
                values = _artifact(root, result, "recovered_model")
                if geometry is None or values is None:
                    models.append(None)
                    continue
                centres, volumes, active, widths = geometry
                model = CellModel.on_active_cells(values, centres, volumes, active, widths)
                quantity, units = _quantity_of(result, "recovered_model")
                models.append((model, quantity, units))
            meshes = [
                _mesh_cells(session.runs.run_dir(run_id), result)
                for run_id, result in zip(ids, results, strict=True)
            ]
            ResultComparison(records, results, models, self, meshes=meshes).exec()
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Cannot compare", str(error))

    def _selected_run_id(self) -> UUID | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 5)
        return None if item is None else UUID(str(item.data(Qt.ItemDataRole.UserRole)))

    def _show_selected(self, *, redraw_model: bool = True) -> None:
        session = self.session
        run_id = self._selected_run_id()
        if session is None or run_id is None:
            return
        record = session.runs.get(run_id)
        session.selected_run_id = run_id
        self._shown_state = record.state
        lines: list[str] = [
            f"Run {run_id}",
            f"Execution: {record.state.value}",
            f"Folder: {session.folder.runs_root / str(run_id)}",
            "",
        ]
        events = session.runs.events(run_id)
        if events:
            latest = events[-1]
            lines.append(
                f"Latest progress: {latest.stage or latest.event_type}; "
                f"iteration {latest.iteration}; {latest.message or ''}"
            )
        if record.error:
            lines.append(f"Run error: {record.error}")
        try:
            review = ResultReview(session.runs)
            lines += [
                f"Scientific review: {review.audit_status(run_id)}",
                f"Selected for this dataset: {'yes' if review.preferred(run_id) else 'no'}",
                "",
            ]
        except (OSError, ValueError, KeyError) as error:
            lines.append(f"Review status unavailable: {error}")
        result = None
        try:
            result = session.runs.result(run_id)
        except (KeyError, ValueError, OSError) as error:
            lines.append(f"Could not be read: {error}")
        if redraw_model or record.state not in (
            RunState.SUCCEEDED,
            RunState.FAILED,
            RunState.CANCELLED,
        ):
            self._draw_convergence(session, run_id)
        if result is None:
            # A run that has not finished, or one whose result file is not there yet:
            # the folder above is still worth showing, because that is where the
            # progress and the checkpoint are being written.
            lines.append("No result yet.")
            self._detail.setPlainText("\n".join(lines))
            self._section.clear("No result yet.")
            return
        if redraw_model:
            self._draw_section(session, run_id, result, self._method_of_selected_row())
        lines.append("Summary")
        for key, value in result.summary.items():
            lines.append(f"  {key.replace('_', ' ')}: {value}")
        lines.append("")
        lines.append("Artifacts")
        for artifact in result.artifacts:
            stage = f" [{artifact.stage}]" if artifact.stage else ""
            lines.append(
                f"  {artifact.artifact_type}{stage}: {artifact.relative_path} "
                f"({artifact.physical_quantity}, {artifact.units})"
            )
        self._detail.setPlainText("\n".join(lines))

    # -- what the run produced, drawn ----------------------------------------

    def _draw_section(self, session: Any, run_id: UUID, result: Any, method: str) -> None:
        """The recovered model on the mesh it was solved on."""
        self._soundings.hide()
        run_dir = session.runs.run_dir(run_id)
        values = _artifact(run_dir, result, "recovered_model")
        geometry = _geometry(run_dir, result)
        if (geometry is None or values is None) and self._draw_layered(
            session, run_id, run_dir, method
        ):
            return
        if geometry is None or values is None:
            self._slice_controls.setVisible(False)
            self._section.clear(
                "This run published no cell centres and a recovered model, so there is no "
                "section to draw. Its artifacts are listed under Summary and artifacts."
            )
            return
        centres, volumes, active, widths = geometry
        try:
            model = CellModel.on_active_cells(values, centres, volumes, active, widths)
        except ValueError as error:
            self._slice_controls.setVisible(False)
            self._section.clear(str(error))
            return
        quantity, units = _quantity_of(result, "recovered_model")
        title = f"{quantity.replace('_', ' ')} recovered by {method}"
        logarithmic = quantity in _LOGARITHMIC_QUANTITIES

        # A two-dimensional pyGIMLi mesh lives in the Easting-Elevation plane and leaves
        # the third column at zero, so there is nothing to cut.
        mesh = _mesh_cells(run_dir, result)
        if (
            float(np.ptp(model.centres[:, 2])) == 0.0
            and mesh is not None
            and mesh[1].shape[0] == np.asarray(values).shape[0]
        ):
            # Drawn as pyGIMLi draws it: the cells as the polygons they are, faded where
            # the data did not reach, electrodes on the surface.
            self._slice_controls.setVisible(False)
            coverage = _artifact(run_dir, result, "model_coverage")
            self._section.mesh_section(
                mesh[0],
                mesh[1],
                np.asarray(values, dtype=float),
                title=title,
                colour_label=_unit_label(quantity, units),
                logarithmic=logarithmic,
                coverage=coverage,
                electrodes=_electrodes(session, run_id),
            )
            return
        if float(np.ptp(model.centres[:, 2])) == 0.0:
            self._slice_controls.setVisible(False)
            extents = model.widths_or_cubes
            self._section.cell_section(
                model.centres[:, 0],
                model.centres[:, 1],
                extents[:, 0],
                extents[:, 1],
                model.values,
                title=title,
                colour_label=units,
                logarithmic=logarithmic,
            )
            return

        self._slice_controls.setVisible(True)
        self._sliced = (model, title, units, logarithmic)
        self._reset_colour_limits()

    def _draw_layered(self, session: Any, run_id: UUID, run_dir: Any, method: str) -> bool:
        """Runs whose model is layers, not cells: batches, one sounding, a 2D MT section."""
        stitched = run_dir / "stitched_conductivity_section.npz"
        if stitched.is_file():
            self._slice_controls.hide()
            self._soundings.load(stitched, method)
            self._soundings.show()
            return True
        section = run_dir / "conductivity_section.npz"
        if section.is_file():
            with np.load(section, allow_pickle=False) as data:
                active = (
                    data["active_cells"].astype(bool)
                    if "active_cells" in data.files
                    else slice(None)
                )
                centres = np.asarray(data["cell_centers_m"])[active]
                widths = np.asarray(data["cell_widths_m"])[active]
                sigma = np.asarray(data["conductivity_s_m"])[active]
            with np.errstate(divide="ignore"):
                rho = np.where(sigma > 0, 1.0 / sigma, np.nan)
            self._slice_controls.setVisible(False)
            self._section.cell_section(
                centres[:, 0],
                centres[:, 1],
                widths[:, 0],
                widths[:, 1],
                rho,
                title=f"resistivity recovered by {method}",
                colour_label="ohm*m",
                logarithmic=True,
            )
            return True
        model = run_dir / "recovered_conductivity_s_m.npy"
        tops = run_dir / "layer_top_depth_m.npy"
        if model.is_file() and tops.is_file():
            observed = next(run_dir.glob("observed_*.npy"), None)
            predicted = next(run_dir.glob("predicted_*.npy"), None)
            times = None
            try:
                system = (session.runs.get(run_id).spec.physics or {}).get("system") or {}
                times = (system.get("times") or {}).get("value")
            except (AttributeError, KeyError, TypeError):
                times = None
            self._slice_controls.setVisible(False)
            self._section.sounding_1d(
                np.load(tops),
                np.load(model),
                title=method,
                times=times,
                observed=np.load(observed) if observed is not None and times is not None else None,
                predicted=np.load(predicted)
                if predicted is not None and times is not None
                else None,
            )
            return True
        return False

    def _reset_colour_limits(self) -> None:
        """Take the colour range from the whole model, then redraw."""
        if self._sliced is None:
            return
        finite = self._sliced[0].values[np.isfinite(self._sliced[0].values)]
        if finite.size:
            self._colour_low.setText(f"{float(finite.min()):.4g}")
            self._colour_high.setText(f"{float(finite.max()):.4g}")
        self._draw_slice()

    def _colour_limits(self) -> tuple[float, float] | None:
        """The range the boxes ask for, or None while they do not make one."""
        try:
            low = float(self._colour_low.text())
            high = float(self._colour_high.text())
        except ValueError:
            return None
        return (low, high) if high > low else None

    def _draw_slice(self) -> None:
        """One plane of a three-dimensional model, at the position asked for."""
        if self._sliced is None:
            return
        model, title, units, logarithmic = self._sliced
        axis = self._slice_axis.currentIndex()
        remaining = [index for index in (0, 1, 2) if index != axis]

        # Step the slider through model planes.
        planes = model.planes(axis)
        index = int(round(self._slice_where.value() / 100.0 * (len(planes) - 1)))
        position = float(planes[index])
        inside = model.slice_at(axis, position)

        names = ("Easting", "Northing", "Elevation")
        self._slice_at.setText(
            f"{names[axis]} {position:,.0f} m  "
            f"(plane {index + 1} of {len(planes)}, {int(inside.sum()):,} cells)"
        )
        if not inside.any():
            self._section.clear("No cells at this position.")
            return
        extents = model.widths_or_cubes
        self._section.cell_section(
            model.centres[inside, remaining[0]],
            model.centres[inside, remaining[1]],
            extents[inside, remaining[0]],
            extents[inside, remaining[1]],
            model.values[inside],
            title=f"{title}\n{names[axis]} {position:,.0f} m",
            x_label=f"{names[remaining[0]]} (m)",
            y_label=f"{names[remaining[1]]} (m)",
            colour_label=units,
            logarithmic=logarithmic,
            limits=_refined_limits(model, remaining),
            # A depth slice is a map: both axes are horizontal distance, so a circular
            # body has to come out circular.
            equal_aspect=axis == 2,
            colour_limits=self._colour_limits(),
            colormap=self._colormap.currentText(),
        )

    def _draw_convergence(self, session: Any, run_id: UUID) -> None:
        """Misfit against iteration, from whatever the plugin reported."""
        history: dict[str, list[tuple[int, float]]] = {}
        for event in session.runs.events(run_id):
            if event.iteration is None:
                continue
            for name, value in (event.misfits or {}).items():
                if isinstance(value, int | float) and np.isfinite(value):
                    history.setdefault(name, []).append((event.iteration, float(value)))
        if not history:
            self._convergence.clear("This run reported no misfit per iteration.")
            return
        name, series = max(history.items(), key=lambda item: len(item[1]))
        series.sort()
        positive = all(value > 0 for _, value in series)
        self._convergence.curve(
            [iteration for iteration, _ in series],
            [value for _, value in series],
            title=f"{name.replace('_', ' ')} by iteration",
            x_label="Iteration",
            y_label=name.replace("_", " "),
            logarithmic_y=positive,
        )

    def _method_of_selected_row(self) -> str:
        item = self._table.item(self._table.currentRow(), 2)
        return "" if item is None else item.text()

    def _resume(self) -> None:
        session = self.session
        run_id = self._selected_run_id()
        if session is None or run_id is None:
            return
        try:
            session.runs.resume(run_id)
        except (KeyError, ValueError) as error:
            QMessageBox.warning(self, "Cannot resume", str(error))
            return
        self.refresh()

    def _cancel(self) -> None:
        session = self.session
        run_id = self._selected_run_id()
        if session is None or run_id is None:
            return
        try:
            session.runs.cancel(run_id)
        except (KeyError, ValueError) as error:
            QMessageBox.warning(self, "Cannot cancel", str(error))
            return
        self.refresh()

    def _delete(self) -> None:
        session = self.session
        run_id = self._selected_run_id()
        if session is None or run_id is None:
            return
        run_dir = session.folder.runs_root / str(run_id)
        # The folder is named, and so is what it holds, because a run is the only record
        # of an inversion that has been paid for and this cannot be undone.
        label = self._table.item(self._table.currentRow(), 0)
        described = f"'{label.text()}'" if label is not None and label.text() else str(run_id)
        confirmed = QMessageBox.question(
            self,
            "Delete this run?",
            f"Delete run {described} and everything it wrote?\n\n"
            f"{run_dir}\n\n"
            "The recovered model, the predicted data and the log all go with it. "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirmed is not QMessageBox.StandardButton.Yes:
            return
        try:
            session.runs.delete(run_id)
        except (KeyError, ValueError, OSError) as error:
            QMessageBox.warning(self, "Cannot delete", str(error))
            return
        self.refresh()


def _artifact(run_dir: Any, result: Any, artifact_type: str) -> np.ndarray | None:
    """One named array from a run's folder, or None if it is not readable."""
    for artifact in result.artifacts:
        if artifact.artifact_type != artifact_type:
            continue
        path = run_dir / str(artifact.relative_path).split("/")[-1]
        try:
            loaded = np.load(path, allow_pickle=False)
        except (OSError, ValueError):
            return None
        return np.asarray(loaded, dtype=float).ravel()
    return None


def _mesh_cells(run_dir: Any, result: Any) -> tuple[np.ndarray, np.ndarray] | None:
    """A two-dimensional mesh's nodes and each cell's node indices, if the run saved them."""
    for artifact in result.artifacts:
        if artifact.artifact_type != "mesh_geometry":
            continue
        path = run_dir / str(artifact.relative_path).split("/")[-1]
        try:
            with np.load(path, allow_pickle=False) as stored:
                if "nodes_m" not in stored.files or "cell_nodes" not in stored.files:
                    return None
                return np.asarray(stored["nodes_m"]), np.asarray(stored["cell_nodes"])
        except (OSError, ValueError):
            return None
    return None


def _electrodes(session: Any, run_id: UUID) -> np.ndarray | None:
    """The electrode positions a resistivity run was made with, from its own spec."""
    try:
        spec = session.runs.get(run_id).spec
        array = (spec.physics or {}).get("array") or {}
        path = array.get("electrodes_path")
        return np.asarray(np.load(path, allow_pickle=False), dtype=float) if path else None
    except (AttributeError, KeyError, OSError, ValueError, TypeError):
        return None


def _unit_label(quantity: str, units: str) -> str:
    """"Resistivity (ohm*m)": the property and its unit, as a colour bar reads."""
    name = quantity.replace("_", " ").capitalize()
    return f"{name} ({units})" if units else name


def _geometry(
    run_dir: Any, result: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None] | None:
    """Cell centres, volumes and the active-cell mask from a run's own artifact."""
    for artifact in result.artifacts:
        if artifact.artifact_type != "mesh_geometry":
            continue
        path = run_dir / str(artifact.relative_path).split("/")[-1]
        try:
            with np.load(path, allow_pickle=False) as archive:
                if "cell_centers_m" not in archive:
                    return None
                centres = np.asarray(archive["cell_centers_m"], dtype=float)
                volumes = (
                    np.asarray(archive["cell_volumes_m3"], dtype=float)
                    if "cell_volumes_m3" in archive
                    else np.ones(len(centres))
                )
                active = (
                    np.asarray(archive["active_cells"], dtype=bool)
                    if "active_cells" in archive
                    else np.ones(len(centres), dtype=bool)
                )
                widths = (
                    np.asarray(archive["cell_widths_m"], dtype=float)
                    if "cell_widths_m" in archive
                    else None
                )
        except (OSError, ValueError):
            return None
        return centres, volumes, active, widths
    return None


def _refined_limits(
    model: CellModel, axes: list[int]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The frame every slice along one axis is drawn in."""
    shown = model.refined()
    if not shown.any():
        return None
    extents = model.widths_or_cubes
    spans = []
    for axis in axes:
        low = float((model.centres[shown, axis] - extents[shown, axis] / 2.0).min())
        high = float((model.centres[shown, axis] + extents[shown, axis] / 2.0).max())
        margin = 0.02 * (high - low)
        spans.append((low - margin, high + margin))
    return spans[0], spans[1]


def _quantity_of(result: Any, artifact_type: str) -> tuple[str, str]:
    for artifact in result.artifacts:
        if artifact.artifact_type == artifact_type:
            return str(artifact.physical_quantity), str(artifact.units)
    return artifact_type, ""


def _evidence(summary: dict[str, object]) -> str:
    """How much data a result rests on, in one cell."""
    parts = [f"{key.replace('_', ' ')} {summary[key]}" for key in _EVIDENCE_KEYS if key in summary]
    return ", ".join(parts)
