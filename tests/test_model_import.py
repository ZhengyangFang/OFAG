"""Importing an inversion OFAG did not compute."""

from importlib.util import find_spec
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ofag.api.app import create_app
from ofag.services.model_import import IMPORT_PLUGIN_ID
from ofag.services.run_service import RunService

needs_discretize = pytest.mark.skipif(
    find_spec("discretize") is None, reason="the simpeg extra is not installed"
)

#: The value EMVision writes into cells above topography in the Kintyre model.
AIR = 1e-8


def _ubc_fixture(directory: Path) -> tuple[Path, Path, np.ndarray]:
    """A 4x3x2 conductivity model with its top layer set to the air value."""
    import discretize

    directory.mkdir(parents=True, exist_ok=True)
    mesh = discretize.TensorMesh(
        [np.full(4, 25.0), np.full(3, 40.0), np.full(2, 10.0)],
        origin=(394189.0, 7528440.0, -20.0),
    )
    # Ground below, air above: shaped in the mesh's own (x, y, z) order so the test
    # knows which cells should survive the import.
    values = np.zeros(mesh.shape_cells, order="F")
    values[:, :, 0] = 0.05
    values[:, :, 1] = AIR
    flat = np.asarray(values.reshape(-1, order="F"), dtype=float)

    mesh_path = directory / "fixture.msh"
    model_path = directory / "fixture.model"
    mesh.write_UBC(str(mesh_path))
    mesh.write_model_UBC(str(model_path), flat)
    return mesh_path, model_path, flat


def _request(mesh_path: Path, model_path: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mesh_path": str(mesh_path),
        "model_path": str(model_path),
        "name": "Third-party AEM inversion",
        "physical_quantity": "conductivity",
        "units": "S/m",
        "coordinate_convention": {"crs": "EPSG:28351"},
        "model_format": "ubc",
        "inactive_value": AIR,
        "produced_by": "A contractor",
    }
    payload.update(overrides)
    return payload


@needs_discretize
def test_an_imported_model_becomes_a_run_every_result_page_can_read(tmp_path: Path) -> None:
    """A product OFAG did not compute is still a result, so it is a run."""
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    service = RunService(artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(service))

    response = client.post("/datasets/external-model", json=_request(mesh_path, model_path))

    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["cell_count"] == 24
    # The top layer is air and was declared as such, so half the cells go.
    assert imported["active_cell_count"] == 12
    assert imported["units"] == "siemens / meter"
    assert imported["value_minimum"] == pytest.approx(0.05)

    run_id = imported["run_id"]
    listed = client.get("/runs").json()
    assert [record["state"] for record in listed] == ["SUCCEEDED"]
    assert listed[0]["spec"]["plugin_id"] == IMPORT_PLUGIN_ID
    # The provenance says imported, not solved.
    assert listed[0]["spec"]["engine"] == "external"
    assert listed[0]["spec"]["physics"]["produced_by"] == "A contractor"

    result = client.get(f"/runs/{run_id}/result").json()
    artifacts = {item["artifact_type"]: item["artifact_id"] for item in result["artifacts"]}
    assert set(artifacts) == {"recovered_model", "mesh_geometry"}

    # The downstream pages work on it with no special case.
    distribution = client.get(
        f"/runs/{run_id}/artifacts/{artifacts['recovered_model']}/distribution"
    )
    assert distribution.status_code == 200
    assert distribution.json()["cell_count"] == 12

    sliced = client.get(f"/runs/{run_id}/artifacts/{artifacts['recovered_model']}/slice?normal=y")
    assert sliced.status_code == 200
    assert sliced.json()["values"]


@needs_discretize
def test_an_imported_run_survives_a_restart(tmp_path: Path) -> None:
    """The record and result are written where RunService rediscovers them."""
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    artifact_root = tmp_path / "artifacts"
    first = TestClient(create_app(RunService(artifact_root=artifact_root)))
    run_id = first.post("/datasets/external-model", json=_request(mesh_path, model_path)).json()[
        "run_id"
    ]

    reopened = TestClient(create_app(RunService(artifact_root=artifact_root)))
    listed = reopened.get("/runs").json()

    assert [record["spec"]["run_id"] for record in listed] == [run_id]
    assert reopened.get(f"/runs/{run_id}/result").json()["summary"]["imported"] is True


@needs_discretize
def test_air_cells_are_kept_when_no_inactive_value_is_declared(tmp_path: Path) -> None:
    """1e-8 is somebody else's convention, not a fact about the numbers."""
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post(
        "/datasets/external-model",
        json=_request(mesh_path, model_path, inactive_value=None),
    )

    assert response.status_code == 200
    assert response.json()["active_cell_count"] == 24
    assert response.json()["value_minimum"] == pytest.approx(AIR)


@needs_discretize
def test_a_model_left_entirely_inactive_is_refused(tmp_path: Path) -> None:
    """An inactive value that matches every cell means the wrong value was given."""
    import discretize

    directory = tmp_path / "release"
    directory.mkdir(parents=True)
    mesh = discretize.TensorMesh([np.full(2, 25.0), np.full(2, 25.0), np.full(2, 10.0)])
    mesh_path = directory / "uniform.msh"
    model_path = directory / "uniform.model"
    mesh.write_UBC(str(mesh_path))
    mesh.write_model_UBC(str(model_path), np.full(mesh.n_cells, 0.05))
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post(
        "/datasets/external-model",
        json=_request(mesh_path, model_path, inactive_value=0.05),
    )

    assert response.status_code == 422
    assert "inactive" in response.json()["detail"]


@needs_discretize
def test_units_must_be_dimensionally_possible_for_the_declared_quantity(tmp_path: Path) -> None:
    """A conductivity model declared in metres is a unit error, not a preference."""
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post(
        "/datasets/external-model", json=_request(mesh_path, model_path, units="m")
    )

    assert response.status_code == 422


@needs_discretize
def test_a_missing_file_is_reported_rather_than_raised(tmp_path: Path) -> None:
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post(
        "/datasets/external-model",
        json=_request(mesh_path, tmp_path / "release" / "absent.model"),
    )

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


@needs_discretize
def test_the_declared_unit_is_converted_not_relabelled(tmp_path: Path) -> None:
    """A model in mS/m must arrive as S/m, with the numbers actually changed."""
    mesh_path, model_path, _ = _ubc_fixture(tmp_path / "release")
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))

    response = client.post(
        "/datasets/external-model",
        json=_request(mesh_path, model_path, units="mS/m"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["units"] == "siemens / meter"
    assert body["value_minimum"] == pytest.approx(0.05e-3)
    stored = np.load(
        tmp_path / "artifacts" / str(UUID(body["run_id"])) / "recovered_model.npy",
        allow_pickle=False,
    )
    assert stored.min() == pytest.approx(0.05e-3)
