"""Test tool dispatch and refusal."""

from pathlib import Path
from uuid import uuid4

import pytest

from ofag.agent.dispatch import GRANTED_BY_DEFAULT, Dispatcher, ToolError
from ofag.agent.tools import Tier, tool_manifest
from ofag.core.constants import QuantityType
from ofag.core.schemas import CoordinateConvention, DatasetSpec, RunSpec

#: A real modelling decision used as a JSON-shaped round-trip payload.
DOI_DECISION = {
    "question": "Use the contractor's investigation depth for Cedar Rapids?",
    "options": [
        {
            "name": "use it",
            "cost": "the resolved extent depends on an external model",
        },
        {
            "name": "omit it",
            "cost": "the model would claim geology below a documented depth bound",
        },
    ],
    "chose": "use it",
    "because": "the current AEM inversion has no investigation-depth calculation of its own",
    "settlement": "judged",
    "reverses_if": "the current inversion computes a validated investigation depth",
    "recorded_at": "scripts/case2_cedar_rapids.py::DOI_COLUMN",
}


@pytest.fixture
def dispatcher(tmp_path):
    return Dispatcher(artifact_root=tmp_path / "runs")


def test_a_name_not_on_the_manifest_does_not_exist(dispatcher) -> None:
    """Matched against the manifest rather than a handler table, so a handler added without
    being declared stays unreachable."""
    with pytest.raises(ToolError, match="no tool named"):
        dispatcher.call("ofag.invert_everything")


def test_a_tier_the_caller_does_not_hold_is_refused_before_the_handler(dispatcher) -> None:
    with pytest.raises(ToolError, match="destructive"):
        dispatcher.call("ofag.delete_run", {"run_id": str(uuid4())})

    assert Tier.DESTRUCTIVE not in GRANTED_BY_DEFAULT


def test_asking_for_the_destructive_tier_is_a_separate_act(tmp_path) -> None:
    granted = Dispatcher(
        artifact_root=tmp_path / "runs", granted=(*GRANTED_BY_DEFAULT, Tier.DESTRUCTIVE)
    )

    assert "ofag.delete_run" in {tool.name for tool in granted.manifest()}
    # Granted and callable, and a run that is not there is a refusal rather than a
    # traceback.
    with pytest.raises(ToolError, match="no run"):
        granted.call("ofag.delete_run", {"run_id": str(uuid4())})


def test_the_manifest_a_caller_sees_is_the_one_it_may_use(dispatcher) -> None:
    """So it cannot plan on a tool it will be refused."""
    visible = {tool.name for tool in dispatcher.manifest()}
    everything = {tool.name for tool in tool_manifest()}

    assert visible < everything
    assert "ofag.delete_run" not in visible


def test_arguments_of_the_wrong_shape_are_caught_with_the_right_shape(dispatcher) -> None:
    with pytest.raises(ToolError, match=r"missing \['plugin_id'\]"):
        dispatcher.call("ofag.conventions", {})

    with pytest.raises(ToolError, match=r"unexpected \['plugin'\]"):
        dispatcher.call("ofag.conventions", {"plugin_id": "x", "plugin": "y"})


def test_a_method_describes_itself_through_the_surface(dispatcher) -> None:
    described = dispatcher.call("ofag.describe_plugin", {"plugin_id": "pygimli.seismic.traveltime"})

    assert described["physics_schema"]["properties"].keys() >= {"array", "regularization"}


def test_a_convention_comes_back_with_what_it_is_measured_against(dispatcher) -> None:
    """The field that exists because a check comparing an engine to itself is the failure
    mode the mechanism is for."""
    checks = dispatcher.call("ofag.conventions", {"plugin_id": "pygimli.seismic.traveltime"})

    assert len(checks) == 2
    assert all(check["against"] for check in checks)


def test_the_corpus_is_searchable_through_the_surface(dispatcher) -> None:
    found = dispatcher.call("ofag.lessons", {"decision": "judgement", "uncovered_only": True})

    assert {row["id"] for row in found} >= {"F042", "F024"}
    assert all(row["covered_by"] is None for row in found)


def test_an_owed_obligation_comes_back_as_an_answer_not_an_exception(dispatcher) -> None:
    """An agent that meets a refusal as an exception will retry it."""
    spec = RunSpec(
        plugin_id="pygimli.ert.dcip",
        plugin_version="0.1.0",
        engine="pygimli",
        project_id=uuid4(),
        label="nothing discharged",
        dataset=DatasetSpec(
            name="d",
            coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
            physical_quantity=QuantityType.TRANSFER_RESISTANCE,
            units="ohm",
        ),
        physics={"array": {"electrodes_path": "a.npy", "quadrupoles_path": "b.npy"}},
    )

    answer = dispatcher.call("ofag.execute", {"spec": spec.model_dump(mode="json")})

    assert answer["ran"] is False
    assert "validated" in answer["owed"]


def test_a_decision_is_validated_and_rendered_but_not_filed(dispatcher) -> None:
    """Where a decision lives is the one thing the schema cannot check, and a tool that
    guessed would put it somewhere nobody looks."""
    answer = dispatcher.call("ofag.record_decision", {"decision": DOI_DECISION})

    assert answer["settlement"] == "judged"
    assert answer["recorded_at"].endswith("DOI_COLUMN")
    assert "This is wrong if" in answer["comment"]
    assert not (Path(dispatcher.artifact_root) / "decisions.yaml").exists()


def test_a_decision_missing_its_reversal_is_refused(dispatcher) -> None:
    from pydantic import ValidationError

    incomplete = {k: v for k, v in DOI_DECISION.items() if k != "reverses_if"}

    with pytest.raises(ValidationError):
        dispatcher.call("ofag.record_decision", {"decision": incomplete})


class TestClassifyingBeforeAsking:
    """The tool that answers whether a question is a question."""

    def test_something_cheap_and_timed_comes_back_as_run_it(self, dispatcher) -> None:
        answer = dispatcher.call(
            "ofag.classify_question",
            {
                "probes": [
                    {"what": "invert the profile flat too", "seconds": 1, "timing": "measured"}
                ]
            },
        )

        assert answer["next"] == "measure"
        assert "on a clock" in answer["because"]

    def test_a_question_with_no_probe_is_a_question(self, dispatcher) -> None:
        answer = dispatcher.call("ofag.classify_question", {"probes": []})

        assert answer["next"] == "ask"
        assert answer["probe"] is None

    def test_an_estimate_is_not_evidence_that_something_is_expensive(self, dispatcher) -> None:
        """F055. The gravity plugin's estimator says forty-one days for a run that takes
        minutes, and a question declined on that number is a question asked for nothing."""
        answer = dispatcher.call(
            "ofag.classify_question",
            {
                "probes": [
                    {
                        "what": "run the gravity forward twice",
                        "seconds": 3576586,
                        "timing": "estimated",
                    }
                ]
            },
        )

        assert answer["next"] == "time it first"
        assert "F055" in answer["because"]

    def test_a_timed_measurement_that_is_genuinely_slow_earns_the_question(
        self, dispatcher
    ) -> None:
        answer = dispatcher.call(
            "ofag.classify_question",
            {
                "probes": [
                    {
                        "what": "invert the airborne survey both ways",
                        "seconds": 1762,
                        "timing": "measured",
                    }
                ]
            },
        )

        assert answer["next"] == "ask"

    def test_a_probe_that_is_the_wrong_shape_is_refused_by_the_model(self, dispatcher) -> None:
        """The dispatcher checks a tool's top-level arguments and leaves what is inside them
        to whatever model the handler hands them to -- the same arrangement `spec` and
        `decision` already use."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            dispatcher.call("ofag.classify_question", {"probes": [{"what": "x", "seconds": 1}]})

        with pytest.raises(ValidationError):
            dispatcher.call(
                "ofag.classify_question",
                {"probes": [{"what": "invert it twice", "seconds": 1, "timing": "guessed"}]},
            )


def test_conventions_of_a_plugin_that_declares_them_unverified_says_so(tmp_path) -> None:
    """It raised TypeError before: UNVERIFIED is not iterable."""
    answer = Dispatcher(artifact_root=tmp_path).call(
        "ofag.conventions", {"plugin_id": "deepwave.fwi.elastic2d"}
    )

    assert answer["unverified"] is True


class TestABadCallIsARefusalNotATraceback:
    """Found by driving the roles end to end: each of these raised a Python error instead of
    a ToolError, which an agent cannot read and so retries."""

    @pytest.mark.parametrize(
        ("name", "arguments", "complaint"),
        [
            ("ofag.journal", ["x"], "object of named fields"),
            (
                "ofag.import_data",
                {"importer_id": "ofag.import.nope", "request": {}},
                "has to be one of",
            ),
            ("ofag.describe_importer", {"importer_id": "ofag.import.nope"}, "has to be one of"),
            ("ofag.validate", {"spec": {"plugin_id": 3}}, "is not a RunSpec"),
            (
                "ofag.import_data",
                {"importer_id": "ofag.import.csv_preview", "request": "x"},
                "has to be an object",
            ),
            ("ofag.retrieve", {"k": 0}, "at least 1"),
            ("ofag.retrieve", {"k": True}, "has to be an integer"),
            ("ofag.retrieve", {"kinds": ["essay"]}, "may hold only"),
            ("ofag.lessons", {"decision": "maybe"}, "has to be one of"),
            ("ofag.build_model", {"grid_id": "x", "rules": [], "sections": {"aem": "x"}}, None),
        ],
    )
    def test_each(self, tmp_path, name, arguments, complaint) -> None:
        with pytest.raises(ToolError) as raised:
            Dispatcher(artifact_root=tmp_path).call(name, arguments)
        if complaint:
            assert complaint in str(raised.value)

    def test_a_procedure_step_is_matched_whatever_its_case(self, tmp_path) -> None:
        found = Dispatcher(artifact_root=tmp_path).call("ofag.lessons", {"procedure": "a2"})

        assert found and all(x["procedure"] == "A2" for x in found)
