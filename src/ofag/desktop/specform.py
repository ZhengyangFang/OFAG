"""An editor built from a model's own definition."""

import json
from enum import Enum
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ofag.services.method_catalog import advanced_parameter

#: Wide enough for any physical quantity OFAG carries, including a velocity in m/s and a
#: susceptibility of 1e-6, without a spin box clamping either.
_LIMIT = 1e12


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """The type inside `X | None`, and whether it was optional."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0], len(get_args(annotation)) > 1
        return annotation, type(None) in get_args(annotation)
    return annotation, False


class SpecForm(QWidget):
    """A form for one pydantic model, and the value it currently describes."""

    changed = Signal()

    def __init__(
        self, model: type[BaseModel], initial: BaseModel | None = None, *, grouped: bool = False
    ) -> None:
        super().__init__()
        self._model = model
        self._editors: dict[str, Any] = {}
        self._layout = QFormLayout()
        self._layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        advanced_layout = self._layout
        if grouped:
            column = QVBoxLayout(self)
            column.addWidget(QLabel("Basic settings"))
            column.addLayout(self._layout)
            advanced = QGroupBox("Advanced parameters")
            advanced.setCheckable(True)
            advanced.setChecked(False)
            advanced.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            inner = QWidget()
            advanced_layout = QFormLayout(inner)
            box = QVBoxLayout(advanced)
            box.addWidget(inner)
            inner.setVisible(False)
            advanced.toggled.connect(inner.setVisible)
            column.addWidget(advanced)
        else:
            self.setLayout(self._layout)
        defaults = initial.model_dump(mode="json") if initial is not None else {}
        for name, field in model.model_fields.items():
            annotation, optional = _unwrap_optional(field.annotation)
            # `field.default` is the sentinel for anything declared with a
            # `default_factory`, which in these models is every QuantitySpec and every
            # mapping.
            editor = self._editor_for(
                annotation,
                defaults.get(name),
                field.get_default(call_default_factory=True),
                optional,
            )
            self._editors[name] = editor
            label = name.replace("_", " ")
            if field.description:
                editor.setToolTip(field.description)
            target = advanced_layout if grouped and advanced_parameter(name) else self._layout
            if isinstance(editor, QGroupBox):
                editor.setTitle(label.title())
                target.addRow(editor)
            else:
                target.addRow(label, editor)
        for widget in self.findChildren(QWidget):
            for signal in (
                "textChanged",
                "valueChanged",
                "currentIndexChanged",
                "toggled",
                "itemChanged",
            ):
                if hasattr(widget, signal):
                    getattr(widget, signal).connect(lambda *_: self.changed.emit())
                    break

    # -- building -----------------------------------------------------------

    def _editor_for(self, annotation: Any, value: Any, default: Any, optional: bool) -> QWidget:
        from ofag.core.schemas import QuantitySpec

        # A required field has no default, and pydantic says so with a sentinel.
        default = _json_default(default)

        if get_origin(annotation) in (list, tuple):
            args = get_args(annotation)
            item_type = args[0] if args else Any
            # Heterogeneous tuples retain their exact JSON representation.
            if len(args) <= 1 or (len(args) == 2 and args[1] is Ellipsis):
                return _SequenceEditor(item_type, value if value is not None else default)

        if annotation is QuantitySpec or (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and annotation.__name__ == "QuantitySpec"
        ):
            seed = value if isinstance(value, dict) else default
            return _QuantityEditor(seed if isinstance(seed, dict) else None)
        if get_origin(annotation) is Literal:
            box = QComboBox()
            for option in get_args(annotation):
                box.addItem(str(option), option)
            _select(box, value if value is not None else default)
            return box
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            box = QComboBox()
            for option in annotation:
                box.addItem(str(option.value), option.value)
            _select(box, value if value is not None else default)
            return box
        if annotation is bool:
            check = QCheckBox()
            check.setChecked(bool(value if value is not None else (default or False)))
            return check
        if annotation is int and not optional:
            spin = QSpinBox()
            spin.setRange(-2_000_000_000, 2_000_000_000)
            spin.setValue(int(value if value is not None else (default or 0)))
            return spin
        if annotation in (int, float):
            # Every number that is not a plain integer is typed rather than spun.
            return _NumberEditor(value if value is not None else default, annotation is int)
        if annotation is str:
            return QLineEdit(str(value if value is not None else (default or "")))
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            group = QGroupBox()
            nested = SpecForm(annotation, None)
            seed = value if isinstance(value, dict) else default
            if isinstance(seed, dict):
                nested.set_value(seed)
            inner = QVBoxLayout()
            inner.addWidget(nested)
            group.setLayout(inner)
            group.setProperty("specForm", nested)
            if optional:
                # An absent sub-model is not a sub-model with blank fields.
                group.setCheckable(True)
                group.setChecked(isinstance(seed, dict))
            return group
        # A sequence of models, a mapping, or anything else the generator cannot express
        # honestly.
        text = QPlainTextEdit()
        text.setMaximumHeight(110)
        text.setPlainText(json.dumps(value if value is not None else default, indent=2))
        text.setToolTip(
            "Edited as JSON: this field is a list or a mapping whose shape is "
            "itself a decision, and a generated widget for it would express "
            "less than the model allows."
        )
        return text

    # -- reading ------------------------------------------------------------

    def value(self) -> dict[str, Any]:
        """What the form currently says, as the model's own JSON shape."""
        payload: dict[str, Any] = {}
        for name, editor in self._editors.items():
            payload[name] = _read(editor)
        return payload

    def set_value(self, payload: dict[str, Any]) -> None:
        for name, editor in self._editors.items():
            if name in payload:
                _write(editor, payload[name])

    def parsed(self) -> BaseModel:
        """The model this form describes, or a ValidationError naming the field."""
        return self._model.model_validate(self.value())

    def errors(self) -> list[str]:
        try:
            self.parsed()
        except ValidationError as error:
            return [
                f"{'.'.join(str(part) for part in item['loc']) or 'spec'}: {item['msg']}"
                for item in error.errors()
            ]
        return []


class _SequenceEditor(QWidget):
    """Editable rows for common arrays, with an explicit JSON escape hatch."""

    def __init__(self, item_type: Any, value: Any) -> None:
        super().__init__()
        self._model = (
            item_type if isinstance(item_type, type) and issubclass(item_type, BaseModel) else None
        )
        self._names = list(self._model.model_fields) if self._model else ["value"]
        self._table = QTableWidget(0, len(self._names))
        self._table.setHorizontalHeaderLabels([name.replace("_", " ") for name in self._names])
        self._table.setMaximumHeight(190)
        self._raw = QPlainTextEdit()
        self._raw.setMaximumHeight(150)
        self._raw.hide()
        self._mode = QCheckBox("Edit as JSON")
        self._mode.toggled.connect(self._switch)
        add = QPushButton("Add row")
        remove = QPushButton("Remove row")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        self._buttons = QWidget()
        buttons = QHBoxLayout(self._buttons)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)
        layout.addWidget(self._raw)
        layout.addWidget(self._buttons)
        layout.addWidget(self._mode)
        self._absent = value is None
        self.write(value)
        self._table.itemChanged.connect(self._edited)

    def _edited(self) -> None:
        self._absent = False

    def _add(self) -> None:
        self._absent = False
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, name in enumerate(self._names):
            default = (
                _json_default(self._model.model_fields[name].get_default(call_default_factory=True))
                if self._model
                else None
            )
            self._table.setItem(row, column, QTableWidgetItem(json.dumps(default)))

    def _remove(self) -> None:
        if self._table.currentRow() >= 0:
            self._absent = False
            self._table.removeRow(self._table.currentRow())

    def _rows(self) -> Any:
        if self._absent:
            return None
        values = []
        for row in range(self._table.rowCount()):
            record = {}
            for column, name in enumerate(self._names):
                item = self._table.item(row, column)
                text = item.text() if item is not None else "null"
                try:
                    record[name] = json.loads(text)
                except ValueError:
                    record[name] = text
            values.append(record if self._model else record["value"])
        return values

    def read(self) -> Any:
        if not self._mode.isChecked():
            return self._rows()
        try:
            return json.loads(self._raw.toPlainText())
        except ValueError:
            return self._raw.toPlainText()

    def write(self, value: Any) -> None:
        if value is not None and not isinstance(value, (list, tuple)):
            self._mode.blockSignals(True)
            self._mode.setChecked(True)
            self._mode.blockSignals(False)
            self._raw.setPlainText(value if isinstance(value, str) else json.dumps(value))
            self._raw.show()
            self._table.hide()
            self._buttons.hide()
            return
        self._raw.setPlainText(json.dumps(value, indent=2))
        self._absent = value is None
        self._table.blockSignals(True)
        values = value if isinstance(value, (list, tuple)) else []
        self._table.setRowCount(len(values))
        for row, record in enumerate(values):
            for column, name in enumerate(self._names):
                cell = record.get(name) if self._model and isinstance(record, dict) else record
                self._table.setItem(row, column, QTableWidgetItem(json.dumps(cell)))
        self._table.blockSignals(False)

    def _switch(self, raw: bool) -> None:
        if raw:
            self._raw.setPlainText(json.dumps(self._rows(), indent=2))
        else:
            try:
                value = json.loads(self._raw.toPlainText())
                if value is not None and not isinstance(value, list):
                    raise ValueError("Expected an array")
                self.write(value)
            except ValueError:
                self._mode.blockSignals(True)
                self._mode.setChecked(True)
                self._mode.blockSignals(False)
                self._raw.setToolTip("Correct the JSON array before returning to the table.")
                return
        self._raw.setVisible(raw)
        self._table.setVisible(not raw)
        self._buttons.setVisible(not raw)


class _NumberEditor(QLineEdit):
    """A number typed rather than spun, so nothing is lost on the way in."""

    def __init__(self, value: Any, integral: bool) -> None:
        super().__init__("" if value is None else repr(value))
        self._integral = integral
        self.setPlaceholderText("unset")

    def read(self) -> Any:
        text = self.text().strip()
        if not text:
            return None
        try:
            return int(text) if self._integral else float(text)
        except ValueError:
            # Handed to the model as typed, so the complaint names the field rather than
            # being swallowed into a silent None.
            return text


class _QuantityEditor(QWidget):
    """A value beside its unit, which is the only way OFAG carries one."""

    def __init__(self, value: dict[str, Any] | None) -> None:
        super().__init__()
        self._value = QLineEdit("" if value is None else str(value.get("value", "")))
        self._value.setPlaceholderText("value")
        self._quantity = QLineEdit("" if value is None else str(value.get("quantity_type", "")))
        self._quantity.setPlaceholderText("quantity type")
        self._unit = QLineEdit("" if value is None else str(value.get("unit", "")))
        self._unit.setPlaceholderText("unit")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._value, 2)
        row.addWidget(self._unit, 1)
        self._quantity.setMaximumWidth(135)
        self._quantity.setToolTip("Physical quantity")
        row.addWidget(self._quantity, 1)
        self.setLayout(row)

    def read(self) -> dict[str, Any] | None:
        text = self._value.text().strip()
        if not text:
            return None
        try:
            number: Any = json.loads(text)
        except json.JSONDecodeError:
            number = text
        return {
            "value": number,
            "quantity_type": self._quantity.text().strip(),
            "unit": self._unit.text().strip(),
        }

    def write(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        self._value.setText(json.dumps(payload.get("value")))
        self._quantity.setText(str(payload.get("quantity_type", "")))
        self._unit.setText(str(payload.get("unit", "")))


def _select(box: QComboBox, value: Any) -> None:
    index = box.findData(value)
    if index >= 0:
        box.setCurrentIndex(index)


def _json_default(default: Any) -> Any:
    """A default rendered as JSON, with pydantic's sentinel treated as absent."""
    if default is None or repr(default).startswith("PydanticUndefined"):
        return None
    if isinstance(default, BaseModel):
        return default.model_dump(mode="json")
    if isinstance(default, (list, tuple)):
        return [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in default
        ]
    return default


def _read(editor: QWidget) -> Any:
    if isinstance(editor, (_QuantityEditor, _NumberEditor, _SequenceEditor)):
        return editor.read()
    if isinstance(editor, QComboBox):
        return editor.currentData()
    if isinstance(editor, QCheckBox):
        return editor.isChecked()
    if isinstance(editor, QSpinBox):
        return int(editor.value())
    if isinstance(editor, QDoubleSpinBox):
        return float(editor.value())
    if isinstance(editor, QLineEdit):
        return editor.text().strip() or None
    if isinstance(editor, QPlainTextEdit):
        text = editor.toPlainText().strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    nested = editor.property("specForm")
    if isinstance(nested, SpecForm):
        # A checkable group is an optional sub-model, and unchecked is absent.
        if isinstance(editor, QGroupBox) and editor.isCheckable() and not editor.isChecked():
            return None
        return nested.value()
    raise TypeError(f"no reader for {type(editor).__name__}")


def _write(editor: QWidget, value: Any) -> None:
    if isinstance(editor, _SequenceEditor):
        editor.write(value)
        return
    if isinstance(editor, _NumberEditor):
        editor.setText("" if value is None else str(value))
        return
    if isinstance(editor, _QuantityEditor):
        editor.write(value)
        return
    if isinstance(editor, QComboBox):
        _select(editor, value)
        return
    if isinstance(editor, QCheckBox):
        editor.setChecked(bool(value))
        return
    if isinstance(editor, QSpinBox):
        editor.setValue(int(value or 0))
        return
    if isinstance(editor, QDoubleSpinBox):
        editor.setValue(float(value or 0.0))
        return
    if isinstance(editor, QLineEdit):
        editor.setText("" if value is None else str(value))
        return
    if isinstance(editor, QPlainTextEdit):
        editor.setPlainText(json.dumps(value, indent=2))
        return
    nested = editor.property("specForm")
    if not isinstance(nested, SpecForm):
        return
    if isinstance(editor, QGroupBox) and editor.isCheckable():
        editor.setChecked(isinstance(value, dict))
    if isinstance(value, dict):
        nested.set_value(value)
