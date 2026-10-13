"""Browser login credentials for the official model endpoints."""

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import jwt

from ofag.agent.providers import ProviderError

AUTH_ROOT = Path.home() / ".ofag" / "auth"
CHATGPT_FILE = AUTH_ROOT / "chatgpt.json"
HOST_FILE = AUTH_ROOT / "host_id"
OPENAI_AUTH = "https://auth.openai.com"
OPENAI_RESOURCE = "https://api.openai.com/v1"
OPENAI_SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def _private_root() -> None:
    AUTH_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        AUTH_ROOT.chmod(0o700)


def _save_private(path: Path, content: str) -> None:
    _private_root()
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _host_id() -> str:
    if HOST_FILE.is_file():
        return HOST_FILE.read_text("utf-8").strip()
    value = f"urn:uuid:{uuid.uuid4()}"
    _save_private(HOST_FILE, value)
    return value


def _credentials() -> dict[str, Any]:
    try:
        value = json.loads(CHATGPT_FILE.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise ProviderError("ChatGPT is not connected; run 'ofag auth login gpt'") from error
    if not isinstance(value, dict) or not all(
        isinstance(value.get(name), str) and value[name]
        for name in ("client_id", "subject", "access_token", "refresh_token")
    ):
        raise ProviderError("ChatGPT credentials are incomplete; sign in again")
    return value


def _request_json(url: str, data: dict[str, str] | None = None, token: str = "") -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read()
            value = json.loads(raw) if raw else {}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
        code = getattr(error, "code", None)
        suffix = f" ({code})" if code else ""
        raise ProviderError(f"authentication request failed{suffix}") from None
    except json.JSONDecodeError:
        raise ProviderError("authentication server returned invalid JSON") from None
    if not isinstance(value, dict):
        raise ProviderError("authentication server returned an invalid response")
    return value


@contextmanager
def _refresh_lock() -> Iterator[None]:
    _private_root()
    path = AUTH_ROOT / "refresh.lock"
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX)  # type: ignore[attr-defined]
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def chatgpt_access_token() -> str:
    with _refresh_lock():
        credentials = _credentials()
        if "chatgpt.tokens.use.direct" not in credentials.get("scopes", []):
            raise ProviderError("ChatGPT plan access was not granted; sign in again")
        if float(credentials.get("expires_at") or 0) > time.time() + 120:
            return str(credentials["access_token"])
        refreshed = _request_json(
            f"{OPENAI_AUTH}/api/accounts/oauth/token",
            {
                "grant_type": "refresh_token",
                "client_id": str(credentials["client_id"]),
                "refresh_token": str(credentials["refresh_token"]),
                "resource": OPENAI_RESOURCE,
            },
        )
        if not refreshed.get("access_token") or not refreshed.get("refresh_token"):
            raise ProviderError("ChatGPT session could not be renewed; sign in again")
        credentials.update(
            access_token=refreshed["access_token"],
            refresh_token=refreshed["refresh_token"],
            expires_at=time.time() + int(refreshed.get("expires_in") or 3600),
            scopes=str(refreshed.get("scope") or " ".join(credentials["scopes"])).split(),
        )
        _save_private(CHATGPT_FILE, json.dumps(credentials))
        return str(credentials["access_token"])


def chatgpt_models(token: str) -> list[str]:
    response = _request_json(f"{OPENAI_RESOURCE}/models", token=token)
    models = response.get("models") or response.get("data") or []
    return [
        str(model["slug"])
        for model in models
        if isinstance(model, dict) and model.get("slug") and model.get("visibility") == "list"
    ]


def login_chatgpt(timeout_s: float = 300.0) -> None:
    """Register or renew one local ChatGPT connection."""
    existing = _credentials() if CHATGPT_FILE.is_file() else None
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge_bytes = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    challenge = challenge_bytes.rstrip(b"=").decode()
    callback: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(parsed.query)
            callback.update({name: values[0] for name, values in query.items() if values})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"You can return to OFAG now.")

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        params = {
            "client_id": str(existing["client_id"]) if existing else "dynamic_agent_client",
            "ext_agent_host_id": _host_id(),
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": OPENAI_SCOPE,
            "resource": OPENAI_RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if existing:
            if existing.get("id_token"):
                params["id_token_hint"] = str(existing["id_token"])
        else:
            params["agent_name_hint"] = "OFAG"
        url = f"{OPENAI_AUTH}/api/accounts/authorize?{urllib.parse.urlencode(params)}"
        if not webbrowser.open(url):
            raise ProviderError("could not open a browser for ChatGPT sign-in")
        deadline = time.monotonic() + timeout_s
        while not callback and time.monotonic() < deadline:
            server.timeout = min(1.0, max(0.1, deadline - time.monotonic()))
            server.handle_request()
    if not callback:
        raise ProviderError("ChatGPT sign-in timed out")
    if not secrets.compare_digest(callback.get("state", ""), state):
        raise ProviderError("ChatGPT sign-in state did not match")
    if callback.get("error"):
        raise ProviderError("ChatGPT sign-in was not approved")
    issued_id = callback.get("client_id") or (str(existing["client_id"]) if existing else "")
    if not issued_id or issued_id == "dynamic_agent_client":
        raise ProviderError("ChatGPT did not complete client registration")
    if existing and issued_id != existing["client_id"]:
        raise ProviderError("ChatGPT returned a different client registration")
    if not callback.get("code"):
        raise ProviderError("ChatGPT sign-in returned no authorization code")
    tokens = _request_json(
        f"{OPENAI_AUTH}/api/accounts/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": issued_id,
            "code": callback["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "resource": OPENAI_RESOURCE,
        },
    )
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str):
        raise ProviderError("ChatGPT returned no identity token")
    try:
        jwks = jwt.PyJWKClient(f"{OPENAI_AUTH}/.well-known/jwks.json")
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        identity = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=issued_id,
            issuer=OPENAI_AUTH,
            leeway=5,
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as error:
        raise ProviderError("ChatGPT identity token could not be verified") from error
    if identity.get("nonce") != nonce:
        raise ProviderError("ChatGPT identity nonce did not match")
    if existing and identity.get("sub") != existing["subject"]:
        raise ProviderError("ChatGPT returned a different account; sign out before switching")
    scopes = str(tokens.get("scope") or "").split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise ProviderError("ChatGPT plan use was not granted")
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ProviderError("ChatGPT returned incomplete credentials")
    credentials = {
        "client_id": issued_id,
        "subject": identity["sub"],
        "id_token": id_token,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "scopes": scopes,
        "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
    }
    _save_private(CHATGPT_FILE, json.dumps(credentials))


def logout_chatgpt() -> bool:
    credentials = _credentials()
    revoked = False
    try:
        discovery = _request_json(f"{OPENAI_AUTH}/.well-known/openid-configuration")
        endpoint = str(discovery.get("revocation_endpoint") or "")
        if not endpoint.startswith(f"{OPENAI_AUTH}/"):
            raise ProviderError("ChatGPT revocation endpoint is unavailable")
        _request_json(
            endpoint,
            {
                "token": str(credentials["refresh_token"]),
                "token_type_hint": "refresh_token",
                "client_id": str(credentials["client_id"]),
            },
        )
        revoked = True
    except ProviderError:
        pass
    CHATGPT_FILE.unlink(missing_ok=True)
    return revoked


def claude_console_token() -> str:
    if shutil.which("ant") is None:
        raise ProviderError("Anthropic ant CLI is missing; install it before browser login")
    try:
        result = subprocess.run(
            ["ant", "auth", "print-credentials", "--access-token"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_ant_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProviderError("could not read Claude Console login") from error
    token = result.stdout.strip()
    if result.returncode or not token:
        raise ProviderError("Claude Console is not connected; run 'ofag auth login claude'")
    return token


def login_claude() -> None:
    if shutil.which("ant") is None:
        raise ProviderError("Anthropic ant CLI is missing; install it before browser login")
    result = subprocess.run(["ant", "auth", "login"], check=False, env=_ant_env())
    if result.returncode:
        raise ProviderError("Claude Console sign-in did not complete")
    claude_console_token()


def logout_claude() -> None:
    if shutil.which("ant") is None:
        raise ProviderError("Anthropic ant CLI is missing")
    result = subprocess.run(["ant", "auth", "logout"], check=False, env=_ant_env())
    if result.returncode:
        raise ProviderError("Claude Console sign-out failed")


def _ant_env() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("ANTHROPIC_API_KEY", None)
    environment.pop("ANTHROPIC_AUTH_TOKEN", None)
    return environment
