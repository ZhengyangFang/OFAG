"""Observations may arrive inline or as a path, and must import identically."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ofag.api.app import create_app
from ofag.core.schemas import GravityCsvImportRequest
from ofag.services.run_service import RunService

CONVENTION = {"crs": "LOCAL_CARTESIAN_METRIC"}
MAPPING: dict[str, object] = {
    "x_column": "easting",
    "y_column": "northing",
    "z_column": "elevation",
    "gravity_column": "gz",
    "default_uncertainty_percent": 1.0,
    "coordinate_unit": "m",
    "gravity_unit": "mGal",
    "coordinate_convention": CONVENTION,
}


def _survey(rows: int = 200) -> str:
    header = "easting,northing,elevation,gz\n"
    return header + "".join(
        f"{100 + i * 10},{200 + i * 5},12.5,{i * 0.01:.4f}\n" for i in range(rows)
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))


def test_the_same_csv_imports_identically_inline_and_from_disk(tmp_path: Path) -> None:
    """Two routes to the same numbers must not be two sets of results."""
    text = _survey()
    path = tmp_path / "survey.csv"
    path.write_text(text, encoding="utf-8")
    client = _client(tmp_path)

    inline = client.post(
        "/datasets/gravity-csv", json={"filename": "survey.csv", "csv_text": text, **MAPPING}
    )
    from_disk = client.post(
        "/datasets/gravity-csv",
        json={"filename": "survey.csv", "source_path": str(path), **MAPPING},
    )

    assert inline.status_code == 200, inline.text
    assert from_disk.status_code == 200, from_disk.text
    for field in (
        "row_count",
        "bounds_m",
        "gravity_min_mgal",
        "gravity_max_mgal",
        "recommended_uncertainty_mgal",
    ):
        assert inline.json()[field] == from_disk.json()[field], field


def test_a_request_names_exactly_one_source() -> None:
    """Two sources is ambiguous; none is nothing to read."""
    common = dict(filename="survey.csv", **MAPPING)
    with pytest.raises(ValidationError, match="not both and not neither"):
        GravityCsvImportRequest(csv_text=_survey(), source_path="survey.csv", **common)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="not both and not neither"):
        GravityCsvImportRequest(**common)  # type: ignore[arg-type]


def test_a_preview_reports_the_whole_file_not_just_what_it_returns(tmp_path: Path) -> None:
    """The mapper needs a header the browser never saw, and an honest total."""
    path = tmp_path / "survey.csv"
    path.write_text(_survey(500), encoding="utf-8")

    response = _client(tmp_path).post(
        "/datasets/csv-preview", json={"source_path": str(path), "max_rows": 5}
    )

    assert response.status_code == 200
    preview = response.json()
    assert preview["columns"] == ["easting", "northing", "elevation", "gz"]
    assert len(preview["rows"]) == 5
    assert preview["total_rows"] == 500
    assert preview["truncated"] is True


def test_a_byte_order_mark_does_not_become_part_of_the_first_column(tmp_path: Path) -> None:
    """Excel writes one, and it would make every mapping of that column fail."""
    path = tmp_path / "excel.csv"
    path.write_bytes(b"\xef\xbb\xbf" + _survey(3).encode("utf-8"))

    response = _client(tmp_path).post("/datasets/csv-preview", json={"source_path": str(path)})

    assert response.status_code == 200
    assert response.json()["columns"][0] == "easting"


def test_a_missing_path_is_reported_rather_than_raised(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/datasets/csv-preview", json={"source_path": str(tmp_path / "absent.csv")}
    )

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


def test_a_headerless_file_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text("", encoding="utf-8")

    response = _client(tmp_path).post("/datasets/csv-preview", json={"source_path": str(path)})

    assert response.status_code == 422
    assert "header" in response.json()["detail"]
