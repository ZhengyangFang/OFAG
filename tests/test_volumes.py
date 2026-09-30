"""The cell grid, and the model written on it."""

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.agent.tools import Tier, tool_manifest
from ofag.agent.volumes import CellGridSpec, build_cell_grid, load_grid, save_grid

#: A box with real relief in it, which is what makes the F034 arithmetic visible.
GROUND = {
    "ground_easting_m": (0.0, 1000.0, 0.0, 1000.0, 500.0),
    "ground_northing_m": (0.0, 0.0, 500.0, 500.0, 250.0),
    "ground_elevation_m": (215.0, 273.0, 220.0, 268.0, 245.0),
    "ground_source": "DTM_HEM, nearest sounding",
}
BOX = {
    "name": "a valley",
    "min_x_m": 0.0,
    "max_x_m": 1000.0,
    "min_y_m": 0.0,
    "max_y_m": 500.0,
    "cell_m": (100.0, 100.0, 10.0),
    "depth_m": 100.0,
}


def _spec(**overrides) -> CellGridSpec:
    return CellGridSpec(**{**BOX, **GROUND, **overrides})


@pytest.fixture
def dispatcher(tmp_path):
    return Dispatcher(
        artifact_root=tmp_path / "artifacts",
        granted=(Tier.READ, Tier.COMPUTE, Tier.WRITE),
    )


class TestTheGroundHasToBeStated:
    def test_a_grid_with_no_ground_will_not_construct(self) -> None:
        """F034. A volume on a plane renders, reports unit shares and is read as geology
        exactly like one that is not."""
        with pytest.raises(ValidationError, match="says nothing about where the ground is"):
            _spec(ground_easting_m=(), ground_northing_m=(), ground_elevation_m=())

    def test_flat_is_an_answer_and_silence_is_not(self) -> None:
        """One point means a declared flat surface, which is legitimate -- and is a different
        statement from not saying."""
        grid = build_cell_grid(
            _spec(
                ground_easting_m=(500.0,),
                ground_northing_m=(250.0,),
                ground_elevation_m=(240.0,),
                ground_source="flat, from the release's own datum",
            )
        )

        assert grid.terrain.relief_m == 0.0
        assert np.all(grid.ground_elevation_m == 240.0)

    def test_the_source_travels_with_the_grid(self) -> None:
        assert build_cell_grid(_spec()).terrain.source == "DTM_HEM, nearest sounding"

    def test_a_ground_of_mismatched_lengths_will_not_construct(self) -> None:
        with pytest.raises(ValidationError, match="for its ground"):
            _spec(ground_elevation_m=(215.0, 273.0))


class TestTheArithmeticThatWasWrong:
    def test_a_cell_sits_at_its_own_ground_minus_its_depth(self) -> None:
        """The F034 defect in one assertion."""
        grid = build_cell_grid(_spec())

        assert np.allclose(
            grid.cell_centres_m[:, 2],
            grid.ground_elevation_m - grid.depth_below_ground_m,
        )

    def test_elevation_and_depth_are_different_arrays(self) -> None:
        """A cell 1,600 m above sea level read as 1,600 m down is the kind of thing that
        produces a plausible model."""
        grid = build_cell_grid(_spec())

        assert grid.depth_below_ground_m.min() > 0.0
        assert grid.cell_centres_m[:, 2].min() > 0.0
        assert not np.allclose(grid.cell_centres_m[:, 2], -grid.depth_below_ground_m)

    def test_the_relief_is_measured_on_the_ground_the_grid_uses(self) -> None:
        """Not on the points it came from."""
        grid = build_cell_grid(_spec())

        # Once per column, not repeated per cell: repeating every value sixty times
        # would leave the relief right and make the quantum detector read a grid that is
        # an artefact of the layer count.
        assert grid.terrain.count == grid.axes[0] * grid.axes[1]
        assert grid.terrain.count < grid.cells
        assert 0.0 < grid.terrain.relief_m <= 273.0 - 215.0


class TestWhatItReportsRatherThanHides:
    def test_the_furthest_column_from_a_ground_point_is_kept(self) -> None:
        """F006: a nearest-neighbour resample is defined everywhere, including past the edge
        of its own source."""
        grid = build_cell_grid(_spec())

        assert grid.ground_distance_m.max() > 0.0
        assert "furthest_column_from_a_ground_point_m" in grid.summary()

    def test_a_cell_bigger_than_its_box_is_refused(self) -> None:
        with pytest.raises(ValueError, match="larger than the box"):
            build_cell_grid(_spec(cell_m=(2000.0, 2000.0, 10.0)))

    def test_a_grid_survives_the_round_trip(self, tmp_path) -> None:
        grid = build_cell_grid(_spec())
        save_grid(grid, tmp_path)

        back = load_grid(grid.grid_id, tmp_path)

        assert back.cells == grid.cells
        assert back.terrain.source == grid.terrain.source
        assert np.allclose(back.cell_centres_m, grid.cell_centres_m)

    def test_a_grid_that_is_not_there_says_how_to_make_one(self, tmp_path) -> None:
        from uuid import uuid4

        with pytest.raises(FileNotFoundError, match="ofag.cell_grid"):
            load_grid(uuid4(), tmp_path)


class TestThroughTheToolSurface:
    def test_every_declared_tool_is_now_callable(self) -> None:
        """The whole point of this pair."""
        from pathlib import Path

        unreachable = []
        for tool in tool_manifest(None):
            try:
                Dispatcher(artifact_root=Path("."))._handler(tool.name)
            except ToolError:
                unreachable.append(tool.name)

        assert unreachable == []

    def test_a_grid_with_no_ground_is_refused_readably(self, dispatcher) -> None:
        bad = {**BOX, **GROUND, "cell_m": list(BOX["cell_m"])}
        bad.update(ground_easting_m=[], ground_northing_m=[], ground_elevation_m=[])

        with pytest.raises(ToolError, match="where the ground is"):
            dispatcher.call("ofag.cell_grid", {"spec": bad})

    def _grid(self, dispatcher) -> str:
        spec = {**BOX, **GROUND}
        spec["cell_m"] = list(BOX["cell_m"])
        for key in ("ground_easting_m", "ground_northing_m", "ground_elevation_m"):
            spec[key] = list(GROUND[key])
        return dispatcher.call("ofag.cell_grid", {"spec": spec})["grid_id"]

    def test_a_grid_can_be_built_and_then_labelled(self, dispatcher) -> None:
        grid_id = self._grid(dispatcher)

        model = dispatcher.call(
            "ofag.build_model",
            {
                "grid_id": grid_id,
                "rules": [
                    {
                        "name": "bedrock",
                        "source": "seismic",
                        "kind": "below_surface",
                        "surface": "basement",
                    },
                    {
                        "name": "cover",
                        "source": "AEM",
                        "kind": "above_surface",
                        "surface": "cover",
                    },
                    {"name": "fill", "source": "nothing measured here", "kind": "remainder"},
                ],
                "surfaces": {"basement": 170.0, "cover": 20.0},
            },
        )

        assert model["undecided_cells"] == 0
        assert {unit["name"] for unit in model["units"]} == {"bedrock", "cover", "fill"}
        assert sum(unit["volume_share"] for unit in model["units"]) == pytest.approx(1.0)
        assert model["ground_source"] == "DTM_HEM, nearest sounding"

    def test_a_rule_whose_surface_nobody_gave_names_the_rule(self, dispatcher) -> None:
        """Rather than a KeyError naming a dictionary."""
        grid_id = self._grid(dispatcher)

        with pytest.raises(ToolError, match=r"rule 'bedrock' needs surface 'basement'"):
            dispatcher.call(
                "ofag.build_model",
                {
                    "grid_id": grid_id,
                    "rules": [
                        {
                            "name": "bedrock",
                            "source": "seismic",
                            "kind": "below_surface",
                            "surface": "basement",
                        }
                    ],
                },
            )

    def test_a_surface_of_the_wrong_length_says_what_it_should_be(self, dispatcher) -> None:
        grid_id = self._grid(dispatcher)

        with pytest.raises(ToolError, match="values for a grid of"):
            dispatcher.call(
                "ofag.build_model",
                {
                    "grid_id": grid_id,
                    "rules": [
                        {
                            "name": "bedrock",
                            "source": "seismic",
                            "kind": "below_surface",
                            "surface": "basement",
                        }
                    ],
                    "surfaces": {"basement": [1.0, 2.0, 3.0]},
                },
            )

    def test_a_model_with_no_rules_is_refused(self, dispatcher) -> None:
        with pytest.raises(ToolError, match="nothing labels itself"):
            dispatcher.call("ofag.build_model", {"grid_id": self._grid(dispatcher), "rules": []})

    def test_a_section_from_a_run_that_wrote_none_is_refused(self, dispatcher) -> None:
        """Only a layered batch writes `stitched_conductivity_section.npz`, so a rule reading
        a gravity run has to be told, not handed an OSError."""
        from ofag.core.schemas import RunRecord, RunState
        from ofag.services.run_service import RunService
        from tests.conftest import gravity_run_spec

        runs = RunService(artifact_root=dispatcher.artifact_root)
        spec = gravity_run_spec()
        record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
        runs._records[spec.run_id] = record
        runs._persist_record(record)
        runs._persist_run_spec(spec)
        grid_id = self._grid(dispatcher)

        with pytest.raises(ToolError, match="source run has no result"):
            dispatcher.call(
                "ofag.build_model",
                {
                    "grid_id": grid_id,
                    "rules": [
                        {
                            "name": "conductor",
                            "source": "AEM",
                            "kind": "property_threshold",
                            "section": "aem",
                            "threshold": 100.0,
                        }
                    ],
                    "sections": {"aem": {"run_id": str(spec.run_id)}},
                },
            )


class TestANullWrittenAsANumber:
    """F031, in the ground. A DEM sampled on a nodata cell returns its sentinel, and before
    this the grid accepted it: relief of a thousand kilometres."""

    @pytest.mark.parametrize("sentinel", [-999999.0, -9999.0, -32768.0, float("nan")])
    def test_a_nodata_elevation_is_refused(self, sentinel: float) -> None:
        with pytest.raises(ValidationError, match="not a surface"):
            _spec(ground_elevation_m=(215.0, 273.0, 220.0, 268.0, sentinel))

    def test_an_elevation_no_surface_on_earth_reaches_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not a surface"):
            _spec(ground_elevation_m=(215.0, 273.0, 220.0, 268.0, 12_000.0))

    def test_a_real_deep_or_high_surface_is_still_a_surface(self) -> None:
        """The Dead Sea shore and a Himalayan valley are both ground."""
        grid = build_cell_grid(
            _spec(ground_elevation_m=(-430.0, 4_500.0, -400.0, 4_400.0, 2_000.0))
        )

        assert grid.terrain.relief_m > 0


class TestASectionFromARealRun:
    """The review finding. build_model looked for a section at root/runs/<id> while every run
    the dispatcher starts lives at root/<id>, so no property_threshold rule could ever be
    used."""

    def test_a_section_written_where_runs_live_is_found_and_used(self, dispatcher) -> None:
        from ofag.core.schemas import RunRecord, RunState
        from ofag.services.run_service import RunService
        from tests.conftest import gravity_run_spec

        runs = RunService(artifact_root=dispatcher.artifact_root)
        spec = gravity_run_spec()
        record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
        runs._records[spec.run_id] = record
        runs._persist_record(record)
        runs._persist_run_spec(spec)

        # Four soundings over the box, conductive at depth: 1 S/m below 20 m.
        layer_tops = np.array([0.0, 20.0, 60.0])
        conductivity = np.tile([0.001, 1.0, 1.0], (4, 1))
        np.savez(
            runs.run_dir(spec.run_id) / "stitched_conductivity_section.npz",
            receiver_locations_m=np.array(
                [[100.0, 100.0, 0.0], [900.0, 100.0, 0.0], [100.0, 400.0, 0.0], [900.0, 400.0, 0.0]]
            ),
            conductivity_s_m=conductivity,
            layer_top_depth_m=layer_tops,
            chi_squared=np.array([1.0, 1.0, 1.0, 1.0]),
        )
        _executed_by_inversion(dispatcher, spec)
        _as(dispatcher, "inversion").call(
            "ofag.diagnose",
            {"run_id": str(spec.run_id), "evidence": "chi-squared 1.0 at all four soundings"},
        )
        _as(dispatcher, "audit").call(
            "ofag.audit",
            {
                "run_id": str(spec.run_id),
                "verdict": "pass",
                "evidence": "misfit read back from the section; depth band below 60 m",
            },
        )

        model = dispatcher.call(
            "ofag.build_model",
            {
                "grid_id": self._grid(dispatcher),
                "rules": [
                    {
                        "name": "conductor",
                        "source": "AEM",
                        "kind": "property_threshold",
                        "section": "aem",
                        "threshold": 10.0,
                        "below_threshold": True,
                    },
                    {"name": "rest", "source": "nothing measured here", "kind": "remainder"},
                ],
                "sections": {"aem": {"run_id": str(spec.run_id), "chi_squared_at_most": 2.0}},
            },
        )

        conductor = next(u for u in model["units"] if u["name"] == "conductor")
        assert conductor["cell_count"] > 0, "the section was read and the rule labelled cells"

    def test_a_section_from_a_run_nobody_audited_is_owed_not_read(self, dispatcher) -> None:
        """The audited stage, where it bites."""
        spec = self._layered_run(dispatcher)
        _executed_by_inversion(dispatcher, spec)
        _as(dispatcher, "inversion").call(
            "ofag.diagnose",
            {"run_id": str(spec.run_id), "evidence": "chi-squared 1.0 at all four soundings"},
        )

        answer = dispatcher.call(
            "ofag.build_model",
            {
                "grid_id": self._grid(dispatcher),
                "rules": [{"name": "rest", "source": "nothing measured here", "kind": "remainder"}],
                "sections": {"aem": {"run_id": str(spec.run_id)}},
            },
        )

        assert answer["built"] is False
        assert answer["owed"] == {str(spec.run_id): ["audited"]}

    def test_the_role_that_ran_it_cannot_pass_its_own_audit(self, dispatcher) -> None:
        spec = self._layered_run(dispatcher)
        _executed_by_inversion(dispatcher, spec)
        inversion = _as(dispatcher, "inversion")
        inversion.call(
            "ofag.diagnose",
            {"run_id": str(spec.run_id), "evidence": "chi-squared 1.0 at all four soundings"},
        )

        with pytest.raises(ToolError, match="F056"):
            inversion.call(
                "ofag.audit",
                {
                    "run_id": str(spec.run_id),
                    "verdict": "pass",
                    "evidence": "my own misfit is fine",
                },
            )

    def test_a_veto_is_owed_in_the_journal(self, dispatcher) -> None:
        spec = self._layered_run(dispatcher)
        _executed_by_inversion(dispatcher, spec)
        _as(dispatcher, "inversion").call(
            "ofag.diagnose",
            {"run_id": str(spec.run_id), "evidence": "chi-squared 1.0 at all four soundings"},
        )

        answer = _as(dispatcher, "audit").call(
            "ofag.audit",
            {
                "run_id": str(spec.run_id),
                "verdict": "veto",
                "evidence": "the ramp was read in microseconds as milliseconds (F054)",
            },
        )

        assert answer["vetoed"] is True
        owed = dispatcher.call("ofag.journal", {})["still_owed"]
        assert f"audit veto on run {spec.run_id}" in owed

    def test_after_a_veto_neither_a_second_reader_nor_a_note_opens_the_model(
        self, dispatcher
    ) -> None:
        spec = self._layered_run(dispatcher)
        run_id = str(spec.run_id)
        _executed_by_inversion(dispatcher, spec)
        inversion = _as(dispatcher, "inversion")
        inversion.call(
            "ofag.diagnose", {"run_id": run_id, "evidence": "chi-squared 1.0 at both soundings"}
        )
        audit = _as(dispatcher, "audit")
        audit.call(
            "ofag.audit",
            {"run_id": run_id, "verdict": "veto", "evidence": "ramp read in the wrong unit (F054)"},
        )

        with pytest.raises(ToolError, match="vetoed"):
            audit.call(
                "ofag.audit",
                {"run_id": run_id, "verdict": "pass", "evidence": "a second reader passes it"},
            )
        inversion.call(
            "ofag.note",
            {
                "kind": "satisfied",
                "what": f"audit veto on run {run_id}",
                "because": "the ramp was checked and is in seconds already",
            },
        )
        answer = dispatcher.call(
            "ofag.build_model",
            {
                "grid_id": self._grid(dispatcher),
                "rules": [{"name": "rest", "source": "nothing measured here", "kind": "remainder"}],
                "sections": {"aem": {"run_id": run_id}},
            },
        )

        assert answer["built"] is False

    @staticmethod
    def _layered_run(dispatcher):
        from ofag.core.schemas import RunRecord, RunState
        from ofag.services.run_service import RunService
        from tests.conftest import gravity_run_spec

        runs = RunService(artifact_root=dispatcher.artifact_root)
        spec = gravity_run_spec()
        record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
        runs._records[spec.run_id] = record
        runs._persist_record(record)
        runs._persist_run_spec(spec)
        np.savez(
            runs.run_dir(spec.run_id) / "stitched_conductivity_section.npz",
            receiver_locations_m=np.array([[100.0, 100.0, 0.0], [900.0, 400.0, 0.0]]),
            conductivity_s_m=np.tile([0.001, 1.0], (2, 1)),
            layer_top_depth_m=np.array([0.0, 20.0]),
            chi_squared=np.array([1.0, 1.0]),
        )
        return spec

    def test_a_section_naming_a_run_that_is_not_here_says_so(self, dispatcher) -> None:
        with pytest.raises(ToolError, match="which is not here"):
            dispatcher.call(
                "ofag.build_model",
                {
                    "grid_id": self._grid(dispatcher),
                    "rules": [
                        {
                            "name": "conductor",
                            "source": "AEM",
                            "kind": "property_threshold",
                            "section": "aem",
                            "threshold": 10.0,
                        }
                    ],
                    "sections": {"aem": {"run_id": "00000000-0000-0000-0000-000000000000"}},
                },
            )

    @staticmethod
    def _grid(dispatcher) -> str:
        spec = {**BOX, **GROUND}
        spec["cell_m"] = list(BOX["cell_m"])
        for key in ("ground_easting_m", "ground_northing_m", "ground_elevation_m"):
            spec[key] = list(GROUND[key])
        return dispatcher.call("ofag.cell_grid", {"spec": spec})["grid_id"]


def _as(dispatcher, actor: str):
    """The same surface, acting under a name the ledger records."""
    from dataclasses import replace

    return replace(dispatcher, actor=actor)


def _executed_by_inversion(dispatcher, spec) -> None:
    """The stages `GuardedRuns.execute` would have written, under the role that ran it."""
    from ofag.agent.obligations import Ledger, Stage
    from ofag.agent.session import LEDGER_NAME
    from ofag.core.schemas import spec_fingerprint

    ledger = Ledger(dispatcher.artifact_root / LEDGER_NAME)
    for stage in (
        Stage.SPECIFIED,
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
        Stage.EXECUTED,
    ):
        ledger.discharge(
            stage, spec_fingerprint(spec), f"{stage.value} as the runner records it", by="inversion"
        )


class TestAStaircaseIsPrintedNotRefused:
    """The gate returns ground that is mostly its own quantisation to be printed."""

    def test_two_elevations_five_metres_apart_make_a_grid_that_says_so(self) -> None:
        grid = build_cell_grid(
            _spec(
                ground_elevation_m=(300.0, 295.0, 300.0, 295.0, 300.0),
            )
        )

        ground = grid.summary()["ground"]
        assert ground["mostly_its_own_quantisation"] is True
        assert ground["steps_of_relief"] == pytest.approx(1.0)
