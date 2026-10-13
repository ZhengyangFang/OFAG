"""The OFAG HTTP API, deliberately thin over application services."""

import hmac
import os
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5

import numpy as np
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    CsvPreview,
    CsvPreviewRequest,
    DatasetKind,
    DatasetSpec,
    GeologicalSection,
    GeologicalSectionRequest,
    GravityCsvImportRequest,
    ImportedGravityDataset,
    ImportedMagneticDataset,
    ImportedTDEMDataset,
    ImportedTopographyDataset,
    MagneticCsvImportRequest,
    ModelPointCloud,
    ModelSlice,
    NumericArtifactSeries,
    ParameterSensitivity,
    PreparedReferenceRun,
    ProjectCreateRequest,
    ProjectMethodsUpdate,
    ProjectRecord,
    ProjectWorkspace,
    ProjectWorkspaceUpdate,
    PropertyDistribution,
    ResourceEstimate,
    RunCheckpoint,
    RunComparison,
    RunComparisonRequest,
    RunEvent,
    RunRecord,
    RunResult,
    RunSpec,
    RunState,
    TDEMBatchSection,
    TDEMBatchSoundingResult,
    TDEMCsvImportRequest,
    TopographyCsvImportRequest,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.execution.state import transition
from ofag.reference_data import (
    SIMPEG_CROSS_GRADIENT,
    fetch_reference_dataset,
    prepare_cross_gradient_gravity_run,
)
from ofag.services.comparison_service import ComparisonService
from ofag.services.data_import import DataImportService
from ofag.services.ert_import import (
    SUPPORTED_INSTRUMENTS,
    ERTFieldImportRequest,
    ERTFieldImportService,
)
from ofag.services.geology_service import GeologyService
from ofag.services.line_data_import import (
    LayeredLineImportRequest,
    LayeredLineImportService,
    LayeredLineInventory,
    LayeredLineInventoryRequest,
)
from ofag.services.model_import import (
    ExternalModelImportRequest,
    ExternalModelImportService,
)
from ofag.services.mt_import import MtImportRequest, MtImportService
from ofag.services.project_folder import folders_in
from ofag.services.project_service import ProjectService
from ofag.services.run_service import RunService
from ofag.services.run_start_policy import RunStartPolicy
from ofag.services.segy_import import SegyImportRequest, SegyImportService
from ofag.services.seismic_prepare import (
    SegyExtractRequest,
    SeismicPrepareService,
    StartingModelRequest,
)

MAX_POINT_CLOUD_CELLS = 2_000_000

#: An unstructured section is drawn cell by cell in the browser, so it is capped well
#: below the point-cloud limit.
MAX_ERT_SECTION_CELLS = 200_000

#: Enough resolution to place a unit boundary by eye, and a bounded response whatever
#: the model's cell count.
MAX_DISTRIBUTION_BINS = 256

# Matches `ModelSlice.normal`; x is Easting, y is Northing, z is Elevation.
SliceNormal = Literal["x", "y", "z"]


def _environment() -> str:
    return os.getenv("OFAG_ENV", "development").lower()


def _auth_dependency() -> Callable[..., None]:
    environment = _environment()
    expected_token = os.getenv("OFAG_API_TOKEN")

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if environment != "production":
            return
        if not expected_token:
            raise HTTPException(
                status_code=503, detail="production API authentication is not configured"
            )
        expected = f"Bearer {expected_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    return require_token


def create_app(
    service: RunService | None = None,
    project_service: ProjectService | None = None,
) -> FastAPI:
    environment = _environment()
    app = FastAPI(
        title="OFAG API",
        version="0.1.0",
        docs_url=None if environment == "production" else "/docs",
        redoc_url=None if environment == "production" else "/redoc",
        openapi_url=None if environment == "production" else "/openapi.json",
    )
    allowed_hosts = ["localhost", "127.0.0.1"]
    if environment == "production":
        allowed_hosts.extend(
            host.strip() for host in os.getenv("OFAG_ALLOWED_HOSTS", "").split(",") if host.strip()
        )
    else:
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    run_service = service or RunService()
    # An injected run root should not mix its isolated runs with projects from the
    # process working directory.
    projects = project_service or ProjectService(run_service.artifact_root.parent / "Result")
    data_import_service = DataImportService()
    ert_import_service = ERTFieldImportService()
    geology_service = GeologyService()
    model_import_service = ExternalModelImportService()
    segy_import_service = SegyImportService()
    seismic_prepare_service = SeismicPrepareService()
    line_data_service = LayeredLineImportService()
    require_token = _auth_dependency()
    project_runs: dict[UUID, RunService] = {}

    def service_for_project(project_id: UUID | None) -> RunService:
        if project_id is None:
            return run_service
        try:
            folder = projects.folder(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if project_id not in project_runs:
            project_runs[project_id] = RunService(artifact_root=folder.runs_root)
        return project_runs[project_id]

    def service_for_run(run_id: UUID) -> RunService:
        for folder in folders_in(projects.result_root):
            if (folder.runs_root / str(run_id) / "run_record.json").is_file():
                try:
                    record = ProjectRecord.model_validate_json(
                        folder.record_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    continue
                return service_for_project(record.project_id)
        return run_service

    def import_root_for(project_id: UUID | None) -> Path | None:
        if project_id is None:
            return None
        try:
            return projects.folder(project_id).imports_root
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    def data_importer_for(project_id: UUID | None) -> DataImportService:
        root = import_root_for(project_id)
        return DataImportService(import_root=root) if root else data_import_service

    workspace_lock = threading.Lock()

    def register_import(
        project_id: UUID | None,
        kind: DatasetKind,
        name: str,
        filename: str,
        imported: Any,
    ) -> None:
        if project_id is None:
            return
        # Read, append and write back under a lock.
        with workspace_lock:
            _register_import_locked(project_id, kind, name, filename, imported)

    def _register_import_locked(
        project_id: UUID,
        kind: DatasetKind,
        name: str,
        filename: str,
        imported: Any,
    ) -> None:
        projects.register_dataset(
            project_id, kind=kind, name=name, source_filename=filename, imported=imported
        )

    @app.get("/health", response_model=dict[str, str])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": environment}

    @app.get("/plugins", dependencies=[Depends(require_token)])
    def plugins() -> tuple[CapabilityManifest, ...]:
        return run_service.list_plugins()

    @app.get(
        "/projects",
        response_model=tuple[ProjectRecord, ...],
        dependencies=[Depends(require_token)],
    )
    def list_projects() -> tuple[ProjectRecord, ...]:
        return projects.list()

    @app.post(
        "/projects",
        response_model=ProjectRecord,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def create_project(request: ProjectCreateRequest) -> ProjectRecord:
        return projects.create(request)

    @app.get(
        "/projects/{project_id}",
        response_model=ProjectRecord,
        dependencies=[Depends(require_token)],
    )
    def get_project(project_id: UUID) -> ProjectRecord:
        try:
            return projects.get(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.put(
        "/projects/{project_id}/methods",
        response_model=ProjectRecord,
        dependencies=[Depends(require_token)],
    )
    def update_project_methods(project_id: UUID, update: ProjectMethodsUpdate) -> ProjectRecord:
        try:
            return projects.update_methods(project_id, update)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/projects/{project_id}/workspace",
        response_model=ProjectWorkspace,
        dependencies=[Depends(require_token)],
    )
    def get_project_workspace(project_id: UUID) -> ProjectWorkspace:
        try:
            return projects.workspace(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.put(
        "/projects/{project_id}/workspace",
        response_model=ProjectWorkspace,
        dependencies=[Depends(require_token)],
    )
    def update_project_workspace(
        project_id: UUID, update: ProjectWorkspaceUpdate
    ) -> ProjectWorkspace:
        try:
            return projects.update_workspace(project_id, update)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/reference-data/simpeg-cross-gradient/gravity-profile",
        response_model=PreparedReferenceRun,
        dependencies=[Depends(require_token)],
    )
    def prepare_official_gravity_profile() -> PreparedReferenceRun:
        """Prepare a gravity-only profile derived from SimPEG's joint tutorial data."""
        try:
            cache_root = Path("data/reference-cache")
            fetch_reference_dataset(SIMPEG_CROSS_GRADIENT.dataset_id, cache_root)
            prepared = prepare_cross_gradient_gravity_run(cache_root)
            payload = yaml.safe_load(Path(prepared.run_spec_path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("prepared gravity RunSpec is not a YAML object")
            return PreparedReferenceRun(
                dataset_id=prepared.dataset_id,
                source_url=SIMPEG_CROSS_GRADIENT.source_url,
                observations_path=prepared.observations_path,
                topography_path=prepared.topography_path,
                observation_count=prepared.observation_count,
                run_spec=RunSpec.model_validate(payload),
            )
        except (OSError, ValueError, yaml.YAMLError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/datasets/validate",
        response_model=ValidationReport,
        dependencies=[Depends(require_token)],
    )
    def validate_dataset(dataset: DatasetSpec) -> ValidationReport:
        return ValidationReport(valid=True)

    @app.post(
        "/datasets/gravity-csv",
        response_model=ImportedGravityDataset,
        dependencies=[Depends(require_token)],
    )
    def import_gravity_csv(
        request: GravityCsvImportRequest, project_id: UUID | None = None
    ) -> ImportedGravityDataset:
        try:
            imported = data_importer_for(project_id).import_gravity_csv(request)
            register_import(
                project_id, DatasetKind.GRAVITY, request.filename, request.filename, imported
            )
            return imported
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/datasets/magnetic-csv",
        response_model=ImportedMagneticDataset,
        dependencies=[Depends(require_token)],
    )
    def import_magnetic_csv(
        request: MagneticCsvImportRequest, project_id: UUID | None = None
    ) -> ImportedMagneticDataset:
        try:
            imported = data_importer_for(project_id).import_magnetic_csv(request)
            register_import(
                project_id, DatasetKind.MAGNETICS, request.filename, request.filename, imported
            )
            return imported
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/mt-edi", dependencies=[Depends(require_token)])
    def import_mt_edi(
        request: MtImportRequest, project_id: UUID | None = None
    ) -> dict[str, object]:
        """Import EDI sites and register their canonical CSV paths in a project."""
        try:
            root = import_root_for(project_id)
            importer = MtImportService(import_root=root) if root else MtImportService()
            imported = importer.import_edi_directory(request)
            if not imported.soundings:
                raise ValueError("No MT sites passed the phase tensor screen.")
            payload = imported.catalog_payload()
            register_import(
                project_id,
                DatasetKind.MT,
                Path(request.source_directory).name,
                request.source_directory,
                payload,
            )
            return payload
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/datasets/tdem-csv",
        response_model=ImportedTDEMDataset,
        dependencies=[Depends(require_token)],
    )
    def import_tdem_csv(
        request: TDEMCsvImportRequest, project_id: UUID | None = None
    ) -> ImportedTDEMDataset:
        try:
            imported = data_importer_for(project_id).import_tdem_csv(request)
            register_import(
                project_id, DatasetKind.AEM, request.filename, request.filename, imported
            )
            return imported
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/datasets/topography-csv",
        response_model=ImportedTopographyDataset,
        dependencies=[Depends(require_token)],
    )
    def import_topography_csv(
        request: TopographyCsvImportRequest, project_id: UUID | None = None
    ) -> ImportedTopographyDataset:
        try:
            imported = data_importer_for(project_id).import_topography_csv(request)
            register_import(
                project_id,
                DatasetKind.TOPOGRAPHY,
                request.filename,
                request.filename,
                imported,
            )
            return imported
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/datasets/ert-instruments", dependencies=[Depends(require_token)])
    def ert_instruments() -> dict[str, object]:
        """The acquisition formats the importer can read, for the file picker."""
        return {
            "instruments": list(SUPPORTED_INSTRUMENTS),
            "available": ert_import_service.dependency_available(),
        }

    @app.post("/datasets/ert-field", dependencies=[Depends(require_token)])
    def import_ert_field(
        request: ERTFieldImportRequest, project_id: UUID | None = None
    ) -> dict[str, object]:
        if not ert_import_service.dependency_available():
            raise HTTPException(
                status_code=503,
                detail="resistivity field import needs `uv sync --extra ert-formats`",
            )
        try:
            root = import_root_for(project_id)
            importer = ERTFieldImportService(import_root=root) if root else ert_import_service
            imported = importer.import_field_file(request)
            register_import(
                project_id,
                DatasetKind.ERT,
                imported.source_filename,
                imported.source_filename,
                imported,
            )
            return asdict(imported)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/datasets/csv-preview",
        response_model=CsvPreview,
        dependencies=[Depends(require_token)],
    )
    def preview_csv(request: CsvPreviewRequest) -> CsvPreview:
        """Read the header and some rows of a CSV the browser never uploaded."""
        try:
            return data_import_service.preview_csv(request)
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/segy", dependencies=[Depends(require_token)])
    def import_segy(
        request: SegyImportRequest, project_id: UUID | None = None
    ) -> dict[str, object]:
        """Read a SEG-Y survey's geometry, in units the request states."""
        if not segy_import_service.dependency_available():
            raise HTTPException(
                status_code=503,
                detail="reading SEG-Y needs `uv sync --extra seismic`",
            )
        try:
            root = import_root_for(project_id)
            importer = SegyImportService(import_root=root) if root else segy_import_service
            imported = importer.import_file(request)
            register_import(
                project_id,
                DatasetKind.SEISMIC,
                request.name,
                imported.source_filename,
                imported,
            )
            return asdict(imported)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/segy/extract", dependencies=[Depends(require_token)])
    def extract_segy(
        request: SegyExtractRequest, project_id: UUID | None = None
    ) -> dict[str, object]:
        """Select shots and channels, as the arrays an inversion consumes."""
        if not seismic_prepare_service.dependency_available():
            raise HTTPException(
                status_code=503, detail="reading SEG-Y needs `uv sync --extra seismic`"
            )
        try:
            root = import_root_for(project_id)
            preparer = SeismicPrepareService(import_root=root) if root else seismic_prepare_service
            return asdict(preparer.extract(request))
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/seismic/starting-model", dependencies=[Depends(require_token)])
    def build_starting_model(
        request: StartingModelRequest, project_id: UUID | None = None
    ) -> dict[str, object]:
        """A linear-gradient starting model on the grid a run will use."""
        try:
            root = import_root_for(project_id)
            preparer = SeismicPrepareService(import_root=root) if root else seismic_prepare_service
            return asdict(preparer.starting_model(request))
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/external-model", dependencies=[Depends(require_token)])
    def import_external_model(request: ExternalModelImportRequest) -> dict[str, object]:
        """Register somebody else's inversion as a completed run."""
        if not model_import_service.dependency_available():
            raise HTTPException(
                status_code=503,
                detail="reading UBC-GIF models needs `uv sync --extra simpeg`",
            )
        run_id = uuid4()
        try:
            runs = service_for_project(request.project_id)
            spec, result, imported = model_import_service.import_model(
                request, run_id, runs.run_dir(run_id)
            )
            runs.adopt_external_result(spec, result)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return asdict(imported)

    @app.post(
        "/datasets/line-data/inventory",
        response_model=LayeredLineInventory,
        dependencies=[Depends(require_token)],
    )
    def line_data_inventory(request: LayeredLineInventoryRequest) -> LayeredLineInventory:
        """List the flight lines in a delivered layered-model file."""
        try:
            return line_data_service.inventory(request)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/datasets/line-data", dependencies=[Depends(require_token)])
    def import_line_data(request: LayeredLineImportRequest) -> dict[str, object]:
        """Register one flight line's layered models as a completed run."""
        run_id = uuid4()
        try:
            runs = service_for_project(request.project_id)
            spec, result, imported = line_data_service.import_line(
                request, run_id, runs.run_dir(run_id)
            )
            runs.adopt_external_result(spec, result)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return asdict(imported)

    @app.get("/geology/engine", dependencies=[Depends(require_token)])
    def geology_engine() -> dict[str, object]:
        """Whether structural modelling is available, for the editor to say so."""
        return {"engine": "gempy", "available": geology_service.dependency_available()}

    @app.post(
        "/geology/section",
        response_model=GeologicalSection,
        dependencies=[Depends(require_token)],
    )
    def geological_section(request: GeologicalSectionRequest) -> GeologicalSection:
        """Interpolate a geological model and read it on one vertical slice."""
        if not geology_service.dependency_available():
            raise HTTPException(
                status_code=503,
                detail="structural modelling needs `uv sync --extra gempy`",
            )
        try:
            return geology_service.section(request.model, request.section)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/runs/validate",
        response_model=ValidationReport,
        dependencies=[Depends(require_token)],
    )
    def validate_run(spec: RunSpec) -> ValidationReport:
        try:
            return service_for_project(spec.project_id).validate(spec)
        except KeyError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/runs/estimate",
        response_model=ResourceEstimate,
        dependencies=[Depends(require_token)],
    )
    def estimate_run(spec: RunSpec) -> ResourceEstimate:
        try:
            runs = service_for_project(spec.project_id)
            report = runs.validate(spec)
            if not report.valid:
                raise HTTPException(status_code=422, detail=report.model_dump(mode="json"))
            return runs.estimate_resources(spec)
        except KeyError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/runs/sensitivity",
        response_model=ParameterSensitivity,
        dependencies=[Depends(require_token)],
    )
    def run_sensitivity(spec: RunSpec) -> ParameterSensitivity:
        """What this configuration's data can see, per relative change."""
        try:
            return service_for_project(spec.project_id).parameter_sensitivity(spec)
        except KeyError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/runs",
        response_model=RunRecord,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def create_run(spec: RunSpec) -> RunRecord:
        try:
            if spec.project_id is not None:
                projects.get(spec.project_id)
            return service_for_project(spec.project_id).create(spec)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/runs", response_model=tuple[RunRecord, ...], dependencies=[Depends(require_token)])
    def list_runs(project_id: UUID | None = None) -> tuple[RunRecord, ...]:
        if project_id is not None:
            return service_for_project(project_id).list_runs(project_id=project_id)
        records = list(run_service.list_runs())
        for folder in folders_in(projects.result_root):
            try:
                record = ProjectRecord.model_validate_json(
                    folder.record_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            records.extend(service_for_project(record.project_id).list_runs())
        return tuple(sorted(records, key=lambda item: item.updated_at, reverse=True))

    @app.post(
        "/runs/{run_id}/start",
        response_model=RunRecord,
        dependencies=[Depends(require_token)],
    )
    def start_run(
        run_id: UUID,
        sample_run_id: UUID | None = None,
        allow_unchecked_large_run: bool = False,
    ) -> RunRecord:
        try:
            runs = service_for_run(run_id)
            spec = runs.get(run_id).spec
            policy = RunStartPolicy(runs)
            assessment = policy.check(
                spec,
                sample_run_id=sample_run_id,
                allow_unchecked_large_run=allow_unchecked_large_run,
            )
            # The transition is checked before the preflight is written: a retried start
            # on a run already RUNNING or SUCCEEDED would otherwise rewrite
            # preflight.json with an authorisation that was never used, and then fail.
            transition(runs.get(run_id).state, RunState.QUEUED)
            policy.record(spec, assessment)
            return runs.start(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/runs/{run_id}", response_model=RunRecord, dependencies=[Depends(require_token)])
    def get_run(run_id: UUID) -> RunRecord:
        try:
            return service_for_run(run_id).get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/runs/{run_id}/result",
        response_model=RunResult,
        dependencies=[Depends(require_token)],
    )
    def get_run_result(run_id: UUID) -> RunResult:
        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=404, detail="run result is not available")
        return result

    @app.post(
        "/runs/{run_id}/resume",
        response_model=RunRecord,
        dependencies=[Depends(require_token)],
    )
    def resume_run(run_id: UUID) -> RunRecord:
        """Continue a run whose process was lost, from the checkpoint it saved."""
        try:
            return service_for_run(run_id).resume(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/runs/{run_id}/checkpoint",
        response_model=RunCheckpoint | None,
        dependencies=[Depends(require_token)],
    )
    def get_checkpoint(run_id: UUID) -> RunCheckpoint | None:
        """What a run saved of itself, so the interface can offer to continue it."""
        try:
            return service_for_run(run_id).checkpoint(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/runs/{run_id}/events", dependencies=[Depends(require_token)])
    def get_events(run_id: UUID) -> tuple[RunEvent, ...]:
        try:
            return service_for_run(run_id).events(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/runs/{run_id}/cancel",
        response_model=RunRecord,
        dependencies=[Depends(require_token)],
    )
    def cancel_run(run_id: UUID) -> RunRecord:
        try:
            return service_for_run(run_id).cancel(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/runs/{run_id}/artifacts", dependencies=[Depends(require_token)])
    def get_artifacts(run_id: UUID) -> tuple[ArtifactManifest, ...]:
        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            return ()
        return result.artifacts

    @app.get(
        "/runs/{run_id}/artifacts/{artifact_id}/download",
        dependencies=[Depends(require_token)],
    )
    def download_artifact(run_id: UUID, artifact_id: UUID) -> FileResponse:
        _, path = _artifact_file(service_for_run(run_id), run_id, artifact_id)
        return FileResponse(path, filename=path.name)

    @app.get(
        "/runs/{run_id}/artifacts/{artifact_id}/series",
        response_model=NumericArtifactSeries,
        dependencies=[Depends(require_token)],
    )
    def artifact_series(run_id: UUID, artifact_id: UUID) -> NumericArtifactSeries:
        artifact, path = _artifact_file(service_for_run(run_id), run_id, artifact_id)
        if path.suffix.lower() != ".npy":
            raise HTTPException(status_code=422, detail="artifact is not a numeric .npy array")
        try:
            values = np.asarray(np.load(path, allow_pickle=False), dtype=float)
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read numeric artifact: {error}"
            ) from error
        if values.ndim != 1:
            raise HTTPException(
                status_code=422, detail="only one-dimensional artifacts can be plotted"
            )
        if values.size > 10_000:
            raise HTTPException(
                status_code=422, detail="artifact exceeds the 10,000-sample plot limit"
            )
        if not np.isfinite(values).all():
            raise HTTPException(status_code=422, detail="artifact contains non-finite values")
        return NumericArtifactSeries(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            physical_quantity=artifact.physical_quantity,
            units=artifact.units,
            sample_indices=tuple(range(values.size)),
            values=tuple(float(value) for value in values),
        )

    @app.get(
        "/runs/{run_id}/tdem-batch-section",
        response_model=TDEMBatchSection,
        dependencies=[Depends(require_token)],
    )
    def tdem_batch_section(run_id: UUID) -> TDEMBatchSection:
        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=409, detail="batch result is not available")
        artifact = next(
            (
                item
                for item in result.artifacts
                if item.artifact_type == "stitched_conductivity_section"
            ),
            None,
        )
        if artifact is None:
            raise HTTPException(status_code=422, detail="run does not contain a TDEM batch section")
        _, path = _artifact_file(service_for_run(run_id), run_id, artifact.artifact_id)
        try:
            with np.load(path, allow_pickle=False) as section:
                sounding_ids = tuple(str(value) for value in section["sounding_ids"])
                locations = np.asarray(section["receiver_locations_m"], dtype=float)
                depths = np.asarray(section["layer_top_depth_m"], dtype=float)
                conductivity = np.asarray(section["conductivity_s_m"], dtype=float)
        except (KeyError, OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"invalid TDEM batch section: {error}"
            ) from error
        if (
            locations.shape != (len(sounding_ids), 3)
            or conductivity.shape != (len(sounding_ids), depths.size)
            or len(sounding_ids) * depths.size > 250_000
            or not all(np.isfinite(values).all() for values in (locations, depths, conductivity))
        ):
            raise HTTPException(status_code=422, detail="invalid or oversized TDEM batch section")
        return TDEMBatchSection(
            sounding_ids=sounding_ids,
            # The three columns are guaranteed by the shape check above.
            receiver_locations_m=tuple(
                (float(row[0]), float(row[1]), float(row[2])) for row in locations
            ),
            layer_top_depth_m=tuple(float(value) for value in depths),
            conductivity_s_m=tuple(tuple(float(value) for value in row) for row in conductivity),
        )

    @app.get(
        "/runs/{run_id}/tdem-batch-soundings/{sounding_id}",
        response_model=TDEMBatchSoundingResult,
        dependencies=[Depends(require_token)],
    )
    def tdem_batch_sounding(run_id: UUID, sounding_id: str) -> TDEMBatchSoundingResult:
        try:
            record = service_for_run(run_id).get(run_id)
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        batch = record.spec.tdem_batch_inversion
        if result is None or batch is None:
            raise HTTPException(
                status_code=422, detail="run is not a completed batch TDEM inversion"
            )
        sounding = next((item for item in batch.soundings if item.sounding_id == sounding_id), None)
        if sounding is None:
            raise HTTPException(status_code=404, detail="sounding does not exist in this batch")
        child_run_id = str(uuid5(run_id, sounding_id))

        def child_values(artifact_type: str) -> np.ndarray:
            artifact = next(
                (
                    item
                    for item in result.artifacts
                    if item.artifact_type == artifact_type
                    and f"/soundings/{child_run_id}/" in item.relative_path
                ),
                None,
            )
            if artifact is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"batch sounding is missing {artifact_type} output",
                )
            _, path = _artifact_file(service_for_run(run_id), run_id, artifact.artifact_id)
            try:
                values = np.asarray(np.load(path, allow_pickle=False), dtype=float).reshape(-1)
            except (OSError, ValueError) as error:
                raise HTTPException(
                    status_code=422, detail=f"unable to read {artifact_type}: {error}"
                ) from error
            if values.size == 0 or values.size > 10_000 or not np.isfinite(values).all():
                raise HTTPException(status_code=422, detail=f"invalid {artifact_type} output")
            return values

        times = np.asarray(
            canonicalize_quantity(
                sounding.system.times.value,
                sounding.system.times.unit,
                QuantityType.TIME,
            ),
            dtype=float,
        )
        observed = child_values("observed_data")
        predicted = child_values("predicted_data")
        conductivity = child_values("recovered_model")
        depths = child_values("layer_top_depth")
        if (
            observed.size != times.size
            or predicted.size != times.size
            or conductivity.size != depths.size
        ):
            raise HTTPException(status_code=422, detail="inconsistent TDEM batch sounding output")
        return TDEMBatchSoundingResult(
            sounding_id=sounding_id,
            times_s=tuple(float(value) for value in times),
            observed_t=tuple(float(value) for value in observed),
            predicted_t=tuple(float(value) for value in predicted),
            layer_top_depth_m=tuple(float(value) for value in depths),
            conductivity_s_m=tuple(float(value) for value in conductivity),
        )

    @app.get(
        "/runs/{run_id}/artifacts/{artifact_id}/point-cloud",
        response_model=ModelPointCloud,
        dependencies=[Depends(require_token)],
    )
    def artifact_point_cloud(run_id: UUID, artifact_id: UUID) -> ModelPointCloud:
        """Return a bounded TreeMesh active-cell model view for VTK.js."""
        artifact, model_path = _artifact_file(service_for_run(run_id), run_id, artifact_id)
        if model_path.suffix.lower() != ".npy":
            raise HTTPException(status_code=422, detail="artifact is not a numeric .npy model")
        try:
            values = np.asarray(np.load(model_path, allow_pickle=False), dtype=float)
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read model artifact: {error}"
            ) from error
        if values.ndim != 1 or not np.isfinite(values).all():
            raise HTTPException(
                status_code=422, detail="model must be a finite one-dimensional array"
            )

        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=404, detail="run result is not available")
        geometry = next(
            (item for item in result.artifacts if item.artifact_type == "mesh_geometry"), None
        )
        if geometry is None:
            raise HTTPException(
                status_code=422, detail="a mesh_geometry artifact is required for 3-D model viewing"
            )
        _, geometry_path = _artifact_file(service_for_run(run_id), run_id, geometry.artifact_id)
        if geometry_path.suffix.lower() != ".npz":
            raise HTTPException(
                status_code=422, detail="mesh geometry artifact must be an .npz archive"
            )
        try:
            with np.load(geometry_path, allow_pickle=False) as geometry_data:
                centers = np.asarray(geometry_data["cell_centers_m"], dtype=float)
                volumes = np.asarray(geometry_data["cell_volumes_m3"], dtype=float)
                active_cells = np.asarray(geometry_data["active_cells"], dtype=bool)
        except (KeyError, OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read mesh geometry: {error}"
            ) from error
        if (
            centers.ndim != 2
            or centers.shape[1] != 3
            or volumes.ndim != 1
            or active_cells.ndim != 1
            or centers.shape[0] != volumes.size
            or centers.shape[0] != active_cells.size
            or not np.isfinite(centers).all()
            or not np.isfinite(volumes).all()
        ):
            raise HTTPException(
                status_code=422, detail="mesh geometry arrays have invalid dimensions"
            )
        active_centers = centers[active_cells]
        active_volumes = volumes[active_cells]
        if values.size != active_centers.shape[0]:
            raise HTTPException(
                status_code=422,
                detail="model size does not match the number of active mesh cells",
            )
        if values.size > MAX_POINT_CLOUD_CELLS:
            raise HTTPException(
                status_code=422,
                detail=(f"model exceeds the {MAX_POINT_CLOUD_CELLS:,}-cell 3-D view limit"),
            )
        return ModelPointCloud(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            physical_quantity=artifact.physical_quantity,
            units=artifact.units,
            points_m=tuple(
                (float(point[0]), float(point[1]), float(point[2])) for point in active_centers
            ),
            cell_volumes_m3=tuple(float(volume) for volume in active_volumes),
            values=tuple(float(value) for value in values),
        )

    @app.get(
        "/runs/{run_id}/artifacts/{artifact_id}/distribution",
        response_model=PropertyDistribution,
        dependencies=[Depends(require_token)],
    )
    def artifact_distribution(
        run_id: UUID,
        artifact_id: UUID,
        bins: int = 48,
        log_scale: bool = False,
        exclude_non_positive: bool = False,
    ) -> PropertyDistribution:
        """Reduce a recovered model to a histogram for choosing unit boundaries."""
        if bins < 4 or bins > MAX_DISTRIBUTION_BINS:
            raise HTTPException(
                status_code=422, detail=f"bins must be between 4 and {MAX_DISTRIBUTION_BINS}"
            )
        artifact, path = _artifact_file(service_for_run(run_id), run_id, artifact_id)
        if path.suffix.lower() != ".npy":
            raise HTTPException(status_code=422, detail="artifact is not a numeric .npy model")
        try:
            values = np.asarray(np.load(path, allow_pickle=False), dtype=float).ravel()
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read model artifact: {error}"
            ) from error
        finite = values[np.isfinite(values)]
        if not finite.size:
            raise HTTPException(status_code=422, detail="artifact holds no finite values")

        excluded = 0
        if log_scale and float(finite.min()) <= 0.0:
            # A recovered model really does reach zero: a 1D airborne inversion floors
            # unconstrained layers, and 0.02% of the Kintyre line data does exactly
            # that.
            if not exclude_non_positive:
                raise HTTPException(
                    status_code=422,
                    detail="a logarithmic distribution needs strictly positive values; "
                    f"this model reaches {float(finite.min()):g} {artifact.units}. "
                    "Pass exclude_non_positive=true to leave those cells out.",
                )
            positive = finite[finite > 0.0]
            if not positive.size:
                raise HTTPException(status_code=422, detail="no cell of this model is positive")
            excluded = int(finite.size - positive.size)
            finite = positive
        minimum = float(finite.min())
        maximum = float(finite.max())
        if maximum == minimum:
            # A uniform model has no spread to bin; one bin around the value is the
            # honest answer and keeps the edges/counts invariant.
            edges = np.array([minimum, minimum + 1.0])
            counts = np.array([finite.size])
        elif log_scale:
            edges = np.logspace(np.log10(minimum), np.log10(maximum), bins + 1)
            # `10 ** log10(x)` need not round back to x, and `np.histogram` discards
            # anything past its last edge, so the most resistive cell in the model would
            # vanish from its own histogram.
            edges[0], edges[-1] = minimum, maximum
            counts, edges = np.histogram(finite, bins=edges)
        else:
            counts, edges = np.histogram(finite, bins=bins, range=(minimum, maximum))
        fractions = (0.05, 0.25, 0.5, 0.75, 0.95)
        quantiles = np.quantile(finite, fractions)
        return PropertyDistribution(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            physical_quantity=artifact.physical_quantity,
            units=artifact.units,
            cell_count=int(finite.size),
            minimum=minimum,
            maximum=maximum,
            bin_edges=tuple(float(edge) for edge in edges),
            counts=tuple(int(count) for count in counts),
            log_scale=log_scale,
            excluded_non_positive=excluded,
            quantiles=tuple(
                (float(fraction), float(value))
                for fraction, value in zip(fractions, quantiles, strict=True)
            ),
        )

    @app.get(
        "/runs/{run_id}/artifacts/{artifact_id}/slice",
        response_model=ModelSlice,
        dependencies=[Depends(require_token)],
    )
    def artifact_model_slice(
        run_id: UUID,
        artifact_id: UUID,
        normal: str = "z",
        index: int | None = None,
    ) -> ModelSlice:
        """Return one model plane instead of transferring an entire 3-D mesh."""
        axis_by_normal: dict[SliceNormal, int] = {"x": 0, "y": 1, "z": 2}
        lowered = normal.lower()
        if lowered not in axis_by_normal:
            raise HTTPException(status_code=422, detail="normal must be one of x, y, or z")
        # The membership test above narrows `lowered` to the mapping's key type.
        slice_normal = lowered

        artifact, model_path = _artifact_file(service_for_run(run_id), run_id, artifact_id)
        if model_path.suffix.lower() != ".npy":
            raise HTTPException(status_code=422, detail="artifact is not a numeric .npy model")
        try:
            values = np.asarray(np.load(model_path, allow_pickle=False), dtype=float)
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read model artifact: {error}"
            ) from error
        if values.ndim != 1 or not np.isfinite(values).all():
            raise HTTPException(
                status_code=422, detail="model must be a finite one-dimensional array"
            )

        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=404, detail="run result is not available")
        geometry = next(
            (item for item in result.artifacts if item.artifact_type == "mesh_geometry"), None
        )
        if geometry is None:
            raise HTTPException(
                status_code=422, detail="a mesh_geometry artifact is required for slice viewing"
            )
        _, geometry_path = _artifact_file(service_for_run(run_id), run_id, geometry.artifact_id)
        if geometry_path.suffix.lower() != ".npz":
            raise HTTPException(
                status_code=422, detail="mesh geometry artifact must be an .npz archive"
            )
        try:
            with np.load(geometry_path, allow_pickle=False) as geometry_data:
                centers = np.asarray(geometry_data["cell_centers_m"], dtype=float)
                active_cells = np.asarray(geometry_data["active_cells"], dtype=bool)
        except (KeyError, OSError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail=f"unable to read mesh geometry: {error}"
            ) from error
        if (
            centers.ndim != 2
            or centers.shape[1] != 3
            or active_cells.ndim != 1
            or centers.shape[0] != active_cells.size
            or not np.isfinite(centers).all()
        ):
            raise HTTPException(
                status_code=422, detail="mesh geometry arrays have invalid dimensions"
            )

        active_centers = centers[active_cells]
        if values.size != active_centers.shape[0]:
            raise HTTPException(
                status_code=422, detail="model size does not match the number of active mesh cells"
            )
        axis = axis_by_normal[slice_normal]
        positions = np.unique(active_centers[:, axis])
        if not positions.size:
            raise HTTPException(status_code=422, detail="mesh does not contain active cells")
        selected_index = len(positions) // 2 if index is None else index
        if selected_index < 0 or selected_index >= len(positions):
            raise HTTPException(
                status_code=422, detail=f"slice index must be between 0 and {len(positions) - 1}"
            )
        selected_position = positions[selected_index]
        selection = active_centers[:, axis] == selected_position
        slice_centers = active_centers[selection]
        slice_values = values[selection]
        return ModelSlice(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            physical_quantity=artifact.physical_quantity,
            units=artifact.units,
            normal=slice_normal,
            coordinate_positions_m=tuple(float(value) for value in positions),
            selected_index=selected_index,
            selected_position_m=float(selected_position),
            value_minimum=float(values.min()),
            value_maximum=float(values.max()),
            points_m=tuple(
                (float(point[0]), float(point[1]), float(point[2])) for point in slice_centers
            ),
            values=tuple(float(value) for value in slice_values),
        )

    @app.get("/runs/{run_id}/ert-section", dependencies=[Depends(require_token)])
    def ert_section(run_id: UUID) -> dict[str, object]:
        """A recovered resistivity section as bounded, engine-neutral arrays."""
        try:
            result = service_for_run(run_id).result(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if result is None:
            raise HTTPException(status_code=404, detail="run result is not available")
        model = next(
            (item for item in result.artifacts if item.artifact_type == "recovered_model"), None
        )
        geometry = next(
            (item for item in result.artifacts if item.artifact_type == "mesh_geometry"), None
        )
        if model is None or geometry is None:
            raise HTTPException(
                status_code=422, detail="this run has no recovered model with mesh geometry"
            )
        _, model_path = _artifact_file(service_for_run(run_id), run_id, model.artifact_id)
        geometry_path = (
            service_for_run(run_id).artifact_root / str(run_id) / "mesh_geometry.npz"
        ).resolve()
        if not geometry_path.is_file():
            raise HTTPException(status_code=404, detail="mesh geometry file is not available")
        values = np.asarray(np.load(model_path, allow_pickle=False), dtype=float)
        with np.load(geometry_path, allow_pickle=False) as stored:
            centers = np.asarray(stored["cell_centers_m"], dtype=float)
            sizes = np.asarray(stored["cell_sizes"], dtype=float)
        # Coverage travels with the section rather than as a separate request: a section
        # read without it invites belief in its unconstrained depths.
        coverage_path = service_for_run(run_id).artifact_root / str(run_id) / "model_coverage.npy"
        coverage = (
            np.asarray(np.load(coverage_path, allow_pickle=False), dtype=float)
            if coverage_path.is_file()
            else np.zeros(0)
        )
        if len(centers) != len(values):
            raise HTTPException(
                status_code=422, detail="mesh geometry does not match the recovered model"
            )
        keep = min(len(values), MAX_ERT_SECTION_CELLS)
        return {
            "artifact_id": str(model.artifact_id),
            "units": model.units,
            "physical_quantity": model.physical_quantity.value,
            "easting_m": [float(value) for value in centers[:keep, 0]],
            "elevation_m": [float(value) for value in centers[:keep, 1]],
            "values": [float(value) for value in values[:keep]],
            "cell_sizes": [float(value) for value in sizes[:keep]],
            "coverage": (
                [float(value) for value in coverage[:keep]] if len(coverage) == len(values) else []
            ),
            "truncated": bool(len(values) > keep),
        }

    @app.post(
        "/comparisons",
        response_model=RunComparison,
        dependencies=[Depends(require_token)],
    )
    def compare_runs(request: RunComparisonRequest) -> RunComparison:
        try:
            baseline = service_for_run(request.baseline_run_id)
            candidate = service_for_run(request.candidate_run_id)
            if baseline is not candidate:
                raise ValueError("both runs must belong to the same project")
            return ComparisonService(baseline).compare(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _artifact_file(
    run_service: RunService, run_id: UUID, artifact_id: UUID
) -> tuple[ArtifactManifest, Path]:
    try:
        result = run_service.result(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="run result is not available")
    artifact = next((item for item in result.artifacts if item.artifact_id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact does not exist")
    artifact_root = run_service.artifact_root.resolve()
    path = (artifact_root / artifact.relative_path).resolve()
    if not path.is_relative_to(artifact_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file is not available")
    return artifact, path


app = create_app()
