import json
import shutil
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetKind,
    ModelSource,
    ProjectCreateRequest,
    ProjectDataset,
    ProjectWorkspace,
    ProjectWorkspaceUpdate,
    PropertyClass,
    SiteModel,
)
from ofag.services.project_service import ProjectService


def _project(root: Path) -> tuple[ProjectService, str]:
    service = ProjectService(root)
    record = service.create(
        ProjectCreateRequest(
            name="Study area",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            enabled_methods=("gravity", "ert"),
        )
    )
    return service, str(record.project_id)


def _dataset(name: str, kind: DatasetKind, dataset_id: str) -> ProjectDataset:
    return ProjectDataset.model_validate(
        {
            "dataset_id": dataset_id,
            "name": name,
            "kind": kind.value,
            "source_filename": f"{name}.dat",
            "payload": {"observation_count": 120},
        }
    )


def test_a_project_registers_many_datasets_of_one_kind(tmp_path: Path) -> None:
    """A resistivity survey is a set of lines, not one file."""
    service, project_id = _project(tmp_path / "projects")
    from uuid import UUID, uuid4

    first, second = str(uuid4()), str(uuid4())
    service.update_workspace(
        UUID(project_id),
        ProjectWorkspaceUpdate(
            datasets=(
                _dataset("Line 1", DatasetKind.ERT, first),
                _dataset("Line 2", DatasetKind.ERT, second),
            ),
            active_dataset_ids={DatasetKind.ERT: UUID(second)},
        ),
    )

    workspace = service.workspace(UUID(project_id))

    assert [item.name for item in workspace.datasets] == ["Line 1", "Line 2"]
    active = workspace.active(DatasetKind.ERT)
    assert active is not None and active.name == "Line 2"


def test_an_active_dataset_must_be_registered_and_of_its_kind() -> None:
    from uuid import UUID, uuid4

    identifier = str(uuid4())
    with pytest.raises(ValidationError, match="is not registered"):
        ProjectWorkspace(
            project_id=UUID(str(uuid4())),
            active_dataset_ids={DatasetKind.ERT: UUID(identifier)},
        )
    with pytest.raises(ValidationError, match="is gravity, not ert"):
        ProjectWorkspace(
            project_id=UUID(str(uuid4())),
            datasets=(_dataset("Grid", DatasetKind.GRAVITY, identifier),),
            active_dataset_ids={DatasetKind.ERT: UUID(identifier)},
        )


def test_duplicate_dataset_ids_are_rejected() -> None:
    from uuid import UUID, uuid4

    identifier = str(uuid4())
    with pytest.raises(ValidationError, match="must be unique"):
        ProjectWorkspace(
            project_id=UUID(str(uuid4())),
            datasets=(
                _dataset("A", DatasetKind.GRAVITY, identifier),
                _dataset("B", DatasetKind.GRAVITY, identifier),
            ),
        )


def test_a_workspace_written_with_one_slot_per_method_still_opens(tmp_path: Path) -> None:
    """Projects created before the register existed must not lose their inputs."""
    from uuid import UUID, uuid4

    service, project_id = _project(tmp_path / "projects")
    gravity_id = str(uuid4())
    legacy = {
        "project_id": project_id,
        "gravity_dataset": {
            "dataset_id": gravity_id,
            "source_filename": "stations.csv",
            "canonical_observations_path": "data/imports/stations.csv",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "row_count": 42,
            "bounds_m": [0, 30, 0, 30, 10, 12],
            "gravity_min_mgal": -1.0,
            "gravity_max_mgal": 2.0,
            "recommended_uncertainty_mgal": 0.1,
        },
        "topography_dataset": {
            "dataset_id": str(uuid4()),
            "source_filename": "surface.csv",
            "canonical_topography_path": "data/imports/surface.csv",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "row_count": 900,
            "bounds_m": [0, 30, 0, 30, 10, 12],
        },
        "gravity_mesh": {
            "mesh_id": str(uuid4()),
            "name": "Gravity shared mesh",
            "source_method": "gravity",
            "mesh_kind": "tensor",
            "cell_size_m": 10,
            "horizontal_padding_m": 80,
            "depth_m": 150,
        },
        "updated_at": "2026-01-01T00:00:00Z",
    }
    # Into the project's own folder, which is named after the project rather than after
    # its identifier: the service reads the records to find it.
    (service.folder(UUID(project_id)).workspace_path).write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    workspace = service.workspace(UUID(project_id))

    assert {item.kind for item in workspace.datasets} == {
        DatasetKind.GRAVITY,
        DatasetKind.TOPOGRAPHY,
    }
    gravity = workspace.active(DatasetKind.GRAVITY)
    assert gravity is not None
    assert gravity.source_filename == "stations.csv"
    # The importer's own result survives untouched, so nothing is re-derived.
    assert gravity.payload["row_count"] == 42
    assert workspace.active(DatasetKind.TOPOGRAPHY) is not None
    mesh = workspace.mesh("gravity")
    assert mesh is not None and mesh.name == "Gravity shared mesh"


def _source(*classes: PropertyClass) -> ModelSource:
    from uuid import uuid4

    return ModelSource(
        run_id=uuid4(),
        artifact_id=uuid4(),
        physical_quantity=QuantityType.RESISTIVITY,
        units="ohm*m",
        classes=classes,
    )


def test_a_site_model_survives_a_restart_with_its_units(tmp_path: Path) -> None:
    """The stage the workflow exists for must persist like every other input."""
    from uuid import UUID

    service, project_id = _project(tmp_path / "projects")
    model = SiteModel(
        name="Hillslope units",
        summary="Saprolite over fractured bedrock, from the 2026 line.",
        sources=(
            _source(
                PropertyClass(name="Saturated regolith", colour="#2f6f9f", maximum=60.0),
                PropertyClass(name="Saprolite", colour="#c9a227", minimum=60.0, maximum=400.0),
                PropertyClass(name="Bedrock", colour="#7d5a3c", minimum=400.0),
            ),
        ),
    )

    service.update_workspace(UUID(project_id), ProjectWorkspaceUpdate(models=(model,)))
    reopened = service.workspace(UUID(project_id))

    stored = reopened.site_model(model.site_model_id)
    assert stored is not None
    assert [item.name for item in stored.sources[0].classes] == [
        "Saturated regolith",
        "Saprolite",
        "Bedrock",
    ]


def test_units_of_one_source_may_not_overlap() -> None:
    """Two units claiming the same resistivity would classify a cell by iteration order."""
    with pytest.raises(ValidationError, match="overlap"):
        _source(
            PropertyClass(name="Saprolite", colour="#c9a227", minimum=60.0, maximum=400.0),
            PropertyClass(name="Bedrock", colour="#7d5a3c", minimum=300.0),
        )


def test_a_unit_boundary_is_half_open_so_a_value_belongs_to_exactly_one() -> None:
    """400 ohm.m must be bedrock, not both saprolite and bedrock."""
    source = _source(
        PropertyClass(name="Saprolite", colour="#c9a227", minimum=60.0, maximum=400.0),
        PropertyClass(name="Bedrock", colour="#7d5a3c", minimum=400.0),
    )

    boundary = source.classify(400.0)
    assert boundary is not None and boundary.name == "Bedrock"
    below = source.classify(399.9)
    assert below is not None and below.name == "Saprolite"
    # Nothing claims 10 ohm.m, and the model says so rather than guessing.
    assert source.classify(10.0) is None


def test_a_source_declares_a_unit_its_quantity_can_carry() -> None:
    """A resistivity model classified in metres would be a silent unit error."""
    from uuid import uuid4

    with pytest.raises(ValidationError):
        ModelSource(
            run_id=uuid4(),
            artifact_id=uuid4(),
            physical_quantity=QuantityType.RESISTIVITY,
            units="m",
        )


def test_a_project_gets_a_directory_somebody_can_recognise(tmp_path: Path) -> None:
    """The point of naming it is that a person can find it without being told."""
    from ofag.services.project_folder import folder_name_for

    service = ProjectService(root=tmp_path / "Result")
    record = service.create(
        ProjectCreateRequest(
            name="Soda Lake / geothermal 2010",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            enabled_methods=("seismic",),
        )
    )

    folder = service.folder(record.project_id)
    assert folder.root == tmp_path / "Result" / "Soda-Lake-geothermal-2010"
    assert folder.record_path.is_file()
    assert folder.imports_root.is_dir()
    assert folder.runs_root.is_dir()
    assert folder_name_for("Soda Lake / geothermal 2010") == "Soda-Lake-geothermal-2010"


def test_a_copied_project_rebases_its_own_files_even_while_original_exists(tmp_path: Path) -> None:
    """A colleague's copy must read its own imports, not the sender's originals."""
    from uuid import uuid4

    original_service = ProjectService(tmp_path / "original")
    record = original_service.create(
        ProjectCreateRequest(
            name="Portable",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    original = original_service.folder(record.project_id)
    dataset_id = uuid4()
    imported = original.imports_root / str(dataset_id) / "observations.csv"
    imported.parent.mkdir(parents=True)
    imported.write_text("x,y,g\n", encoding="utf-8")
    external = tmp_path / "other-project" / "imports" / "outside.csv"
    external.parent.mkdir(parents=True)
    external.write_text("external\n", encoding="utf-8")
    original_service.update_workspace(
        record.project_id,
        ProjectWorkspaceUpdate(
            datasets=(
                ProjectDataset(
                    dataset_id=dataset_id,
                    name="survey",
                    kind=DatasetKind.GRAVITY,
                    source_filename="outside.csv",
                    payload={
                        "canonical_observations_path": imported.as_posix(),
                        "source_path": external.as_posix(),
                    },
                ),
            ),
        ),
    )
    run = original.runs_root / str(uuid4())
    run.mkdir()
    (run / "run_record.json").write_text(
        json.dumps({"spec": {"datasets": [{"observations_path": imported.as_posix()}]}}),
        encoding="utf-8",
    )
    (run / "run_spec.yaml").write_text(
        f"observations_path: '{imported.as_posix()}'\n", encoding="utf-8"
    )

    destination_root = tmp_path / "received"
    shutil.copytree(original.root, destination_root / original.root.name)
    received_service = ProjectService(destination_root)
    received = received_service.folder(record.project_id)
    expected = (received.imports_root / str(dataset_id) / "observations.csv").resolve()

    payload = received_service.workspace(record.project_id).datasets[0].payload
    assert Path(payload["canonical_observations_path"]) == expected
    assert payload["source_path"] == external.as_posix()
    record_file = received.runs_root / run.name / "run_record.json"
    assert expected.as_posix() in record_file.read_text(encoding="utf-8")
    assert expected.as_posix() in (received.runs_root / run.name / "run_spec.yaml").read_text(
        encoding="utf-8"
    )


def test_incomplete_project_copy_retries_missing_import_on_next_open(tmp_path: Path) -> None:
    from uuid import uuid4

    service = ProjectService(tmp_path / "original")
    record = service.create(
        ProjectCreateRequest(
            name="Delayed",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    original = service.folder(record.project_id)
    dataset_id = uuid4()
    imported = original.imports_root / str(dataset_id) / "observations.csv"
    imported.parent.mkdir(parents=True)
    imported.write_text("x,y,g\n", encoding="utf-8")
    service.update_workspace(
        record.project_id,
        ProjectWorkspaceUpdate(
            datasets=(
                ProjectDataset(
                    dataset_id=dataset_id,
                    name="survey",
                    kind=DatasetKind.GRAVITY,
                    source_filename="survey.csv",
                    payload={"canonical_observations_path": imported.as_posix()},
                ),
            )
        ),
    )
    destination = tmp_path / "received" / original.root.name
    shutil.copytree(original.root, destination, ignore=shutil.ignore_patterns("observations.csv"))
    received_service = ProjectService(destination.parent)
    assert (
        received_service.workspace(record.project_id)
        .datasets[0]
        .payload["canonical_observations_path"]
        == imported.as_posix()
    )

    copied = destination / "imports" / str(dataset_id) / "observations.csv"
    copied.write_text("x,y,g\n", encoding="utf-8")
    assert (
        received_service.workspace(record.project_id)
        .datasets[0]
        .payload["canonical_observations_path"]
        == copied.resolve().as_posix()
    )


def test_relocated_checkpoint_still_matches_rebased_run(tmp_path: Path) -> None:
    from ofag.core.schemas import RunRecord, RunState
    from ofag.plugins.protocol import PluginContext
    from tests.conftest import gravity_run_spec

    service = ProjectService(tmp_path / "original")
    project = service.create(
        ProjectCreateRequest(
            name="Interrupted",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    original = service.folder(project.project_id)
    data_path = original.imports_root / "source.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text("x,y,g\n", encoding="utf-8")
    spec = gravity_run_spec().model_copy(
        update={
            "project_id": project.project_id,
            "parameters": {"observations_path": data_path.as_posix()},
        }
    )
    run_dir = original.runs_root / str(spec.run_id)
    run_dir.mkdir()
    (run_dir / "run_record.json").write_text(
        RunRecord(spec=spec, state=RunState.INTERRUPTED).model_dump_json(), encoding="utf-8"
    )
    PluginContext(original.runs_root).checkpoint(
        spec,
        {"model_path": data_path.as_posix()},
        plugin_id=spec.plugin_id,
        plugin_version=spec.plugin_version,
    )

    destination = tmp_path / "received" / original.root.name
    shutil.copytree(original.root, destination)
    received = ProjectService(destination.parent).folder(project.project_id)
    rebased = RunRecord.model_validate_json(
        (received.runs_root / str(spec.run_id) / "run_record.json").read_text(encoding="utf-8")
    ).spec
    checkpoint = PluginContext(received.runs_root).resume_from(rebased)
    assert checkpoint is not None
    assert (
        checkpoint.state["model_path"]
        == (received.imports_root / "source.csv").resolve().as_posix()
    )


def test_portable_export_copies_external_input_and_preserves_checkpoint(tmp_path: Path) -> None:
    from ofag.core.schemas import RunRecord, RunState
    from ofag.plugins.protocol import PluginContext
    from tests.conftest import gravity_run_spec

    service = ProjectService(tmp_path / "sender")
    project = service.create(
        ProjectCreateRequest(
            name="Portable field",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    original = service.folder(project.project_id)
    external = tmp_path / "outside" / "observations.csv"
    external.parent.mkdir()
    external.write_text("x,y,g\n", encoding="utf-8")
    dataset_id = uuid4()
    service.update_workspace(
        project.project_id,
        ProjectWorkspaceUpdate(
            datasets=(
                ProjectDataset(
                    dataset_id=dataset_id,
                    name="stations",
                    kind=DatasetKind.GRAVITY,
                    source_filename=external.name,
                    payload={"source_path": external.as_posix()},
                ),
            )
        ),
    )
    spec = gravity_run_spec().model_copy(
        update={
            "project_id": project.project_id,
            "parameters": {"observations_path": external.as_posix()},
        }
    )
    run_dir = original.runs_root / str(spec.run_id)
    run_dir.mkdir()
    (run_dir / "run_record.json").write_text(
        RunRecord(spec=spec, state=RunState.INTERRUPTED).model_dump_json(), encoding="utf-8"
    )
    PluginContext(original.runs_root).checkpoint(
        spec,
        {"input_path": external.as_posix()},
        plugin_id=spec.plugin_id,
        plugin_version=spec.plugin_version,
    )

    exported = service.export_portable(project.project_id, tmp_path / "recipient")
    received = ProjectService(exported.parent)
    copied = Path(received.workspace(project.project_id).datasets[0].payload["source_path"])
    assert copied.is_file() and copied.is_relative_to(exported)
    assert copied.read_text(encoding="utf-8") == external.read_text(encoding="utf-8")
    rebuilt = RunRecord.model_validate_json(
        (exported / "runs" / str(spec.run_id) / "run_record.json").read_text(encoding="utf-8")
    ).spec
    assert rebuilt.parameters["observations_path"] == copied.as_posix()
    checkpoint = PluginContext(exported / "runs").resume_from(rebuilt)
    assert checkpoint is not None and checkpoint.state["input_path"] == copied.as_posix()
    assert service.workspace(project.project_id).datasets[0].payload["source_path"] == (
        external.as_posix()
    )


def test_portable_export_refuses_a_missing_external_input(tmp_path: Path) -> None:
    service = ProjectService(tmp_path / "sender")
    project = service.create(
        ProjectCreateRequest(
            name="Missing source",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    missing = (tmp_path / "missing.csv").as_posix()
    service.update_workspace(
        project.project_id,
        ProjectWorkspaceUpdate(
            datasets=(
                ProjectDataset(
                    dataset_id=uuid4(),
                    name="stations",
                    kind=DatasetKind.GRAVITY,
                    source_filename="missing.csv",
                    payload={"source_path": missing},
                ),
            )
        ),
    )
    destination = tmp_path / "recipient"
    with pytest.raises(FileNotFoundError, match="missing"):
        service.export_portable(project.project_id, destination)
    assert list(destination.iterdir()) == []


def test_portable_export_refuses_a_run_that_may_still_write(tmp_path: Path) -> None:
    from ofag.core.schemas import RunRecord, RunState
    from tests.conftest import gravity_run_spec

    service = ProjectService(tmp_path / "sender")
    project = service.create(
        ProjectCreateRequest(
            name="Active",
            coordinate_convention=CoordinateConvention(crs="EPSG:32109"),
            enabled_methods=("gravity",),
        )
    )
    spec = gravity_run_spec().model_copy(update={"project_id": project.project_id})
    run_dir = service.folder(project.project_id).runs_root / str(spec.run_id)
    run_dir.mkdir()
    (run_dir / "run_record.json").write_text(
        RunRecord(spec=spec, state=RunState.QUEUED).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="active runs"):
        service.export_portable(project.project_id, tmp_path / "recipient")


def test_export_rejects_external_directory_containing_staging(tmp_path):
    from ofag.services.project_export import _external_references
    from ofag.services.project_folder import ProjectFolder

    root = tmp_path / "staging"
    root.mkdir()
    (root / "workspace.json").write_text(
        json.dumps({"source_path": tmp_path.as_posix()}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="contains the export"):
        _external_references(ProjectFolder(root))


def test_export_final_repair_failure_leaves_no_partial_project(tmp_path, monkeypatch):
    from ofag.services import project_export

    service, project_id = _project(tmp_path / "sender")
    repair = project_export.repair_project_paths
    calls = 0

    def fail_final(folder):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("failed final relocation")
        repair(folder)

    monkeypatch.setattr(project_export, "repair_project_paths", fail_final)
    destination = tmp_path / "recipient"
    with pytest.raises(OSError, match="failed final relocation"):
        service.export_portable(UUID(project_id), destination)
    assert list(destination.iterdir()) == []


def test_two_projects_of_the_same_name_do_not_share_a_directory(tmp_path: Path) -> None:
    """A name is a title, not an identity; two surveys of one field share it."""
    service = ProjectService(root=tmp_path / "Result")
    request = ProjectCreateRequest(
        name="Brady",
        coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
        enabled_methods=("ert",),
    )

    first = service.create(request)
    second = service.create(request)

    assert service.folder(first.project_id).root.name == "Brady"
    assert service.folder(second.project_id).root.name == "Brady-2"
    assert service.get(first.project_id).project_id == first.project_id
    assert service.get(second.project_id).project_id == second.project_id


def test_a_name_no_file_system_would_take_still_gets_a_folder(tmp_path: Path) -> None:
    """Including one that reduces to nothing, and one Windows reserves."""
    from ofag.services.project_folder import folder_name_for

    assert folder_name_for("Käsegrotte: Nord*Süd?") == "Kasegrotte-Nord-Sud"
    assert folder_name_for("   ...   ") == "project"
    assert folder_name_for("Проект") == "project"  # a script NFKD cannot fold to ASCII
    # `CON` is unusable on Windows whatever the extension, and fails silently.
    assert folder_name_for("con") == "project"
    assert len(folder_name_for("x" * 300)) <= 60


def test_a_directory_without_a_record_is_not_a_project(tmp_path: Path) -> None:
    """Somebody else's folder, or one a crash left half-written."""
    root = tmp_path / "Result"
    service = ProjectService(root=root)
    service.create(
        ProjectCreateRequest(
            name="Real",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            enabled_methods=("gravity",),
        )
    )
    (root / "notes").mkdir()
    (root / "notes" / "scratch.txt").write_text("nothing to do with a project", encoding="utf-8")

    assert [record.name for record in service.list()] == ["Real"]
