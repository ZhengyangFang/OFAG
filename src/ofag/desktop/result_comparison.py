"""Compare two saved runs, keeping physical quantities and colour scales explicit."""

import json
from typing import Any

import numpy as np
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.core.cell_model import CellModel
from ofag.desktop.plotting import PlotPanel
from ofag.services.project_changes import configuration_changes


class ResultComparison(QDialog):
    def __init__(
        self,
        records: list[Any],
        results: list[Any],
        models: list[tuple[CellModel, str, str] | None],
        parent: QWidget | None = None,
        meshes: list[Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare saved results")
        self.resize(1150, 780)
        layout = QVBoxLayout(self)
        compatible = (
            all(model is not None for model in models)
            and models[0][1:] == models[1][1:]  # type: ignore[index]
            and _coordinates(records[0].spec) == _coordinates(records[1].spec)
            and bool(_coordinates(records[0].spec))
        )
        available = all(model is not None for model in models)
        note = (
            "Shared colour limits; compare coverage and fit before choosing a result."
            if compatible
            else "Separate physical scales. Set reference positions to compare the same location."
        )
        layout.addWidget(QLabel(note))
        row = QHBoxLayout()
        limits = None
        if compatible:
            values = np.concatenate([m[0].values for m in models if m is not None])
            finite = values[np.isfinite(values)]
            if finite.size:
                limits = (float(finite.min()), float(finite.max()))
        cut = None
        if available:
            centres = np.concatenate([m[0].centres for m in models if m is not None])
            cut = float(np.median(centres[:, 1]))
        for index, (record, result, model) in enumerate(zip(records, results, models, strict=True)):
            column = QVBoxLayout()
            column.addWidget(QLabel(record.spec.label or str(record.spec.run_id)))
            plot = PlotPanel()
            if available and model is not None:
                cell, quantity, units = model
                if not compatible:
                    finite = cell.values[np.isfinite(cell.values)]
                    limits = (float(finite.min()), float(finite.max())) if finite.size else None
                is_2d = np.ptp(cell.centres[:, 2]) == 0
                vertical = 1 if is_2d else 2
                widths = cell.widths_or_cubes
                mask = (
                    np.ones(len(cell.values), dtype=bool)
                    if is_2d
                    else abs(cell.centres[:, 1] - cut) <= widths[:, 1] / 2
                )
                plot.cell_section(
                    cell.centres[mask, 0],
                    cell.centres[mask, vertical],
                    widths[mask, 0],
                    widths[mask, vertical],
                    cell.values[mask],
                    title=f"{quantity} | northing {cut:g}" if not is_2d else quantity,
                    colour_label=units,
                    colour_limits=limits,
                )
                reference = QDoubleSpinBox()
                reference.setRange(-1e8, 1e8)
                reference.setDecimals(2)
                reference.setPrefix("Reference X (m): ")
                reference.setToolTip(
                    "Subtract a surveyed reference position; each profile has its own origin."
                )
                column.addWidget(reference)
                mesh = meshes[index] if meshes else None

                def draw_offset(
                    value: float,
                    p: PlotPanel = plot,
                    c: Any = cell,
                    w: Any = widths,
                    m: Any = mask,
                    v: int = vertical,
                    q: str = quantity,
                    u: str = units,
                    bounds: Any = limits,
                    polygons: Any = mesh,
                ) -> None:
                    if polygons is not None:
                        nodes = polygons[0].copy()
                        nodes[:, 0] -= value
                        p.mesh_section(
                            nodes,
                            polygons[1],
                            c.values,
                            title=q,
                            colour_label=u,
                            colour_limits=bounds,
                            x_label="Distance from reference (m)",
                        )
                    else:
                        p.cell_section(
                            c.centres[m, 0] - value,
                            c.centres[m, v],
                            w[m, 0],
                            w[m, v],
                            c.values[m],
                            title=q,
                            colour_label=u,
                            colour_limits=bounds,
                        )

                reference.valueChanged.connect(draw_offset)
                if mesh is not None:
                    draw_offset(0)
            else:
                plot.clear("No compatible cell model to plot.")
            column.addWidget(plot, 1)
            text = QTextEdit()
            text.setReadOnly(True)
            text.setPlainText(json.dumps(result.summary, indent=2, default=str))
            text.setMaximumHeight(170)
            column.addWidget(text)
            row.addLayout(column, 1)
        layout.addLayout(row, 1)
        differences = QTextEdit()
        differences.setReadOnly(True)
        differences.setMaximumHeight(160)
        omit = {"run_id", "label", "project_id"}
        specs = [
            {k: v for k, v in record.spec.model_dump(mode="json").items() if k not in omit}
            for record in records
        ]
        differences.setPlainText(
            "Configuration differences (left -> right)\n"
            + "\n".join(configuration_changes(specs[0], specs[1]))
        )
        layout.addWidget(differences)


def _coordinates(spec: Any) -> tuple[Any, ...]:
    datasets = [item.dataset for item in spec.datasets]
    if not datasets and spec.dataset is not None:
        datasets = [spec.dataset]
    return tuple(item.coordinate_convention for item in datasets)
