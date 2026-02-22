"""FastAPI application for WhatsApp Codex agent."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from app.codex_client import CodexAppServerClient
from app.config import Settings, get_settings
from app.models import HealthResponse, InboundAcceptedResponse, InboundMessage
from app.service import ChatService
from app.store import SessionStore
from app.whatsapp_sidecar import WhatsAppSidecarClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_SELF_CHAT_MODE = "self_chat"
_APPROVED_SENDERS_MODE = "approved_senders"


class _Container:
    """Dependency container for application state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.whatsapp_access_mode = _normalize_access_mode(settings.whatsapp_access_mode)
        self.store = SessionStore(settings.database_path)
        self.codex = CodexAppServerClient(
            codex_bin=settings.codex_bin,
            client_name=settings.codex_client_name,
            model=settings.codex_model,
            cwd=settings.codex_cwd,
        )
        self.sidecar = WhatsAppSidecarClient(
            base_url=settings.sidecar_url,
            shared_secret=settings.sidecar_shared_secret,
        )
        self.service = ChatService(store=self.store, codex=self.codex)
        self.chat_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.approved_sender_identities = _parse_approved_sender_identities(settings.whatsapp_approved_numbers)
        if self.whatsapp_access_mode == _APPROVED_SENDERS_MODE and not self.approved_sender_identities:
            logger.warning("No approved WhatsApp senders configured; inbound messages will be ignored")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    settings = get_settings()
    container = _Container(settings)
    app.state.container = container
    await container.store.init()
    await container.codex.start()
    logger.info("Application started")
    try:
        yield
    finally:
        await container.sidecar.close()
        await container.codex.close()
        logger.info("Application stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.post("/whatsapp/inbound")
async def whatsapp_inbound(
    payload: InboundMessage,
    x_sidecar_secret: str | None = Header(default=None),
) -> InboundAcceptedResponse:
    """Handle inbound WhatsApp message from sidecar."""
    container: _Container = app.state.container
    expected = container.settings.sidecar_shared_secret

    if expected and x_sidecar_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid sidecar secret")

    asyncio.create_task(_process_inbound(payload, container))
    return InboundAcceptedResponse(accepted=True)


async def _process_inbound(payload: InboundMessage, container: _Container) -> None:
    """Process an inbound message asynchronously."""
    allowed = _should_process_inbound(
        payload,
        access_mode=container.whatsapp_access_mode,
        approved_sender_identities=container.approved_sender_identities,
    )
    if not allowed:
        logger.info(
            "Ignoring inbound by access policy: mode=%s from=%s from_identity=%s from_me=%s self_jid=%s is_group=%s",
            container.whatsapp_access_mode,
            payload.from_id,
            payload.from_identity,
            payload.from_me,
            payload.self_jid,
            payload.is_group,
        )
        return

    chat_key = _normalize_jid(payload.from_id)
    reply_to = payload.from_id

    if (
        container.whatsapp_access_mode == _SELF_CHAT_MODE
        and payload.from_identity
        and payload.self_jid
        and _jid_identity(payload.from_identity) == _jid_identity(payload.self_jid)
    ):
        reply_to = payload.from_identity

    logger.info(
        "Processing inbound: mode=%s from=%s from_identity=%s from_me=%s reply_to=%s",
        container.whatsapp_access_mode,
        payload.from_id,
        payload.from_identity,
        payload.from_me,
        reply_to,
    )

    lock = container.chat_locks[chat_key]
    async with lock:
        try:
            response = await container.service.handle_message(chat_key, payload.text)
            chunks = _chunk_text(response.text)
            for chunk in chunks:
                await container.sidecar.send_text(reply_to, chunk)
        except Exception:
            logger.exception("Failed to handle inbound message")
            try:
                await container.sidecar.send_text(
                    reply_to,
                    "I hit an internal error while handling that message.",
                )
            except Exception:
                logger.exception("Failed to send error message to WhatsApp")


def _normalize_access_mode(value: str) -> str:
    """Normalize access mode to canonical form."""
    mode = value.strip().casefold()
    if mode == _APPROVED_SENDERS_MODE:
        return _APPROVED_SENDERS_MODE
    if mode != _SELF_CHAT_MODE:
        logger.warning("Invalid WHATSAPP_ACCESS_MODE=%r; defaulting to self_chat", value)
    return _SELF_CHAT_MODE


def _should_process_inbound(
    payload: InboundMessage,
    *,
    access_mode: str,
    approved_sender_identities: set[str],
) -> bool:
    """Determine if an inbound message should be processed."""
    sender_identity = payload.from_identity or payload.from_id

    if payload.is_group:
        return False

    if access_mode == _SELF_CHAT_MODE:
        if not payload.self_jid:
            return False
        return _jid_identity(sender_identity) == _jid_identity(payload.self_jid)

    if payload.from_me:
        return False

    if access_mode != _APPROVED_SENDERS_MODE:
        return False
    if not approved_sender_identities:
        return False
    return _jid_identity(sender_identity) in approved_sender_identities


def _normalize_jid(value: str) -> str:
    """Normalize a JID to canonical form."""
    clean = value.strip().casefold()
    if "@" not in clean:
        return clean
    local, domain = clean.split("@", 1)
    if ":" in local:
        local = local.split(":", 1)[0]
    return f"{local}@{domain}"


def _jid_identity(value: str) -> str:
    """Extract the identity (digits only) from a JID."""
    normalized = _normalize_jid(value)
    local = normalized.split("@", 1)[0]
    digits = re.sub(r"\D", "", local)
    return digits or local


def _iter_approved_number_values(value: str | list[str] | None) -> list[str]:
    """Iterate over approved number values, splitting on commas and newlines."""
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]

    parts: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[,\n]", str(raw)):
            clean = part.strip()
            if clean:
                parts.append(clean)
    return parts


def _parse_approved_sender_identities(value: str | list[str] | None) -> set[str]:
    """Parse approved sender identities from config value."""
    identities: set[str] = set()
    for raw in _iter_approved_number_values(value):
        if not raw:
            continue
        identities.add(_jid_identity(raw))
    return identities


def _chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """Split text into chunks for WhatsApp message limits."""
    clean = text.strip()
    if not clean:
        return ["I could not generate a response."]
    if len(clean) <= max_chars:
        return [clean]

    chunks: list[str] = []
    remaining = clean
    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
