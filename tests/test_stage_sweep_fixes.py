"""What a sweep of every stage over the three real projects found blank, now drawn."""

import os
from importlib.util import find_spec

import numpy as np
import pytest

from ofag.services.data_preview import MU_0, sounding_directory, station_values

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
needs_qt = pytest.mark.skipif(
    find_spec("PySide6") is None, reason="the desktop extra is not installed"
)


class TestReaders:
    def test_stations_are_x_y_and_their_last_column(self, tmp_path) -> None:
        path = tmp_path / "observations_mgal.csv"
        path.write_text("x_m,y_m,z_m,gravity_mgal\n1,2,3,-0.5\n4,5,6,0.25\n", encoding="utf-8")

        stations = station_values(path)

        assert stations.label == "gravity_mgal" and list(stations.values) == [-0.5, 0.25]

    def test_an_mt_site_becomes_apparent_resistivity_and_phase(self, tmp_path) -> None:
        # A 100 ohm.m half-space at 1 Hz: |Z| = sqrt(omega mu0 rho), phase 45 degrees.
        omega = 2 * np.pi
        z = np.sqrt(omega * MU_0 * 100.0) * np.exp(1j * np.pi / 4)
        (tmp_path / "S1.csv").write_text(
            f"frequency_hz,impedance_real_ohm,impedance_imag_ohm,uncertainty_ohm\n1.0,{z.real},{z.imag},0.1\n",
            encoding="utf-8",
        )

        curves = sounding_directory(tmp_path)

        assert curves.kind == "mt"
        assert curves.y[0][0] == pytest.approx(100.0) and curves.phase_degrees[0][
            0
        ] == pytest.approx(45.0)

    def test_tem_soundings_are_decays_and_the_walk_copies_are_left_out(self, tmp_path) -> None:
        for name in ("a", "b", "tdem_dbdt_walk"):
            (tmp_path / f"{name}.csv").write_text(
                "time_s,magnetic_flux_density_time_derivative_t_s\n1e-5,-2e-5\n1e-4,-3e-7\n",
                encoding="utf-8",
            )

        curves = sounding_directory(tmp_path)

        assert curves.kind == "decay" and curves.names == ("a", "b")
        assert curves.y[0][0] == pytest.approx(2e-5)  # the magnitude

    def test_many_soundings_are_sampled_and_the_total_kept(self, tmp_path) -> None:
        for index in range(305):
            (tmp_path / f"L1-{index:04d}.csv").write_text("ppm\n1.0\n2.0\n", encoding="utf-8")

        curves = sounding_directory(tmp_path)

        assert curves.kind == "channels" and curves.total == 305 and len(curves.names) == 300


@needs_qt
class TestDrawing:
    @staticmethod
    def _panel():
        from PySide6.QtWidgets import QApplication

        from ofag.desktop.plotting import PlotPanel

        QApplication.instance() or QApplication([])
        return PlotPanel()

    def test_a_batch_is_a_map_and_the_longest_lines_section(self) -> None:
        panel = self._panel()
        positions = np.array(
            [[x, y, 100.0] for y, count in ((0.0, 5), (50.0, 3)) for x in range(0, count * 10, 10)]
        )
        lines = np.array(["L1"] * 5 + ["L2"] * 3)
        conductivity = np.full((8, 3), 0.01)

        panel.layered_soundings(
            positions,
            [0.0, 5.0, 15.0],
            conductivity,
            title="batch",
            line_of=lines,
            elevations=positions[:, 2],
        )

        plan, section = panel._figure.axes[:2]
        assert "line L1, the longest of 2" in section.get_xlabel()
        assert sum(len(c.get_paths()) for c in section.collections) == 5 * 3

    def test_one_sounding_shows_its_model_and_its_fit(self) -> None:
        panel = self._panel()
        panel.sounding_1d(
            [0.0, 10.0],
            [0.01, 0.001],
            title="t",
            times=[1e-5, 1e-4],
            observed=[-2e-5, -3e-7],
            predicted=[-2.1e-5, -2.9e-7],
        )

        model, fit = panel._figure.axes[:2]
        assert model.get_xscale() == "log" and fit.get_title() == "fit to the data"


@needs_qt
def test_the_inversion_form_is_filled_from_the_survey_register(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from ofag.core.schemas import CoordinateConvention, DatasetKind, ProjectCreateRequest
    from ofag.desktop.session import Session
    from ofag.desktop.stages.inversion import InversionStage, _fill_paths

    QApplication.instance() or QApplication([])
    assert _fill_paths(
        {"array": {"sensors_path": None, "shot_receiver_path": None}, "n": 3},
        {"sensors_path": "s.npy", "pairs_path": "p.npy"},
    ) == {"array": {"sensors_path": "s.npy", "shot_receiver_path": "p.npy"}, "n": 3}

    from ofag.services.project_service import ProjectService

    projects = ProjectService(root=tmp_path / "Result")
    record = projects.create(
        ProjectCreateRequest(
            name="p",
            coordinate_convention=CoordinateConvention(crs="EPSG:26915"),
            elevation_reference="NAVD88",
            enabled_methods=("ert",),
        )
    )
    projects.register_dataset(
        record.project_id,
        kind=DatasetKind.ERT,
        name="line",
        source_filename="l",
        imported={
            "dataset_id": "7c8f0a5e-0000-4000-8000-000000000009",
            "electrodes_path": "e.npy",
            "quadrupoles_path": "q.npy",
            "observations_path": "o.csv",
        },
    )
    stage = InversionStage()
    stage.set_session(Session.open(projects, record.project_id))
    stage._plugin.setCurrentIndex(
        next(
            i
            for i in range(stage._plugin.count())
            if stage._plugin.itemData(i) == "pygimli.ert.dcip"
        )
    )
    stage._dataset.setCurrentIndex(
        next(i for i in range(stage._dataset.count()) if stage._dataset.itemData(i) is not None)
    )

    array = stage._form.value()["array"]
    assert (array["electrodes_path"], array["quadrupoles_path"]) == ("e.npy", "q.npy")
    assert "Data paths loaded" in stage._report.toPlainText()
