import json
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ofag.api import app as api_module
from ofag.api.app import create_app
from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArtifactManifest,
    CoordinateConvention,
    DatasetSpec,
    LayeredEarthSpec,
    QuantitySpec,
    RunRecord,
    RunResult,
    RunSpec,
    RunState,
    TDEMBatchInversionSpec,
    TDEMBatchSoundingSpec,
    TDEMModelSpec,
    TDEMSystemSpec,
)
from ofag.reference_data import PreparedGravityReference, ReferenceDatasetReceipt
from ofag.services.project_service import ProjectService
from ofag.services.run_service import RunService
from tests.conftest import await_terminal_state, gravity_run_spec
from tests.test_mt_import import _site


def test_api_lists_plugins_and_validates_run(tmp_path: Path) -> None:
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))
    plugins = client.get("/plugins")
    assert plugins.status_code == 200
    assert plugins.json()[0]["plugin_id"] == "ofag.fixture.gravity3d"
    response = client.post("/runs/validate", json=gravity_run_spec().model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["valid"] is True
    estimate = client.post("/runs/estimate", json=gravity_run_spec().model_dump(mode="json"))
    assert estimate.status_code == 200
    assert estimate.json()["memory_mb"] >= 64
    assert estimate.json()["estimate_basis"] == "heuristic_uncalibrated"


def test_api_large_run_requires_trial_or_explicit_waiver(tmp_path: Path, monkeypatch) -> None:
    from ofag.core.schemas import ResourceEstimate

    runs = RunService(artifact_root=tmp_path / "runs")
    monkeypatch.setattr(
        runs,
        "estimate_resources",
        lambda spec: ResourceEstimate(cpu_cores=1, memory_mb=64, estimated_seconds=120),
    )
    client = TestClient(create_app(runs, ProjectService(tmp_path / "projects")))
    spec = gravity_run_spec()
    assert client.post("/runs", json=spec.model_dump(mode="json")).status_code == 201

    blocked = client.post(f"/runs/{spec.run_id}/start")
    assert blocked.status_code == 409
    assert "smaller sample" in blocked.text
    started = client.post(f"/runs/{spec.run_id}/start?allow_unchecked_large_run=true")
    assert started.status_code == 200
    receipt = runs.run_dir(spec.run_id) / "preflight.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["unchecked_large_run_waived"]


def test_production_api_requires_token_and_configured_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OFAG_ENV", "production")
    monkeypatch.setenv("OFAG_API_TOKEN", "secret")
    monkeypatch.setenv("OFAG_ALLOWED_HOSTS", "ofag.example.org")
    client = TestClient(
        create_app(RunService(artifact_root=tmp_path / "runs")),
        base_url="http://ofag.example.org",
    )
    assert client.get("/plugins").status_code == 401
    assert client.get("/plugins", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert (
        client.get(
            "/plugins", headers={"Authorization": "Bearer secret", "Host": "other.example.org"}
        ).status_code
        == 400
    )


def test_api_creates_persists_and_updates_a_project(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            RunService(artifact_root=tmp_path / "artifacts"),
            ProjectService(tmp_path / "projects"),
        )
    )
    payload = {
        "name": "Iowa test area",
        "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        "elevation_reference": "Local datum",
        "enabled_methods": ["gravity", "aem"],
    }

    created = client.post("/projects", json=payload)

    assert created.status_code == 201
    project_id = created.json()["project_id"]
    assert [item["name"] for item in client.get("/projects").json()] == ["Iowa test area"]
    updated = client.put(f"/projects/{project_id}/methods", json={"enabled_methods": ["gravity"]})
    assert updated.status_code == 200
    assert updated.json()["enabled_methods"] == ["gravity"]
    assert client.get(f"/projects/{project_id}").json()["elevation_reference"] == "Local datum"
    workspace = client.get(f"/projects/{project_id}/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["datasets"] == []

    # A study area holds several surveys, so the workspace is a register rather than one
    # slot per method.
    first_line, second_line = str(uuid4()), str(uuid4())
    saved_workspace = client.put(
        f"/projects/{project_id}/workspace",
        json={
            "datasets": [
                {
                    "dataset_id": first_line,
                    "name": "Line 1",
                    "kind": "gravity",
                    "source_filename": "line-1.csv",
                    "payload": {"row_count": 4},
                },
                {
                    "dataset_id": second_line,
                    "name": "Line 2",
                    "kind": "gravity",
                    "source_filename": "line-2.csv",
                    "payload": {"row_count": 9},
                },
            ],
            "active_dataset_ids": {"gravity": second_line},
            "meshes": [
                {
                    "name": "Gravity shared mesh",
                    "source_method": "gravity",
                    "mesh_kind": "tensor",
                    "cell_size_m": 10,
                    "horizontal_padding_m": 80,
                    "depth_m": 150,
                    "mesh_top_elevation_m": 12,
                }
            ],
        },
    )
    assert saved_workspace.status_code == 200
    assert saved_workspace.json()["meshes"][0]["name"] == "Gravity shared mesh"
    restored_workspace = client.get(f"/projects/{project_id}/workspace").json()
    assert [item["name"] for item in restored_workspace["datasets"]] == ["Line 1", "Line 2"]
    assert restored_workspace["active_dataset_ids"]["gravity"] == second_line
    spec = gravity_run_spec().model_copy(update={"project_id": UUID(project_id)})
    created_run = client.post("/runs", json=spec.model_dump(mode="json"))
    assert created_run.status_code == 201
    assert created_run.json()["spec"]["project_id"] == project_id
    restored = client.get(f"/runs?project_id={project_id}")
    assert restored.status_code == 200
    assert [item["spec"]["run_id"] for item in restored.json()] == [str(spec.run_id)]
    project_folder = ProjectService(tmp_path / "projects").folder(UUID(project_id))
    restarted_service = RunService(artifact_root=project_folder.runs_root)
    assert [record.spec.run_id for record in restarted_service.list_runs(UUID(project_id))] == [
        spec.run_id
    ]


def test_api_imports_gravity_csv_as_canonical_mgal_data(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/gravity-csv",
        json={
            "filename": "stations.csv",
            "csv_text": "east,north,elevation,gz_mgal,error_mgal\n0,0,10,2,0.1\n20,5,12,4,0.2\n",
            "x_column": "east",
            "y_column": "north",
            "z_column": "elevation",
            "gravity_column": "gz_mgal",
            "uncertainty_column": "error_mgal",
            "coordinate_unit": "m",
            "gravity_unit": "mGal",
            "uncertainty_unit": "mGal",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 2
    assert payload["gravity_min_mgal"] == 2.0
    assert np.isclose(payload["recommended_uncertainty_mgal"], 0.15)
    assert Path(payload["canonical_observations_path"]).is_file()


def test_api_imports_mt_sites_into_project_workspace(tmp_path: Path) -> None:
    source = tmp_path / "edis"
    source.mkdir()
    _site(source, "LAYERED", 1.0 + 1.0j, -1.0 - 1.0j)
    projects = ProjectService(tmp_path / "projects")
    project = projects.create(
        api_module.ProjectCreateRequest(
            name="MT survey",
            coordinate_convention=CoordinateConvention(crs="EPSG:26912"),
            elevation_reference="local",
            enabled_methods=("mt",),
        )
    )
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "runs"), projects))
    response = client.post(
        f"/datasets/mt-edi?project_id={project.project_id}",
        json={
            "source_directory": str(source),
            "coordinate_convention": {"crs": "EPSG:26912"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["soundings"]) == 1
    assert Path(payload["soundings"][0]["observations_path"]).is_file()
    assert projects.folder(project.project_id).imports_root in Path(payload["directory"]).parents
    assert projects.workspace(project.project_id).datasets[0].payload == payload


def test_api_import_with_project_id_appears_in_that_project(tmp_path: Path) -> None:
    projects = ProjectService(tmp_path / "projects")
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"), projects))
    created = client.post(
        "/projects",
        json={
            "name": "Iowa survey",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "elevation_reference": "local",
            "enabled_methods": ["gravity"],
        },
    )
    project_id = UUID(created.json()["project_id"])

    response = client.post(
        f"/datasets/gravity-csv?project_id={project_id}",
        json={
            "filename": "stations.csv",
            "csv_text": "x,y,z,g\n0,0,0,1\n",
            "x_column": "x",
            "y_column": "y",
            "z_column": "z",
            "gravity_column": "g",
            "coordinate_unit": "m",
            "gravity_unit": "mGal",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    imported = Path(response.json()["canonical_observations_path"])
    assert imported.is_relative_to(projects.folder(project_id).imports_root)
    registered = client.get(f"/projects/{project_id}/workspace").json()["datasets"]
    assert len(registered) == 1
    assert registered[0]["dataset_id"] == response.json()["dataset_id"]


def test_api_uses_declared_default_uncertainty_percent(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/gravity-csv",
        json={
            "filename": "stations.csv",
            "csv_text": "x,y,z,gz\n0,0,10,2\n20,5,12,4\n",
            "x_column": "x",
            "y_column": "y",
            "z_column": "z",
            "gravity_column": "gz",
            "coordinate_unit": "m",
            "gravity_unit": "mGal",
            "default_uncertainty_percent": 1.0,
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    assert response.json()["recommended_uncertainty_mgal"] == 0.04


def test_api_imports_topography_csv_as_canonical_metres(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/topography-csv",
        json={
            "filename": "surface.csv",
            "csv_text": "east_km,north_km,elevation_km\n0,1,0.12\n2,3,0.18\n",
            "x_column": "east_km",
            "y_column": "north_km",
            "z_column": "elevation_km",
            "coordinate_unit": "km",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 2
    assert payload["bounds_m"] == [0.0, 2000.0, 1000.0, 3000.0, 120.0, 180.0]
    assert Path(payload["canonical_topography_path"]).is_file()


def test_api_imports_magnetic_csv_as_canonical_nt_data(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/magnetic-csv",
        json={
            "filename": "tmi.csv",
            "csv_text": "east,north,elevation,tmi,error\n0,0,10,120,2\n20,5,12,180,4\n",
            "x_column": "east",
            "y_column": "north",
            "z_column": "elevation",
            "tmi_column": "tmi",
            "uncertainty_column": "error",
            "coordinate_unit": "m",
            "tmi_unit": "nT",
            "uncertainty_unit": "nT",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tmi_min_nt"] == 120.0
    assert payload["tmi_max_nt"] == 180.0
    assert payload["recommended_uncertainty_nt"] == 3.0
    assert Path(payload["canonical_observations_path"]).is_file()


def test_api_imports_tdem_csv_as_canonical_si_channels(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/tdem-csv",
        json={
            "filename": "sounding.csv",
            "csv_text": "time_ms,b_nt,error_nt\n0.1,120,3\n1,12,1\n",
            "time_column": "time_ms",
            "response_column": "b_nt",
            "uncertainty_column": "error_nt",
            "time_unit": "ms",
            "response_unit": "nT",
            "uncertainty_unit": "nT",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["times_s"] == [0.0001, 0.001]
    assert np.isclose(payload["response_min_t"], 1.2e-08)
    assert np.isclose(payload["recommended_uncertainty_t"], 2e-09)
    assert Path(payload["canonical_observations_path"]).is_file()


FIXTURES = Path(__file__).parent / "fixtures"


def test_api_imports_long_table_tdem_batch_as_individual_soundings(tmp_path: Path) -> None:
    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/datasets/tdem-csv",
        json={
            "filename": "line.csv",
            "csv_text": (FIXTURES / "tdem_batch_three_soundings.csv").read_text(encoding="utf-8"),
            "import_mode": "batch",
            "sounding_id_column": "sounding_id",
            "x_column": "x_m",
            "y_column": "y_m",
            "z_column": "z_m",
            "coordinate_unit": "m",
            "time_column": "time_s",
            "response_column": "magnetic_flux_density_t",
            "time_unit": "s",
            "response_unit": "T",
            "default_uncertainty_percent": 5,
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["import_mode"] == "batch"
    assert payload["sounding_count"] == 3
    assert [item["sounding_id"] for item in payload["soundings"]] == ["A01", "A02", "A03"]
    assert payload["soundings"][1]["location_m"] == [50.0, 0.0, 0.0]
    assert Path(payload["batch_manifest_path"]).is_file()
    assert all(Path(item["canonical_observations_path"]).is_file() for item in payload["soundings"])


def test_api_prepares_official_gravity_profile_for_workbench(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    spec_path = tmp_path / "prepared-run.yaml"
    spec = gravity_run_spec().model_dump(mode="json")
    spec["plugin_id"] = "simpeg.pf.gravity3d"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(
        api_module,
        "fetch_reference_dataset",
        lambda _dataset_id, _cache_root: ReferenceDatasetReceipt(
            dataset_id="simpeg.cross-gradient",
            source_url="https://example.invalid/cross_gradient_data.tar.gz",
            archive_path="unused",
            extracted_path="unused",
            downloaded=True,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "prepare_cross_gradient_gravity_run",
        lambda _cache_root: PreparedGravityReference(
            dataset_id="simpeg.cross-gradient",
            observations_path="prepared/observations_si.csv",
            topography_path="prepared/topography_si.csv",
            run_spec_path=str(spec_path),
            observation_count=4,
        ),
    )

    response = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts"))).post(
        "/reference-data/simpeg-cross-gradient/gravity-profile"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_id"] == "simpeg.cross-gradient"
    assert payload["observation_count"] == 4
    assert payload["run_spec"]["plugin_id"] == "simpeg.pf.gravity3d"


def test_api_downloads_a_completed_run_artifact(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    record = service.create(gravity_run_spec())
    service.start(record.spec.run_id)
    record = await_terminal_state(service, record.spec.run_id)
    assert record.state is RunState.SUCCEEDED
    result = service.result(record.spec.run_id)
    assert result is not None
    artifact = result.artifacts[0]

    client = TestClient(create_app(service))
    response = client.get(f"/runs/{record.spec.run_id}/artifacts/{artifact.artifact_id}/download")

    assert response.status_code == 200
    assert response.content


def test_api_returns_batch_tdem_section_and_selected_sounding(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    run_id = uuid4()
    times = [1e-5, 1e-4]

    def quantity(value: float | list[float], kind: QuantityType, unit: str) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=kind, unit=unit)

    def sounding(sounding_id: str, x: float) -> TDEMBatchSoundingSpec:
        return TDEMBatchSoundingSpec(
            sounding_id=sounding_id,
            observations_path="unused.csv",
            system=TDEMSystemSpec(
                times=quantity(times, QuantityType.TIME, "s"),
                source_location=quantity([x, 0.0, 20.0], QuantityType.LENGTH, "m"),
                receiver_location=quantity([x, 0.0, 20.0], QuantityType.LENGTH, "m"),
                source_radius=quantity(6.0, QuantityType.LENGTH, "m"),
                source_current=quantity(1.0, QuantityType.ELECTRIC_CURRENT, "A"),
            ),
            data_uncertainty=quantity(1e-12, QuantityType.MAGNETIC_FLUX_DENSITY, "T"),
        )

    spec = RunSpec(
        run_id=run_id,
        plugin_id="simpeg.aem.batch_tdem1d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="batch",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
            units="T",
        ),
        tdem_batch_inversion=TDEMBatchInversionSpec(
            earth=LayeredEarthSpec(layer_thicknesses=quantity([5.0], QuantityType.LENGTH, "m")),
            model=TDEMModelSpec(
                initial_conductivity=quantity(0.1, QuantityType.CONDUCTIVITY, "S/m"),
                lower_bound=quantity(0.001, QuantityType.CONDUCTIVITY, "S/m"),
                upper_bound=quantity(1.0, QuantityType.CONDUCTIVITY, "S/m"),
            ),
            soundings=(sounding("A01", 0.0), sounding("A02", 50.0)),
        ),
        parameters={"batch_manifest_path": "batch_manifest.json"},
    )
    run_dir = tmp_path / "artifacts" / str(run_id)
    artifacts: list[ArtifactManifest] = []
    for index, sounding_id in enumerate(("A01", "A02")):
        child_id = uuid5(run_id, sounding_id)
        child_dir = run_dir / "soundings" / str(child_id)
        child_dir.mkdir(parents=True, exist_ok=True)
        for artifact_type, values in {
            "observed_data": [2e-11, 3e-12],
            "predicted_data": [2.1e-11, 2.9e-12],
            "recovered_model": [0.1 + index * 0.1, 0.2 + index * 0.1],
            "layer_top_depth": [0.0, 5.0],
        }.items():
            path = child_dir / f"{artifact_type}.npy"
            np.save(path, np.asarray(values))
            artifacts.append(
                ArtifactManifest(
                    artifact_type=artifact_type,
                    physical_quantity=QuantityType.CONDUCTIVITY,
                    units="S/m",
                    source_run_id=run_id,
                    relative_path=path.relative_to(tmp_path / "artifacts").as_posix(),
                )
            )
    section_path = run_dir / "stitched_conductivity_section.npz"
    np.savez(
        section_path,
        sounding_ids=np.asarray(["A01", "A02"]),
        receiver_locations_m=np.asarray([[0.0, 0.0, 20.0], [50.0, 0.0, 20.0]]),
        layer_top_depth_m=np.asarray([0.0, 5.0]),
        conductivity_s_m=np.asarray([[0.1, 0.2], [0.2, 0.3]]),
    )
    artifacts.append(
        ArtifactManifest(
            artifact_type="stitched_conductivity_section",
            physical_quantity=QuantityType.CONDUCTIVITY,
            units="S/m",
            source_run_id=run_id,
            relative_path=section_path.relative_to(tmp_path / "artifacts").as_posix(),
        )
    )
    service._records[run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[run_id] = RunResult(run_id=run_id, summary={}, artifacts=tuple(artifacts))
    client = TestClient(create_app(service))

    section_response = client.get(f"/runs/{run_id}/tdem-batch-section")
    sounding_response = client.get(f"/runs/{run_id}/tdem-batch-soundings/A02")

    assert section_response.status_code == 200
    assert section_response.json()["conductivity_s_m"] == [[0.1, 0.2], [0.2, 0.3]]
    assert sounding_response.status_code == 200
    assert sounding_response.json()["sounding_id"] == "A02"
    assert sounding_response.json()["predicted_t"] == [2.1e-11, 2.9e-12]


def test_api_returns_a_bounded_numeric_artifact_series(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    run_dir = tmp_path / "artifacts" / str(spec.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "plot_values.npy"
    np.save(artifact_path, np.array([1.0, 2.5, 4.0]))
    artifact = ArtifactManifest(
        artifact_type="predicted_data",
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="m/s^2",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/plot_values.npy",
    )
    service._records[spec.run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[spec.run_id] = RunResult(
        run_id=spec.run_id,
        summary={"fixture": True},
        artifacts=(artifact,),
    )

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{artifact.artifact_id}/series"
    )

    assert response.status_code == 200
    assert response.json()["values"] == [1.0, 2.5, 4.0]
    assert response.json()["sample_index_unit"] == "dimensionless"


def test_api_returns_active_tree_mesh_cells_for_3d_viewing(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    run_dir = tmp_path / "artifacts" / str(spec.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    model_path = run_dir / "recovered_density.npy"
    geometry_path = run_dir / "mesh_geometry.npz"
    np.save(model_path, np.array([0.1, 0.25]))
    np.savez(
        geometry_path,
        cell_centers_m=np.array([[0.0, 0.0, -10.0], [2.0, 0.0, -10.0], [4.0, 0.0, -10.0]]),
        cell_volumes_m3=np.array([1.0, 2.0, 4.0]),
        active_cells=np.array([True, False, True]),
    )
    model = ArtifactManifest(
        artifact_type="recovered_density",
        physical_quantity=QuantityType.DENSITY_CONTRAST,
        units="g/cm^3",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/recovered_density.npy",
    )
    geometry = ArtifactManifest(
        artifact_type="mesh_geometry",
        physical_quantity=QuantityType.LENGTH,
        units="m",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/mesh_geometry.npz",
    )
    service._records[spec.run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[spec.run_id] = RunResult(
        run_id=spec.run_id,
        summary={"fixture": True},
        artifacts=(model, geometry),
    )

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{model.artifact_id}/point-cloud"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["points_m"] == [[0.0, 0.0, -10.0], [4.0, 0.0, -10.0]]
    assert payload["cell_volumes_m3"] == [1.0, 4.0]
    assert payload["values"] == [0.1, 0.25]


def test_api_returns_only_the_requested_model_slice(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    run_dir = tmp_path / "artifacts" / str(spec.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    np.save(run_dir / "recovered_density.npy", np.array([0.1, 0.2, 0.3, 0.4]))
    np.savez(
        run_dir / "mesh_geometry.npz",
        cell_centers_m=np.array(
            [[0.0, 0.0, -10.0], [2.0, 0.0, -10.0], [0.0, 2.0, -10.0], [2.0, 2.0, -10.0]]
        ),
        cell_volumes_m3=np.ones(4),
        active_cells=np.ones(4, dtype=bool),
    )
    model = ArtifactManifest(
        artifact_type="recovered_model",
        physical_quantity=QuantityType.DENSITY_CONTRAST,
        units="g/cm^3",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/recovered_density.npy",
    )
    geometry = ArtifactManifest(
        artifact_type="mesh_geometry",
        physical_quantity=QuantityType.LENGTH,
        units="m",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/mesh_geometry.npz",
    )
    service._records[spec.run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[spec.run_id] = RunResult(
        run_id=spec.run_id, summary={"fixture": True}, artifacts=(model, geometry)
    )

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{model.artifact_id}/slice?normal=x&index=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["normal"] == "x"
    assert payload["coordinate_positions_m"] == [0.0, 2.0]
    assert payload["selected_index"] == 1
    assert payload["points_m"] == [[2.0, 0.0, -10.0], [2.0, 2.0, -10.0]]
    assert payload["values"] == [0.2, 0.4]


def test_api_large_recovered_model_uses_point_cloud_not_series(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    run_dir = tmp_path / "artifacts" / str(spec.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    model_path = run_dir / "recovered_density_g_cc.npy"
    geometry_path = run_dir / "mesh_geometry.npz"
    count = 10_001
    np.save(model_path, np.linspace(-0.2, 0.3, count))
    np.savez(
        geometry_path,
        cell_centers_m=np.c_[np.arange(count), np.zeros(count), np.zeros(count)],
        cell_volumes_m3=np.ones(count),
        active_cells=np.ones(count, dtype=bool),
    )
    model = ArtifactManifest(
        artifact_type="recovered_model",
        physical_quantity=QuantityType.DENSITY_CONTRAST,
        units="g/cm^3",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/recovered_density_g_cc.npy",
    )
    geometry = ArtifactManifest(
        artifact_type="mesh_geometry",
        physical_quantity=QuantityType.DIMENSIONLESS,
        units="dimensionless",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/mesh_geometry.npz",
    )
    service._records[spec.run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[spec.run_id] = RunResult(
        run_id=spec.run_id, summary={"fixture": True}, artifacts=(model, geometry)
    )
    client = TestClient(create_app(service))

    series_response = client.get(f"/runs/{spec.run_id}/artifacts/{model.artifact_id}/series")
    point_cloud_response = client.get(
        f"/runs/{spec.run_id}/artifacts/{model.artifact_id}/point-cloud"
    )
    slice_response = client.get(
        f"/runs/{spec.run_id}/artifacts/{model.artifact_id}/slice?normal=x&index=5000"
    )

    assert series_response.status_code == 422
    assert point_cloud_response.status_code == 200
    assert len(point_cloud_response.json()["values"]) == count
    assert slice_response.status_code == 200
    assert len(slice_response.json()["values"]) == 1


def _resistivity_run(tmp_path: Path, values: np.ndarray) -> tuple[RunService, RunSpec, UUID]:
    """A succeeded run whose recovered model is `values`, for distribution tests."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    run_dir = tmp_path / "artifacts" / str(spec.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    np.save(run_dir / "recovered_model.npy", values)
    model = ArtifactManifest(
        artifact_type="recovered_model",
        physical_quantity=QuantityType.RESISTIVITY,
        units="ohm*m",
        source_run_id=spec.run_id,
        relative_path=f"{spec.run_id}/recovered_model.npy",
    )
    service._records[spec.run_id] = RunRecord(spec=spec, state=RunState.SUCCEEDED)
    service._results[spec.run_id] = RunResult(
        run_id=spec.run_id, summary={"fixture": True}, artifacts=(model,)
    )
    return service, spec, model.artifact_id


def test_api_reduces_a_large_model_to_a_bounded_distribution(tmp_path: Path) -> None:
    """Choosing unit boundaries needs the spread, not the 250,000 cells behind it."""
    rng = np.random.default_rng(0)
    # Two populations, as a real section has: conductive cover over resistive rock.
    values = np.concatenate(
        [rng.normal(30.0, 3.0, 150_000), rng.normal(900.0, 60.0, 100_000)]
    ).clip(min=1.0)
    service, spec, artifact_id = _resistivity_run(tmp_path, values)

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{artifact_id}/distribution?bins=32&log_scale=true"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cell_count"] == 250_000
    assert payload["units"] == "ohm*m"
    assert len(payload["bin_edges"]) == len(payload["counts"]) + 1 == 33
    assert sum(payload["counts"]) == 250_000
    # The two populations must still be separable, or the histogram is useless for the
    # one thing it exists to support.
    edges = payload["bin_edges"]
    occupied = [index for index, count in enumerate(payload["counts"]) if count]
    gaps = [b - a for a, b in zip(occupied, occupied[1:], strict=False)]
    assert max(gaps) > 1, "the conductive and resistive modes were merged into one block"
    assert edges[0] == pytest.approx(values.min())
    assert edges[-1] == pytest.approx(values.max())
    quantiles = {fraction: value for fraction, value in payload["quantiles"]}
    assert quantiles[0.05] < 100.0 < quantiles[0.95]


def test_api_refuses_a_logarithmic_distribution_over_signed_values(tmp_path: Path) -> None:
    """Dropping the non-positive cells would describe a model that is not on disk."""
    service, spec, artifact_id = _resistivity_run(
        tmp_path, np.array([-0.2, 0.0, 0.3, 0.4], dtype=float)
    )

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{artifact_id}/distribution?log_scale=true"
    )

    assert response.status_code == 422
    assert "positive" in response.json()["detail"]


def test_api_distribution_of_a_uniform_model_still_has_matching_edges(tmp_path: Path) -> None:
    """A starting model that never moved has no spread; the response must not degenerate."""
    service, spec, artifact_id = _resistivity_run(tmp_path, np.full(500, 100.0))

    response = TestClient(create_app(service)).get(
        f"/runs/{spec.run_id}/artifacts/{artifact_id}/distribution"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["minimum"] == payload["maximum"] == 100.0
    assert payload["counts"] == [500]
    assert len(payload["bin_edges"]) == 2


def test_api_compares_completed_run_summaries_and_numeric_artifacts(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    baseline_spec = gravity_run_spec()
    candidate_spec = baseline_spec.model_copy(update={"run_id": uuid4()})
    baseline_dir = tmp_path / "artifacts" / str(baseline_spec.run_id)
    candidate_dir = tmp_path / "artifacts" / str(candidate_spec.run_id)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    np.save(baseline_dir / "predicted.npy", np.array([1.0, 2.0]))
    np.save(candidate_dir / "predicted.npy", np.array([2.0, 4.0]))
    baseline_artifact = ArtifactManifest(
        artifact_type="predicted_data",
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="m/s^2",
        source_run_id=baseline_spec.run_id,
        relative_path=f"{baseline_spec.run_id}/predicted.npy",
    )
    candidate_artifact = ArtifactManifest(
        artifact_type="predicted_data",
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="m/s^2",
        source_run_id=candidate_spec.run_id,
        relative_path=f"{candidate_spec.run_id}/predicted.npy",
    )
    service._records[baseline_spec.run_id] = RunRecord(spec=baseline_spec, state=RunState.SUCCEEDED)
    service._records[candidate_spec.run_id] = RunRecord(
        spec=candidate_spec, state=RunState.SUCCEEDED
    )
    service._results[baseline_spec.run_id] = RunResult(
        run_id=baseline_spec.run_id,
        summary={"phi_data": 3.0, "label": "baseline"},
        artifacts=(baseline_artifact,),
    )
    service._results[candidate_spec.run_id] = RunResult(
        run_id=candidate_spec.run_id,
        summary={"phi_data": 5.5, "label": "candidate"},
        artifacts=(candidate_artifact,),
    )

    response = TestClient(create_app(service)).post(
        "/comparisons",
        json={
            "baseline_run_id": str(baseline_spec.run_id),
            "candidate_run_id": str(candidate_spec.run_id),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_deltas"] == {"phi_data": 2.5}
    assert payload["artifact_comparisons"][0]["sample_count"] == 2
    assert payload["artifact_comparisons"][0]["mean_delta"] == 1.5
    assert payload["artifact_comparisons"][0]["root_mean_square_delta"] == np.sqrt(2.5)


def test_a_plugin_that_cannot_report_what_its_data_sees_says_so(tmp_path: Path) -> None:
    """The endpoint a caller tunes against has to fail legibly."""
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post("/runs/sensitivity", json=gravity_run_spec().model_dump(mode="json"))

    assert response.status_code == 422
    assert "cannot report what its data sees" in response.json()["detail"]
