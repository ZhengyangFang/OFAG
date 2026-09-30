"""The model an agent thinks with, behind one interface, from any provider."""

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "ProviderKind",
    "ProviderConfig",
    "ProviderError",
    "ToolSpec",
    "ToolCall",
    "ToolResult",
    "Turn",
    "Reply",
    "ChatModel",
    "AnthropicModel",
    "OpenAICompatibleModel",
    "model_from",
    "resolve_key",
    "is_variable_name",
    "session_headers",
    "SESSION_HEADERS",
    "encode_tool_name",
    "decode_tool_name",
    "OpenAIResponsesModel",
    "PRESETS",
    "Preset",
    "endpoint",
    "probe",
    "USER_AGENT",
    "load_settings",
    "save_settings",
    "AgentSettings",
    "SETTINGS_PATH",
]


class ProviderKind(StrEnum):
    """A wire protocol, not a company: most providers speak one of these three."""

    #: The Anthropic Messages API (`/v1/messages`).
    ANTHROPIC = "anthropic"
    #: OpenAI chat completions (`/chat/completions`): OpenAI, DeepSeek, Qwen, Kimi, GLM,
    #: Doubao, OpenRouter, SiliconFlow, Ollama, vLLM, LM Studio.
    OPENAI_COMPATIBLE = "openai_compatible"
    #: The OpenAI Responses API (`/responses`), which some models are served over and
    #: nothing else.
    OPENAI_RESPONSES = "openai_responses"


_DEFAULTS: dict[ProviderKind, tuple[str, str, str]] = {
    ProviderKind.ANTHROPIC: ("https://api.anthropic.com", "claude-opus-5-5", "ANTHROPIC_API_KEY"),
    ProviderKind.OPENAI_COMPATIBLE: ("https://api.openai.com/v1", "gpt-5", "OPENAI_API_KEY"),
    ProviderKind.OPENAI_RESPONSES: ("https://api.openai.com/v1", "gpt-5", "OPENAI_API_KEY"),
}

#: Sent on every request. urllib's own ("Python-urllib/3.x") is refused by relays behind
#: Cloudflare with a 403 before the key is ever read, which is indistinguishable from a
#: bad key to the person looking at it.
USER_AGENT = "OFAG/0.1 (+https://github.com; agent runner)"


@dataclass(frozen=True)
class Preset:
    """A provider or relay, filled in."""

    label: str
    kind: "ProviderKind"
    base_url: str
    #: An example; providers rename models often, so check their list.
    model: str
    api_key_env: str


PRESETS: tuple[Preset, ...] = (
    Preset(
        "Anthropic",
        ProviderKind.ANTHROPIC,
        "https://api.anthropic.com",
        "claude-opus-5-5",
        "ANTHROPIC_API_KEY",
    ),
    Preset(
        "OpenAI (chat)",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.openai.com/v1",
        "gpt-5",
        "OPENAI_API_KEY",
    ),
    Preset(
        "OpenAI (Responses)",
        ProviderKind.OPENAI_RESPONSES,
        "https://api.openai.com/v1",
        "gpt-5",
        "OPENAI_API_KEY",
    ),
    Preset(
        "Google Gemini",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.5-pro",
        "GEMINI_API_KEY",
    ),
    Preset(
        "DeepSeek",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.deepseek.com/v1",
        "deepseek-chat",
        "DEEPSEEK_API_KEY",
    ),
    Preset(
        "Qwen (Alibaba Cloud Model Studio)",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-max",
        "DASHSCOPE_API_KEY",
    ),
    Preset(
        "Kimi (Moonshot AI)",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.moonshot.cn/v1",
        "kimi-latest",
        "MOONSHOT_API_KEY",
    ),
    Preset(
        "GLM (Zhipu AI)",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4.6",
        "ZHIPUAI_API_KEY",
    ),
    Preset(
        "Doubao (Volcano Engine Ark)",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-seed-1-6",
        "ARK_API_KEY",
    ),
    Preset(
        "MiniMax",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.minimaxi.com/v1",
        "MiniMax-M2",
        "MINIMAX_API_KEY",
    ),
    Preset(
        "SiliconFlow",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.siliconflow.cn/v1",
        "deepseek-ai/DeepSeek-V3",
        "SILICONFLOW_API_KEY",
    ),
    Preset(
        "OpenRouter",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://openrouter.ai/api/v1",
        "anthropic/claude-opus-4.1",
        "OPENROUTER_API_KEY",
    ),
    Preset(
        "OpenCode Go · GLM/Kimi/DeepSeek",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://opencode.ai/zen/go/v1",
        "kimi-k3",
        "OPENCODE_API_KEY",
    ),
    Preset(
        "OpenCode Go · Qwen/MiniMax",
        ProviderKind.ANTHROPIC,
        "https://opencode.ai/zen/go/v1",
        "qwen3.8-max",
        "OPENCODE_API_KEY",
    ),
    Preset(
        "OpenCode Go · Grok/GPT",
        ProviderKind.OPENAI_RESPONSES,
        "https://opencode.ai/zen/go/v1",
        "grok-4.7",
        "OPENCODE_API_KEY",
    ),
    Preset(
        "OpenCode Zen",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://opencode.ai/zen/v1",
        "kimi-k3",
        "OPENCODE_API_KEY",
    ),
    Preset(
        "xAI Grok", ProviderKind.OPENAI_COMPATIBLE, "https://api.x.ai/v1", "grok-4", "XAI_API_KEY"
    ),
    Preset(
        "Mistral",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.mistral.ai/v1",
        "mistral-large-latest",
        "MISTRAL_API_KEY",
    ),
    Preset(
        "Groq",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "GROQ_API_KEY",
    ),
    Preset(
        "Together",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://api.together.xyz/v1",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "TOGETHER_API_KEY",
    ),
    Preset(
        "Relay · OpenAI protocol",
        ProviderKind.OPENAI_COMPATIBLE,
        "https://",
        "",
        "OFAG_RELAY_API_KEY",
    ),
    Preset(
        "Relay · Anthropic protocol",
        ProviderKind.ANTHROPIC,
        "https://",
        "",
        "OFAG_RELAY_API_KEY",
    ),
    Preset(
        "Ollama (this machine)",
        ProviderKind.OPENAI_COMPATIBLE,
        "http://localhost:11434/v1",
        "qwen3",
        "",
    ),
    Preset(
        "LM Studio (this machine)",
        ProviderKind.OPENAI_COMPATIBLE,
        "http://localhost:1234/v1",
        "local-model",
        "",
    ),
    Preset(
        "vLLM (this machine)",
        ProviderKind.OPENAI_COMPATIBLE,
        "http://localhost:8000/v1",
        "local-model",
        "",
    ),
)


def endpoint(kind: "ProviderKind", base_url: str) -> str:
    """The URL a request goes to, from a base however it was pasted."""
    base = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/messages"):
        if base.endswith(suffix):
            return base
    if kind is ProviderKind.ANTHROPIC:
        return base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    if kind is ProviderKind.OPENAI_RESPONSES:
        return base + "/responses"
    return base + "/chat/completions"


@dataclass(frozen=True)
class ProviderConfig:
    """Where a model is and which one; never the key itself."""

    kind: ProviderKind = ProviderKind.ANTHROPIC
    model: str = "claude-opus-5-5"
    base_url: str = "https://api.anthropic.com"
    #: The environment variable the key is read from.
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 8192
    timeout_s: float = 300.0

    @classmethod
    def default_for(cls, kind: ProviderKind) -> "ProviderConfig":
        base, model, env = _DEFAULTS[kind]
        return cls(kind=kind, model=model, base_url=base, api_key_env=env)

    @property
    def host(self) -> str:
        return self.base_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def is_local(self) -> bool:
        """Whether requests stay on this machine."""
        host = self.host.split(":", 1)[0].lower()
        return host in {"localhost", "127.0.0.1", "::1", "[::1]"}


class ProviderError(RuntimeError):
    """The model could not be reached or refused the request."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    #: The OFAG name, decoded.
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Turn:
    """One turn of a conversation, in no provider's format."""

    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    #: What the model reasoned before answering, where the provider returns it:
    #: `reasoning_content` from DeepSeek, GLM and Qwen, Anthropic's thinking blocks, a
    #: Responses reasoning summary.
    reasoning: str = ""


class ChatModel(Protocol):
    """What the orchestrator needs from a model, and nothing more."""

    def respond(self, system: str, turns: Sequence[Turn], tools: Sequence[ToolSpec]) -> Reply: ...


def encode_tool_name(name: str) -> str:
    """`ofag.list_plugins` -> `ofag__list_plugins`, which both protocols accept."""
    return name.replace(".", "__")


def decode_tool_name(name: str) -> str:
    return name.replace("__", ".")


#: A POST: url, headers, body -> response body. Injected by the tests.
Transport = Callable[[str, dict[str, str], bytes, float], bytes]


def _urllib_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https or a local server the user chose
        return bytes(response.read())


_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def is_variable_name(text: str) -> bool:
    """Whether this can be the name of an environment variable."""
    return bool(_VARIABLE.match(text.strip()))


def resolve_key(config: ProviderConfig, typed: str | None = None) -> str:
    """The key for a request: typed for this session, else the environment."""
    if typed and typed.strip():
        return typed.strip()
    if config.api_key_env and not is_variable_name(config.api_key_env):
        # Never echoed: what is in that field is most likely the key itself.
        raise ProviderError(
            "the key variable field holds something that is not a variable name -- it looks "
            "like a key. Put the key in 'Key (this session)', and in 'Key variable' the name "
            "of an environment variable such as OPENCODE_API_KEY."
        )
    if config.api_key_env:
        value = os.environ.get(config.api_key_env, "").strip()
        if value:
            return value
    if config.is_local:
        return ""
    raise ProviderError(
        f"no API key for {config.host}: set the environment variable "
        f"{config.api_key_env or '(none named)'} or enter a key for this session"
    )


def _post_json(
    transport: Transport,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    secret: str,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    try:
        raw = transport(url, headers, body, timeout)
    except urllib.error.HTTPError as failed:
        detail = failed.read().decode("utf-8", "replace")[:600]
        hint = _HINTS.get(failed.code, "")
        raise ProviderError(
            _scrub(f"{url} answered {failed.code}: {detail}{hint}", secret)
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as failed:
        raise ProviderError(_scrub(f"could not reach {url}: {failed}", secret)) from None
    try:
        answer = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as bad:
        raise ProviderError(f"{url} returned something that is not JSON: {bad}") from None
    if not isinstance(answer, dict):
        raise ProviderError(f"{url} returned {type(answer).__name__}, not an object")
    return answer


#: What a status usually means when talking to a provider or a relay.
_HINTS = {
    401: "\n-> The key was refused: check which environment variable it is read from.",
    403: (
        "\n-> Refused before the model was asked: a wrong or expired key, a key for a "
        "different product of the same company, or a relay that blocks this client."
    ),
    404: (
        "\n-> Nothing at that address: the base URL, or the protocol chosen for this "
        "model, is wrong. The URL tried is shown above."
    ),
    429: "\n-> Rate or quota limit reached on this key.",
}


#: Providers that ask each request to name the conversation it belongs to, and the
#: header they read it from.
SESSION_HEADERS: dict[str, str] = {"opencode.ai": "x-opencode-session"}


def session_headers(config: "ProviderConfig", session_id: str) -> dict[str, str]:
    """The session header for this provider, or nothing."""
    if not session_id:
        return {}
    host = config.host.split(":", 1)[0].lower()
    for domain, header in SESSION_HEADERS.items():
        if host == domain or host.endswith("." + domain):
            return {header: session_id}
    return {}


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "<key>") if secret else text


@dataclass
class AnthropicModel:
    """The Messages API."""

    config: ProviderConfig
    key: str
    transport: Transport = _urllib_post
    #: The conversation this request belongs to; see `session_headers`.
    session_id: str = ""

    def respond(self, system: str, turns: Sequence[Turn], tools: Sequence[ToolSpec]) -> Reply:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system,
            "messages": [self._message(turn) for turn in turns],
        }
        if tools:
            payload["tools"] = [
                {
                    "name": encode_tool_name(t.name),
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "user-agent": USER_AGENT,
        }
        if self.key:
            # Both: Anthropic reads x-api-key, and relays that speak its protocol split
            # between that and a bearer token.
            headers["x-api-key"] = self.key
            headers["authorization"] = f"Bearer {self.key}"
        headers.update(session_headers(self.config, self.session_id))
        answer = _post_json(
            self.transport,
            endpoint(ProviderKind.ANTHROPIC, self.config.base_url),
            headers,
            payload,
            self.config.timeout_s,
            self.key,
        )
        text: list[str] = []
        thought: list[str] = []
        calls: list[ToolCall] = []
        for block in answer.get("content") or ():
            if block.get("type") == "text":
                text.append(str(block.get("text", "")))
            elif block.get("type") == "thinking":
                thought.append(str(block.get("thinking", "")))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(block["id"]),
                        name=decode_tool_name(str(block["name"])),
                        arguments=dict(block.get("input") or {}),
                    )
                )
        usage = answer.get("usage") or {}
        return Reply(
            text="\n".join(t for t in text if t).strip(),
            tool_calls=tuple(calls),
            stop_reason=str(answer.get("stop_reason") or ""),
            reasoning="\n".join(t for t in thought if t).strip(),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    @staticmethod
    def _message(turn: Turn) -> dict[str, Any]:
        if turn.role == "user":
            return {"role": "user", "content": turn.text}
        if turn.role == "assistant":
            content: list[dict[str, Any]] = []
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            content += [
                {
                    "type": "tool_use",
                    "id": c.id,
                    "name": encode_tool_name(c.name),
                    "input": c.arguments,
                }
                for c in turn.tool_calls
            ]
            return {"role": "assistant", "content": content or turn.text}
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": r.call_id,
                    "content": r.content,
                    "is_error": r.is_error,
                }
                for r in turn.results
            ],
        }


@dataclass
class OpenAICompatibleModel:
    """The chat completions protocol, which local servers speak too."""

    config: ProviderConfig
    key: str
    transport: Transport = _urllib_post
    #: The conversation this request belongs to; see `session_headers`.
    session_id: str = ""

    def respond(self, system: str, turns: Sequence[Turn], tools: Sequence[ToolSpec]) -> Reply:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for turn in turns:
            messages += self._messages(turn)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": encode_tool_name(t.name),
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        headers = {"content-type": "application/json", "user-agent": USER_AGENT}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        headers.update(session_headers(self.config, self.session_id))
        answer = _post_json(
            self.transport,
            endpoint(ProviderKind.OPENAI_COMPATIBLE, self.config.base_url),
            headers,
            payload,
            self.config.timeout_s,
            self.key,
        )
        choices = answer.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.config.host} returned no choices")
        message = choices[0].get("message") or {}
        calls: list[ToolCall] = []
        for call in message.get("tool_calls") or ():
            function = call.get("function") or {}
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                # Handed to the dispatcher as-is, which refuses it readably, rather than
                # dropped: the model should see what it sent.
                arguments = {"__unparsed__": raw}
            calls.append(
                ToolCall(
                    id=str(call.get("id") or f"call_{len(calls)}"),
                    name=decode_tool_name(str(function.get("name", ""))),
                    arguments=arguments if isinstance(arguments, dict) else {"__unparsed__": raw},
                )
            )
        usage = answer.get("usage") or {}
        return Reply(
            text=str(message.get("content") or "").strip(),
            tool_calls=tuple(calls),
            stop_reason=str(choices[0].get("finish_reason") or ""),
            reasoning=str(
                message.get("reasoning_content") or message.get("reasoning") or ""
            ).strip(),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    @staticmethod
    def _messages(turn: Turn) -> list[dict[str, Any]]:
        if turn.role == "user":
            return [{"role": "user", "content": turn.text}]
        if turn.role == "assistant":
            message: dict[str, Any] = {"role": "assistant", "content": turn.text or None}
            if turn.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": encode_tool_name(c.name),
                            "arguments": json.dumps(c.arguments),
                        },
                    }
                    for c in turn.tool_calls
                ]
            return [message]
        return [
            {"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in turn.results
        ]


@dataclass
class OpenAIResponsesModel:
    """The Responses API: instructions, a list of input items, output items."""

    config: ProviderConfig
    key: str
    transport: Transport = _urllib_post
    #: The conversation this request belongs to; see `session_headers`.
    session_id: str = ""

    def respond(self, system: str, turns: Sequence[Turn], tools: Sequence[ToolSpec]) -> Reply:
        items: list[dict[str, Any]] = []
        for turn in turns:
            if turn.role == "user":
                items.append({"role": "user", "content": turn.text})
            elif turn.role == "assistant":
                if turn.text:
                    items.append({"role": "assistant", "content": turn.text})
                items += [
                    {
                        "type": "function_call",
                        "call_id": c.id,
                        "name": encode_tool_name(c.name),
                        "arguments": json.dumps(c.arguments),
                    }
                    for c in turn.tool_calls
                ]
            else:
                items += [
                    {"type": "function_call_output", "call_id": r.call_id, "output": r.content}
                    for r in turn.results
                ]
        payload: dict[str, Any] = {
            "model": self.config.model,
            "instructions": system,
            "input": items,
            "max_output_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": encode_tool_name(t.name),
                    "description": t.description,
                    "parameters": t.input_schema,
                }
                for t in tools
            ]
        headers = {"content-type": "application/json", "user-agent": USER_AGENT}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        headers.update(session_headers(self.config, self.session_id))
        answer = _post_json(
            self.transport,
            endpoint(ProviderKind.OPENAI_RESPONSES, self.config.base_url),
            headers,
            payload,
            self.config.timeout_s,
            self.key,
        )
        text: list[str] = []
        thought: list[str] = []
        calls: list[ToolCall] = []
        for item in answer.get("output") or ():
            if item.get("type") == "reasoning":
                for part in item.get("summary") or ():
                    thought.append(str(part.get("text", "")))
            if item.get("type") == "message":
                for part in item.get("content") or ():
                    if part.get("type") in {"output_text", "text"}:
                        text.append(str(part.get("text", "")))
            elif item.get("type") == "function_call":
                raw = item.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
                except json.JSONDecodeError:
                    arguments = {"__unparsed__": raw}
                calls.append(
                    ToolCall(
                        id=str(item.get("call_id") or item.get("id") or f"call_{len(calls)}"),
                        name=decode_tool_name(str(item.get("name", ""))),
                        arguments=arguments
                        if isinstance(arguments, dict)
                        else {"__unparsed__": raw},
                    )
                )
        usage = answer.get("usage") or {}
        return Reply(
            text="\n".join(t for t in text if t).strip(),
            tool_calls=tuple(calls),
            stop_reason=str(answer.get("status") or ""),
            reasoning="\n".join(t for t in thought if t).strip(),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )


def model_from(
    config: ProviderConfig, key: str, transport: Transport | None = None, *, session_id: str = ""
) -> ChatModel:
    chosen = transport or _urllib_post
    if config.kind is ProviderKind.ANTHROPIC:
        return AnthropicModel(config=config, key=key, transport=chosen, session_id=session_id)
    if config.kind is ProviderKind.OPENAI_RESPONSES:
        return OpenAIResponsesModel(config=config, key=key, transport=chosen, session_id=session_id)
    return OpenAICompatibleModel(config=config, key=key, transport=chosen, session_id=session_id)


def probe(config: ProviderConfig, key: str, transport: Transport | None = None) -> str:
    """One small request, to say whether this configuration works before it is used."""
    if not config.model.strip():
        raise ProviderError("no model named: fill in the model the provider serves")
    import uuid

    reply = model_from(config, key, transport, session_id=f"ofag-probe-{uuid.uuid4().hex}").respond(
        "You are checking a connection. Reply with the single word OK.",
        [Turn(role="user", text="Reply with OK.")],
        [],
    )
    return reply.text or "(an empty reply, but the request was accepted)"


# -- settings, kept per user and never per project ---------------------------------

#: Outside every project, because a project folder is exported and shared and a provider
#: setting is the user's, not the project's.
SETTINGS_PATH = Path.home() / ".ofag" / "agent_settings.json"


@dataclass(frozen=True)
class AgentSettings:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    #: A role's model when it is not the lead's.
    role_models: dict[str, str] = field(default_factory=dict)

    def config_for(self, role: str) -> ProviderConfig:
        model = self.role_models.get(role, "").strip()
        return replace(self.provider, model=model) if model else self.provider


def load_settings(path: Path | None = None) -> AgentSettings:
    source = path or SETTINGS_PATH
    if not source.is_file():
        return AgentSettings()
    try:
        raw = json.loads(source.read_text("utf-8"))
        provider = dict(raw.get("provider") or {})
        provider["kind"] = ProviderKind(provider.get("kind", ProviderKind.ANTHROPIC))
        known = set(ProviderConfig.__dataclass_fields__)
        if not is_variable_name(str(provider.get("api_key_env", ""))):
            # A key saved by an earlier version, or typed into this file: dropped rather
            # than carried, so it is not shown or sent as a name.
            provider["api_key_env"] = ""
        return AgentSettings(
            provider=ProviderConfig(**{k: v for k, v in provider.items() if k in known}),
            role_models={str(k): str(v) for k, v in dict(raw.get("role_models") or {}).items()},
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        # A settings file somebody edited into nonsense falls back to the defaults
        # rather than locking the user out of the panel.
        return AgentSettings()


def save_settings(settings: AgentSettings, path: Path | None = None) -> Path:
    target = path or SETTINGS_PATH
    name = settings.provider.api_key_env
    if name and not is_variable_name(name):
        raise ProviderError(
            "not saved: the key variable field holds something that is not a variable name, "
            "and it is probably the key. Keys are never written to disk."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    provider = asdict(settings.provider)
    provider["kind"] = settings.provider.kind.value
    assert "key" not in provider and "api_key" not in provider
    target.write_text(
        json.dumps({"provider": provider, "role_models": settings.role_models}, indent=2),
        encoding="utf-8",
    )
    return target
