"""The model layer: each protocol's wire format, and a key that is never written."""

import json
import os
import urllib.error
from io import BytesIO

import pytest

from ofag.agent.providers import (
    AgentSettings,
    AnthropicModel,
    OpenAICompatibleModel,
    ProviderConfig,
    ProviderError,
    ProviderKind,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    decode_tool_name,
    encode_tool_name,
    load_settings,
    resolve_key,
    save_settings,
)

TOOLS = [ToolSpec("ofag.list_plugins", "list them", {"type": "object", "properties": {}})]
TURNS = [
    Turn(role="user", text="what plugins are there?"),
    Turn(role="assistant", text="", tool_calls=(ToolCall("c1", "ofag.list_plugins", {}),)),
    Turn(role="tool", results=(ToolResult("c1", "ofag.list_plugins", "[]"),)),
]


class Recorder:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.sent: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, body, timeout):
        self.sent.append((url, headers, json.loads(body)))
        return json.dumps(self.answer).encode()


def test_a_dotted_tool_name_survives_both_protocols() -> None:
    assert encode_tool_name("ofag.list_plugins") == "ofag__list_plugins"
    assert decode_tool_name(encode_tool_name("ofag.build_model")) == "ofag.build_model"


class TestAnthropic:
    def test_the_request_and_the_reply(self) -> None:
        wire = Recorder(
            {
                "content": [
                    {"type": "text", "text": "Calling it."},
                    {
                        "type": "tool_use",
                        "id": "t9",
                        "name": "ofag__journal",
                        "input": {"about": "x"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )
        model = AnthropicModel(ProviderConfig(), key="sk-secret", transport=wire)

        reply = model.respond("be brief", TURNS, TOOLS)

        url, headers, body = wire.sent[0]
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "sk-secret"
        assert body["system"] == "be brief" and body["tools"][0]["name"] == "ofag__list_plugins"
        assert body["messages"][1]["content"][0] == {
            "type": "tool_use",
            "id": "c1",
            "name": "ofag__list_plugins",
            "input": {},
        }
        assert body["messages"][2]["content"][0]["type"] == "tool_result"
        assert reply.text == "Calling it."
        assert reply.tool_calls == (ToolCall("t9", "ofag.journal", {"about": "x"}),)
        assert (reply.input_tokens, reply.output_tokens) == (10, 5)


class TestOpenAICompatible:
    def test_the_request_and_the_reply(self) -> None:
        wire = Recorder(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "k1",
                                    "type": "function",
                                    "function": {
                                        "name": "ofag__lessons",
                                        "arguments": '{"id": "P19"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )
        config = ProviderConfig.default_for(ProviderKind.OPENAI_COMPATIBLE)
        model = OpenAICompatibleModel(config, key="k", transport=wire)

        reply = model.respond("be brief", TURNS, TOOLS)

        url, headers, body = wire.sent[0]
        assert url.endswith("/chat/completions") and headers["authorization"] == "Bearer k"
        assert body["messages"][0] == {"role": "system", "content": "be brief"}
        assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "ofag__list_plugins"
        assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "[]"}
        assert reply.tool_calls == (ToolCall("k1", "ofag.lessons", {"id": "P19"}),)

    def test_arguments_that_are_not_json_reach_the_dispatcher_rather_than_vanish(self) -> None:
        wire = Recorder(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "k1",
                                    "function": {"name": "ofag__journal", "arguments": "{oops"},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        model = OpenAICompatibleModel(
            ProviderConfig.default_for(ProviderKind.OPENAI_COMPATIBLE), "k", wire
        )

        assert model.respond("s", TURNS, TOOLS).tool_calls[0].arguments == {"__unparsed__": "{oops"}


class TestTheKey:
    def test_typed_beats_the_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

        assert resolve_key(ProviderConfig(), typed="typed") == "typed"
        assert resolve_key(ProviderConfig()) == "from-env"

    def test_no_key_for_a_cloud_host_is_refused_and_a_local_one_needs_none(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
            resolve_key(ProviderConfig())
        local = ProviderConfig(
            kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url="http://localhost:11434/v1",
            api_key_env="",
        )
        assert local.is_local and resolve_key(local) == ""

    def test_an_error_from_the_server_does_not_repeat_the_key(self) -> None:
        def refuses(url, headers, body, timeout):
            raise urllib.error.HTTPError(
                url, 401, "no", {}, BytesIO(b'{"error": "bad key sk-secret"}')
            )

        model = AnthropicModel(ProviderConfig(), key="sk-secret", transport=refuses)
        with pytest.raises(ProviderError) as raised:
            model.respond("s", TURNS, TOOLS)

        assert "401" in str(raised.value) and "sk-secret" not in str(raised.value)


class TestSettings:
    def test_they_round_trip_and_never_hold_a_key(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-appear")
        path = tmp_path / "agent_settings.json"
        settings = AgentSettings(
            provider=ProviderConfig(model="claude-sonnet-5"), role_models={"audit": "x"}
        )

        save_settings(settings, path)

        assert load_settings(path) == settings
        assert "sk-" not in path.read_text("utf-8")

    def test_a_role_uses_the_leads_model_unless_it_has_its_own(self) -> None:
        settings = AgentSettings(role_models={"audit": "claude-sonnet-5", "data": " "})

        assert settings.config_for("audit").model == "claude-sonnet-5"
        assert settings.config_for("data").model == settings.provider.model

    def test_a_mangled_file_falls_back_to_the_defaults(self, tmp_path) -> None:
        path = tmp_path / "s.json"
        path.write_text("{not json", encoding="utf-8")

        assert load_settings(path) == AgentSettings()

    def test_the_default_file_is_outside_every_project(self) -> None:
        from ofag.agent.providers import SETTINGS_PATH

        assert SETTINGS_PATH.parent.name == ".ofag"
        assert os.path.expanduser("~") in str(SETTINGS_PATH)
