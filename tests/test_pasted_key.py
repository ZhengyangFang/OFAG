"""A key pasted where the variable name goes: caught, never saved, never shown."""

import os
from importlib.util import find_spec

import pytest

from ofag.agent.providers import (
    AgentSettings,
    ProviderConfig,
    ProviderError,
    ProviderKind,
    is_variable_name,
    load_settings,
    resolve_key,
    save_settings,
)

KEY = "sk-" + "Zq" * 30 + "-not-a-real-key"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.parametrize("name", ["OPENCODE_API_KEY", "ANTHROPIC_API_KEY", "_X", "key2"])
def test_a_variable_name_is_one(name) -> None:
    assert is_variable_name(name)


@pytest.mark.parametrize("text", [KEY, "sk-abc", "my key", "A" * 80, "1ABC"])
def test_a_key_is_not_a_variable_name(text) -> None:
    assert not is_variable_name(text)


def test_a_key_in_the_variable_field_is_refused_without_being_repeated() -> None:
    config = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://opencode.ai/zen/go/v1",
        api_key_env=KEY,
    )

    with pytest.raises(ProviderError) as raised:
        resolve_key(config)

    assert "Key (this session)" in str(raised.value)
    assert KEY not in str(raised.value) and "sk-" not in str(raised.value)


def test_it_is_never_saved(tmp_path) -> None:
    path = tmp_path / "agent_settings.json"

    with pytest.raises(ProviderError, match="never written to disk"):
        save_settings(AgentSettings(provider=ProviderConfig(api_key_env=KEY)), path)

    assert not path.exists()


def test_one_saved_by_the_earlier_version_is_dropped_on_load(tmp_path) -> None:
    path = tmp_path / "agent_settings.json"
    path.write_text(
        '{"provider": {"kind": "anthropic", "api_key_env": "' + KEY + '"}}', encoding="utf-8"
    )

    assert load_settings(path).provider.api_key_env == ""


@pytest.mark.skipif(find_spec("PySide6") is None, reason="the desktop extra is not installed")
def test_the_dialog_moves_it_to_the_session_field() -> None:
    from PySide6.QtWidgets import QApplication

    from ofag.desktop.agent_panel import ProviderDialog

    QApplication.instance() or QApplication([])
    seen = []
    dialog = ProviderDialog(
        AgentSettings(), "", prober=lambda config, key: seen.append((config, key)) or "OK"
    )
    index = next(
        i
        for i in range(dialog._preset.count())
        if dialog._preset.itemText(i).startswith("OpenCode Go · GLM")
    )
    dialog._preset.setCurrentIndex(index)
    dialog._env.setText(KEY)

    dialog._run_probe()

    config, key = seen[0]
    assert key == KEY and config.api_key_env == "OPENCODE_API_KEY"
    settings, session_key = dialog.result_settings()
    assert session_key == KEY and settings.provider.api_key_env == "OPENCODE_API_KEY"
    assert "moved" in dialog._verdict.text()
