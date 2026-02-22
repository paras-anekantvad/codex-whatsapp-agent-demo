"""Typed wrapper around the Codex app-server SDK."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from codex_app_server_client import AsyncCodexClient
from codex_app_server_client.thread import AsyncThread, EventAction
from codex_app_server_client.types.auth import LoginAccountParams
from codex_app_server_client.types.common import ApprovalPolicySimple, ReadOnlySandboxPolicy
from codex_app_server_client.types.events import ItemCompletedEvent, ThreadEvent
from codex_app_server_client.types.threads import (
    ThreadCompactStartParams,
    ThreadListParams,
    ThreadResumeParams,
    ThreadStartParams,
)

from app.models import TurnResult
from app.policy import is_allowed_item_type

logger = logging.getLogger(__name__)


class CodexAppServerClient:
    """Wrapper around the Codex SDK with typed return values."""

    def __init__(
        self,
        codex_bin: str,
        client_name: str,
        model: str,
        cwd: str | None,
    ) -> None:
        self._model = model
        self._cwd = cwd

        self._client = AsyncCodexClient(
            codex_bin=codex_bin,
            client_name=client_name,
            client_title="Codex WhatsApp Agent",
            client_version="0.1.0",
            experimental_api=True,
            env=os.environ.copy(),
        )
        self._started = False

    async def start(self) -> None:
        """Start the Codex subprocess."""
        if self._started:
            return
        await self._client.start()
        self._started = True

    async def restart(self) -> None:
        """Restart the Codex subprocess."""
        if not self._started:
            await self.start()
            return
        await self._client.restart()
        self._started = True

    async def close(self) -> None:
        """Close the Codex subprocess."""
        await self._client.close()
        self._started = False

    async def thread_start(self, title: str | None = None) -> dict[str, Any]:
        """Start a new thread."""
        params = ThreadStartParams(
            model=self._model,
            approval_policy=ApprovalPolicySimple.NEVER,
            cwd=str(Path(self._cwd)) if self._cwd else None,
        )
        result = await self._client.thread_start(params)
        thread_dict: dict[str, Any] = result.thread.model_dump(by_alias=True, exclude_none=True)

        if title:
            try:
                await self._client.thread_set_name(result.thread.id, title)
            except Exception:
                logger.exception("Failed to set thread name")

        return thread_dict

    async def thread_resume(self, thread_id: str) -> dict[str, Any]:
        """Resume an existing thread."""
        result = await self._client.thread_resume(
            ThreadResumeParams(thread_id=thread_id, approval_policy=ApprovalPolicySimple.NEVER)
        )
        return dict(result.thread.model_dump(by_alias=True, exclude_none=True))

    async def thread_list(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent threads."""
        result = await self._client.thread_list(ThreadListParams(cursor=None, limit=limit, sort_key="updated_at"))
        return [dict(thread.model_dump(by_alias=True, exclude_none=True)) for thread in result.data]

    async def thread_compact_start(self, thread_id: str) -> None:
        """Start compaction for a thread."""
        params = ThreadCompactStartParams(thread_id=thread_id)
        await self._client.thread_compact_start(params)

    async def account_read(self, refresh_token: bool = False) -> dict[str, Any]:
        """Read account information."""
        result = await self._client.account_read(refresh_token=refresh_token)
        return dict(result.model_dump(by_alias=True, exclude_none=True))

    async def account_login_start_chatgpt(self) -> dict[str, Any]:
        """Start ChatGPT login flow."""
        return dict(await self._client.account_login_start(LoginAccountParams(type="chatgpt")))

    async def account_login_cancel(self, login_id: str) -> None:
        """Cancel a pending login."""
        await self._client.account_login_cancel(login_id)

    async def run_turn(
        self,
        thread_id: str,
        text: str,
        developer_instructions: str,
        timeout_s: float = 240,
    ) -> TurnResult:
        """Run a conversation turn with policy enforcement."""
        blocked_item_type: str | None = None

        def on_event(method: str, event: ThreadEvent) -> EventAction | None:
            nonlocal blocked_item_type
            if isinstance(event, ItemCompletedEvent):
                item = event.item if isinstance(event.item, dict) else {}
                item_type = item.get("type")
                if isinstance(item_type, str) and not is_allowed_item_type(item_type):
                    blocked_item_type = item_type
                    return EventAction.INTERRUPT
            return None

        thread = AsyncThread(client=self._client, thread_id=thread_id)
        sdk_result = await thread.run(
            text,
            model=self._model,
            on_event=on_event,
            timeout_s=timeout_s,
            approval_policy=ApprovalPolicySimple.NEVER,
            sandbox_policy=ReadOnlySandboxPolicy(),
        )

        if blocked_item_type:
            msg = (
                "I can only do chat and research (web search + URL fetch). This request attempted a disallowed action."
            )
            return TurnResult(
                text=msg,
                status=sdk_result.status,
                blocked_item_type=blocked_item_type,
            )

        if sdk_result.final_response:
            return TurnResult(
                text=sdk_result.final_response,
                status=sdk_result.status,
                blocked_item_type=None,
            )

        fallback = "I could not produce a response for that request. Please try rephrasing it."
        return TurnResult(text=fallback, status=sdk_result.status, blocked_item_type=None)
