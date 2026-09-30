"""Getting data in, which the tool surface could not do at all."""

import textwrap
from pathlib import Path

import pytest

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.agent.importers import IMPORTERS, Importer, importer, importer_ids, request_schema
from ofag.agent.tools import Tier, tool_manifest


@pytest.fixture
def dispatcher(tmp_path):
    return Dispatcher(
        artifact_root=tmp_path / "artifacts",
        granted=(Tier.READ, Tier.COMPUTE, Tier.WRITE),
    )


class TestTheRegistry:
    def test_every_reader_names_a_service_and_a_method(self) -> None:
        for item in IMPORTERS:
            assert item.service, item.importer_id
            assert item.method, item.importer_id

    def test_every_schema_comes_from_the_services_own_model(self) -> None:
        """Not a hand-written copy. `describe_plugin` returns a plugin's own physics model
        for the same reason: two statements of one shape drift."""
        for item in IMPORTERS:
            schema = request_schema(item)
            assert schema.get("properties"), item.importer_id
            assert schema is not request_schema(item), "a fresh dict, not the model's own"

    def test_the_identifiers_are_unique(self) -> None:
        assert len(set(importer_ids())) == len(IMPORTERS)

    def test_asking_for_a_reader_that_does_not_exist_says_what_there_is(self) -> None:
        """An agent handed `None` writes a plan around a reader that is not there."""
        with pytest.raises(KeyError, match="ofag.import.tem_usf"):
            importer("ofag.import.invented")

    def test_the_readers_that_write_a_run_are_marked(self) -> None:
        """Two of them produce a run rather than a dataset and need one from `RunService`, so
        the dispatcher has to know which."""
        adopting = {i.importer_id for i in IMPORTERS if i.adopts_a_run}

        assert adopting == {"ofag.import.layered_line", "ofag.import.external_model"}


class TestTheSurface:
    def test_the_pipeline_now_has_a_beginning(self, dispatcher) -> None:
        """The whole point. Before this, nothing on the surface put data in."""
        names = {tool.name for tool in dispatcher.manifest()}

        assert {"ofag.list_importers", "ofag.describe_importer", "ofag.import_data"} <= names

    def test_looking_is_read_and_reading_in_is_write(self, dispatcher) -> None:
        by_name = {tool.name: tool for tool in tool_manifest(None)}

        assert by_name["ofag.list_importers"].tier is Tier.READ
        assert by_name["ofag.describe_importer"].tier is Tier.READ
        assert by_name["ofag.import_data"].tier is Tier.WRITE

    def test_every_declared_tool_has_a_handler(self) -> None:
        """The failure this module exists to fix is a tool an agent can see and cannot call."""
        unreachable = []
        for tool in tool_manifest(None):
            try:
                Dispatcher(artifact_root=Path("."))._handler(tool.name)
            except ToolError:
                unreachable.append(tool.name)

        assert unreachable == []

    def test_listing_says_which_readers_this_installation_can_actually_use(
        self, dispatcher
    ) -> None:
        listed = dispatcher.call("ofag.list_importers", {})

        assert len(listed) == len(IMPORTERS)
        for row in listed:
            assert set(row) == {
                "importer_id",
                "what",
                "tier",
                "refuses",
                "needs_extra",
                "available",
            }

    def test_describing_one_returns_its_request_schema(self, dispatcher) -> None:
        described = dispatcher.call(
            "ofag.describe_importer", {"importer_id": "ofag.import.tem_usf"}
        )

        assert described["request_schema"]["properties"].keys() >= {
            "source_directory",
            "coordinate_convention",
        }

    def test_a_readers_refusals_are_in_what_the_agent_reads(self, dispatcher) -> None:
        """So it can plan around them rather than discover them."""
        described = dispatcher.call(
            "ofag.describe_importer", {"importer_id": "ofag.import.tem_usf"}
        )

        assert "turn-off ramp" in described["refuses"]


class TestReadingSomethingIn:
    @staticmethod
    def _csv(tmp_path: Path) -> Path:
        path = tmp_path / "stations.csv"
        path.write_text(
            textwrap.dedent("""\
            easting,northing,elevation,anomaly
            330000,4260000,1550.0,-217.2
            330050,4260000,1551.0,-217.4
            330100,4260000,1552.5,-217.1
            """),
            encoding="utf-8",
        )
        return path

    def test_a_delivery_can_be_looked_at_before_it_is_mapped(self, dispatcher, tmp_path) -> None:
        preview = dispatcher.call(
            "ofag.import_data",
            {
                "importer_id": "ofag.import.csv_preview",
                "request": {"source_path": self._csv(tmp_path).as_posix(), "max_rows": 2},
            },
        )

        assert preview["columns"] == ["easting", "northing", "elevation", "anomaly"]
        assert preview["total_rows"] == 3

    def test_a_request_the_reader_refuses_comes_back_readable(self, dispatcher) -> None:
        """The reader's own rule is the most useful thing an agent can be told, so it travels
        whole rather than as a validation dump."""
        with pytest.raises(ToolError, match="refused the request"):
            dispatcher.call(
                "ofag.import_data",
                {"importer_id": "ofag.import.csv_preview", "request": {"max_rows": 2}},
            )

    def test_a_file_that_is_not_there_is_a_refusal_and_not_a_crash(
        self, dispatcher, tmp_path
    ) -> None:
        with pytest.raises(ToolError, match="refused"):
            dispatcher.call(
                "ofag.import_data",
                {
                    "importer_id": "ofag.import.csv_preview",
                    "request": {"source_path": (tmp_path / "absent.csv").as_posix()},
                },
            )

    def test_an_unknown_reader_says_what_there_is(self, dispatcher) -> None:
        """A refusal the caller can read, naming the readers there are."""
        with pytest.raises(ToolError, match="ofag.import.csv_preview"):
            dispatcher.call(
                "ofag.import_data", {"importer_id": "ofag.import.invented", "request": {}}
            )

    def test_a_reader_whose_extra_is_missing_says_how_to_get_it(self, dispatcher) -> None:
        """Rather than an ImportError from three frames down."""
        missing = Importer(
            importer_id="ofag.import.pretend",
            what="a reader needing something that is not installed",
            request_model=dict,
            service="data",
            method="preview_csv",
            needs_extra="ert-formats",
        )

        assert Dispatcher._extra_present(missing) in (True, False)


class TestDeletingARun:
    def test_it_is_destructive_and_nothing_grants_that_by_default(self, tmp_path) -> None:
        ordinary = Dispatcher(artifact_root=tmp_path)

        assert "ofag.delete_run" not in {tool.name for tool in ordinary.manifest()}

    def test_deleting_a_run_that_is_not_there_is_a_refusal(self, tmp_path) -> None:
        granted = Dispatcher(artifact_root=tmp_path, granted=(Tier.DESTRUCTIVE,))

        with pytest.raises(ToolError, match="no run"):
            granted.call("ofag.delete_run", {"run_id": "00000000-0000-0000-0000-000000000000"})
