"""Imports stay on the project's register, whoever made them."""

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from ofag.agent.roles import Role, dispatcher_for
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetKind,
    ProjectCreateRequest,
    RunRecord,
    RunState,
)
from ofag.services.project_service import ProjectService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _project(tmp_path):
    projects = ProjectService(root=tmp_path / "Result")
    record = projects.create(
        ProjectCreateRequest(
            name="Llano",
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            elevation_reference="NAVD88",
            enabled_methods=("ert", "gravity"),
        )
    )
    return projects, record.project_id


class TestRegisterDataset:
    def test_it_registers_and_a_second_call_is_harmless(self, tmp_path) -> None:
        projects, project_id = _project(tmp_path)
        payload = {"dataset_id": str(uuid4()), "canonical_observations_path": "imports/x/obs.csv"}

        first = projects.register_dataset(
            project_id,
            kind=DatasetKind.GRAVITY,
            name="Gravity",
            source_filename="gravity.csv",
            imported=payload,
        )
        again = projects.register_dataset(
            project_id,
            kind=DatasetKind.GRAVITY,
            name="Gravity",
            source_filename="gravity.csv",
            imported=payload,
        )

        assert first.dataset_id == again.dataset_id
        assert [d.name for d in projects.workspace(project_id).datasets] == ["Gravity"]

    def test_a_pydantic_result_is_stored_as_json(self, tmp_path) -> None:
        projects, project_id = _project(tmp_path)
        result = CoordinateConvention(crs="EPSG:26914")

        dataset = projects.register_dataset(
            project_id,
            kind=DatasetKind.TOPOGRAPHY,
            name="t",
            source_filename="t.csv",
            imported=result,
        )

        assert dataset.payload["crs"] == "EPSG:26914" and dataset.payload["dataset_id"]


class TestAnAgentsImportIsRegistered:
    def test_an_import_by_the_data_role_appears_in_the_project(self, tmp_path) -> None:
        projects, project_id = _project(tmp_path)
        runs = projects.folder(project_id).runs_root
        csv = tmp_path / "gravity.csv"
        csv.write_text(
            "easting,northing,elevation,gz\n0,0,100,-1.5\n10,0,101,-1.2\n0,10,99,-1.4\n",
            encoding="utf-8",
        )

        answer = dispatcher_for(Role.DATA, runs).call(
            "ofag.import_data",
            {
                "importer_id": "ofag.import.gravity_csv",
                "request": {
                    "filename": "gravity.csv",
                    "source_path": csv.as_posix(),
                    "x_column": "easting",
                    "y_column": "northing",
                    "z_column": "elevation",
                    "gravity_column": "gz",
                    "coordinate_unit": "m",
                    "gravity_unit": "mGal",
                    "coordinate_convention": {"crs": "EPSG:26914"},
                },
            },
        )

        assert answer["registered_in_project"] == "gravity.csv"
        (dataset,) = projects.workspace(project_id).datasets
        assert (
            dataset.kind is DatasetKind.GRAVITY and str(dataset.dataset_id) == answer["dataset_id"]
        )
        assert (
            dispatcher_for(Role.LEAD, runs).call("ofag.project", {})["datasets"][0]["name"]
            == "gravity.csv"
        )

    def test_outside_a_project_nothing_is_registered(self, tmp_path) -> None:
        csv = tmp_path / "gravity.csv"
        csv.write_text(
            "easting,northing,elevation,gz\n0,0,100,-1.5\n10,0,101,-1.2\n", encoding="utf-8"
        )

        answer = dispatcher_for(Role.DATA, tmp_path / "loose").call(
            "ofag.import_data",
            {
                "importer_id": "ofag.import.gravity_csv",
                "request": {
                    "filename": "gravity.csv",
                    "source_path": csv.as_posix(),
                    "x_column": "easting",
                    "y_column": "northing",
                    "z_column": "elevation",
                    "gravity_column": "gz",
                    "coordinate_unit": "m",
                    "gravity_unit": "mGal",
                    "coordinate_convention": {"crs": "EPSG:26914"},
                },
            },
        )

        assert "registered_in_project" not in answer


UNITS = {"transfer_resistance": "ohm", "magnetic_flux_density_time_derivative": "V/m^2"}


class TestTheBackfillFromRuns:
    """The runs decide what was inverted: the case state had moved on to later import copies
    that no run read."""

    @staticmethod
    def _run(
        runs_root: Path, name: str, quantity: str, plugin: str, import_id: str, *, batch=False
    ):
        from ofag.core.schemas import QuantityType
        from tests.conftest import gravity_run_spec

        spec = gravity_run_spec()
        channel_dataset = spec.dataset.model_copy(
            update={
                "name": name,
                "physical_quantity": QuantityType(quantity),
                "units": UNITS[quantity],
            }
        )
        if batch:
            spec = spec.model_copy(
                update={
                    "plugin_id": plugin,
                    "dataset": channel_dataset,
                    "datasets": (),
                    "physics": {
                        "soundings": [{"observations_path": f"imports/{import_id}/s1.csv"}]
                    },
                }
            )
        else:
            from ofag.core.schemas import DataChannelSpec, QuantitySpec, QuantityType

            channel = DataChannelSpec(
                channel_id="dc",
                dataset=channel_dataset,
                observations_path=f"{runs_root.parent.as_posix()}/imports/{import_id}/observations.csv",
                data_uncertainty=QuantitySpec(
                    value=0.05, quantity_type=QuantityType.TRANSFER_RESISTANCE, unit="ohm"
                ),
            )
            spec = spec.model_copy(update={"plugin_id": plugin, "datasets": (channel,)})
        record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
        folder = runs_root / str(spec.run_id)
        folder.mkdir(parents=True)
        (folder / "run_record.json").write_text(record.model_dump_json(), encoding="utf-8")
        return record

    def test_what_the_runs_read_is_registered_and_lineage_finds_it(self, tmp_path) -> None:
        from register_case_datasets import register

        from ofag.desktop.stages.lineage import _source_datasets

        projects, project_id = _project(tmp_path)
        folder = projects.folder(project_id)
        runs_root = folder.runs_root
        old, new = str(uuid4()), str(uuid4())
        first = self._run(
            runs_root, "llano-ert1-dc", "transfer_resistance", "pygimli.ert.dcip", old
        )
        second = self._run(
            runs_root, "llano-ert1-dc", "transfer_resistance", "pygimli.ert.dcip", new
        )
        batch = self._run(
            runs_root,
            "llano-tdem",
            "magnetic_flux_density_time_derivative",
            "simpeg.aem.batch_tdem1d",
            str(uuid4()),
            batch=True,
        )
        (folder.root / "case_state.json").write_text(
            json.dumps(
                {
                    "srt_imports": [
                        {"profile": 2, "dataset_id": str(uuid4()), "source": "srt2.txt"}
                    ],
                    "ert_imports": [
                        {"profile": 1, "dataset_id": str(uuid4()), "source": "ert1.dat"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        from_runs, from_state, kept = register(folder.root)
        again = register(folder.root)

        datasets = projects.workspace(project_id).datasets
        names = sorted(d.name for d in datasets)
        # ERT1 once, though read from two copies; the TDEM batch run; SRT2, which no run
        # read; and ERT1 from the case state left out as a duplicate.
        assert names == ["SRT2 first arrivals", "llano-ert1-dc", "llano-tdem"]
        assert (from_runs, from_state, kept) == (2, 1, 0) and again == (2, 1, 0)
        ert = next(d for d in datasets if d.name == "llano-ert1-dc")
        assert ert.payload["other_copies"] and len(ert.payload["used_by_runs"]) == 2
        for record in (first, second, batch):
            assert _source_datasets(record, datasets)

    def test_a_dataset_imported_by_hand_is_never_touched(self, tmp_path) -> None:
        from register_case_datasets import register

        projects, project_id = _project(tmp_path)
        projects.register_dataset(
            project_id,
            kind=DatasetKind.GRAVITY,
            name="by hand",
            source_filename="g.csv",
            imported={"dataset_id": str(uuid4())},
        )

        assert register(projects.folder(project_id).root)[2] == 1
        assert [d.name for d in projects.workspace(project_id).datasets] == ["by hand"]


@pytest.fixture(autouse=True)
def _no_leak_of_script_path():
    yield
