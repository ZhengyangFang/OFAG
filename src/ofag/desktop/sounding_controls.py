"""Select a batch's line, depth and measured fit without changing saved results."""

from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

from ofag.desktop.plotting import PlotPanel


class SoundingControls(QWidget):
    def __init__(self, plot: PlotPanel) -> None:
        super().__init__()
        self.plot = plot
        self.data: dict[str, Any] = {}
        self.line = QComboBox()
        self.depth_choice = QComboBox()
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0.01, 1e6)
        self.limit.setValue(1.0)
        self.only_fit = QCheckBox("Within limit")
        self.note = QLabel()
        row = QHBoxLayout(self)
        for widget in (
            QLabel("Line"),
            self.line,
            QLabel("Depth"),
            self.depth_choice,
            QLabel("χ² ≤"),
            self.limit,
            self.only_fit,
            self.note,
        ):
            row.addWidget(widget)
        self.line.currentIndexChanged.connect(self.draw)
        self.depth_choice.currentIndexChanged.connect(self.draw)
        self.limit.valueChanged.connect(self.draw)
        self.only_fit.toggled.connect(self.draw)

    def load(self, path: Path, title: str) -> None:
        self.data = {}
        with np.load(path, allow_pickle=False) as archive:
            data = {key: archive[key].copy() for key in archive.files}
        xyz = data.get("receiver_locations_m")
        if xyz is None:
            xyz = np.column_stack([data["easting_m"], data["northing_m"], data["elevation_m"]])
        ids = data.get("sounding_ids", np.arange(len(xyz)).astype(str))
        lines = (
            np.array([str(i).split("-")[0] for i in ids])
            if all("-" in str(i) for i in ids)
            else np.full(len(xyz), "Survey")
        )
        for box in (self.line, self.depth_choice):
            box.blockSignals(True)
            box.clear()
        self.line.addItems(sorted(set(lines)))
        for index, value in enumerate(data["layer_top_depth_m"]):
            self.depth_choice.addItem(f"{value:g} m", index)
        self.depth_choice.setCurrentIndex(
            min(len(data["layer_top_depth_m"]) // 3, self.depth_choice.count() - 1)
        )
        for box in (self.line, self.depth_choice):
            box.blockSignals(False)
        known = "chi_squared" in data
        self.only_fit.setChecked(False)
        self.only_fit.setEnabled(known)
        self.limit.setEnabled(known)
        self.data = {**data, "xyz": xyz, "lines": lines, "title": title}
        self.draw()

    def draw(self, *_: Any) -> None:
        if not self.data:
            return
        data = self.data
        fit = data.get("chi_squared")
        mask = np.ones(len(data["xyz"]), dtype=bool)
        flagged = None
        if fit is not None:
            flagged = ~np.isfinite(fit) | (fit > self.limit.value())
            self.note.setText(f"{int((~flagged).sum())}/{len(fit)} within limit")
            if self.only_fit.isChecked():
                mask &= ~flagged
        else:
            self.note.setText("Per-site fit unavailable")
        mask &= data["lines"] == self.line.currentText()
        if not mask.any():
            self.plot.clear("No soundings match this line and quality limit.")
            return
        xyz = data["xyz"][mask]
        self.plot.layered_soundings(
            xyz,
            data["layer_top_depth_m"],
            data["conductivity_s_m"][mask],
            title=f"{data['title']} · {self.line.currentText()}",
            elevations=xyz[:, 2] if np.ptp(xyz[:, 2]) > 0 else None,
            layer_index=self.depth_choice.currentIndex(),
            flagged=flagged[mask] if flagged is not None else None,
        )
