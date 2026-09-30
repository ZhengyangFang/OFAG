"""Removing a run, and saying what it was for while it is still there."""

from pathlib import Path
from uuid import uuid4

import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    RunState,
    TensorMeshSpec,
)
from ofag.execution.state import IN_FLIGHT_STATES
from ofag.services.run_service import RunService


def _spec(tmp_path: Path, label: str | None = None) -> RunSpec:
    observations = tmp_path / f"{uuid4().hex}.csv"
    observations.write_text(
        "x_m,y_m,z_m,gravity_mgal\n"
        "-10.0,-10.0,5.0,0.011\n"
        "10.0,-10.0,5.0,0.015\n"
        "-10.0,10.0,5.0,0.013\n"
        "10.0,10.0,5.0,0.017\n",
        encoding="utf-8",
    )
    return RunSpec(
        plugin_id="simpeg.pf.gravity3d",
        engine="simpeg",
        label=label,
        dataset=DatasetSpec(
            name="deletable",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        parameters={
            "observations_path": str(observations),
            "initial_density_contrast": QuantitySpec(
                value=0.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
            ),
            "data_uncertainty": QuantitySpec(
                value=1e-3, quantity_type=QuantityType.GRAVITY_ACCELERATION, unit="mGal"
            ),
        },
    )


class TestTheLabel:
    def test_a_run_can_say_what_it_was_for(self, tmp_path) -> None:
        runs = RunService(artifact_root=tmp_path / "runs")
        spec = _spec(tmp_path, label="DOI, weighted, reference -0.130")
        runs.create(spec)

        (record,) = runs.list_runs()
        assert record.spec.label == "DOI, weighted, reference -0.130"

    def test_the_label_survives_a_restart(self, tmp_path) -> None:
        """The list is rebuilt from disk, so a label that lives only in memory is a label the
        operator loses the moment they close the workbench."""
        root = tmp_path / "runs"
        spec = _spec(tmp_path, label="the one we kept")
        RunService(artifact_root=root).create(spec)

        (record,) = RunService(artifact_root=root).list_runs()

        assert record.spec.label == "the one we kept"

    def test_a_run_without_one_is_still_a_run(self, tmp_path) -> None:
        runs = RunService(artifact_root=tmp_path / "runs")
        runs.create(_spec(tmp_path))

        (record,) = runs.list_runs()
        assert record.spec.label is None


class TestDeleting:
    def test_the_run_and_its_folder_both_go(self, tmp_path) -> None:
        runs = RunService(artifact_root=tmp_path / "runs")
        spec = _spec(tmp_path, label="scratch")
        runs.create(spec)
        run_dir = runs.run_dir(spec.run_id)
        assert run_dir.is_dir()

        runs.delete(spec.run_id)

        assert not run_dir.exists()
        assert runs.list_runs() == ()

    def test_a_deleted_run_does_not_come_back_from_disk(self, tmp_path) -> None:
        """`list_runs` merges memory with the directory, so a delete that left either behind
        would resurrect the run on the next listing."""
        root = tmp_path / "runs"
        runs = RunService(artifact_root=root)
        spec = _spec(tmp_path)
        runs.create(spec)
        runs.delete(spec.run_id)

        assert runs.list_runs() == ()
        assert RunService(artifact_root=root).list_runs() == ()

    def test_deleting_one_leaves_the_others(self, tmp_path) -> None:
        runs = RunService(artifact_root=tmp_path / "runs")
        kept, scratch = _spec(tmp_path, "kept"), _spec(tmp_path, "scratch")
        runs.create(kept)
        runs.create(scratch)

        runs.delete(scratch.run_id)

        assert [record.spec.label for record in runs.list_runs()] == ["kept"]
        assert runs.run_dir(kept.run_id).is_dir()

    @pytest.mark.parametrize("state", sorted(IN_FLIGHT_STATES, key=str))
    def test_a_run_a_process_may_be_writing_to_is_refused(self, tmp_path, state) -> None:
        """The directory is not the service's to remove while a child owns it."""
        runs = RunService(artifact_root=tmp_path / "runs")
        spec = _spec(tmp_path)
        record = runs.create(spec)
        runs._records[spec.run_id] = record.model_copy(update={"state": state})

        with pytest.raises(ValueError, match="cancel it before deleting it"):
            runs.delete(spec.run_id)

        assert runs.run_dir(spec.run_id).is_dir()

    def test_a_cancelled_run_can_be_deleted(self, tmp_path) -> None:
        """Which is the whole route out of the refusal above."""
        runs = RunService(artifact_root=tmp_path / "runs")
        spec = _spec(tmp_path)
        runs.create(spec)
        runs.cancel(spec.run_id)
        assert runs.get(spec.run_id).state is RunState.CANCELLED

        runs.delete(spec.run_id)

        assert runs.list_runs() == ()

    def test_deleting_a_run_that_is_not_there_is_refused(self, tmp_path) -> None:
        runs = RunService(artifact_root=tmp_path / "runs")

        with pytest.raises((KeyError, ValueError)):
            runs.delete(uuid4())
