"""OAuth callback relay for ChatGPT authentication."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

DEFAULT_CODEX_CALLBACK_URL: str = "http://127.0.0.1:1455/auth/callback"


def extract_expected_redirect_uri(auth_url: str) -> str | None:
    """Extract the redirect_uri parameter from an OAuth auth URL."""
    parsed = urlparse(auth_url)
    if parsed.scheme not in {"http", "https"}:
        return None

    query = parse_qs(parsed.query)
    values = query.get("redirect_uri")
    if not values:
        return None

    redirect_uri = values[0].strip()
    if not redirect_uri:
        return None

    target = urlparse(redirect_uri)
    if target.scheme not in {"http", "https"} or not target.netloc:
        return None

    return redirect_uri


def build_callback_replay_url(expected_redirect_uri: str | None, callback_url: str) -> str:
    """Build a URL to replay the OAuth callback to Codex.

    Raises ValueError if the callback URL is invalid or missing required parameters.
    """
    raw = callback_url.strip()
    parsed_callback = urlparse(raw)

    if parsed_callback.scheme not in {"http", "https"} or not parsed_callback.netloc:
        raise ValueError("Invalid callback URL. Paste the full redirect URL from your browser.")

    callback_query = parse_qs(parsed_callback.query)
    has_success = "code" in callback_query and "state" in callback_query
    has_error = "error" in callback_query and "state" in callback_query

    if not has_success and not has_error:
        raise ValueError("Callback URL is missing required auth parameters.")

    destination = urlparse(expected_redirect_uri or DEFAULT_CODEX_CALLBACK_URL)
    if destination.scheme not in {"http", "https"} or not destination.netloc:
        raise ValueError("Stored callback destination is invalid. Run /auth login again.")

    filtered_query: list[tuple[str, str]] = []
    for key in ("code", "state", "error", "error_description"):
        values = callback_query.get(key)
        if not values:
            continue
        for value in values:
            filtered_query.append((key, value))

    query = urlencode(filtered_query, doseq=True)
    path = destination.path or "/auth/callback"
    return urlunparse((destination.scheme, destination.netloc, path, "", query, ""))


async def replay_callback_to_codex(replay_url: str) -> None:
    """Replay the OAuth callback to Codex's local callback endpoint."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(replay_url, follow_redirects=False)
        if response.status_code >= 400:
            response.raise_for_status()
