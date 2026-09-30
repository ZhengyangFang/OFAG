"""Two-dimensional ERT sections drawn the way pyGIMLi draws them."""

import os
from importlib.util import find_spec

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    find_spec("PySide6") is None, reason="the desktop extra is not installed"
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Two triangles sharing an edge, a unit square split on its diagonal.
NODES = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, -5.0, 0.0], [0.0, -5.0, 0.0]])
CELLS = np.array([[0, 1, 2], [0, 2, 3]])


def _panel():
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.plotting import PlotPanel

    QApplication.instance() or QApplication([])
    return PlotPanel()


def _collection(panel):
    from matplotlib.collections import PolyCollection

    axes = panel._figure.axes[0]
    return next(c for c in axes.collections if isinstance(c, PolyCollection)), axes


def test_each_cell_is_filled_as_its_own_polygon() -> None:
    panel = _panel()
    panel.mesh_section(NODES, CELLS, [30.0, 300.0], title="t", logarithmic=True)

    collection, _ = _collection(panel)
    paths = collection.get_paths()
    assert len(paths) == 2
    assert np.allclose(paths[0].vertices[:3], NODES[CELLS[0], :2])


def test_the_colour_scale_is_logarithmic_and_labelled_in_the_units() -> None:
    from matplotlib.colors import LogNorm

    panel = _panel()
    panel.mesh_section(
        NODES, CELLS, [30.0, 300.0], title="t", logarithmic=True, colour_label="Resistivity (ohm*m)"
    )

    collection, _ = _collection(panel)
    assert isinstance(collection.norm, LogNorm)
    colour_bar = panel._figure.axes[1]
    assert colour_bar.get_ylabel() == "Resistivity (ohm*m)"
    labels = [t.get_text() for t in colour_bar.get_yticklabels() if t.get_text()]
    assert "100" in labels and not any("^" in label for label in labels)


def test_electrodes_are_marked_on_the_surface() -> None:
    panel = _panel()
    panel.mesh_section(
        NODES,
        CELLS,
        [30.0, 300.0],
        title="t",
        electrodes=np.array([[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [10.0, 0.0, 0.0]]),
    )

    _, axes = _collection(panel)
    (line,) = [drawn for drawn in axes.lines if drawn.get_label() == "electrodes"]
    assert list(line.get_xdata()) == [0.0, 5.0, 10.0]


def test_a_model_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(ValueError, match="values for 2 cells"):
        _panel().mesh_section(NODES, CELLS, [30.0, 300.0, 3.0], title="t")


class TestCoverageAlpha:
    """pyGIMLi's `addCoverageAlpha`: clear at the 2nd percentile, full at the 40th."""

    def test_the_well_covered_cells_keep_full_colour_and_the_rest_fade(self) -> None:
        from ofag.desktop.plotting import coverage_alpha

        alpha = coverage_alpha(np.linspace(-4.0, 1.0, 101))

        assert alpha[0] == 0.0 and alpha[-1] == 1.0
        assert np.all(alpha[50:] == 1.0)  # above the 40th percentile
        assert np.all(np.diff(alpha) >= 0)

    def test_non_finite_coverage_is_clear(self) -> None:
        from ofag.desktop.plotting import coverage_alpha

        alpha = coverage_alpha(np.array([np.nan, 1.0, 2.0, 3.0]))

        assert alpha[0] == 0.0

    def test_it_reaches_the_drawing(self) -> None:
        panel = _panel()
        panel.mesh_section(NODES, CELLS, [30.0, 300.0], title="t", coverage=[-3.0, 1.0])

        collection, _ = _collection(panel)
        assert list(np.round(collection.get_alpha(), 3)) == [0.0, 1.0]


def test_the_results_stage_reads_the_mesh_and_electrodes_a_run_saved(tmp_path) -> None:
    from types import SimpleNamespace

    from ofag.desktop.stages.results import _electrodes, _mesh_cells, _unit_label

    np.savez(
        tmp_path / "mesh_geometry.npz",
        nodes_m=NODES,
        cell_nodes=CELLS,
        cell_centers_m=NODES[:2],
        cell_sizes=np.ones(2),
    )
    result = SimpleNamespace(
        artifacts=[
            SimpleNamespace(artifact_type="mesh_geometry", relative_path="run/mesh_geometry.npz")
        ]
    )
    nodes, cells = _mesh_cells(tmp_path, result)
    assert cells.shape == (2, 3) and nodes.shape == (4, 3)

    electrodes = tmp_path / "electrodes_m.npy"
    np.save(electrodes, np.array([[0.0, 0.0, 0.0]]))
    spec = SimpleNamespace(physics={"array": {"electrodes_path": str(electrodes)}})
    session = SimpleNamespace(runs=SimpleNamespace(get=lambda run_id: SimpleNamespace(spec=spec)))
    assert _electrodes(session, "id").shape == (1, 3)
    assert _unit_label("resistivity", "ohm*m") == "Resistivity (ohm*m)"
