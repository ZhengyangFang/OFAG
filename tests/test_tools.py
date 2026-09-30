"""The tool surface, and the promises written into it."""

import json

import pytest

from ofag.agent.tools import REFUSALS, Tier, describe_plugin, tool_manifest, tools_by_tier
from ofag.plugins.registry import default_registry


@pytest.fixture(scope="module")
def manifest():
    return tool_manifest()


def test_every_tool_is_named_once_and_typed(manifest) -> None:
    names = [tool.name for tool in manifest]

    assert len(names) == len(set(names))
    assert all(name.startswith("ofag.") for name in names)
    for tool in manifest:
        assert tool.input_schema["type"] == "object"
        assert json.dumps(tool.input_schema)


def test_a_tool_that_refuses_says_so_in_its_description(manifest) -> None:
    """The difference between an agent that plans and one that discovers the rules by hitting
    them."""
    for tool in manifest:
        if tool.name in REFUSALS:
            assert tool.refuses == REFUSALS[tool.name]
            assert tool.refuses in tool.description
        else:
            assert tool.refuses is None


def test_execute_names_every_obligation_it_will_refuse_for(manifest) -> None:
    execute = next(tool for tool in manifest if tool.name == "ofag.execute")

    for owed in ("validated", "conventions", "estimated", "walk"):
        assert owed in (execute.refuses or "").lower()


def test_the_plugin_list_comes_from_the_registry(manifest) -> None:
    """A method added to the project appears here without anyone remembering, and one that is
    removed stops being offered."""
    registered = sorted(plugin.plugin_id for plugin in default_registry().all())
    describe = next(tool for tool in manifest if tool.name == "ofag.describe_plugin")

    assert describe.input_schema["properties"]["plugin_id"]["enum"] == registered
    assert "pygimli.seismic.traveltime" in registered


def test_a_method_hands_back_the_shape_of_its_own_specification() -> None:
    """An agent that has to guess what a run takes will guess something plausible, and a
    plausible wrong specification is the whole problem."""
    described = describe_plugin("pygimli.seismic.traveltime")

    assert described["plugin_id"] == "pygimli.seismic.traveltime"
    schema = described["physics_schema"]
    assert "array" in schema["properties"]
    assert "regularization" in schema["properties"]
    # The absolute-error trap is in the limitations, where a caller meets it.
    assert any("ABSOLUTE" in limitation for limitation in described["limitations"])


def test_every_registered_method_can_describe_itself() -> None:
    for plugin in default_registry().all():
        described = describe_plugin(plugin.plugin_id)
        assert described["plugin_version"]
        assert described["limitations"], f"{plugin.plugin_id} declares no limitations"


def test_the_surface_is_tiered_and_the_destructive_tier_is_small(manifest) -> None:
    """Not safety theatre. This project's own state has been left inconsistent by tidying
    more than once."""
    tiers = tools_by_tier()

    assert tiers[Tier.DESTRUCTIVE] == ("ofag.delete_run",)
    assert len(tiers[Tier.READ]) > len(tiers[Tier.WRITE])
    assert set(sum(tiers.values(), ())) == {tool.name for tool in manifest}


def test_the_corpus_is_reachable_as_a_tool(manifest) -> None:
    """The recorded failures are of no use to an agent that cannot ask about them -- by step,
    by method, or by the identifier a paper cites."""
    lessons = next(tool for tool in manifest if tool.name == "ofag.lessons")

    assert set(lessons.input_schema["properties"]) == {
        "id",
        "procedure",
        "method",
        "decision",
        "uncovered_only",
    }
    assert "ran clean" in lessons.summary
