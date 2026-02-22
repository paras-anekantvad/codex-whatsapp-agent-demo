"""Slash command parsing for WhatsApp messages."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SlashCommand(BaseModel):
    """Parsed slash command."""

    model_config = ConfigDict(extra="forbid")

    name: str
    args: str


def parse_slash_command(text: str) -> SlashCommand | None:
    """Parse a slash command from message text.

    Returns None if the text is not a slash command.
    """
    raw = text.strip()
    if not raw.startswith("/"):
        return None

    body = raw[1:]
    if not body:
        return None

    parts = body.split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return SlashCommand(name=name, args=args)
