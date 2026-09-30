"""The conversation id OpenCode's gateway asks for, and nobody else is sent."""

import json

import pytest

from ofag.agent.providers import (
    PRESETS,
    ProviderConfig,
    ProviderKind,
    Turn,
    model_from,
    probe,
    session_headers,
)


class Recorder:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.headers: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        self.headers.append(headers)
        return json.dumps(self.answer).encode()


ANSWERS = {
    ProviderKind.ANTHROPIC: {"content": [{"type": "text", "text": "OK"}]},
    ProviderKind.OPENAI_COMPATIBLE: {"choices": [{"message": {"content": "OK"}}]},
    ProviderKind.OPENAI_RESPONSES: {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]
    },
}


@pytest.mark.parametrize(
    "preset", [p for p in PRESETS if p.label.startswith("OpenCode")], ids=lambda p: p.label
)
def test_every_opencode_preset_names_the_conversation(preset) -> None:
    config = ProviderConfig(kind=preset.kind, base_url=preset.base_url, model=preset.model)
    wire = Recorder(ANSWERS[preset.kind])

    model = model_from(config, "k", wire, session_id="ofag-abc123")
    model.respond("s", [Turn(role="user", text="hi")], [])
    model.respond("s", [Turn(role="user", text="again")], [])

    assert [h["x-opencode-session"] for h in wire.headers] == ["ofag-abc123", "ofag-abc123"]


@pytest.mark.parametrize(
    "base",
    [
        "https://api.anthropic.com",
        "https://api.deepseek.com/v1",
        "https://openrouter.ai/api/v1",
        "https://evil-opencode.ai.example/v1",
    ],
)
def test_no_other_provider_is_sent_the_id(base) -> None:
    assert session_headers(ProviderConfig(base_url=base), "ofag-abc123") == {}


def test_without_an_id_nothing_is_sent() -> None:
    assert session_headers(ProviderConfig(base_url="https://opencode.ai/zen/go/v1"), "") == {}


def test_the_connection_test_sends_one_too() -> None:
    wire = Recorder(ANSWERS[ProviderKind.OPENAI_COMPATIBLE])
    config = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://opencode.ai/zen/go/v1",
        model="glm-5.2",
    )

    probe(config, "k", wire)

    assert wire.headers[0]["x-opencode-session"].startswith("ofag-probe-")


def test_the_panel_names_every_request_of_a_conversation_the_same(tmp_path) -> None:
    """Lead and workers alike: one conversation, one id, the orchestrator's."""
    import os
    from importlib.util import find_spec

    if find_spec("PySide6") is None:
        pytest.skip("the desktop extra is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from ofag.agent.providers import AgentSettings
    from ofag.desktop.agent_panel import AgentPanel
    from tests.test_agent_panel import _session, _wait_until

    QApplication.instance() or QApplication([])
    answers = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "d1",
                                    "function": {
                                        "name": "ofag__delegate",
                                        "arguments": json.dumps(
                                            {"role": "audit", "task": "check R"}
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "R is not diagnosed."}}]},
            {"choices": [{"message": {"content": "Nothing can be read in yet."}}]},
        ]
    )
    headers: list[dict] = []

    def wire(url, sent_headers, body, timeout):
        headers.append(sent_headers)
        return json.dumps(next(answers)).encode()

    config = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://opencode.ai/zen/go/v1",
        model="glm-5.2",
        api_key_env="",
    )
    panel = AgentPanel(
        settings_loader=lambda: AgentSettings(provider=config), settings_saver=lambda s: None
    )
    panel._model_factory = lambda cfg, key: model_from(
        cfg, key, wire, session_id=panel._conversation_id()
    )
    panel._session_key = "k"
    panel.set_session(_session(tmp_path))
    panel.input.setPlainText("Can R go into the model?")

    panel.submit()
    _wait_until(lambda: panel.send.isEnabled())

    ids = {h["x-opencode-session"] for h in headers}
    assert len(headers) == 3 and len(ids) == 1
    assert ids.pop() == f"ofag-{panel._orchestrator.conversation_id}"
