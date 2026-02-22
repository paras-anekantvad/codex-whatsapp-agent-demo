"""Policy rules for allowed item types and auto-decline behavior."""

from __future__ import annotations

ALLOWED_ITEM_TYPES: frozenset[str] = frozenset(
    {
        "userMessage",
        "agentMessage",
        "plan",
        "reasoning",
        "webSearch",
        "contextCompaction",
        "compacted",
    }
)


def is_allowed_item_type(item_type: str) -> bool:
    """Check if an item type is allowed by the research-only policy."""
    return item_type in ALLOWED_ITEM_TYPES


def should_auto_decline_server_request(method: str) -> bool:
    """Check if a server request method should be auto-declined."""
    return method.endswith("/requestApproval")
