"""Reading a released drill log without believing what it looks like."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.schemas import CoordinateConvention
from ofag.services.borehole_import import BoreholeImportService, DrillLogImportRequest

CONVENTION = CoordinateConvention(crs="EPSG:26912")
FOOT_M = 0.3048


def _collars(path: Path, *, elevation: bool = False) -> Path:
    header = "hole,east,north,depth,az,incl" + (",elev" if elevation else "")
    rows = [
        # A hole at 500 ft, inclined; and a vertical one at 200 ft.
        "A,600000,5030000,500,225,-50" + (",2000" if elevation else ""),
        "B,601000,5031000,200,0,-90" + (",2100" if elevation else ""),
    ]
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _lithology(path: Path, encoding: str = "utf-8") -> Path:
    text = "\n".join(
        [
            "hole,from,to,rock",
            "A,0,40,overburden",
            "A,40,300,bronzite cumulate",
            "A,300,500,plagioclase cumulate",
            "B,0,200,bronzite cumulate",
        ]
    )
    path.write_text(text + "\n", encoding=encoding)
    return path


def _lithology_for(path_root: Path, hole: str, depth_ft: float) -> Path:
    """A one-interval log for a named hole, for the collar-only tests."""
    path = path_root / f"litho_{hole}.csv"
    path.write_text(f"hole,from,to,rock\n{hole},0,{depth_ft},norite\n", encoding="utf-8")
    return path


def _topography(path: Path) -> Path:
    east, north = np.meshgrid(
        np.linspace(599_000, 602_000, 12), np.linspace(5_029_000, 5_032_000, 12)
    )
    elevation = 2000.0 + 0.05 * (east - 599_000)
    np.savetxt(
        path,
        np.c_[east.ravel(), north.ravel(), elevation.ravel()],
        delimiter=",",
        header="x_m,y_m,z_m",
        comments="",
        fmt="%.6f",
    )
    return path


def _request(tmp_path: Path, **overrides: object) -> DrillLogImportRequest:
    fields: dict[str, object] = {
        "collars_path": str(_collars(tmp_path / "collars.csv")),
        "lithology_path": str(_lithology(tmp_path / "litho.csv")),
        "hole_id_column": "hole",
        "x_column": "east",
        "y_column": "north",
        "total_depth_column": "depth",
        "azimuth_column": "az",
        "inclination_column": "incl",
        "inclination_reference": "dip_negative_down",
        "interval_hole_id_column": "hole",
        "from_column": "from",
        "to_column": "to",
        "unit_column": "rock",
        "coordinate_unit": "m",
        "collar_depth_unit": "ft",
        "interval_depth_unit": "ft",
        "coordinate_convention": CONVENTION,
        "topography_path": str(_topography(tmp_path / "topo.csv")),
    }
    fields.update(overrides)
    return DrillLogImportRequest.model_validate(fields)


def test_depths_are_converted_from_the_unit_the_release_states(tmp_path: Path) -> None:
    """Every depth in the Stillwater logs is in feet and nothing in the column names says so."""
    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(tmp_path)
    )

    hole = next(item for item in imported.boreholes if item.name == "A")
    assert hole.total_depth_m == pytest.approx(500 * FOOT_M)
    deepest = max(interval.to_depth_m for interval in hole.intervals)
    assert deepest == pytest.approx(500 * FOOT_M)


def test_a_collar_with_no_elevation_is_placed_on_the_supplied_surface(tmp_path: Path) -> None:
    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(tmp_path)
    )

    assert imported.collar_elevation_source == "topography surface"
    hole = next(item for item in imported.boreholes if item.name == "A")
    # The surface rises 0.05 m per metre east of 599,000.
    assert hole.collar_z_m == pytest.approx(2050.0, abs=15.0)


def test_an_import_with_no_elevation_anywhere_is_refused(tmp_path: Path) -> None:
    """Rather than taking the collar to sea level, which would put every contact in the hole
    at an unknown depth and say nothing about it."""
    with pytest.raises(ValidationError, match="topography_path is required"):
        _request(tmp_path, topography_path=None)


def test_an_inclined_hole_states_its_attitude_and_a_vertical_one_keeps_the_flag(
    tmp_path: Path,
) -> None:
    """Check inclined and vertical borehole geometry."""
    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(tmp_path)
    )

    inclined = next(item for item in imported.boreholes if item.name == "A")
    vertical = next(item for item in imported.boreholes if item.name == "B")

    assert inclined.vertical is False
    # Logged as -50 from horizontal; OFAG stores 40 from vertical.
    assert [station.inclination_degrees for station in inclined.survey] == [40.0]
    assert vertical.vertical is True
    assert vertical.survey == ()
    # An inclined hole does not reach as deep as its along-hole length.
    _, _, elevation = inclined.position_at(inclined.total_depth_m)
    assert inclined.collar_z_m - elevation < inclined.total_depth_m


def test_the_inclination_reference_must_be_stated(tmp_path: Path) -> None:
    """Three conventions are in use and two of them are numerically indistinguishable: a hole
    logged at 50 is forty degrees off vertical under one and fifty under another, and
    nothing in the file says which."""
    with pytest.raises(ValidationError, match="inclination_reference is required"):
        _request(tmp_path, inclination_reference=None)


def test_a_dip_measured_positive_down_is_not_read_as_an_angle_off_vertical(
    tmp_path: Path,
) -> None:
    path = tmp_path / "collars_positive.csv"
    path.write_text(
        "hole,east,north,depth,az,incl\nA,600000,5030000,500,225,50\n", encoding="utf-8"
    )
    service = BoreholeImportService(import_root=tmp_path / "imports")

    positive = service.import_drill_logs(
        _request(tmp_path, collars_path=str(path), inclination_reference="dip_positive_down")
    )
    vertical = service.import_drill_logs(
        _request(tmp_path, collars_path=str(path), inclination_reference="from_vertical")
    )

    # Fifty below horizontal is forty off vertical, not fifty.
    assert positive.boreholes[0].survey[0].inclination_degrees == 40.0
    assert vertical.boreholes[0].survey[0].inclination_degrees == 50.0


def test_a_windows_encoded_table_is_read_and_the_encoding_is_reported(tmp_path: Path) -> None:
    """One of the five Stillwater lithology tables is cp1252 and nothing declares it."""
    path = tmp_path / "litho_cp1252.csv"
    path.write_text(
        "hole,from,to,rock\nA,0,500,bronzite cumulate ’A’\nB,0,200,norite\n",
        encoding="cp1252",
    )

    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(tmp_path, lithology_path=str(path))
    )

    assert imported.lithology_encoding == "cp1252"
    assert any("’" in name for name, _ in imported.vocabulary)


def test_two_tables_in_different_units_are_refused_rather_than_averaged(tmp_path: Path) -> None:
    """An interval deeper than the hole it is in is what a unit mismatch between the collar
    table and the log table looks like."""
    path = tmp_path / "litho_metres.csv"
    path.write_text("hole,from,to,rock\nA,0,500,norite\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not in the same unit"):
        BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
            _request(tmp_path, lithology_path=str(path), interval_depth_unit="m")
        )


def test_the_logged_vocabulary_comes_back_so_a_unit_map_can_be_written(tmp_path: Path) -> None:
    """Stillwater logs 104 distinct rock names over 1,077 intervals, which is a petrography
    and not a stratigraphy."""
    service = BoreholeImportService(import_root=tmp_path / "imports")

    unmapped = service.import_drill_logs(_request(tmp_path))
    assert dict(unmapped.vocabulary) == {
        "bronzite cumulate": 2,
        "overburden": 1,
        "plagioclase cumulate": 1,
    }
    assert {unit.name for unit in unmapped.units} == {
        "bronzite cumulate",
        "overburden",
        "plagioclase cumulate",
    }

    mapped = service.import_drill_logs(
        _request(
            tmp_path,
            unit_map={
                "bronzite cumulate": "Ultramafic series",
                "plagioclase cumulate": "Banded series",
            },
            exclude_units=("overburden",),
        )
    )
    assert {unit.name for unit in mapped.units} == {"Ultramafic series", "Banded series"}
    # The excluded rows are reported rather than silently missing.
    assert any("overburden" in reason for _, reason in mapped.dropped)


def test_a_unit_keeps_its_colour_across_imports(tmp_path: Path) -> None:
    """A colour that changed when a hole was added would make two runs of the same model look
    like different ground."""
    service = BoreholeImportService(import_root=tmp_path / "imports")

    first = service.import_drill_logs(_request(tmp_path))
    second = service.import_drill_logs(_request(tmp_path))

    assert {unit.name: unit.colour for unit in first.units} == {
        unit.name: unit.colour for unit in second.units
    }


def test_the_canonical_copy_lands_under_the_root_it_was_given(tmp_path: Path) -> None:
    root = tmp_path / "imports"
    imported = BoreholeImportService(import_root=root).import_drill_logs(_request(tmp_path))

    assert Path(imported.canonical_path).is_relative_to(root)
    assert Path(imported.canonical_path).is_file()


def test_collars_in_another_system_are_projected_into_the_project(tmp_path: Path) -> None:
    """The Stillwater collars are latitude and longitude and OFAG works in metres, so the
    system is stated and the projection happens at the boundary -- the same rule the unit
    policy follows."""
    path = tmp_path / "collars_geographic.csv"
    path.write_text(
        "hole,east,north,depth,az,incl\nCC1,-110.028343,45.387322,479,225,-50\n",
        encoding="utf-8",
    )

    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(
            tmp_path,
            collars_path=str(path),
            coordinate_unit=None,
            source_crs="EPSG:4326",
            lithology_path=str(_lithology_for(tmp_path, "CC1", 479)),
        )
    )

    hole = imported.boreholes[0]
    # Inside the airborne survey that flew over it, measured from that file.
    assert 555_850 <= hole.collar_x_m <= 600_939
    assert 5_019_262 <= hole.collar_y_m <= 5_042_484


def test_a_unit_and_a_system_cannot_both_describe_the_collars(tmp_path: Path) -> None:
    """A CRS already states its own unit, so declaring both invites them to disagree and
    gives the reader no way to tell which was meant."""
    with pytest.raises(ValidationError, match="not both"):
        _request(tmp_path, source_crs="EPSG:4326")
    with pytest.raises(ValidationError, match="not neither"):
        _request(tmp_path, coordinate_unit=None)


def test_an_elevation_column_needs_its_own_unit(tmp_path: Path) -> None:
    """A horizontal CRS says nothing about the vertical, and US releases routinely give
    degrees across and feet up."""
    with pytest.raises(ValidationError, match="elevation_unit is required"):
        _request(tmp_path, z_column="elev")


def test_a_second_import_reuses_the_units_the_first_made(tmp_path: Path) -> None:
    """A release published as four area files is one borehole dataset."""
    service = BoreholeImportService(import_root=tmp_path / "imports")

    first = service.import_drill_logs(
        _request(tmp_path, unit_map={"bronzite cumulate": "Ultramafic series"})
    )
    second = service.import_drill_logs(
        _request(
            tmp_path,
            unit_map={"bronzite cumulate": "Ultramafic series"},
            known_units=first.units,
        )
    )

    by_name = {unit.name: unit.unit_id for unit in first.units}
    assert {unit.name: unit.unit_id for unit in second.units} == by_name


def test_a_logged_description_is_refused_as_a_unit_name(tmp_path: Path) -> None:
    """Stillwater logs names like "plagioclase cumulate/plagioclase bronzite cumulate
    interlayered with olivine plagioclase cumulate" -- an interval's description, not a
    unit in a pile."""
    sentence = "plagioclase cumulate interlayered with olivine plagioclase cumulate and norite too"
    path = tmp_path / "litho_long.csv"
    path.write_text(f"hole,from,to,rock\nA,0,500,{sentence}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="descriptions rather than unit names"):
        BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
            _request(tmp_path, lithology_path=str(path))
        )


def test_a_raster_can_be_the_topography_and_says_so(tmp_path: Path) -> None:
    """The DEM is a GeoTIFF; turning one into a canonical point cloud would be one and a half
    million rows to answer thirty questions."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "dem.tif"
    elevation = np.full((40, 40), 2000.0, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=40,
        width=40,
        count=1,
        dtype="float32",
        crs="EPSG:26912",
        transform=from_origin(599_000, 5_032_000, 100.0, 100.0),
    ) as target:
        target.write(elevation, 1)

    imported = BoreholeImportService(import_root=tmp_path / "imports").import_drill_logs(
        _request(tmp_path, topography_path=str(path), elevation_unit="m")
    )

    assert imported.collar_elevation_source == "raster dem.tif"
    assert all(hole.collar_z_m == pytest.approx(2000.0) for hole in imported.boreholes)


def test_a_canonical_topography_csv_takes_no_elevation_unit(tmp_path: Path) -> None:
    """Its columns are named for metres, so a unit would be a second opinion."""
    with pytest.raises(ValidationError, match="nothing to describe"):
        _request(tmp_path, elevation_unit="ft")
