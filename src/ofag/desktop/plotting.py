"""A figure embedded in the window."""

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from matplotlib.backends.backend_qtagg import (  # type: ignore[attr-defined]
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.collections import PatchCollection, PolyCollection
from matplotlib.colors import LogNorm, Normalize
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FormatStrFormatter, LogLocator, NullFormatter
from PySide6.QtWidgets import QVBoxLayout, QWidget


class PlotPanel(QWidget):
    """One figure with the standard pan, zoom and save toolbar."""

    def __init__(self) -> None:
        super().__init__()
        self._figure = Figure(figsize=(6, 4), layout="constrained")
        # matplotlib's Qt backend is untyped, so the three calls that reach it are
        # gathered here and in `_redraw` rather than scattered as seven suppressions
        # through the drawing methods.
        self._canvas = FigureCanvasQTAgg(self._figure)  # type: ignore[no-untyped-call]
        toolbar = NavigationToolbar2QT(self._canvas, self)  # type: ignore[no-untyped-call]
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toolbar)
        layout.addWidget(self._canvas, 1)
        self.setLayout(layout)

    def _redraw(self) -> None:
        self._canvas.draw_idle()  # type: ignore[no-untyped-call]

    def clear(self, message: str = "") -> None:
        self._figure.clear()
        if message:
            axes = self._figure.add_subplot()
            axes.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
            axes.set_axis_off()
        self._redraw()

    def scatter_section(
        self,
        x: npt.ArrayLike,
        y: npt.ArrayLike,
        values: npt.ArrayLike,
        *,
        title: str,
        x_label: str = "Distance (m)",
        y_label: str = "Elevation (m)",
        colour_label: str = "",
        logarithmic: bool = False,
    ) -> None:
        """Cell centres coloured by a recovered property."""
        self._figure.clear()
        axes = self._figure.add_subplot()
        drawn, label = _colour_values(values, colour_label, logarithmic)
        mapping = axes.scatter(
            np.asarray(x, dtype=float), np.asarray(y, dtype=float), c=drawn, s=14, marker="s"
        )
        axes.set_title(title)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        axes.set_aspect("equal", adjustable="datalim")
        bar = self._figure.colorbar(mapping, ax=axes)
        if label:
            bar.set_label(label)
        self._redraw()

    def cell_section(
        self,
        x: npt.ArrayLike,
        y: npt.ArrayLike,
        width: npt.ArrayLike,
        height: npt.ArrayLike,
        values: npt.ArrayLike,
        *,
        title: str,
        x_label: str = "Distance (m)",
        y_label: str = "Elevation (m)",
        colour_label: str = "",
        logarithmic: bool = False,
        limits: tuple[tuple[float, float], tuple[float, float]] | None = None,
        colour_limits: tuple[float, float] | None = None,
        colormap: str = "viridis",
        equal_aspect: bool = False,
    ) -> None:
        """Cells drawn at their own size, coloured by a recovered property."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        width = np.asarray(width, dtype=float)
        height = np.asarray(height, dtype=float)
        self._figure.clear()
        axes = self._figure.add_subplot()
        drawn, label = _colour_values(values, colour_label, logarithmic)
        patches = [
            Rectangle((left, bottom), w, h)
            for left, bottom, w, h in zip(
                x - width / 2.0, y - height / 2.0, width, height, strict=True
            )
        ]
        collection = PatchCollection(patches, array=drawn, edgecolors="none", cmap=colormap)
        if colour_limits is not None:
            # Held across slices on purpose.
            collection.set_clim(*colour_limits)
        axes.add_collection(collection)
        if limits is None:
            axes.set_xlim(float((x - width / 2.0).min()), float((x + width / 2.0).max()))
            axes.set_ylim(float((y - height / 2.0).min()), float((y + height / 2.0).max()))
        else:
            # A starting view, not a crop: every cell is drawn, and the toolbar's pan
            # and zoom reach the rest.
            axes.set_xlim(*limits[0])
            axes.set_ylim(*limits[1])
        axes.set_title(title)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        # Equal only where both axes are the same kind of distance.
        axes.set_aspect("equal" if equal_aspect else "auto")
        bar = self._figure.colorbar(collection, ax=axes)
        if label:
            bar.set_label(label)
        self._redraw()

    def mesh_section(
        self,
        nodes: npt.ArrayLike,
        cells: npt.ArrayLike,
        values: npt.ArrayLike,
        *,
        title: str,
        colour_label: str = "",
        logarithmic: bool = False,
        coverage: npt.ArrayLike | None = None,
        electrodes: npt.ArrayLike | None = None,
        x_label: str = "Distance (m)",
        y_label: str = "Elevation (m)",
        colormap: str = "Spectral_r",
        colour_limits: tuple[float, float] | None = None,
    ) -> None:
        """An unstructured two-dimensional model, drawn the way pyGIMLi draws it."""
        points = np.asarray(nodes, dtype=float)[:, :2]
        connectivity = np.asarray(cells, dtype=int)
        array = np.asarray(values, dtype=float)
        if connectivity.shape[0] != array.shape[0]:
            raise ValueError(
                f"{array.shape[0]} values for {connectivity.shape[0]} cells; a model drawn "
                "on a mesh it was not solved on is the right numbers in the wrong places"
            )
        self._figure.clear()
        axes = self._figure.add_subplot()
        polygons = points[connectivity]
        finite = np.isfinite(array) & (array > 0 if logarithmic else True)
        shown = array[finite]
        if logarithmic and shown.size:
            norm: Normalize = LogNorm(vmin=float(shown.min()), vmax=float(shown.max()))
        else:
            norm = Normalize(
                vmin=float(shown.min()) if shown.size else 0.0,
                vmax=float(shown.max()) if shown.size else 1.0,
            )
        collection = PolyCollection(
            polygons[finite],
            array=shown,
            cmap=colormap,
            norm=norm,
            edgecolors="face",
            linewidths=0.15,
        )
        if colour_limits is not None:
            collection.set_clim(*colour_limits)
        if coverage is not None:
            alpha = coverage_alpha(coverage)
            if alpha.shape[0] == array.shape[0]:
                collection.set_alpha(alpha[finite])
        axes.add_collection(collection)
        if electrodes is not None:
            positions = np.asarray(electrodes, dtype=float)
            if positions.ndim == 2 and positions.shape[0]:
                z = positions[:, -1] if positions.shape[1] >= 2 else np.zeros(positions.shape[0])
                axes.plot(
                    positions[:, 0],
                    z,
                    "v",
                    color="black",
                    markersize=3.5,
                    linestyle="none",
                    label="electrodes",
                    zorder=3,
                )
        axes.set_xlim(float(points[:, 0].min()), float(points[:, 0].max()))
        axes.set_ylim(float(points[:, 1].min()), float(points[:, 1].max()) + 1.0)
        axes.set_aspect("equal", adjustable="box")
        axes.set_title(title)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        bar = self._figure.colorbar(collection, ax=axes, shrink=0.9, pad=0.02)
        if logarithmic:
            # Ticks at 1, 2 and 5 of each decade, written as numbers: a reader wants
            # "200 ohm.m", not the exponent of ten it is.
            bar.ax.yaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
            bar.ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
            bar.ax.yaxis.set_minor_formatter(NullFormatter())
        if colour_label:
            bar.set_label(colour_label)
        self._redraw()

    def pseudosection(self, section: Any, *, title: str) -> None:
        """Apparent resistivity as a pseudosection, as pyGIMLi shows ERT data."""
        x = np.asarray(section.midpoint_m, dtype=float)
        depth = np.asarray(section.pseudo_depth_m, dtype=float)
        values = np.asarray(section.apparent_resistivity_ohm_m, dtype=float)
        self._figure.clear()
        axes = self._figure.add_subplot()
        if values.size == 0:
            self.clear("No reading with a positive apparent resistivity to draw.")
            return
        height = _typical_step(depth)
        # Width per pseudo-depth level: readings at one level are spaced by the array's
        # own step, which is coarser than the step between all midpoints -- sized to the
        # latter, the blocks left gaps between them.
        widths = np.empty_like(x)
        for level in np.unique(np.round(depth, 6)):
            rows = np.round(depth, 6) == level
            widths[rows] = _typical_step(x[rows]) if rows.sum() > 1 else _typical_step(x)
        width = float(np.median(widths))
        patches = [
            Rectangle((xi - wi / 2, di - height / 2), wi, height)
            for xi, di, wi in zip(x, depth, widths, strict=True)
        ]
        collection = PatchCollection(
            patches,
            array=values,
            cmap="Spectral_r",
            edgecolors="face",
            linewidths=0.2,
            norm=LogNorm(vmin=float(values.min()), vmax=float(values.max())),
        )
        axes.add_collection(collection)
        electrodes = np.asarray(section.electrodes_x_m, dtype=float)
        axes.plot(
            electrodes,
            np.zeros_like(electrodes),
            "v",
            color="black",
            markersize=3.5,
            linestyle="none",
            label="electrodes",
            zorder=3,
        )
        axes.set_xlim(
            float(min(electrodes.min(), (x - width).min())),
            float(max(electrodes.max(), (x + width).max())),
        )
        axes.set_ylim(float((depth + height).max()), -height)
        axes.set_title(title)
        axes.set_xlabel("Distance (m)")
        axes.set_ylabel("Pseudo-depth (m), 0.2 x spread")
        bar = self._figure.colorbar(collection, ax=axes, pad=0.02)
        bar.ax.yaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
        bar.ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
        bar.ax.yaxis.set_minor_formatter(NullFormatter())
        bar.set_label("Apparent resistivity (ohm*m)")
        self._redraw()

    def traveltime_curves(self, curves: Any, *, title: str) -> None:
        """First-arrival picks, one curve per shot, time increasing downward."""
        self._figure.clear()
        axes = self._figure.add_subplot()
        for shot_x, receivers, times in curves.shots:
            receivers, times = _break_at_gaps(
                np.asarray(receivers, dtype=float), np.asarray(times, dtype=float)
            )
            (line,) = axes.plot(
                receivers, np.asarray(times) * 1000.0, marker=".", markersize=4, linewidth=1
            )
            axes.plot([shot_x], [0.0], "*", color=line.get_color(), markersize=9)
        axes.invert_yaxis()
        axes.set_title(title)
        axes.set_xlabel("Distance (m)")
        axes.set_ylabel("Traveltime (ms)")
        axes.grid(True, linewidth=0.3, alpha=0.5)
        self._redraw()

    def unit_cells(
        self,
        x: npt.ArrayLike,
        y: npt.ArrayLike,
        width: npt.ArrayLike,
        height: npt.ArrayLike,
        unit: npt.ArrayLike,
        *,
        legend: Sequence[tuple[str, str]],
        title: str,
        x_label: str,
        y_label: str,
        equal_aspect: bool = False,
    ) -> None:
        """Cells of a labelled model, one colour per unit, each at its own size."""
        from matplotlib.patches import Patch

        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        width = np.asarray(width, dtype=float)
        height = np.asarray(height, dtype=float)
        unit = np.asarray(unit, dtype=int)
        self._figure.clear()
        axes = self._figure.add_subplot()
        if x.size == 0:
            self.clear("No cell of the model lies on this cut.")
            return
        colours = [legend[u][1] if 0 <= u < len(legend) else "#ffffff" for u in unit]
        patches = [
            Rectangle((xi - wi / 2, yi - hi / 2), wi, hi)
            for xi, yi, wi, hi in zip(x, y, width, height, strict=True)
        ]
        axes.add_collection(
            PatchCollection(patches, facecolors=colours, edgecolors="face", linewidths=0.2)
        )
        axes.set_xlim(float((x - width / 2).min()), float((x + width / 2).max()))
        axes.set_ylim(float((y - height / 2).min()), float((y + height / 2).max()))
        axes.set_aspect("equal" if equal_aspect else "auto")
        axes.set_title(title)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        present = sorted(set(unit.tolist()) & set(range(len(legend))))
        axes.legend(
            handles=[
                Patch(facecolor=legend[i][1], edgecolor="#666", label=legend[i][0]) for i in present
            ],
            loc="upper center",
            bbox_to_anchor=(0.5, -0.14),
            ncol=2,
            fontsize="small",
            frameon=False,
        )
        self._redraw()

    def layered_soundings(
        self,
        positions: npt.ArrayLike,
        layer_tops: npt.ArrayLike,
        conductivity: npt.ArrayLike,
        *,
        title: str,
        elevations: npt.ArrayLike | None = None,
        line_of: npt.ArrayLike | None = None,
        layer_index: int | None = None,
        selected_line: str | None = None,
        flagged: npt.ArrayLike | None = None,
    ) -> None:
        """A batch of layered soundings: where they are, and the section they make."""
        xyz = np.asarray(positions, dtype=float)
        tops = np.asarray(layer_tops, dtype=float)
        sigma = np.asarray(conductivity, dtype=float)
        with np.errstate(divide="ignore"):
            rho = np.where(sigma > 0, 1.0 / sigma, np.nan)
        finite = rho[np.isfinite(rho)]
        if finite.size == 0:
            self.clear("No positive conductivity to draw.")
            return
        norm = LogNorm(
            vmin=float(np.nanpercentile(finite, 1)), vmax=float(np.nanpercentile(finite, 99))
        )
        self._figure.clear()
        plan, section = self._figure.subplots(2, 1, height_ratios=(1, 1.3))
        # One depth for the map: a third of the way down the layers.
        layer = int(
            np.clip(round(len(tops) / 3) if layer_index is None else layer_index, 0, len(tops) - 1)
        )
        mapping = plan.scatter(
            xyz[:, 0], xyz[:, 1], c=rho[:, layer], s=9, marker="s", cmap="Spectral_r", norm=norm
        )
        plan.set_aspect("equal", adjustable="datalim")
        plan.set_title(
            f"{title}: resistivity at {tops[layer]:.0f} m depth, {xyz.shape[0]} soundings"
        )
        plan.set_xlabel("Easting (m)")
        plan.set_ylabel("Northing (m)")
        if flagged is not None and np.any(flagged):
            bad = np.asarray(flagged, dtype=bool)
            plan.scatter(
                xyz[bad, 0],
                xyz[bad, 1],
                marker="x",
                c="black",
                s=24,
                label="Above χ² limit / unknown",
            )
            plan.legend(fontsize="small")
        # A survey flown as lines is drawn one line at a time: projected together,
        # eighteen lines interleave into stripes nobody can read.
        chosen = np.ones(len(xyz), dtype=bool)
        line_note = ""
        if line_of is not None:
            lines = np.asarray(line_of).astype(str)
            names, counts = np.unique(lines, return_counts=True)
            if len(names) > 1:
                longest = selected_line if selected_line in names else names[int(np.argmax(counts))]
                chosen = lines == longest
                line_note = f"line {longest}" + (
                    f", the longest of {len(names)}" if selected_line is None else ""
                )
                plan.scatter(
                    xyz[chosen, 0],
                    xyz[chosen, 1],
                    s=16,
                    facecolors="none",
                    edgecolors="black",
                    linewidths=0.6,
                )
        top_of = (
            np.asarray(elevations, dtype=float)[chosen]
            if elevations is not None
            else np.zeros(int(chosen.sum()))
        )
        xyz, rho = xyz[chosen], rho[chosen]
        # The long axis, by principal components of the positions.
        centred = xyz[:, :2] - xyz[:, :2].mean(axis=0)
        axis = (
            np.linalg.svd(centred, full_matrices=False)[2][0]
            if len(xyz) > 1
            else np.array([1.0, 0.0])
        )
        distance = centred @ axis
        distance -= distance.min()
        order = np.argsort(distance)
        steps = np.diff(distance[order])
        width = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 1.0
        thickness = np.diff(tops)
        bottoms = np.append(tops[1:], tops[-1] + (thickness[-1] if thickness.size else 1.0))
        patches, values = [], []
        for index in order:
            for k in range(len(tops)):
                upper = top_of[index] - tops[k]
                patches.append(
                    Rectangle(
                        (distance[index] - width / 2, upper - (bottoms[k] - tops[k])),
                        width,
                        bottoms[k] - tops[k],
                    )
                )
                values.append(rho[index, k])
        collection = PatchCollection(
            patches,
            array=np.asarray(values),
            cmap="Spectral_r",
            norm=norm,
            edgecolors="face",
            linewidths=0.1,
        )
        section.add_collection(collection)
        section.set_xlim(float(distance.min() - width), float(distance.max() + width))
        section.set_ylim(float((top_of - bottoms[-1]).min()), float(top_of.max() + 1.0))
        section.set_xlabel(
            f"Distance along {line_note} (m)"
            if line_note
            else "Distance along the survey's long axis (m)"
        )
        section.set_ylabel(
            "Elevation (m)" if elevations is not None else "Depth below the sounding (m)"
        )
        bar = self._figure.colorbar(mapping, ax=[plan, section], pad=0.02)
        bar.ax.yaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
        bar.ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
        bar.ax.yaxis.set_minor_formatter(NullFormatter())
        bar.set_label("Resistivity (ohm*m)")
        self._redraw()

    def sounding_1d(
        self,
        layer_tops: npt.ArrayLike,
        conductivity: npt.ArrayLike,
        *,
        title: str,
        times: npt.ArrayLike | None = None,
        observed: npt.ArrayLike | None = None,
        predicted: npt.ArrayLike | None = None,
    ) -> None:
        """One layered sounding: the model, and how well it fits the data it came from."""
        tops = np.asarray(layer_tops, dtype=float)
        sigma = np.asarray(conductivity, dtype=float)
        with np.errstate(divide="ignore"):
            rho = np.where(sigma > 0, 1.0 / sigma, np.nan)
        self._figure.clear()
        fits = times is not None and observed is not None and predicted is not None
        axes = self._figure.subplots(1, 2 if fits else 1, squeeze=False)[0]
        model = axes[0]
        thickness = np.diff(tops)
        bottom = tops[-1] + (thickness[-1] if thickness.size else 1.0)
        depths = np.append(tops, bottom)
        model.step(np.append(rho, rho[-1]), depths, where="post", color="#2e7d32")
        model.set_xscale("log")
        model.invert_yaxis()
        model.set_xlabel("Resistivity (ohm*m)")
        model.set_ylabel("Depth (m)")
        model.set_title(f"{title}: model")
        model.grid(True, which="both", linewidth=0.3, alpha=0.5)
        if fits:
            data = axes[1]
            t = np.asarray(times, dtype=float)
            data.loglog(
                t,
                np.abs(np.asarray(observed, dtype=float)),
                "o",
                color="#1f4e79",
                markersize=4,
                label="observed",
            )
            data.loglog(
                t,
                np.abs(np.asarray(predicted, dtype=float)),
                "-",
                color="#d62728",
                label="predicted",
            )
            data.set_xlabel("Time (s)")
            data.set_ylabel("|dB/dt| (T/s)")
            data.set_title("fit to the data")
            data.legend(fontsize="small")
            data.grid(True, which="both", linewidth=0.3, alpha=0.5)
        self._redraw()

    def station_map(self, stations: Any, *, title: str) -> None:
        """Stations in plan, coloured by their value: a gravity anomaly, an elevation."""
        self._figure.clear()
        axes = self._figure.add_subplot()
        values = np.asarray(stations.values, dtype=float)
        label = stations.label
        if label.startswith("gravity"):
            limit = float(np.nanmax(np.abs(values))) or 1.0
            norm: Normalize = Normalize(vmin=-limit, vmax=limit)
            cmap = "RdBu_r"  # signed about zero, so white is no anomaly
        else:
            norm = Normalize(vmin=float(np.nanmin(values)), vmax=float(np.nanmax(values)))
            cmap = "gist_earth"
        mapping = axes.scatter(stations.x_m, stations.y_m, c=values, s=14, cmap=cmap, norm=norm)
        axes.set_aspect("equal", adjustable="datalim")
        axes.set_title(title)
        axes.set_xlabel("Easting (m)")
        axes.set_ylabel("Northing (m)")
        units = {"gravity_mgal": "Gravity (mGal)", "z_m": "Elevation (m)"}
        self._figure.colorbar(mapping, ax=axes, pad=0.02).set_label(units.get(label, label))
        self._redraw()

    def sounding_curves(self, curves: Any, *, title: str) -> None:
        """Every sounding of a survey as its method is read, drawn together."""
        self._figure.clear()
        shown = (
            f"{len(curves.names)} of {curves.total}"
            if curves.total > len(curves.names)
            else f"{curves.total}"
        )
        style: dict[str, Any] = {"linewidth": 0.7, "alpha": 0.6}
        if curves.kind == "mt":
            rho_axes, phase_axes = self._figure.subplots(2, 1, sharex=True, height_ratios=(2, 1))
            for period, rho, phase in zip(curves.x, curves.y, curves.phase_degrees, strict=False):
                rho_axes.loglog(period, rho, **style)
                phase_axes.semilogx(period, phase, **style)
            rho_axes.set_ylabel("Apparent resistivity (ohm*m)")
            rho_axes.set_title(f"{title}: {shown} sites")
            phase_axes.set_ylabel("Phase (degrees)")
            phase_axes.set_xlabel("Period (s)")
            for axes in (rho_axes, phase_axes):
                axes.grid(True, which="both", linewidth=0.3, alpha=0.5)
        else:
            axes = self._figure.add_subplot()
            for x, y in zip(curves.x, curves.y, strict=False):
                if curves.kind == "decay":
                    axes.loglog(x, y, **style)
                else:
                    axes.plot(x, y, **style)
            if curves.kind == "decay":
                axes.set_xlabel("Time (s)")
                axes.set_ylabel("|dB/dt| (T/s)")
                noun = "soundings"
            else:
                axes.set_xlabel("Channel, in the order delivered")
                axes.set_ylabel("Response (as delivered)")
                noun = "soundings"
            axes.set_title(f"{title}: {shown} {noun}")
            axes.grid(True, which="both", linewidth=0.3, alpha=0.5)
        self._redraw()

    def curve(
        self,
        x: Sequence[float],
        y: Sequence[float],
        *,
        title: str,
        x_label: str,
        y_label: str,
        logarithmic_y: bool = False,
    ) -> None:
        """One series, which is what a misfit history and a sounding both are."""
        self._figure.clear()
        axes = self._figure.add_subplot()
        axes.plot(np.asarray(x, dtype=float), np.asarray(y, dtype=float), marker="o", ms=3)
        if logarithmic_y:
            axes.set_yscale("log")
        axes.set_title(title)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        axes.grid(True, alpha=0.3)
        self._redraw()

    def stations(
        self,
        east: Any,
        north: Any,
        *,
        title: str,
        second: tuple[Any, Any, str] | None = None,
    ) -> None:
        """A survey in map view, which is how a geometry error becomes visible."""
        self._figure.clear()
        axes = self._figure.add_subplot()
        axes.scatter(
            np.asarray(east, dtype=float), np.asarray(north, dtype=float), s=10, label="receivers"
        )
        if second is not None:
            other_east, other_north, label = second
            axes.scatter(
                np.asarray(other_east, dtype=float),
                np.asarray(other_north, dtype=float),
                s=26,
                marker="*",
                label=label,
            )
            axes.legend(loc="best", fontsize="small")
        axes.set_title(title)
        axes.set_xlabel("Easting (m)")
        axes.set_ylabel("Northing (m)")
        axes.set_aspect("equal", adjustable="datalim")
        axes.ticklabel_format(useOffset=False, style="plain")
        self._redraw()


def _break_at_gaps(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A gap in the receivers left open rather than bridged by a straight line."""
    if x.size < 3:
        return x, y
    steps = np.diff(x)
    typical = float(np.median(steps[steps > 0])) if np.any(steps > 0) else 0.0
    gaps = np.where(steps > 1.5 * typical)[0] if typical > 0 else np.array([], dtype=int)
    if gaps.size == 0:
        return x, y
    return np.insert(x, gaps + 1, np.nan), np.insert(y, gaps + 1, np.nan)


def _typical_step(values: np.ndarray) -> float:
    """The usual spacing between distinct values, for blocks that tile without gaps."""
    distinct = np.unique(np.round(values, 6))
    steps = np.diff(distinct)
    steps = steps[steps > 1e-9]
    return float(np.median(steps)) if steps.size else 1.0


def coverage_alpha(coverage: npt.ArrayLike, drop_threshold: float = 0.4) -> np.ndarray:
    """pyGIMLi's coverage-to-opacity rule (`pygimli.viewer.mpl.addCoverageAlpha`)."""
    values = np.asarray(coverage, dtype=float)
    finite = np.isfinite(values)
    alpha = np.zeros(values.shape, dtype=float)
    if finite.sum() < 2:
        return np.where(finite, 1.0, 0.0)
    low, high = np.quantile(values[finite], [0.02, drop_threshold])
    if high <= low:
        alpha[finite] = 1.0
        return alpha
    alpha[finite] = np.clip((values[finite] - low) / (high - low), 0.0, 1.0)
    return alpha


def _colour_values(
    values: npt.ArrayLike, colour_label: str, logarithmic: bool
) -> tuple[np.ndarray, str]:
    """What to colour by, and what to call it."""
    array = np.asarray(values, dtype=float)
    finite = np.isfinite(array)
    if logarithmic:
        shown = np.where(finite & (array > 0), array, np.nan)
        return np.log10(shown), (f"log10 {colour_label}" if colour_label else "log10")
    return np.where(finite, array, np.nan), colour_label
