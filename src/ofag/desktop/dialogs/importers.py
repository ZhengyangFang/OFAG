"""Asking for everything a file does not say about itself."""

import csv
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ofag.core.schemas import CoordinateConvention, DatasetKind
from ofag.desktop.session import Session

#: Units offered per quantity.
_LENGTH_UNITS = ("m", "km", "ft", "dm", "cm")
_GRAVITY_UNITS = ("mGal", "uGal", "m/s^2")
_FIELD_UNITS = ("nT", "T")

#: What a column field shows when the file's own header cannot be read, or when none of
#: its columns is the canonical name.
_CHOOSE = "— choose a column —"

#: Separators to try when reading a header, strongest first.
_DELIMITERS = ",;\t|"
_FALLBACK_DELIMITERS = " "


def header_of(source: Path) -> tuple[str, ...]:
    """The column names a delimited text file declares, or none."""
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            first = handle.readline()
    except (OSError, UnicodeDecodeError):
        return ()
    if not first.strip():
        return ()
    delimiter = ","
    for candidates in (_DELIMITERS, _FALLBACK_DELIMITERS):
        try:
            delimiter = csv.Sniffer().sniff(first, delimiters=candidates).delimiter
        except csv.Error:
            continue
        break
    names = [name.strip().strip('"') for name in first.splitlines()[0].split(delimiter)]
    return tuple(name for name in names if name)


class ImportDialog(QDialog):
    """Collect the declaration for one file, then call the right importer."""

    def __init__(self, kind: DatasetKind, source: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import {kind.value}")
        self.setMinimumWidth(560)
        self._kind = kind
        self._source = source

        self._name = QLineEdit(source.stem)
        self._form = QFormLayout()
        self._form.addRow("Name in this project", self._name)
        self._form.addRow("File", QLabel(str(source)))

        self._columns = header_of(source)
        self._fields: dict[str, QWidget] = {}
        builder = {
            DatasetKind.GRAVITY: self._build_gravity,
            DatasetKind.MAGNETICS: self._build_magnetics,
            DatasetKind.AEM: self._build_aem,
            DatasetKind.MT: self._build_mt,
            DatasetKind.TOPOGRAPHY: self._build_topography,
            DatasetKind.ERT: self._build_ert,
            DatasetKind.SEISMIC: self._build_segy,
        }[kind]
        builder()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(self._form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def dataset_name(self) -> str:
        return self._name.text().strip() or self._source.stem

    # -- field helpers ------------------------------------------------------

    def _text(self, key: str, label: str, default: str = "", tip: str = "") -> None:
        widget = QLineEdit(default)
        if tip:
            widget.setToolTip(tip)
        self._fields[key] = widget
        self._form.addRow(label, widget)

    def _column(self, key: str, label: str, canonical: str) -> None:
        """One column of the file, chosen from the ones it actually has."""
        if not self._columns:
            self._text(key, label, canonical)
            return
        widget = QComboBox()
        widget.setEditable(True)
        widget.addItem(_CHOOSE)
        widget.addItems(self._columns)
        match = [name for name in self._columns if name.casefold() == canonical.casefold()]
        widget.setCurrentText(match[0] if match else _CHOOSE)
        widget.setToolTip(f"Columns in {self._source.name}: {', '.join(self._columns)}")
        self._fields[key] = widget
        self._form.addRow(label, widget)

    def _choice(self, key: str, label: str, options: tuple[str, ...], tip: str = "") -> None:
        widget = QComboBox()
        widget.setEditable(True)
        widget.addItems(options)
        if tip:
            widget.setToolTip(tip)
        self._fields[key] = widget
        self._form.addRow(label, widget)

    def _number(self, key: str, label: str, value: float, low: float, high: float) -> None:
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setDecimals(4)
        widget.setValue(value)
        self._fields[key] = widget
        self._form.addRow(label, widget)

    def _integer(self, key: str, label: str, value: int, low: int, high: int) -> None:
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        self._fields[key] = widget
        self._form.addRow(label, widget)

    def _value(self, key: str) -> Any:
        widget = self._fields[key]
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            text = widget.currentText().strip()
            # The placeholder is not a column name, and passing it on would reach the
            # importer as one and be reported as missing.
            return "" if text == _CHOOSE else text
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        if isinstance(widget, QSpinBox):
            return int(widget.value())
        raise TypeError(f"no reader for {type(widget).__name__}")

    # -- per-kind forms -----------------------------------------------------

    def _build_columns(self, quantity: str, units: tuple[str, ...]) -> None:
        self._column("x_column", "Easting column", "x")
        self._column("y_column", "Northing column", "y")
        self._column("z_column", "Elevation column", "z")
        self._column(f"{quantity}_column", f"{quantity.capitalize()} column", quantity)
        self._choice(
            "coordinate_unit",
            "Coordinate unit",
            _LENGTH_UNITS,
            "Never inferred. A survey read as metres that was written in feet "
            "is wrong by a factor of three and looks entirely plausible.",
        )
        self._choice(f"{quantity}_unit", f"{quantity.capitalize()} unit", units)

    def _build_gravity(self) -> None:
        self._build_columns("gravity", _GRAVITY_UNITS)
        self._text("uncertainty_column", "Uncertainty column (optional)", "")
        self._number("default_uncertainty_percent", "Default uncertainty", 2.0, 0.0, 100.0)

    def _build_magnetics(self) -> None:
        self._build_columns("tmi", _FIELD_UNITS)
        self._text("uncertainty_column", "Uncertainty column (optional)", "")
        self._number("default_uncertainty_percent", "Default uncertainty", 2.0, 0.0, 100.0)

    def _build_aem(self) -> None:
        self._text("sounding_id_column", "Sounding id column", "sounding_id")
        self._text("x_column", "Easting column", "x")
        self._text("y_column", "Northing column", "y")
        self._text("z_column", "Elevation column", "z")
        self._text("time_column", "Time column", "time_s")
        self._text("response_column", "Response column", "dbdt")
        self._choice("coordinate_unit", "Coordinate unit", _LENGTH_UNITS)
        self._choice("time_unit", "Time unit", ("s", "ms", "us"))
        self._choice("response_unit", "Response unit", ("V/m^2", "T/s"))

    def _build_topography(self) -> None:
        self._text("x_column", "Easting column", "x")
        self._text("y_column", "Northing column", "y")
        self._text("z_column", "Elevation column", "z")
        self._choice("coordinate_unit", "Coordinate unit", _LENGTH_UNITS)

    def _build_mt(self) -> None:
        self._choice(
            "impedance_component", "Impedance component", ("xy", "yx", "determinant", "average")
        )
        self._text("exclude_name_fragments", "Skip names containing", "_bvv")
        self._choice("remote_reference", "Remote reference", ("yes", "no"))
        self._number("maximum_skew", "Maximum phase tensor skew (degrees)", 3.0, 0.1, 45.0)
        self._number("uncertainty_floor", "Minimum relative uncertainty", 0.02, 0.0001, 1.0)

    def _build_ert(self) -> None:
        from ofag.services.ert_import import SUPPORTED_INSTRUMENTS

        self._choice(
            "instrument",
            "Instrument format",
            SUPPORTED_INSTRUMENTS,
            "BERT is pyGIMLi's unified format and is read by pyGIMLi itself, "
            "which is the engine that will invert it. The rest are acquisition "
            "formats only the vendor parsers know.",
        )
        self._choice("coordinate_unit", "Coordinate unit", _LENGTH_UNITS)
        self._text("electrode_file", "Separate electrode file (optional)", "")

    def _build_segy(self) -> None:
        from ofag.services.segy_import import STANDARD_HEADER_BYTES

        self._integer(
            "source_x_byte", "Source easting byte", STANDARD_HEADER_BYTES["source_x"], 1, 233
        )
        self._integer(
            "source_y_byte", "Source northing byte", STANDARD_HEADER_BYTES["source_y"], 1, 233
        )
        self._integer(
            "receiver_x_byte", "Receiver easting byte", STANDARD_HEADER_BYTES["receiver_x"], 1, 233
        )
        self._integer(
            "receiver_y_byte", "Receiver northing byte", STANDARD_HEADER_BYTES["receiver_y"], 1, 233
        )
        self._choice(
            "coordinate_scalar",
            "Coordinate scalar",
            ("header", "1", "0.1", "0.01", "10"),
            "Byte 71 multiplies when positive and divides when negative. It "
            "carries a power of ten, not a unit, so a survey stored in "
            "decimetres reads ten times too large even when the scalar is "
            "applied correctly.",
        )
        self._choice(
            "coordinate_unit",
            "Coordinate unit",
            _LENGTH_UNITS,
            "SEG-Y's own flag says only 'length' and does not distinguish "
            "metres from feet. Soda Lake is stored in decimetres and says so "
            "nowhere.",
        )

    # -- calling the importer ----------------------------------------------

    def run(self, session: Session) -> dict[str, Any]:
        """Import the file and return the importer's own result."""
        convention = session.record.coordinate_convention
        handler = {
            DatasetKind.GRAVITY: self._run_gravity,
            DatasetKind.MAGNETICS: self._run_magnetics,
            DatasetKind.AEM: self._run_aem,
            DatasetKind.MT: self._run_mt,
            DatasetKind.TOPOGRAPHY: self._run_topography,
            DatasetKind.ERT: self._run_ert,
            DatasetKind.SEISMIC: self._run_segy,
        }[self._kind]
        imported = handler(session, convention)
        return imported if isinstance(imported, dict) else _as_payload(imported)

    def _run_mt(self, session: Session, convention: CoordinateConvention) -> dict[str, Any]:
        from ofag.services.mt_import import MtImportRequest

        imported = session.mt_imports.import_edi_directory(
            MtImportRequest(
                source_directory=str(self._source),
                coordinate_convention=convention,
                exclude_name_fragments=tuple(
                    part.strip()
                    for part in self._value("exclude_name_fragments").split(",")
                    if part.strip()
                ),
                remote_reference=self._value("remote_reference") == "yes",
                impedance_component=self._value("impedance_component"),
                maximum_phase_tensor_skew_degrees=self._value("maximum_skew"),
                minimum_relative_uncertainty=self._value("uncertainty_floor"),
            )
        )
        if not imported.soundings:
            raise ValueError("No MT sites passed the phase tensor screen.")
        return imported.catalog_payload()

    def _run_gravity(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.core.schemas import GravityCsvImportRequest

        return session.imports.import_gravity_csv(
            GravityCsvImportRequest(
                filename=self._source.name,
                source_path=str(self._source),
                x_column=self._value("x_column"),
                y_column=self._value("y_column"),
                z_column=self._value("z_column"),
                gravity_column=self._value("gravity_column"),
                uncertainty_column=self._value("uncertainty_column") or None,
                default_uncertainty_percent=self._value("default_uncertainty_percent"),
                coordinate_unit=self._value("coordinate_unit"),
                gravity_unit=self._value("gravity_unit"),
                coordinate_convention=convention,
            )
        )

    def _run_magnetics(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.core.schemas import MagneticCsvImportRequest

        return session.imports.import_magnetic_csv(
            MagneticCsvImportRequest(
                filename=self._source.name,
                source_path=str(self._source),
                x_column=self._value("x_column"),
                y_column=self._value("y_column"),
                z_column=self._value("z_column"),
                tmi_column=self._value("tmi_column"),
                uncertainty_column=self._value("uncertainty_column") or None,
                default_uncertainty_percent=self._value("default_uncertainty_percent"),
                coordinate_unit=self._value("coordinate_unit"),
                tmi_unit=self._value("tmi_unit"),
                coordinate_convention=convention,
            )
        )

    def _run_aem(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.core.schemas import TDEMCsvImportRequest

        return session.imports.import_tdem_csv(
            TDEMCsvImportRequest(
                filename=self._source.name,
                source_path=str(self._source),
                import_mode="batch",
                sounding_id_column=self._value("sounding_id_column"),
                x_column=self._value("x_column"),
                y_column=self._value("y_column"),
                z_column=self._value("z_column"),
                time_column=self._value("time_column"),
                response_column=self._value("response_column"),
                coordinate_unit=self._value("coordinate_unit"),
                time_unit=self._value("time_unit"),
                response_unit=self._value("response_unit"),
                coordinate_convention=convention,
            )
        )

    def _run_topography(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.core.schemas import TopographyCsvImportRequest

        return session.imports.import_topography_csv(
            TopographyCsvImportRequest(
                filename=self._source.name,
                source_path=str(self._source),
                x_column=self._value("x_column"),
                y_column=self._value("y_column"),
                z_column=self._value("z_column"),
                coordinate_unit=self._value("coordinate_unit"),
                coordinate_convention=convention,
            )
        )

    def _run_ert(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.services.ert_import import ERTFieldImportRequest

        return session.ert_imports.import_field_file(
            ERTFieldImportRequest(
                source_path=str(self._source),
                instrument=self._value("instrument"),
                coordinate_convention=convention,
                coordinate_unit=self._value("coordinate_unit"),
                electrode_file=self._value("electrode_file") or None,
            )
        )

    def _run_segy(self, session: Session, convention: CoordinateConvention) -> Any:
        from ofag.services.segy_import import SegyImportRequest

        scalar_text = self._value("coordinate_scalar")
        return session.segy_imports.import_file(
            SegyImportRequest(
                source_path=str(self._source),
                name=self.dataset_name(),
                coordinate_convention=convention,
                source_x_byte=self._value("source_x_byte"),
                source_y_byte=self._value("source_y_byte"),
                receiver_x_byte=self._value("receiver_x_byte"),
                receiver_y_byte=self._value("receiver_y_byte"),
                coordinate_scalar="header" if scalar_text == "header" else float(scalar_text),
                coordinate_unit=self._value("coordinate_unit"),
            )
        )


def _as_payload(imported: Any) -> dict[str, Any]:
    """The importer's result as JSON-safe fields the register can hold."""
    import json
    from dataclasses import asdict, is_dataclass

    if is_dataclass(imported) and not isinstance(imported, type):
        raw = asdict(imported)
    elif hasattr(imported, "model_dump"):
        raw = imported.model_dump(mode="json")
    else:  # pragma: no cover - every importer returns one of the two
        raise TypeError(f"cannot store a {type(imported).__name__}")
    return dict(json.loads(json.dumps(raw, default=str)))
