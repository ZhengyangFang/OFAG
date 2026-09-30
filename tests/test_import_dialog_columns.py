"""Showing an operator the columns their file actually has."""

from pathlib import Path

import pytest

from ofag.desktop.dialogs.importers import header_of


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


class TestReadingAHeader:
    def test_a_comma_separated_header(self, tmp_path) -> None:
        source = _write(tmp_path / "a.csv", "x,y,z,gravity\n1,2,3,4\n")

        assert header_of(source) == ("x", "y", "z", "gravity")

    def test_a_tab_separated_header(self, tmp_path) -> None:
        """Which is what the Utah FORGE station file is."""
        source = _write(tmp_path / "a.txt", "name\tEasting\tNorthing\tgCBGA\nF1\t1\t2\t3\n")

        assert header_of(source) == ("name", "Easting", "Northing", "gCBGA")

    def test_a_semicolon_separated_header(self, tmp_path) -> None:
        source = _write(tmp_path / "a.csv", "east;north;value\n1;2;3\n")

        assert header_of(source) == ("east", "north", "value")

    def test_quotes_and_spaces_are_stripped(self, tmp_path) -> None:
        source = _write(tmp_path / "a.csv", '"x" , "y" , "gravity"\n1,2,3\n')

        assert header_of(source) == ("x", "y", "gravity")

    def test_a_byte_order_mark_does_not_become_part_of_the_first_name(self, tmp_path) -> None:
        """Excel writes one, and `x` with a BOM in front matches nothing."""
        source = _write(tmp_path / "a.csv", "x,y,z\n1,2,3\n", encoding="utf-8-sig")

        assert header_of(source) == ("x", "y", "z")

    def test_only_the_first_line_is_read(self, tmp_path) -> None:
        """A line-data file can be hundreds of megabytes, and this runs while the operator
        waits for a dialog to open."""
        source = _write(tmp_path / "a.csv", "x,y\n" + "1,2\n" * 50_000)

        assert header_of(source) == ("x", "y")

    def test_a_file_that_is_not_there_gives_nothing(self, tmp_path) -> None:
        assert header_of(tmp_path / "absent.csv") == ()

    def test_an_empty_file_gives_nothing(self, tmp_path) -> None:
        assert header_of(_write(tmp_path / "a.csv", "")) == ()

    def test_a_binary_file_gives_nothing_rather_than_raising(self, tmp_path) -> None:
        """A dialog opening on a SEG-Y must not fall over reading its header."""
        source = tmp_path / "a.sgy"
        source.write_bytes(bytes(range(256)) * 4)

        assert header_of(source) == ()


class TestThePicker:
    @staticmethod
    def _dialog(tmp_path: Path, header: str):
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        from ofag.core.schemas import DatasetKind
        from ofag.desktop.dialogs.importers import ImportDialog

        QApplication.instance() or QApplication([])
        source = _write(tmp_path / "survey.csv", header + "\n1,2,3,4\n")
        return ImportDialog(DatasetKind.GRAVITY, source)

    def test_the_files_own_columns_are_offered(self, tmp_path) -> None:
        dialog = self._dialog(tmp_path, "Easting,Northing,NAVD88,gCBGA")

        offered = dialog._fields["x_column"]
        assert [offered.itemText(i) for i in range(1, offered.count())] == [
            "Easting",
            "Northing",
            "NAVD88",
            "gCBGA",
        ]

    def test_nothing_is_preselected_when_no_column_has_the_canonical_name(self, tmp_path) -> None:
        """A dropdown that guessed which column is the elevation would be the same silent
        assumption as a text box pre-filled with one, and the importer would take the
        guess without complaint."""
        dialog = self._dialog(tmp_path, "Easting,Northing,NAVD88,gCBGA")

        assert dialog._value("x_column") == ""
        assert dialog._value("gravity_column") == ""

    def test_an_exact_match_is_preselected(self, tmp_path) -> None:
        """A file already written the canonical way should just import."""
        dialog = self._dialog(tmp_path, "X,Y,Z,Gravity")

        assert dialog._value("x_column") == "X"
        assert dialog._value("gravity_column") == "Gravity"

    def test_a_typed_name_is_kept(self, tmp_path) -> None:
        """The box stays editable, so a file this cannot parse is still usable."""
        dialog = self._dialog(tmp_path, "Easting,Northing,NAVD88,gCBGA")
        dialog._fields["z_column"].setCurrentText("NAVD88")

        assert dialog._value("z_column") == "NAVD88"
