"""Combo selections that also work for Python UUIDs stored as item data."""

from typing import Any

from PySide6.QtWidgets import QComboBox


def find_data(box: QComboBox, value: Any) -> int:
    # Qt's QVariant comparison does not compare independently read Python UUIDs.
    return next((index for index in range(box.count()) if box.itemData(index) == value), -1)
