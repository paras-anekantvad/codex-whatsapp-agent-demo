"""Tests for OAuth callback relay."""

import httpx
import pytest

from app.auth_relay import (
    build_callback_replay_url,
    extract_expected_redirect_uri,
    replay_callback_to_codex,
)


def test_extract_expected_redirect_uri_from_auth_url() -> None:
    auth_url = "https://chatgpt.com/login?x=1&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback"
    redirect_uri = extract_expected_redirect_uri(auth_url)
    assert redirect_uri == "http://localhost:1455/auth/callback"


def test_extract_expected_redirect_uri_returns_none_for_missing() -> None:
    auth_url = "https://chatgpt.com/login?x=1"
    assert extract_expected_redirect_uri(auth_url) is None


def test_extract_expected_redirect_uri_returns_none_for_invalid_scheme() -> None:
    auth_url = "ftp://chatgpt.com/login?redirect_uri=http://localhost:1455"
    assert extract_expected_redirect_uri(auth_url) is None


def test_build_callback_replay_url_uses_expected_destination() -> None:
    callback_url = "http://localhost:9999/auth/callback?code=abc&state=xyz"
    replay = build_callback_replay_url("http://127.0.0.1:1455/auth/callback", callback_url)
    assert replay == "http://127.0.0.1:1455/auth/callback?code=abc&state=xyz"


def test_build_callback_replay_url_rejects_missing_params() -> None:
    callback_url = "http://localhost:1455/auth/callback?foo=bar"
    with pytest.raises(ValueError, match="missing required auth parameters"):
        build_callback_replay_url("http://127.0.0.1:1455/auth/callback", callback_url)


def test_build_callback_replay_url_accepts_error_params() -> None:
    callback_url = "http://localhost:9999/auth/callback?error=access_denied&state=xyz"
    replay = build_callback_replay_url("http://127.0.0.1:1455/auth/callback", callback_url)
    assert "error=access_denied" in replay
    assert "state=xyz" in replay


def test_build_callback_replay_url_rejects_invalid_scheme() -> None:
    callback_url = "ftp://localhost/auth/callback?code=abc&state=xyz"
    with pytest.raises(ValueError, match="Invalid callback URL"):
        build_callback_replay_url("http://127.0.0.1:1455/auth/callback", callback_url)


@pytest.mark.asyncio
async def test_replay_callback_to_codex_accepts_302(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 302

        def raise_for_status(self) -> None:
            raise AssertionError("raise_for_status should not be called for 302")

    class _Client:
        def __init__(self, timeout: int) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object,
        ) -> bool:
            return False

        async def get(self, url: str, follow_redirects: bool = False) -> _Response:
            captured["url"] = url
            captured["follow_redirects"] = follow_redirects
            return _Response()

    monkeypatch.setattr("app.auth_relay.httpx.AsyncClient", _Client)

    await replay_callback_to_codex("http://localhost:1455/auth/callback?code=abc&state=xyz")

    assert captured["timeout"] == 15
    assert captured["follow_redirects"] is False


@pytest.mark.asyncio
async def test_replay_callback_to_codex_raises_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        status_code = 400

        def raise_for_status(self) -> None:
            request = httpx.Request("GET", "http://localhost:1455/auth/callback")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    class _Client:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object,
        ) -> bool:
            return False

        async def get(self, url: str, follow_redirects: bool = False) -> _Response:
            return _Response()

    monkeypatch.setattr("app.auth_relay.httpx.AsyncClient", _Client)

    with pytest.raises(httpx.HTTPStatusError):
        await replay_callback_to_codex("http://localhost:1455/auth/callback?code=abc&state=xyz")
