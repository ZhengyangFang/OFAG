"""What a survey looks like before it is inverted: pseudosections and traveltimes."""

import math
import os
from importlib.util import find_spec

import numpy as np
import pytest

from ofag.services.data_preview import PSEUDO_DEPTH_FACTOR, pseudosection, traveltime_curves


def _ert(tmp_path, electrodes, quadrupoles, resistance):
    np.save(tmp_path / "electrodes_m.npy", np.asarray(electrodes, dtype=float))
    np.save(tmp_path / "quadrupoles.npy", np.asarray(quadrupoles, dtype=int))
    (tmp_path / "observations_ohm.csv").write_text(
        "resistance_ohm\n" + "\n".join(f"{r:.10e}" for r in resistance) + "\n", encoding="utf-8"
    )
    return (
        tmp_path / "electrodes_m.npy",
        tmp_path / "quadrupoles.npy",
        tmp_path / "observations_ohm.csv",
    )


LINE = [[x, 0.0, 0.0] for x in (0.0, 10.0, 20.0, 30.0)]


class TestApparentResistivity:
    def test_a_wenner_reading_is_two_pi_a_times_its_resistance(self, tmp_path) -> None:
        """Wenner, A M N B at spacing a: K = 2 pi a."""
        section = pseudosection(*_ert(tmp_path, LINE, [[0, 3, 1, 2]], [1.5]))

        assert section.apparent_resistivity_ohm_m[0] == pytest.approx(2 * math.pi * 10.0 * 1.5)

    def test_a_remote_electrode_contributes_nothing(self, tmp_path) -> None:
        """Pole-pole, B and N at infinity: K = 2 pi a."""
        section = pseudosection(*_ert(tmp_path, LINE, [[0, -1, 1, -1]], [2.0]))

        assert section.apparent_resistivity_ohm_m[0] == pytest.approx(2 * math.pi * 10.0 * 2.0)

    def test_the_midpoint_and_pseudo_depth(self, tmp_path) -> None:
        section = pseudosection(*_ert(tmp_path, LINE, [[0, 3, 1, 2]], [1.0]))

        assert section.midpoint_m[0] == pytest.approx(15.0)
        assert section.pseudo_depth_m[0] == pytest.approx(PSEUDO_DEPTH_FACTOR * 30.0)

    def test_a_reading_with_no_positive_apparent_resistivity_is_counted_not_hidden(
        self, tmp_path
    ) -> None:
        section = pseudosection(*_ert(tmp_path, LINE, [[0, 3, 1, 2], [0, 3, 1, 2]], [1.0, -0.2]))

        assert section.dropped == 1 and section.apparent_resistivity_ohm_m.size == 1

    def test_files_from_two_surveys_are_refused(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="not one survey"):
            pseudosection(*_ert(tmp_path, LINE, [[0, 3, 1, 2]], [1.0, 2.0]))


def test_traveltimes_are_grouped_by_shot_and_ordered_by_position(tmp_path) -> None:
    np.save(tmp_path / "sensors_m.npy", np.array([[0.0, 0, 0], [4.0, 0, 0], [8.0, 0, 0]]))
    np.save(tmp_path / "shot_receiver.npy", np.array([[0, 2], [0, 1], [2, 0]]))
    (tmp_path / "traveltime_s.csv").write_text("traveltime_s\n0.02\n0.01\n0.03\n", encoding="utf-8")

    curves = traveltime_curves(
        tmp_path / "sensors_m.npy", tmp_path / "shot_receiver.npy", tmp_path / "traveltime_s.csv"
    )

    (first_x, receivers, times), (second_x, _, _) = curves.shots
    assert (first_x, second_x) == (0.0, 8.0)
    assert list(receivers) == [4.0, 8.0] and list(times) == [0.01, 0.02]


@pytest.mark.skipif(find_spec("PySide6") is None, reason="the desktop extra is not installed")
class TestTheSetupStage:
    @staticmethod
    def _app():
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        return QApplication.instance() or QApplication([])

    @staticmethod
    def _session(tmp_path, payload, kind):
        from ofag.core.schemas import CoordinateConvention, DatasetKind, ProjectCreateRequest
        from ofag.desktop.session import Session
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
            kind=DatasetKind(kind),
            name="survey",
            source_filename="s",
            imported=payload,
        )
        return Session.open(projects, record.project_id)

    def test_selecting_a_resistivity_survey_draws_its_pseudosection(self, tmp_path) -> None:
        from matplotlib.collections import PatchCollection

        from ofag.desktop.stages.setup import SetupStage

        self._app()
        electrodes, quadrupoles, observations = _ert(
            tmp_path, LINE, [[0, 3, 1, 2], [0, 1, 2, 3]], [1.0, 0.5]
        )
        session = self._session(
            tmp_path,
            {
                "dataset_id": "7c8f0a5e-0000-4000-8000-000000000001",
                "electrodes_path": str(electrodes),
                "quadrupoles_path": str(quadrupoles),
                "observations_path": str(observations),
            },
            "ert",
        )
        stage = SetupStage()
        stage.set_session(session)

        axes = stage._plot._figure.axes[0]
        assert any(isinstance(c, PatchCollection) for c in axes.collections)
        assert "Pseudo-depth" in axes.get_ylabel()
        assert stage._prepare_button.isHidden() and stage._build_button.isHidden()
        # Nothing to select or build for a resistivity survey: the column is gone.
        assert stage._left_holder.isHidden() and stage._report.isHidden()

    def test_the_segy_steps_are_offered_only_for_a_segy_line(self, tmp_path) -> None:
        from ofag.desktop.stages.setup import SetupStage

        self._app()
        session = self._session(
            tmp_path, {"dataset_id": "7c8f0a5e-0000-4000-8000-000000000002"}, "seismic"
        )
        stage = SetupStage()
        stage.set_session(session)

        assert not stage._prepare_button.isHidden() and not stage._build_button.isHidden()
        assert not stage._left_holder.isHidden()
