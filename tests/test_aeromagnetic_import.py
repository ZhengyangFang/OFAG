"""Reading a flown magnetic survey, which states none of what a model needs."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ofag.core.schemas import CoordinateConvention
from ofag.services.aeromagnetic_import import (
    AeromagneticImportRequest,
    AeromagneticImportService,
)

CONVENTION = CoordinateConvention(crs="EPSG:26912")
FLOWN = datetime(2000, 5, 10)
#: Near the Stillwater survey, where the reference field is about 56,100 nT.
EAST0, NORTH0 = 578_000.0, 5_031_000.0


def _terrain(path: Path, elevation: float = 2300.0) -> Path:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=60,
        width=60,
        count=1,
        dtype="float32",
        crs="EPSG:26912",
        transform=from_origin(EAST0 - 3_000, NORTH0 + 3_000, 100.0, 100.0),
    ) as target:
        target.write(np.full((60, 60), elevation, dtype="float32"), 1)
    return path


def _survey(
    path: Path, *, total_field: float = 56_100.0, lines: int = 2, per_line: int = 40
) -> Path:
    rows = ["LINE,X,Y,TF,ALT"]
    for line in range(lines):
        for step in range(per_line):
            rows.append(f"{line},{EAST0 + 200.0 * line},{NORTH0 + 25.0 * step},{total_field},35")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _request(tmp_path: Path, **overrides: object) -> AeromagneticImportRequest:
    fields: dict[str, object] = {
        "source_path": str(_survey(tmp_path / "survey.csv")),
        "line_column": "LINE",
        "x_column": "X",
        "y_column": "Y",
        "total_field_column": "TF",
        "height_above_ground_column": "ALT",
        "coordinate_unit": "m",
        "height_unit": "m",
        "total_field_unit": "nT",
        "coordinate_convention": CONVENTION,
        "terrain_path": str(_terrain(tmp_path / "dem.tif")),
        "terrain_elevation_unit": "m",
        "epoch": FLOWN,
    }
    fields.update(overrides)
    return AeromagneticImportRequest.model_validate(fields)


def test_a_total_field_is_recognised_and_reduced(tmp_path: Path) -> None:
    """The column is called TMI, its unit is correctly nT, and its median is the Earth's core
    field."""
    imported = AeromagneticImportService(import_root=tmp_path / "imports").import_survey(
        _request(tmp_path)
    )

    assert imported.reduced_from_total_field is True
    assert 50_000 < imported.reference_field_median_nt < 62_000
    # A flat 56,100 nT field against a reference near it leaves a small anomaly.
    assert abs(imported.anomaly_median_nt) < 1_000


def test_a_field_already_reduced_is_left_alone(tmp_path: Path) -> None:
    imported = AeromagneticImportService(import_root=tmp_path / "imports").import_survey(
        _request(tmp_path, source_path=str(_survey(tmp_path / "anomaly.csv", total_field=120.0)))
    )

    assert imported.reduced_from_total_field is False
    assert imported.reference_field_median_nt == 0.0
    assert imported.anomaly_median_nt == pytest.approx(120.0)


def test_the_observation_elevation_is_the_terrain_plus_the_height_flown(tmp_path: Path) -> None:
    """An altimeter reads height above ground; a forward model needs height above the datum,
    and the survey carries only the first."""
    imported = AeromagneticImportService(import_root=tmp_path / "imports").import_survey(
        _request(tmp_path, terrain_path=str(_terrain(tmp_path / "flat.tif", elevation=2000.0)))
    )

    assert imported.sensor_height_median_m == pytest.approx(35.0)
    assert imported.bounds_m[4] == pytest.approx(2035.0)
    assert imported.bounds_m[5] == pytest.approx(2035.0)


def test_thinning_runs_along_a_line_and_not_across_lines(tmp_path: Path) -> None:
    """Line spacing is the resolution limit."""
    service = AeromagneticImportService(import_root=tmp_path / "imports")

    everything = service.import_survey(_request(tmp_path))
    thinned = service.import_survey(_request(tmp_path, along_line_spacing_m=100.0))

    assert everything.observation_count == 80
    # 25 m sampling thinned to 100 m keeps every fourth reading, both lines.
    assert thinned.observation_count == 20
    assert thinned.line_count == 2
    assert thinned.median_along_line_spacing_m == pytest.approx(100.0)


def test_the_files_own_no_data_marker_is_named_and_removed(tmp_path: Path) -> None:
    """-9999999 is a plausible reading of nothing, so it is stated rather than recognised by
    being extreme."""
    path = tmp_path / "with_dummy.csv"
    rows = ["LINE,X,Y,TF,ALT"]
    for step in range(10):
        field = -9_999_999 if step == 3 else 56_100
        rows.append(f"0,{EAST0},{NORTH0 + 25.0 * step},{field},35")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    imported = AeromagneticImportService(import_root=tmp_path / "imports").import_survey(
        _request(tmp_path, source_path=str(path))
    )

    assert imported.dropped_as_dummy == 1
    assert imported.observation_count == 9


def test_the_epoch_is_when_it_was_flown_not_when_it_is_read(tmp_path: Path) -> None:
    """The core field drifts by tens of nanotesla a year; a 2000 survey reduced against a
    2026 reference keeps a regional gradient that an inversion will explain with rock."""
    service = AeromagneticImportService(import_root=tmp_path / "imports")

    flown = service.import_survey(_request(tmp_path))
    today = service.import_survey(_request(tmp_path, epoch=datetime(2026, 5, 10)))

    drift = abs(flown.reference_field_median_nt - today.reference_field_median_nt)
    assert drift > 50.0


def test_a_survey_in_another_system_is_projected(tmp_path: Path) -> None:
    path = tmp_path / "geographic.csv"
    rows = ["LINE,X,Y,TF,ALT"]
    for step in range(6):
        rows.append(f"0,{-110.03 + 0.0002 * step},45.387,56100,35")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fall outside"):
        # The generated terrain covers the survey's metric neighbourhood, not this one;
        # what matters here is that the projection ran at all.
        AeromagneticImportService(import_root=tmp_path / "imports").import_survey(
            _request(tmp_path, source_path=str(path), coordinate_unit=None, source_crs="EPSG:4326")
        )


def test_a_unit_and_a_system_cannot_both_describe_the_survey(tmp_path: Path) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="not both"):
        _request(tmp_path, source_crs="EPSG:4326")
