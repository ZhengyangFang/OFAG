"""An open project, and the services rooted in its folder."""

from dataclasses import dataclass
from functools import cached_property
from uuid import UUID

from PySide6.QtCore import QObject, Signal

from ofag.core.schemas import ProjectRecord, ProjectWorkspace, ProjectWorkspaceUpdate
from ofag.services.comparison_service import ComparisonService
from ofag.services.data_import import DataImportService
from ofag.services.ert_import import ERTFieldImportService
from ofag.services.geology_service import GeologyService
from ofag.services.model_import import ExternalModelImportService
from ofag.services.mt_import import MtImportService
from ofag.services.project_folder import ProjectFolder
from ofag.services.project_service import ProjectService
from ofag.services.run_service import RunService
from ofag.services.segy_import import SegyImportService
from ofag.services.seismic_prepare import SeismicPrepareService


class ProjectEvents(QObject):
    """GUI-thread notifications; services remain independent of Qt."""

    changed = Signal(str)
    navigate = Signal(str)
    focus_requested = Signal(str, str)


@dataclass
class Session:
    """The open project and everything that reads or writes inside it."""

    projects: ProjectService
    record: ProjectRecord
    folder: ProjectFolder
    selected_dataset_id: UUID | None = None
    selected_run_id: UUID | None = None
    active_stage: str = "data"

    @cached_property
    def events(self) -> ProjectEvents:
        return ProjectEvents()

    @classmethod
    def open(cls, projects: ProjectService, project_id: UUID) -> "Session":
        return cls(
            projects=projects,
            record=projects.get(project_id),
            folder=projects.folder(project_id),
        )

    # -- services, each rooted in this project's own folder -----------------

    @cached_property
    def runs(self) -> RunService:
        return RunService(artifact_root=self.folder.runs_root)

    @cached_property
    def imports(self) -> DataImportService:
        return DataImportService(import_root=self.folder.imports_root)

    @cached_property
    def ert_imports(self) -> ERTFieldImportService:
        return ERTFieldImportService(import_root=self.folder.imports_root)

    @cached_property
    def mt_imports(self) -> MtImportService:
        return MtImportService(import_root=self.folder.imports_root)

    @cached_property
    def segy_imports(self) -> SegyImportService:
        return SegyImportService(import_root=self.folder.imports_root)

    @cached_property
    def seismic(self) -> SeismicPrepareService:
        return SeismicPrepareService(import_root=self.folder.imports_root)

    @cached_property
    def external_models(self) -> ExternalModelImportService:
        # Takes no root: it writes into a run directory `RunService` hands it, because
        # the run layout belongs to the service that owns runs.
        return ExternalModelImportService()

    @cached_property
    def geology(self) -> GeologyService:
        return GeologyService()

    @cached_property
    def comparisons(self) -> ComparisonService:
        return ComparisonService(self.runs)

    # -- the workspace, which every stage reads and several write -----------

    def workspace(self) -> ProjectWorkspace:
        return self.projects.workspace(self.record.project_id)

    def save_workspace(self, workspace: ProjectWorkspace) -> ProjectWorkspace:
        """Persist the workspace, keeping only what the update is allowed to say."""
        stored = workspace.model_dump()
        payload = {
            name: stored[name] for name in ProjectWorkspaceUpdate.model_fields if name in stored
        }
        updated = self.projects.update_workspace(
            self.record.project_id, ProjectWorkspaceUpdate.model_validate(payload)
        )
        self.events.changed.emit("workspace")
        return updated

    def reload(self) -> None:
        self.record = self.projects.get(self.record.project_id)
