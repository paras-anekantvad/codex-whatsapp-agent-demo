"""Chat service handling message processing and commands."""

from __future__ import annotations

import asyncio
from typing import Any

from app.auth_relay import (
    build_callback_replay_url,
    extract_expected_redirect_uri,
    replay_callback_to_codex,
)
from app.codex_client import CodexAppServerClient
from app.command_parser import SlashCommand, parse_slash_command
from app.models import ChatResponse
from app.store import SessionStore
from app.system_prompt import RESEARCH_ONLY_SYSTEM_PROMPT


class ChatService:
    """Service for handling chat messages and commands."""

    def __init__(self, store: SessionStore, codex: CodexAppServerClient) -> None:
        self._store = store
        self._codex = codex

    async def handle_message(self, chat_id: str, text: str) -> ChatResponse:
        """Handle an inbound message, routing to command or turn execution."""
        command = parse_slash_command(text)
        if command:
            return await self._handle_command(chat_id, command)

        thread_id = await self._store.get_thread_for_chat(chat_id)
        if not thread_id:
            thread = await self._codex.thread_start()
            thread_id = thread.get("id")
            if not isinstance(thread_id, str):
                return ChatResponse(text="Could not create a new session.")
            await self._store.set_thread_for_chat(chat_id, thread_id)

        for attempt in range(2):
            try:
                result = await self._codex.run_turn(
                    thread_id=thread_id,
                    text=text,
                    developer_instructions=RESEARCH_ONLY_SYSTEM_PROMPT,
                )
                break
            except RuntimeError as exc:
                if not _is_thread_not_found_error(exc):
                    raise
                if attempt == 1:
                    return ChatResponse(text="Session expired and could not be recovered. Send /new and try again.")
                thread = await self._codex.thread_start()
                thread_id = thread.get("id")
                if not isinstance(thread_id, str):
                    return ChatResponse(text="Could not create a new session.")
                await self._store.set_thread_for_chat(chat_id, thread_id)

        return ChatResponse(text=result.text)

    async def _handle_command(self, chat_id: str, command: SlashCommand) -> ChatResponse:
        """Handle a slash command."""
        if command.name == "help":
            return ChatResponse(
                text=(
                    "Available commands:\n"
                    "/new [title]\n"
                    "/sessions [limit]\n"
                    "/resume <thread_id|index>\n"
                    "/compact [instructions]\n"
                    "/auth status|login|complete|cancel [login_id]\n"
                    "/help"
                )
            )

        if command.name == "new":
            title = command.args.strip() or None
            thread = await self._codex.thread_start(title=title)
            thread_id = thread.get("id")
            if not isinstance(thread_id, str):
                return ChatResponse(text="Failed to start a new session.")
            await self._store.set_thread_for_chat(chat_id, thread_id)
            return ChatResponse(text=f"Started new session: `{thread_id}`")

        if command.name == "sessions":
            limit = _parse_limit(command.args, default=5, max_value=20)
            threads = await self._codex.thread_list(limit=limit)
            if not threads:
                return ChatResponse(text="No sessions found.")
            lines = ["Sessions:"]
            for idx, thread in enumerate(threads, start=1):
                thread_id = thread.get("id", "unknown")
                preview = str(thread.get("preview", "")).strip().replace("\n", " ")
                preview_part = f" — {preview[:80]}" if preview else ""
                lines.append(f"{idx}. `{thread_id}`{preview_part}")
            return ChatResponse(text="\n".join(lines))

        if command.name == "resume":
            arg = command.args.strip()
            if not arg:
                return ChatResponse(text="Usage: /resume <thread_id|index>")

            resume_thread_id: str | None = None
            if arg.isdigit():
                idx = int(arg)
                if idx <= 0:
                    return ChatResponse(text="Index must be 1 or higher.")
                threads = await self._codex.thread_list(limit=max(20, idx))
                if idx > len(threads):
                    return ChatResponse(text=f"Only {len(threads)} sessions available in this page.")
                candidate = threads[idx - 1].get("id")
                if isinstance(candidate, str):
                    resume_thread_id = candidate
            else:
                resume_thread_id = arg

            if not resume_thread_id:
                return ChatResponse(text="Could not resolve a session to resume.")

            await self._codex.thread_resume(resume_thread_id)
            await self._store.set_thread_for_chat(chat_id, resume_thread_id)
            return ChatResponse(text=f"Resumed session: `{resume_thread_id}`")

        if command.name == "compact":
            thread_id = await self._store.get_thread_for_chat(chat_id)
            if not thread_id:
                return ChatResponse(text="No active session. Use /new first.")
            await self._codex.thread_compact_start(thread_id)
            return ChatResponse(text="Compaction started for the active session.")

        if command.name == "auth":
            return await self._handle_auth_command(command)

        return ChatResponse(text="Unknown command. Send /help.")

    async def _handle_auth_command(self, command: SlashCommand) -> ChatResponse:
        """Handle /auth subcommands."""
        args = command.args.split(maxsplit=1)
        action = args[0].lower() if args else "status"
        rest = args[1].strip() if len(args) > 1 else ""

        if action == "status":
            info = await self._codex.account_read(refresh_token=True)
            account = info.get("account")
            if not account:
                return ChatResponse(text="Auth: not logged in. Run /auth login and try again.")
            account_type = account.get("type", "unknown")
            email = account.get("email")
            plan_type = account.get("planType")
            extra: list[str] = []
            if email:
                extra.append(str(email))
            if plan_type:
                extra.append(f"plan={plan_type}")
            suffix = f" ({', '.join(extra)})" if extra else ""
            return ChatResponse(text=f"Auth: {account_type}{suffix}")

        if action == "login":
            result = await self._codex.account_login_start_chatgpt()
            login_id = result.get("loginId")
            auth_url = result.get("authUrl")
            if not isinstance(login_id, str) or not isinstance(auth_url, str):
                return ChatResponse(text="Login started but auth details were incomplete.")

            await self._store.set_pending_login(
                login_id=login_id,
                auth_url=auth_url,
                expected_redirect_uri=extract_expected_redirect_uri(auth_url),
            )
            return ChatResponse(
                text=(
                    "1) Open this URL and sign in: "
                    f"{auth_url}\n"
                    "2) Copy the final browser redirect URL and send: "
                    "/auth complete <full_url>"
                )
            )

        if action == "complete":
            callback_url = rest
            if not callback_url:
                return ChatResponse(text="Usage: /auth complete <full_url>")

            pending = await self._store.get_pending_login()
            if not pending:
                return ChatResponse(text="No pending login found. Run /auth login first.")

            try:
                replay_url = build_callback_replay_url(pending.expected_redirect_uri, callback_url)
            except ValueError as exc:
                return ChatResponse(text=str(exc))

            try:
                await replay_callback_to_codex(replay_url)
            except Exception:
                return ChatResponse(text="Could not complete login from that callback URL. Try /auth login again.")

            try:
                await self._codex.restart()
            except Exception:
                return ChatResponse(text="Callback relayed; auth may be delayed, run /auth status in 10-20s.")

            account = await self._wait_for_chatgpt_login()
            if account:
                await self._store.clear_pending_login()
                email = account.get("email")
                plan_type = account.get("planType")
                details: list[str] = []
                if email:
                    details.append(str(email))
                if plan_type:
                    details.append(f"plan={plan_type}")
                suffix = f" ({', '.join(details)})" if details else ""
                return ChatResponse(text=f"Sign-in completed: chatgpt{suffix}")

            return ChatResponse(text="Callback relayed; auth may be delayed, run /auth status in 10-20s.")

        if action == "apikey":
            return ChatResponse(text="API key via WhatsApp is disabled. Use OPENAI_API_KEY env var.")

        if action == "cancel":
            pending = await self._store.get_pending_login()
            login_id = rest or (pending.login_id if pending else None)
            if not login_id:
                return ChatResponse(text="No pending login id found. Use /auth login first.")
            await self._codex.account_login_cancel(login_id)
            await self._store.clear_pending_login()
            return ChatResponse(text=f"Cancelled login: {login_id}")

        return ChatResponse(text="Usage: /auth status|login|complete|cancel [login_id]")

    async def _wait_for_chatgpt_login(
        self,
        timeout_seconds: float = 12,
        interval_seconds: float = 0.6,
    ) -> dict[str, Any] | None:
        """Poll for ChatGPT login completion."""
        elapsed = 0.0
        while elapsed <= timeout_seconds:
            info = await self._codex.account_read(refresh_token=True)
            account = info.get("account")
            if isinstance(account, dict) and account.get("type") == "chatgpt":
                return account

            await asyncio.sleep(interval_seconds)
            elapsed += interval_seconds
        return None


def _parse_limit(raw: str, default: int, max_value: int) -> int:
    """Parse a limit argument with bounds checking."""
    value = raw.strip()
    if not value:
        return default
    if not value.isdigit():
        return default
    parsed = int(value)
    if parsed <= 0:
        return default
    return min(parsed, max_value)


def _is_thread_not_found_error(error: RuntimeError) -> bool:
    """Check if an error is a 'thread not found' error."""
    return "thread not found" in str(error).lower()
