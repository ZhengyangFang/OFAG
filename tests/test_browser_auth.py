"""Check browser credential boundaries and provider wire formats."""

import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from ofag.agent import browser_auth
from ofag.agent.providers import (
    AgentSettings,
    AnthropicModel,
    OpenAIResponsesModel,
    ProviderConfig,
    ProviderError,
    ProviderKind,
    ToolCall,
    ToolSpec,
    Turn,
    save_settings,
)
from ofag.cli.main import app


def test_chatgpt_credentials_refresh_outside_project(tmp_path, monkeypatch) -> None:
    root = tmp_path / "private"
    monkeypatch.setattr(browser_auth, "AUTH_ROOT", root)
    monkeypatch.setattr(browser_auth, "CHATGPT_FILE", root / "chatgpt.json")
    monkeypatch.setattr(browser_auth, "HOST_FILE", root / "host_id")
    browser_auth._save_private(
        browser_auth.CHATGPT_FILE,
        json.dumps(
            {
                "client_id": "client",
                "subject": "subject",
                "access_token": "old-secret",
                "refresh_token": "old-refresh",
                "scopes": ["chatgpt.tokens.use.direct"],
                "expires_at": 0,
            }
        ),
    )
    calls = []

    def refresh(url, data=None, token=""):
        calls.append((url, data))
        return {
            "access_token": "new-secret",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "chatgpt.tokens.use.direct",
        }

    monkeypatch.setattr(browser_auth, "_request_json", refresh)
    assert browser_auth.chatgpt_access_token() == "new-secret"
    assert browser_auth.chatgpt_access_token() == "new-secret"
    assert len(calls) == 1
    assert json.loads(browser_auth.CHATGPT_FILE.read_text())["refresh_token"] == "new-refresh"


def test_chatgpt_response_uses_namespaced_tools_and_stream(monkeypatch) -> None:
    monkeypatch.setattr(browser_auth, "chatgpt_access_token", lambda: "private-token")
    sent = []

    def wire(url, headers, body, timeout):
        sent.append((url, headers, json.loads(body)))
        event = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "namespace": "ofag",
                        "name": "list_plugins",
                        "call_id": "c1",
                        "arguments": "{}",
                    }
                ],
            },
        }
        return f"data: {json.dumps(event)}\n\n".encode()

    config = replace(
        ProviderConfig.default_for(ProviderKind.OPENAI_RESPONSES),
        auth_source="chatgpt",
        api_key_env="",
    )
    reply = OpenAIResponsesModel(config, "", wire).respond(
        "Use tools",
        [Turn(role="user", text="List plugins")],
        [ToolSpec("ofag.list_plugins", "List", {"type": "object"})],
    )
    _, headers, body = sent[0]
    assert headers["authorization"] == "Bearer private-token"
    assert body["store"] is False and body["stream"] is True
    assert "max_output_tokens" not in body
    assert body["tools"][0]["name"] == "ofag"
    assert body["tools"][0]["tools"][0]["name"] == "list_plugins"
    assert reply.tool_calls == (ToolCall("c1", "ofag.list_plugins", {}),)


def test_claude_console_uses_bearer_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(browser_auth, "claude_console_token", lambda: "private-token")
    sent = []

    def wire(url, headers, body, timeout):
        sent.append(headers)
        return b'{"content": [{"type": "text", "text": "OK"}]}'

    config = replace(ProviderConfig(), auth_source="anthropic_console", api_key_env="")
    reply = AnthropicModel(config, "", wire).respond(
        "Reply OK", [Turn(role="user", text="OK")], []
    )
    assert reply.text == "OK"
    assert sent[0]["authorization"] == "Bearer private-token"
    assert "x-api-key" not in sent[0]


def test_browser_auth_rejects_non_official_endpoint() -> None:
    config = replace(ProviderConfig(), auth_source="anthropic_console", base_url="https://relay.test")
    with pytest.raises(ProviderError, match="official Anthropic endpoint"):
        AnthropicModel(config, "", lambda *_: b"{}").respond("", [], [])


def test_auth_status_does_not_print_identity_or_secrets(tmp_path, monkeypatch) -> None:
    import ofag.agent.providers as providers

    path = tmp_path / "settings.json"
    config = replace(
        ProviderConfig.default_for(ProviderKind.OPENAI_RESPONSES),
        auth_source="chatgpt",
        api_key_env="",
    )
    save_settings(AgentSettings(provider=config), path)
    monkeypatch.setattr(providers, "SETTINGS_PATH", path)
    result = CliRunner().invoke(app, ["--json", "auth", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["auth_source"] == "chatgpt"
    assert "account" not in payload
    assert "private-token" not in result.stdout


def test_gpt_login_saves_only_provider_selection(tmp_path, monkeypatch) -> None:
    import ofag.agent.providers as providers

    path = tmp_path / "settings.json"
    monkeypatch.setattr(providers, "SETTINGS_PATH", path)
    monkeypatch.setattr(browser_auth, "login_chatgpt", lambda: None)
    monkeypatch.setattr(browser_auth, "chatgpt_access_token", lambda: "private-token")
    monkeypatch.setattr(browser_auth, "chatgpt_models", lambda token: ["gpt-test"])
    result = CliRunner().invoke(app, ["auth", "login", "gpt"])
    assert result.exit_code == 0
    assert providers.load_settings().provider.auth_source == "chatgpt"
    assert providers.load_settings().provider.model == "gpt-test"
    assert "private-token" not in path.read_text("utf-8") + result.stdout
