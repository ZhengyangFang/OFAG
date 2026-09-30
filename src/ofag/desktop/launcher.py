"""Choosing or creating the project to work on."""

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ofag.core.constants import ProjectMethod
from ofag.core.schemas import CoordinateConvention, ProjectCreateRequest
from ofag.services.project_folder import folder_name_for
from ofag.services.project_service import ProjectService


class ProjectLauncher(QDialog):
    """Open one of the projects under the result root, or start a new one."""

    def __init__(self, projects: ProjectService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Projects")
        self.resize(760, 520)
        self._projects = projects
        self.chosen: UUID | None = None

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._open_selected())
        self._reload()

        open_button = QPushButton("Open")
        open_button.clicked.connect(self._open_selected)
        export_button = QPushButton("Export portable copy…")
        export_button.clicked.connect(self._export_selected)

        existing = QVBoxLayout()
        existing.addWidget(QLabel(f"Projects under {projects.result_root.resolve()}"))
        existing.addWidget(self._list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(export_button)
        row.addWidget(open_button)
        existing.addLayout(row)
        left = QGroupBox("Open an existing project")
        left.setLayout(existing)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Soda Lake geothermal")
        self._name.textChanged.connect(self._preview_folder)
        self._crs = QLineEdit()
        self._crs.setPlaceholderText("EPSG:32109")
        self._crs.setToolTip(
            "Stated, never inferred. Every coordinate in this project is read "
            "and written in this system."
        )
        self._elevation = QComboBox()
        self._elevation.setEditable(True)
        self._elevation.addItems(["ellipsoidal", "NAVD88", "EGM2008", "local datum"])
        self._folder_preview = QLabel("")
        self._folder_preview.setObjectName("folderPreview")

        self._methods: dict[ProjectMethod, QCheckBox] = {}
        methods_layout = QVBoxLayout()
        for method in ProjectMethod:
            box = QCheckBox(method.value)
            self._methods[method] = box
            methods_layout.addWidget(box)
        methods = QGroupBox("Methods this project uses")
        methods.setLayout(methods_layout)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Coordinate system", self._crs)
        form.addRow("Elevation reference", self._elevation)
        form.addRow("Folder", self._folder_preview)
        create_button = QPushButton("Create project")
        create_button.clicked.connect(self._create)

        new = QVBoxLayout()
        new.addLayout(form)
        new.addWidget(methods)
        new.addStretch(1)
        new.addWidget(create_button)
        right = QGroupBox("Start a new project")
        right.setLayout(new)

        columns = QHBoxLayout()
        columns.addWidget(left, 1)
        columns.addWidget(right, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(columns, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self._preview_folder()

    # -- existing projects --------------------------------------------------

    def _reload(self) -> None:
        self._list.clear()
        for record in self._projects.list():
            folder = self._projects.folder(record.project_id)
            item = QListWidgetItem(f"{record.name}\n{folder.root}")
            item.setData(Qt.ItemDataRole.UserRole, record.project_id)
            self._list.addItem(item)

    def _open_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.information(self, "OFAG", "Select a project, or create one.")
            return
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _export_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.information(self, "OFAG", "Select a project to export.")
            return
        destination = QFileDialog.getExistingDirectory(
            self, "Choose the recipient folder", str(Path.home())
        )
        if not destination:
            return
        try:
            path = self._projects.export_portable(
                item.data(Qt.ItemDataRole.UserRole), Path(destination)
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Export failed", str(error))
            return
        QMessageBox.information(self, "Portable copy ready", str(path))

    # -- a new project ------------------------------------------------------

    def _preview_folder(self) -> None:
        """Show the directory before it is made, because it is named and kept."""
        name = self._name.text().strip()
        if not name:
            self._folder_preview.setText("")
            return
        root = self._projects.result_root
        self._folder_preview.setText(str((root / folder_name_for(name)).resolve()))

    def _create(self) -> None:
        name = self._name.text().strip()
        crs = self._crs.text().strip()
        if not name:
            QMessageBox.warning(self, "OFAG", "A project needs a name.")
            return
        if not crs:
            QMessageBox.warning(
                self,
                "OFAG",
                "A project needs a coordinate system. It is never guessed from "
                "the first file imported, because a wrong one is invisible "
                "until the section is in the wrong place.",
            )
            return
        enabled = tuple(method for method, box in self._methods.items() if box.isChecked())
        if not enabled:
            QMessageBox.warning(self, "OFAG", "Choose at least one method.")
            return
        try:
            record = self._projects.create(
                ProjectCreateRequest(
                    name=name,
                    coordinate_convention=CoordinateConvention(crs=crs),
                    elevation_reference=self._elevation.currentText().strip() or "ellipsoidal",
                    enabled_methods=enabled,
                )
            )
        except (ValueError, OSError) as error:
            QMessageBox.critical(self, "OFAG", str(error))
            return
        self.chosen = record.project_id
        self.accept()
