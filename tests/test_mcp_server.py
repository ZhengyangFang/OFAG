"""The MCP transport, tested where it has content."""

import json

import pytest

from ofag.agent.dispatch import Dispatcher
from ofag.agent.mcp_server import answer, described
from ofag.agent.tools import Tier, tool_manifest


@pytest.fixture
def dispatcher(tmp_path):
    return Dispatcher(artifact_root=tmp_path)


class TestWhatItAnnounces:
    def test_it_announces_exactly_what_the_dispatcher_grants(self, dispatcher) -> None:
        """Not `tool_manifest`, which is everything."""
        announced = {described(tool).name for tool in dispatcher.manifest()}
        granted = {tool.name for tool in tool_manifest(None) if tool.tier in dispatcher.granted}

        assert announced == granted

    def test_a_tier_the_caller_lacks_is_not_announced(self, tmp_path) -> None:
        read_only = Dispatcher(artifact_root=tmp_path, granted=(Tier.READ,))

        tiers = {tool.tier for tool in read_only.manifest()}

        assert tiers == {Tier.READ}
        assert "ofag.execute" not in {t.name for t in read_only.manifest()}

    def test_every_refusal_is_in_the_prose_an_agent_reads(self, dispatcher) -> None:
        """An agent plans against the description and meets the refusal only if it did not."""
        for tool in dispatcher.manifest():
            if tool.refuses:
                assert tool.refuses.strip() in described(tool).description, tool.name

    def test_every_description_says_the_tier(self, dispatcher) -> None:
        for tool in dispatcher.manifest():
            assert f"Tier: {tool.tier.value}." in described(tool).description

    def test_the_schema_is_passed_through_unaltered(self, dispatcher) -> None:
        """It is generated from the platform's own models, so a transport that edited it
        would be the one place they could drift apart."""
        for tool in dispatcher.manifest():
            assert described(tool).input_schema is tool.input_schema


class TestWhatComesBack:
    def test_a_call_that_works_comes_back_as_readable_text(self, dispatcher) -> None:
        text, failed = answer(dispatcher, "ofag.list_plugins", {})

        assert not failed
        json.loads(text)

    def test_an_unknown_tool_is_an_error_answer_and_not_an_exception(self, dispatcher) -> None:
        """An agent that receives a transport-level exception has nothing to read and retries
        it."""
        text, failed = answer(dispatcher, "ofag.invent_a_tool", {})

        assert failed
        assert "no tool named" in text
        assert "ofag.list_plugins" in text, "the refusal says what does exist"

    def test_a_tier_refusal_says_to_ask_for_the_tier(self, tmp_path) -> None:
        read_only = Dispatcher(artifact_root=tmp_path, granted=(Tier.READ,))

        text, failed = answer(read_only, "ofag.execute", {})

        assert failed
        assert "Ask for the tier" in text

    def test_bad_arguments_come_back_saying_what_the_tool_takes(self, dispatcher) -> None:
        text, failed = answer(dispatcher, "ofag.describe_plugin", {"nonsense": 1})

        assert failed
        assert "unexpected" in text

    def test_the_transport_invents_no_refusal_of_its_own(self, dispatcher) -> None:
        """Every error text here is one the dispatcher wrote."""
        from ofag.agent.dispatch import ToolError

        text, failed = answer(dispatcher, "ofag.invent_a_tool", {})
        try:
            dispatcher.call("ofag.invent_a_tool", {})
        except ToolError as refusal:
            assert text == str(refusal)
        else:  # pragma: no cover
            pytest.fail("the dispatcher accepted a tool that does not exist")
        assert failed
