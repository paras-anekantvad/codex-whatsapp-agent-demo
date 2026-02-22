"""SQLite persistence for session and auth state."""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from app.models import PendingLogin


class SessionStore:
    """SQLite-backed storage for chat sessions and auth state."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def init(self) -> None:
        """Initialize database schema."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    chat_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_login_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    login_id TEXT,
                    auth_url TEXT,
                    expected_redirect_uri TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            await self._ensure_auth_login_columns(db)
            await db.commit()

    async def _ensure_auth_login_columns(self, db: aiosqlite.Connection) -> None:
        """Ensure auth_login_state table has all required columns."""
        cursor = await db.execute("PRAGMA table_info(auth_login_state)")
        rows = await cursor.fetchall()
        columns = {row[1] for row in rows}

        if "auth_url" not in columns:
            await db.execute("ALTER TABLE auth_login_state ADD COLUMN auth_url TEXT")
        if "expected_redirect_uri" not in columns:
            await db.execute("ALTER TABLE auth_login_state ADD COLUMN expected_redirect_uri TEXT")

    async def get_thread_for_chat(self, chat_id: str) -> str | None:
        """Get the thread ID for a chat, or None if not found."""
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                "SELECT thread_id FROM chat_sessions WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            return str(row[0]) if row else None

    async def set_thread_for_chat(self, chat_id: str, thread_id: str) -> None:
        """Set the thread ID for a chat."""
        now = int(time.time())
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO chat_sessions(chat_id, thread_id, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    updated_at = excluded.updated_at
                """,
                (chat_id, thread_id, now),
            )
            await db.commit()

    async def set_pending_login(
        self,
        login_id: str,
        auth_url: str | None,
        expected_redirect_uri: str | None,
    ) -> None:
        """Store pending login state."""
        now = int(time.time())
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO auth_login_state(
                    id, login_id, auth_url, expected_redirect_uri, updated_at
                )
                VALUES(1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    login_id = excluded.login_id,
                    auth_url = excluded.auth_url,
                    expected_redirect_uri = excluded.expected_redirect_uri,
                    updated_at = excluded.updated_at
                """,
                (login_id, auth_url, expected_redirect_uri, now),
            )
            await db.commit()

    async def clear_pending_login(self) -> None:
        """Clear pending login state."""
        now = int(time.time())
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO auth_login_state(
                    id, login_id, auth_url, expected_redirect_uri, updated_at
                )
                VALUES(1, NULL, NULL, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    login_id = NULL,
                    auth_url = NULL,
                    expected_redirect_uri = NULL,
                    updated_at = excluded.updated_at
                """,
                (now,),
            )
            await db.commit()

    async def get_pending_login(self) -> PendingLogin | None:
        """Get pending login state, or None if not found."""
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """
                SELECT login_id, auth_url, expected_redirect_uri
                FROM auth_login_state
                WHERE id = 1
                """
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return PendingLogin(
                login_id=str(row[0]),
                auth_url=str(row[1]) if row[1] else None,
                expected_redirect_uri=str(row[2]) if row[2] else None,
            )
