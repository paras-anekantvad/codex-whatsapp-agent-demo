"""Shared Pydantic models for the WhatsApp Codex agent."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InboundMessage(BaseModel):
    """Inbound WhatsApp message from sidecar."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_id: str = Field(alias="from")
    from_identity: str | None = None
    text: str
    message_id: str | None = None
    from_me: bool = False
    is_group: bool = False
    self_jid: str | None = None


class PendingLogin(BaseModel):
    """Pending OAuth login state."""

    model_config = ConfigDict(extra="forbid")

    login_id: str
    auth_url: str | None = None
    expected_redirect_uri: str | None = None


class ChatResponse(BaseModel):
    """Response from chat service."""

    model_config = ConfigDict(extra="forbid")

    text: str


class TurnResult(BaseModel):
    """Result from a Codex turn execution."""

    model_config = ConfigDict(extra="forbid")

    text: str
    status: str
    blocked_item_type: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(extra="forbid")

    status: str


class InboundAcceptedResponse(BaseModel):
    """Response for accepted inbound message."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
