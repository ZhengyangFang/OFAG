"""Shared map for comparing measured survey coverage."""

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ofag.desktop.plotting import PlotPanel
from ofag.services.survey_coverage import project_coverage


class CoverageView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.plot = PlotPanel()
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.note)

    def load(self, session: Any) -> None:
        if session is None:
            return
        coverage = project_coverage(session.folder.root)
        self.plot._figure.clear()
        axes = self.plot._figure.add_subplot()
        for name, points in coverage.stations.items():
            axes.scatter(points[:, 0], points[:, 1], s=10, label=f"{name} ({len(points)})")
        axes.set(xlabel="Easting (m)", ylabel="Northing (m)", title=coverage.crs)
        axes.set_aspect("equal", adjustable="datalim")
        if coverage.stations:
            axes.legend(fontsize="small")
        else:
            axes.set_axis_off()
            axes.text(
                0.5,
                0.5,
                "No mapped station coordinates.",
                ha="center",
                va="center",
                transform=axes.transAxes,
            )
        self.plot._redraw()
        self.note.setText(
            "Measured station coverage; does not show resolution depth."
            + (
                f" {len(coverage.unavailable)} datasets need map coordinates."
                if coverage.unavailable
                else ""
            )
        )
        self.note.setToolTip(
            "\n".join(f"{key}: {value}" for key, value in coverage.unavailable.items())
        )
