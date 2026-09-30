"""Rows of named values, from whatever file they arrived in."""

from pathlib import Path

import pytest

from ofag.formats.tables import Table, read_table, read_text_table, supported_suffixes


def test_a_quoted_line_break_does_not_split_a_row(tmp_path: Path) -> None:
    """The csv module needs `newline=""` to keep a quoted field whole."""
    path = tmp_path / "quoted.csv"
    path.write_text(
        'hole,rock,note\r\nA,norite,"first line\r\nsecond line"\r\nB,gabbro,short\r\n',
        encoding="utf-8",
        newline="",
    )

    table = read_table(path)

    assert len(table) == 2
    assert "second line" in table.rows[0]["note"]


def test_a_windows_encoded_file_is_read_and_the_encoding_reported(tmp_path: Path) -> None:
    path = tmp_path / "cp1252.csv"
    path.write_text("name\ncumulate ’A’\n", encoding="cp1252")

    table = read_table(path)

    assert table.encoding == "cp1252"
    assert table.rows[0]["name"].endswith("’")


def test_a_byte_order_mark_does_not_become_part_of_the_first_column(tmp_path: Path) -> None:
    """Excel writes one. Left in, every mapping of the first column fails."""
    path = tmp_path / "bom.csv"
    path.write_bytes("hole,depth\nA,10\n".encode("utf-8-sig"))

    table = read_table(path)

    assert table.columns == ("hole", "depth")


def test_a_tab_separated_file_is_read_by_its_extension(tmp_path: Path) -> None:
    """Rather than sniffed: a file whose first rows hold no commas would be read as a single
    column, and the caller who named it .tsv already said."""
    path = tmp_path / "tabbed.tsv"
    path.write_text("hole\tdepth\nA\t10\n", encoding="utf-8")

    table = read_table(path)

    assert table.columns == ("hole", "depth")
    assert table.rows[0]["depth"] == "10"


def test_an_unreadable_extension_says_what_can_be_read(tmp_path: Path) -> None:
    path = tmp_path / "survey.segy"
    path.write_bytes(b"\x00")

    with pytest.raises(ValueError, match="readable here"):
        read_table(path)

    assert ".csv" in supported_suffixes()


def test_text_already_in_hand_needs_no_file() -> None:
    table = read_text_table("a,b\n1,2\n")

    assert table.columns == ("a", "b")
    assert table.rows == ({"a": "1", "b": "2"},)


def test_separated_text_declares_no_coordinate_system(tmp_path: Path) -> None:
    """Which is why a caller importing one has to say what it is in."""
    path = tmp_path / "plain.csv"
    path.write_text("x,y\n1,2\n", encoding="utf-8")

    assert read_table(path).crs is None


@pytest.mark.skipif(".xlsx" not in supported_suffixes(), reason="openpyxl is not installed")
def test_an_excel_sheet_comes_back_as_text_like_every_other_format(tmp_path: Path) -> None:
    """A reader that sometimes returned a float and sometimes a string would make every
    importer handle both."""
    from openpyxl import Workbook

    path = tmp_path / "book.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["hole", "depth"])
    sheet.append(["A", 10.5])
    book.save(path)

    table = read_table(path)

    assert table.source_format == "excel"
    assert table.rows[0] == {"hole": "A", "depth": "10.5"}


@pytest.mark.skipif(".dbf" not in supported_suffixes(), reason="pyogrio is not installed")
def test_a_vector_attribute_table_brings_the_system_it_declares(tmp_path: Path) -> None:
    """A shapefile always carries a CRS and separated text never does, so an importer can
    check a caller's claim against the file's own."""
    import struct

    import numpy as np

    pyogrio = pytest.importorskip("pyogrio")

    def wkb_point(east: float, north: float) -> bytes:
        # Little-endian byte order, geometry type 1 (point), then the two coordinates.
        return struct.pack("<BIdd", 1, 1, east, north)

    path = tmp_path / "points.gpkg"
    pyogrio.raw.write(
        path,
        geometry=np.asarray([wkb_point(600_000.0, 5_030_000.0), wkb_point(601_000.0, 5_031_000.0)]),
        field_data=[np.asarray(["A", "B"]), np.asarray([10.0, 20.0])],
        fields=["hole", "depth"],
        field_mask=None,
        layer="points",
        geometry_type="Point",
        crs="EPSG:26912",
        driver="GPKG",
    )

    table = read_table(path)

    assert table.source_format == "vector"
    assert table.crs is not None and "26912" in table.crs
    assert [row["hole"] for row in table.rows] == ["A", "B"]


def test_a_table_reports_how_many_rows_it_holds() -> None:
    assert len(Table(columns=("a",), rows=({"a": "1"},), source_format="text", encoding=None)) == 1
