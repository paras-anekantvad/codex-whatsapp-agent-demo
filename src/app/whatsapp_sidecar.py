"""HTTP client for WhatsApp sidecar communication."""

from __future__ import annotations

import httpx


class WhatsAppSidecarClient:
    """Client for sending messages through the WhatsApp sidecar."""

    def __init__(self, base_url: str, shared_secret: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._shared_secret = shared_secret
        self._client = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def send_text(self, to: str, text: str) -> None:
        """Send a text message through the sidecar."""
        headers: dict[str, str] = {}
        if self._shared_secret:
            headers["x-sidecar-secret"] = self._shared_secret

        response = await self._client.post(
            f"{self._base_url}/send",
            json={"to": to, "text": text},
            headers=headers,
        )
        response.raise_for_status()
