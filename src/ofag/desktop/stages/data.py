"""What the project holds, and how something gets into it."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ofag.core.schemas import DatasetKind
from ofag.desktop.dialogs.importers import ImportDialog
from ofag.desktop.navigation import Stage
from ofag.desktop.stages.base import StagePanel

#: Which importer reads which kind, and what to say while choosing a file.
_FILE_FILTERS: dict[DatasetKind, str] = {
    DatasetKind.GRAVITY: "Comma-separated values (*.csv);;All files (*)",
    DatasetKind.MAGNETICS: "Comma-separated values (*.csv);;All files (*)",
    DatasetKind.AEM: "Comma-separated values (*.csv);;All files (*)",
    DatasetKind.MT: "EDI directory",
    DatasetKind.TOPOGRAPHY: "Comma-separated values (*.csv);;All files (*)",
    DatasetKind.ERT: "Resistivity data (*.ohm *.dat *.stg *.bin *.txt);;All files (*)",
    DatasetKind.SEISMIC: "SEG-Y (*.sgy *.segy *.SGY *.SEGY);;All files (*)",
}


class DataStage(StagePanel):
    """One catalogue for every survey the project holds."""

    def __init__(self) -> None:
        super().__init__(Stage.DATA)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Kind", "Source file", "Imported", "Dataset id"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnHidden(4, True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self._kind = QComboBox()
        for kind in DatasetKind:
            self._kind.addItem(kind.value, kind)
        import_button = QPushButton("Import a survey…")
        import_button.clicked.connect(self._import)
        remove_button = QPushButton("Remove from project")
        remove_button.clicked.connect(self._remove)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Kind"))
        controls.addWidget(self._kind)
        controls.addWidget(import_button)
        controls.addStretch(1)
        controls.addWidget(remove_button)

        self._count = QLabel("")
        self._body.addLayout(controls)
        self._body.addWidget(self._table, 1)
        self._body.addWidget(self._count)

    # -- reading the register ----------------------------------------------

    def refresh(self) -> None:
        session = self.session
        if session is None:
            return
        datasets = session.workspace().datasets
        self._table.setRowCount(len(datasets))
        for row, dataset in enumerate(datasets):
            for column, text in enumerate(
                (
                    dataset.name,
                    dataset.kind.value,
                    dataset.source_filename,
                    dataset.imported_at.strftime("%Y-%m-%d %H:%M"),
                    str(dataset.dataset_id),
                )
            ):
                item = QTableWidgetItem(text)
                if column == 4:
                    item.setData(Qt.ItemDataRole.UserRole, dataset.dataset_id)
                self._table.setItem(row, column, item)
        self._count.setText(
            f"{len(datasets)} dataset{'' if len(datasets) == 1 else 's'} in "
            f"{session.folder.imports_root}"
        )

    # -- bringing one in ----------------------------------------------------

    def focus_record(self, identifier: str) -> None:
        self.refresh()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 4)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == identifier:
                self._table.setCurrentCell(row, 0)
                self._table.selectRow(row)
                break

    def _import(self) -> None:
        session = self.session
        if session is None:
            return
        # Rebuilt from the value rather than taken as stored.
        kind = DatasetKind(self._kind.currentData())
        if kind is DatasetKind.MT:
            path_text = QFileDialog.getExistingDirectory(
                self, "Import MT EDI directory", str(Path.home())
            )
        else:
            path_text, _ = QFileDialog.getOpenFileName(
                self, f"Import {kind.value}", str(Path.home()), _FILE_FILTERS[kind]
            )
        if not path_text:
            return
        dialog = ImportDialog(kind, Path(path_text), self)
        if not dialog.exec():
            return
        try:
            payload = dialog.run(session)
        except (ValueError, OSError, KeyError) as error:
            QMessageBox.critical(self, "Import failed", str(error))
            return

        session.projects.register_dataset(
            session.record.project_id,
            kind=kind,
            name=dialog.dataset_name(),
            source_filename=Path(path_text).name,
            imported=payload,
        )
        self.refresh()
        session.events.changed.emit("workspace")

    def _remove(self) -> None:
        session = self.session
        row = self._table.currentRow()
        if session is None or row < 0:
            return
        item = self._table.item(row, 4)
        if item is None:
            return
        dataset_id = item.data(Qt.ItemDataRole.UserRole)
        workspace = session.workspace()
        remaining = tuple(
            dataset for dataset in workspace.datasets if dataset.dataset_id != dataset_id
        )
        # The canonical copy under imports/ is left where it is: a run that used it
        # still points at it, and removing a row from a register is not a decision to
        # delete the data a section was built from.
        session.save_workspace(workspace.model_copy(update={"datasets": remaining}))
        self.refresh()
