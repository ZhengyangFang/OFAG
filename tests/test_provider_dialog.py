"""The model settings dialog: presets fill it, and a test shows the server's answer."""

import os
from importlib.util import find_spec

import pytest

from ofag.agent.providers import PRESETS, AgentSettings, ProviderError

pytestmark = pytest.mark.skipif(
    find_spec("PySide6") is None, reason="the desktop extra is not installed"
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _choose(dialog, label: str) -> None:
    index = next(i for i in range(dialog._preset.count()) if dialog._preset.itemText(i) == label)
    dialog._preset.setCurrentIndex(index)


def test_a_preset_fills_the_fields_and_shows_where_requests_go() -> None:
    from ofag.desktop.agent_panel import ProviderDialog

    _app()
    dialog = ProviderDialog(AgentSettings(), "")
    _choose(dialog, "OpenCode Go · Qwen/MiniMax")

    config = dialog.current_config()
    preset = next(p for p in PRESETS if p.label == "OpenCode Go · Qwen/MiniMax")
    assert (config.kind, config.base_url, config.model, config.api_key_env) == (
        preset.kind,
        preset.base_url,
        preset.model,
        preset.api_key_env,
    )
    assert dialog._endpoint.text() == "https://opencode.ai/zen/go/v1/messages"


def test_changing_the_protocol_keeps_a_relays_address() -> None:
    """A relay's base URL is typed by hand; switching protocol must not wipe it."""
    from ofag.agent.providers import ProviderKind
    from ofag.desktop.agent_panel import ProviderDialog

    _app()
    dialog = ProviderDialog(AgentSettings(), "")
    dialog._base.setText("https://my-relay.example/v1")
    dialog._kind.setCurrentIndex(dialog._kind.findData(ProviderKind.ANTHROPIC))

    assert dialog._base.text() == "https://my-relay.example/v1"
    assert dialog._endpoint.text() == "https://my-relay.example/v1/messages"


def test_the_test_button_uses_the_typed_key_and_a_short_timeout() -> None:
    from ofag.desktop.agent_panel import ProviderDialog

    _app()
    seen = []
    dialog = ProviderDialog(
        AgentSettings(), "sk-typed", prober=lambda config, key: seen.append((config, key)) or "OK"
    )
    _choose(dialog, "DeepSeek")

    dialog._run_probe()

    config, key = seen[0]
    assert key == "sk-typed" and config.timeout_s == 30.0 and config.model == "deepseek-chat"
    assert "Works" in dialog._verdict.text()


def test_a_failed_test_shows_the_servers_own_answer() -> None:
    from ofag.desktop.agent_panel import ProviderDialog

    _app()

    def refuses(config, key):
        raise ProviderError(
            "https://relay.example/v1/chat/completions answered 403: error code: 1010"
        )

    dialog = ProviderDialog(AgentSettings(), "sk", prober=refuses)
    dialog._run_probe()

    assert "error code: 1010" in dialog._verdict.text()
