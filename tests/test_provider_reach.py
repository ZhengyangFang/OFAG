"""Reaching a model through anyone's endpoint: presets, relays, and why one failed."""

import json
import urllib.error
from io import BytesIO

import pytest

from ofag.agent.providers import (
    PRESETS,
    USER_AGENT,
    AnthropicModel,
    OpenAIResponsesModel,
    ProviderConfig,
    ProviderError,
    ProviderKind,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    endpoint,
    model_from,
    probe,
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


@pytest.mark.parametrize(
    ("kind", "base", "expected"),
    [
        (
            ProviderKind.ANTHROPIC,
            "https://api.anthropic.com",
            "https://api.anthropic.com/v1/messages",
        ),
        (
            ProviderKind.ANTHROPIC,
            "https://opencode.ai/zen/go/v1/",
            "https://opencode.ai/zen/go/v1/messages",
        ),
        (
            ProviderKind.OPENAI_COMPATIBLE,
            "https://api.deepseek.com/v1",
            "https://api.deepseek.com/v1/chat/completions",
        ),
        (
            ProviderKind.OPENAI_COMPATIBLE,
            "https://open.bigmodel.cn/api/paas/v4",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        ),
        (
            ProviderKind.OPENAI_RESPONSES,
            "https://opencode.ai/zen/go/v1",
            "https://opencode.ai/zen/go/v1/responses",
        ),
        (
            ProviderKind.OPENAI_COMPATIBLE,
            "https://relay.example/v1/chat/completions",
            "https://relay.example/v1/chat/completions",
        ),
        (
            ProviderKind.ANTHROPIC,
            "https://relay.example/v1/messages",
            "https://relay.example/v1/messages",
        ),
    ],
)
def test_a_base_pasted_any_of_three_ways_reaches_the_endpoint(kind, base, expected) -> None:
    assert endpoint(kind, base) == expected


ANSWERS = {
    ProviderKind.ANTHROPIC: {"content": [{"type": "text", "text": "OK"}]},
    ProviderKind.OPENAI_COMPATIBLE: {"choices": [{"message": {"content": "OK"}}]},
    ProviderKind.OPENAI_RESPONSES: {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]
    },
}


@pytest.mark.parametrize("kind", list(ProviderKind))
def test_every_protocol_sends_a_user_agent_a_relay_will_accept(kind) -> None:
    wire = Recorder(ANSWERS[kind])

    reply = model_from(ProviderConfig.default_for(kind), "k", wire).respond("s", TURNS, TOOLS)

    assert reply.text == "OK"
    assert wire.sent[0][1]["user-agent"] == USER_AGENT
    assert "urllib" not in USER_AGENT.lower()


def test_the_anthropic_protocol_sends_the_key_both_ways() -> None:
    wire = Recorder({"content": []})
    AnthropicModel(ProviderConfig(), key="k", transport=wire).respond("s", TURNS, TOOLS)

    headers = wire.sent[0][1]
    assert headers["x-api-key"] == "k" and headers["authorization"] == "Bearer k"


def test_the_responses_protocol_request_and_reply() -> None:
    wire = Recorder(
        {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Looking."}]},
                {
                    "type": "function_call",
                    "call_id": "r1",
                    "name": "ofag__journal",
                    "arguments": '{"about": "ramp"}',
                },
            ],
            "status": "completed",
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }
    )
    config = ProviderConfig.default_for(ProviderKind.OPENAI_RESPONSES)

    reply = OpenAIResponsesModel(config, "k", wire).respond("be brief", TURNS, TOOLS)

    url, _, body = wire.sent[0]
    assert url.endswith("/responses") and body["instructions"] == "be brief"
    assert (
        body["tools"][0]["name"] == "ofag__list_plugins" and body["tools"][0]["type"] == "function"
    )
    assert body["input"][1] == {
        "type": "function_call",
        "call_id": "c1",
        "name": "ofag__list_plugins",
        "arguments": "{}",
    }
    assert body["input"][2] == {"type": "function_call_output", "call_id": "c1", "output": "[]"}
    assert reply.text == "Looking."
    assert reply.tool_calls == (ToolCall("r1", "ofag.journal", {"about": "ramp"}),)
    assert (reply.input_tokens, reply.output_tokens) == (7, 3)


class TestPresets:
    def test_every_preset_is_usable_and_named_once(self) -> None:
        labels = [p.label for p in PRESETS]
        assert len(labels) == len(set(labels))
        for preset in PRESETS:
            config = ProviderConfig(
                kind=preset.kind,
                base_url=preset.base_url,
                model=preset.model,
                api_key_env=preset.api_key_env,
            )
            assert preset.base_url.startswith("https://") or config.is_local, preset.label
            # A cloud endpoint names where its key is; a local one needs none.
            assert bool(preset.api_key_env) != config.is_local, preset.label

    def test_opencode_go_is_offered_over_each_of_its_three_protocols(self) -> None:
        go = [p for p in PRESETS if p.label.startswith("OpenCode Go")]

        assert {endpoint(p.kind, p.base_url) for p in go} == {
            "https://opencode.ai/zen/go/v1/chat/completions",
            "https://opencode.ai/zen/go/v1/messages",
            "https://opencode.ai/zen/go/v1/responses",
        }

    def test_chinese_providers_and_a_relay_for_each_protocol_are_there(self) -> None:
        labels = " ".join(p.label for p in PRESETS)
        for name in ("DeepSeek", "Qwen", "Kimi", "GLM", "Doubao", "SiliconFlow", "MiniMax"):
            assert name in labels
        relays = {p.kind for p in PRESETS if "Relay" in p.label}
        assert relays == {ProviderKind.OPENAI_COMPATIBLE, ProviderKind.ANTHROPIC}


class TestProbe:
    def test_it_returns_what_the_model_said(self) -> None:
        wire = Recorder({"choices": [{"message": {"content": "OK"}}]})

        assert probe(ProviderConfig.default_for(ProviderKind.OPENAI_COMPATIBLE), "k", wire) == "OK"
        assert wire.sent[0][2]["messages"][-1] == {"role": "user", "content": "Reply with OK."}

    @pytest.mark.parametrize(
        ("status", "body", "hint"),
        [
            (404, b"<html>not here</html>", "base URL, or the protocol"),
            (403, b"error code: 1010", "blocks this client"),
            (401, b'{"error":"Invalid API key."}', "key was refused"),
        ],
    )
    def test_a_refusal_carries_the_servers_answer_and_what_it_usually_means(
        self, status, body, hint
    ) -> None:
        def refuses(url, headers, sent, timeout):
            raise urllib.error.HTTPError(url, status, "no", {}, BytesIO(body))

        with pytest.raises(ProviderError) as raised:
            probe(ProviderConfig(), "sk-secret", refuses)

        message = str(raised.value)
        assert body.decode()[:10] in message and hint in message and "sk-secret" not in message

    def test_no_model_is_refused_before_anything_is_sent(self) -> None:
        with pytest.raises(ProviderError, match="no model named"):
            probe(ProviderConfig(model=" "), "k", Recorder({}))
