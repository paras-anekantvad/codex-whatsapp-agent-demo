# AGENTS.md — WhatsApp Codex Agent

## Overview
WhatsApp bridge for Codex app-server with chat/research-only behavior. Single-container deployment with Node.js sidecar (Baileys) and Python FastAPI orchestrator.

Package name: `codex-whatsapp-agent`
Python baseline: 3.12

## Setup
```bash
make install   # or: uv sync --dev
```

## Dev Commands

Use the Makefile (preferred):
```bash
make install      # uv sync --dev
make check        # run all quality gates
make pre-commit   # alias for check
make test         # uv run pytest -q
make lint         # uv run ruff check .
make format       # uv run ruff format --check .
make type-check   # uv run mypy --strict src tests
make fix          # auto-fix formatting and lint
make clean        # remove caches and .venv
make dev          # run dev server
```

Or run commands directly:
```bash
uv run pytest -q                     # run tests
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run mypy --strict src tests       # typecheck
node --check sidecar/src/*.js        # verify sidecar JS
```

## Architecture

### Package Layout
```
src/app/
├── main.py           # FastAPI app, /health, /whatsapp/inbound, access policy
├── service.py        # ChatService, slash command handlers, turn execution
├── codex_client.py   # SDK wrapper (CodexAppServerClient), policy enforcement
├── store.py          # SQLite persistence (SessionStore)
├── config.py         # Settings via pydantic-settings
├── models.py         # Shared Pydantic models (InboundMessage, ChatResponse, etc.)
├── policy.py         # ALLOWED_ITEM_TYPES, is_allowed_item_type()
├── auth_relay.py     # OAuth callback URL parsing and replay
├── command_parser.py # SlashCommand model, parse_slash_command()
├── system_prompt.py  # RESEARCH_ONLY_SYSTEM_PROMPT constant
└── whatsapp_sidecar.py  # HTTP client for sidecar /send endpoint

sidecar/src/
├── index.js          # Express server, Baileys socket, message forwarding
└── normalizers.js    # JID normalization, text extraction

tests/
├── test_command_parser.py
├── test_policy.py
├── test_auth_relay.py
├── test_service_auth_complete.py
└── test_group_scope.py
```

### Key Dependencies
- `codex-app-server-client` — Local SDK at `../codex-app-server-client-sdk`
- `fastapi`, `uvicorn` — HTTP server
- `pydantic`, `pydantic-settings` — Config and models
- `aiosqlite` — Async SQLite
- `httpx` — HTTP client

## Key Design Decisions

1. **Pydantic-first**: All I/O boundaries use Pydantic v2 models with `extra="forbid"`. No raw dicts in business logic.

2. **Strict typing**: `mypy --strict` enforced. All functions fully annotated.

3. **SDK-backed Codex client**: Uses `codex-app-server-client` SDK, not raw JSON-RPC. The SDK handles protocol details.

4. **Research-only policy**: Only safe item types allowed (`userMessage`, `agentMessage`, `reasoning`, `webSearch`, etc.). Command execution and file changes are blocked.

5. **Access modes**: `self_chat` (only self messages) or `approved_senders` (allowlist). Groups always rejected.

6. **Sidecar separation**: Node.js sidecar handles WhatsApp protocol. Python handles business logic. Don't modify sidecar unless necessary.

## Coding Guidelines

- **Type annotations**: Complete type hints on all functions. Use `str | None` not `Optional[str]`.
- **Pydantic models**: Use `ConfigDict(extra="forbid")` for strict validation. Use `Field(alias="...")` for wire format.
- **Linting**: ruff with E, W, F, I, B, C4, UP rules. Line length 120.
- **Imports**: Use `from __future__ import annotations` in all modules.
- **Error handling**: Return `ChatResponse` with error message, don't raise to user.
- **Async**: All service methods are async. Use `asyncio.Lock` for per-chat serialization.

## Testing

- Tests in `tests/` directory
- Run with `make test` or `uv run pytest -q`
- Use `tmp_path` fixture for SQLite store tests
- Mock external calls with `monkeypatch`
- Test file naming: `test_<module>.py`

## Before Committing

Always run:
```bash
make check
```

This runs format check, lint, type-check, tests, and sidecar JS verification.
