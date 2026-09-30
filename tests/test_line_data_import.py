"""Layered-earth models delivered along flight lines."""

from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ofag.api.app import create_app
from ofag.services.line_data_import import IMPORT_PLUGIN_ID, MAX_SECTION_VALUES
from ofag.services.run_service import RunService

LAYERS = 5
CONVENTION = {"crs": "EPSG:28351"}


def _release(
    directory: Path, per_line: dict[str, int], thickness_drift: float = 0.0
) -> tuple[Path, Path]:
    """A small file in the shape the real release uses."""
    directory.mkdir(parents=True, exist_ok=True)
    names = ["uniqueid", "survey", "line", "easting", "northing", "elevation", "nlayers"]
    names += [f"conductivity:{index + 1}" for index in range(LAYERS)]
    names += [f"thickness:{index + 1}" for index in range(LAYERS - 1)]
    names += ["PhiD"]
    header = directory / "release.hdr"
    header.write_text(
        "".join(f"{index + 1}\t{name}\n" for index, name in enumerate(names))
        + f"{len(names) + 1}\tCarriage return\n",
        encoding="utf-8",
    )

    rows: list[str] = []
    unique = 0
    for line, count in per_line.items():
        for step in range(count):
            unique += 1
            thickness = [10.0 + index * 5.0 + step * thickness_drift for index in range(LAYERS - 1)]
            conductivity = [0.001 * (index + 1) * (1 + step) for index in range(LAYERS)]
            fields = [
                f"{unique:8d}",
                "1168",
                f"{line:>8s}",
                f"{400000.0 + step * 25.0:12.1f}",
                f"{7500000.0 + step * 2.0:14.1f}",
                f"{300.0 - step * 0.5:9.2f}",
                f"{LAYERS:4d}",
                *[f"{value:12.6f}" for value in conductivity],
                *[f"{value:10.4f}" for value in thickness],
                "1.02",
            ]
            rows.append(" ".join(fields))
    data = directory / "release.dat"
    data.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return data, header


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))


def test_an_inventory_lists_the_lines_without_parsing_the_models(tmp_path: Path) -> None:
    """A release names its lines nowhere but inside itself."""
    data, header = _release(tmp_path / "release", {"10010": 40, "10020": 7})

    response = _client(tmp_path).post(
        "/datasets/line-data/inventory",
        json={"data_path": str(data), "header_path": str(header)},
    )

    assert response.status_code == 200, response.text
    inventory = response.json()
    assert inventory["total_soundings"] == 47
    assert inventory["layer_count"] == LAYERS
    # Largest first: with hundreds of lines, the one worth opening is the long one.
    assert [item["line"] for item in inventory["lines"]] == ["10010", "10020"]
    first = inventory["lines"][0]
    assert first["sounding_count"] == 40
    assert first["easting_min_m"] == pytest.approx(400000.0)
    assert first["easting_max_m"] == pytest.approx(400000.0 + 39 * 25.0)
    # The trailing "Carriage return" entry is not a column.
    assert "Carriage return" not in inventory["columns"]


def test_one_line_imports_as_a_run_the_batch_section_view_can_read(tmp_path: Path) -> None:
    data, header = _release(tmp_path / "release", {"10010": 12, "10020": 5})
    client = _client(tmp_path)

    response = client.post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "10010",
            "name": "Line 10010",
            "conductivity_units": "S/m",
            "coordinate_convention": CONVENTION,
            "max_soundings": 100,
        },
    )

    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["sounding_count"] == 12
    assert imported["imported_sounding_count"] == 12
    assert imported["decimation"] == 1
    assert imported["layer_count"] == LAYERS
    # Layer tops accumulate the thicknesses; the last layer is a half-space.
    assert imported["deepest_layer_top_m"] == pytest.approx(10 + 15 + 20 + 25)

    run_id = imported["run_id"]
    listed = client.get("/runs").json()
    assert listed[0]["spec"]["plugin_id"] == IMPORT_PLUGIN_ID
    assert listed[0]["spec"]["engine"] == "external"

    section = client.get(f"/runs/{run_id}/tdem-batch-section")
    assert section.status_code == 200, section.text
    body = section.json()
    assert len(body["sounding_ids"]) == 12
    assert len(body["layer_top_depth_m"]) == LAYERS
    assert body["layer_top_depth_m"][0] == 0.0
    assert len(body["conductivity_s_m"][0]) == LAYERS

    # And as a plain model, so the histogram and the site model read it too.
    result = client.get(f"/runs/{run_id}/result").json()
    artifacts = {item["artifact_type"]: item["artifact_id"] for item in result["artifacts"]}
    assert set(artifacts) >= {"stitched_conductivity_section", "recovered_model", "mesh_geometry"}
    distribution = client.get(
        f"/runs/{run_id}/artifacts/{artifacts['recovered_model']}/distribution"
    )
    assert distribution.status_code == 200
    assert distribution.json()["cell_count"] == 12 * LAYERS


def test_a_long_line_is_thinned_and_says_by_how_much(tmp_path: Path) -> None:
    """Which soundings were dropped is part of what the section is."""
    data, header = _release(tmp_path / "release", {"10010": 100})

    imported = (
        _client(tmp_path)
        .post(
            "/datasets/line-data",
            json={
                "data_path": str(data),
                "header_path": str(header),
                "line": "10010",
                "name": "Line 10010",
                "coordinate_convention": CONVENTION,
                "max_soundings": 25,
            },
        )
        .json()
    )

    assert imported["sounding_count"] == 100
    assert imported["decimation"] == 4
    assert imported["imported_sounding_count"] == 25


def test_asking_for_more_than_the_section_can_hold_is_refused_with_the_number(
    tmp_path: Path,
) -> None:
    """The viewer's own limit, said before a minute is spent reading."""
    data, header = _release(tmp_path / "release", {"10010": 10})

    response = _client(tmp_path).post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "10010",
            "name": "Line 10010",
            "coordinate_convention": CONVENTION,
            "max_soundings": MAX_SECTION_VALUES,
        },
    )

    assert response.status_code == 422
    assert str(MAX_SECTION_VALUES // LAYERS) in response.json()["detail"]


def test_models_that_do_not_share_a_depth_axis_are_refused(tmp_path: Path) -> None:
    """Resampling onto the first sounding's layers would move every contact."""
    data, header = _release(tmp_path / "release", {"10010": 6}, thickness_drift=1.5)

    response = _client(tmp_path).post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "10010",
            "name": "Line 10010",
            "coordinate_convention": CONVENTION,
        },
    )

    assert response.status_code == 422
    assert "depth axis" in response.json()["detail"]


def test_a_line_that_is_not_in_the_file_is_refused_by_name(tmp_path: Path) -> None:
    data, header = _release(tmp_path / "release", {"10010": 4})

    response = _client(tmp_path).post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "99999",
            "name": "Absent",
            "coordinate_convention": CONVENTION,
        },
    )

    assert response.status_code == 422
    assert "99999" in response.json()["detail"]


def test_the_declared_unit_is_converted_not_relabelled(tmp_path: Path) -> None:
    data, header = _release(tmp_path / "release", {"10010": 3})
    client = _client(tmp_path)

    imported = client.post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "10010",
            "name": "Line 10010",
            "conductivity_units": "mS/m",
            "coordinate_convention": CONVENTION,
        },
    ).json()

    assert imported["units"] == "siemens / meter"
    assert imported["value_minimum"] == pytest.approx(0.001e-3)
    stored = np.load(
        tmp_path / "artifacts" / str(UUID(imported["run_id"])) / "recovered_model.npy",
        allow_pickle=False,
    )
    assert stored.min() == pytest.approx(0.001e-3)


def test_a_log_histogram_may_leave_out_non_positive_cells_only_when_asked(tmp_path: Path) -> None:
    """A 1D inversion floors layers it cannot constrain; the model reaches zero."""
    data, header = _release(tmp_path / "release", {"10010": 3})
    client = _client(tmp_path)
    imported = client.post(
        "/datasets/line-data",
        json={
            "data_path": str(data),
            "header_path": str(header),
            "line": "10010",
            "name": "Line 10010",
            "coordinate_convention": CONVENTION,
        },
    ).json()
    run_id = imported["run_id"]
    artifacts = {
        item["artifact_type"]: item["artifact_id"]
        for item in client.get(f"/runs/{run_id}/result").json()["artifacts"]
    }
    path = tmp_path / "artifacts" / str(UUID(run_id)) / "recovered_model.npy"
    values = np.load(path, allow_pickle=False)
    values[0] = 0.0
    np.save(path, values)
    url = f"/runs/{run_id}/artifacts/{artifacts['recovered_model']}/distribution?log_scale=true"

    refused = client.get(url)
    assert refused.status_code == 422
    assert "exclude_non_positive" in refused.json()["detail"]

    allowed = client.get(url + "&exclude_non_positive=true")
    assert allowed.status_code == 200
    assert allowed.json()["excluded_non_positive"] == 1
    assert allowed.json()["cell_count"] == values.size - 1
