"""Tests for auth command handling in ChatService."""

from typing import Any

import pytest

from app.service import ChatService
from app.store import SessionStore


class _FakeCodexForAuth:
    def __init__(self) -> None:
        self.account_reads = 0
        self.refresh_flags: list[bool] = []
        self.restart_calls = 0

    async def account_read(self, refresh_token: bool = False) -> dict[str, Any]:
        self.account_reads += 1
        self.refresh_flags.append(refresh_token)
        return {
            "account": {"type": "chatgpt", "email": "user@example.com", "planType": "pro"},
            "requiresOpenaiAuth": True,
        }

    async def restart(self) -> None:
        self.restart_calls += 1


@pytest.mark.asyncio
async def test_auth_complete_requires_pending_login(tmp_path: Any) -> None:
    store = SessionStore(tmp_path / "state.db")
    await store.init()
    service = ChatService(store=store, codex=_FakeCodexForAuth())  # type: ignore[arg-type]

    response = await service.handle_message(
        "chat-1",
        "/auth complete http://localhost:1455/auth/callback?code=abc&state=xyz",
    )

    assert "No pending login found" in response.text


@pytest.mark.asyncio
async def test_auth_complete_replays_callback_and_clears_pending(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path / "state.db")
    await store.init()
    await store.set_pending_login(
        login_id="login-1",
        auth_url="https://chatgpt.com/login?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback",
        expected_redirect_uri="http://localhost:1455/auth/callback",
    )

    captured: dict[str, str | None] = {"url": None}

    async def _fake_replay(url: str) -> None:
        captured["url"] = url

    monkeypatch.setattr("app.service.replay_callback_to_codex", _fake_replay)

    codex = _FakeCodexForAuth()
    service = ChatService(store=store, codex=codex)  # type: ignore[arg-type]
    response = await service.handle_message(
        "chat-1",
        "/auth complete https://example.com/final?code=abc&state=xyz",
    )

    assert captured["url"] == "http://localhost:1455/auth/callback?code=abc&state=xyz"
    assert "Sign-in completed: chatgpt" in response.text
    assert codex.restart_calls == 1
    assert True in codex.refresh_flags
    assert await store.get_pending_login() is None


@pytest.mark.asyncio
async def test_auth_complete_shows_delay_hint_when_auth_not_visible(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path / "state.db")
    await store.init()
    await store.set_pending_login(
        login_id="login-1",
        auth_url="https://chatgpt.com/login?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback",
        expected_redirect_uri="http://localhost:1455/auth/callback",
    )

    async def _fake_replay(_: str) -> None:
        return None

    monkeypatch.setattr("app.service.replay_callback_to_codex", _fake_replay)

    codex = _FakeCodexForAuth()
    service = ChatService(store=store, codex=codex)  # type: ignore[arg-type]

    async def _no_auth(
        timeout_seconds: float = 12,
        interval_seconds: float = 0.6,
    ) -> None:
        return None

    monkeypatch.setattr(service, "_wait_for_chatgpt_login", _no_auth)

    response = await service.handle_message(
        "chat-1",
        "/auth complete https://example.com/final?code=abc&state=xyz",
    )

    assert response.text == "Callback relayed; auth may be delayed, run /auth status in 10-20s."
    assert codex.restart_calls == 1
    assert await store.get_pending_login() is not None


@pytest.mark.asyncio
async def test_auth_status_uses_refresh_token(tmp_path: Any) -> None:
    store = SessionStore(tmp_path / "state.db")
    await store.init()
    codex = _FakeCodexForAuth()
    service = ChatService(store=store, codex=codex)  # type: ignore[arg-type]

    response = await service.handle_message("chat-1", "/auth status")

    assert response.text.startswith("Auth: chatgpt")
    assert codex.refresh_flags == [True]


@pytest.mark.asyncio
async def test_auth_status_shows_login_hint_when_account_missing(tmp_path: Any) -> None:
    class _NoAccountCodex(_FakeCodexForAuth):
        async def account_read(self, refresh_token: bool = False) -> dict[str, Any]:
            self.account_reads += 1
            self.refresh_flags.append(refresh_token)
            return {"account": None, "requiresOpenaiAuth": True}

    store = SessionStore(tmp_path / "state.db")
    await store.init()
    codex = _NoAccountCodex()
    service = ChatService(store=store, codex=codex)  # type: ignore[arg-type]

    response = await service.handle_message("chat-1", "/auth status")

    assert response.text == "Auth: not logged in. Run /auth login and try again."
