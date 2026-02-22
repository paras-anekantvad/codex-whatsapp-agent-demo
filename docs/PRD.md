# WhatsApp Codex Agent — Product Requirements Document

## Overview

A single-container WhatsApp assistant that connects chat messages to Codex app-server with a research-only interaction model. Users interact via slash commands to manage sessions and authentication, while the system enforces strict safety policies that prevent code execution and file modifications.

## Problem Statement

Users need a way to access Codex's research and Q&A capabilities from WhatsApp without exposing dangerous operations like command execution or file system access. The system must:

- Provide a familiar chat interface on WhatsApp
- Maintain conversation sessions across restarts
- Support ChatGPT authentication via manual OAuth relay
- Enforce research-only behavior at multiple layers
- Control who can interact with the bot

## User Experience

### Slash Commands

| Command | Example | Description |
|---------|---------|-------------|
| `/help` | `/help` | Display available commands |
| `/new` | `/new Research topic` | Start a new session with optional title |
| `/sessions` | `/sessions 10` | List recent sessions (default: 5, max: 20) |
| `/resume` | `/resume 3` or `/resume thr_abc123` | Resume session by index or ID |
| `/compact` | `/compact` | Compact current session to reduce context |
| `/auth status` | `/auth status` | Check authentication state |
| `/auth login` | `/auth login` | Start ChatGPT OAuth flow |
| `/auth complete` | `/auth complete <callback_url>` | Complete OAuth with browser redirect URL |
| `/auth cancel` | `/auth cancel` | Cancel pending login |

### Conversation Flow

1. User sends a message to the WhatsApp bot
2. System checks access policy (self_chat or approved_senders)
3. If no active session, creates one automatically
4. Message is processed by Codex with research-only constraints
5. Response is chunked (max 3000 chars) and sent back via WhatsApp

### Error Recovery

- **Thread not found**: Automatically creates new session and retries once
- **Internal errors**: User receives friendly error message, can retry

## Access Control

### `self_chat` Mode (Default)

Only processes messages where the sender identity matches the bot's own WhatsApp identity (`self_jid`). Used for personal assistant scenarios where you message yourself.

### `approved_senders` Mode

Only processes messages from phone numbers in the allowlist. Configure via `WHATSAPP_APPROVED_NUMBERS` environment variable (comma or newline separated).

### Common Rules

- **Groups are always ignored** — No group chat support
- **Own outbound messages ignored** — In `approved_senders` mode, `from_me=true` messages are skipped
- **Sidecar authentication** — Optional shared secret between sidecar and orchestrator

## Safety Model

### Three-Layer Enforcement

1. **System Prompt**: Instructs the model to only perform research and Q&A, never execute commands or modify files

2. **Item Type Filter**: Only allows safe operation types:
   - `userMessage`, `agentMessage` — Chat messages
   - `plan`, `reasoning` — Model thinking
   - `webSearch` — Web research
   - `contextCompaction`, `compacted` — Context management

3. **Approval Auto-Decline**: Any server approval requests are automatically rejected

### Blocked Operations

- Command/shell execution
- File creation, modification, or deletion
- MCP tool calls
- Any operation requiring user approval

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Container                         │
│                                                                 │
│  ┌─────────────────────┐      ┌─────────────────────────────┐  │
│  │   Node.js Sidecar   │      │    Python Orchestrator      │  │
│  │     (Baileys)       │      │        (FastAPI)            │  │
│  │                     │      │                             │  │
│  │  • QR code pairing  │ HTTP │  • Access policy gate       │  │
│  │  • Socket lifecycle │─────▶│  • Slash command routing    │  │
│  │  • Message normali- │      │  • Session management       │  │
│  │    zation           │◀─────│  • Auth relay               │  │
│  │  • Send/receive     │      │                             │  │
│  └─────────────────────┘      └──────────────┬──────────────┘  │
│           │                                  │                  │
│           │                                  │ stdio JSON-RPC   │
│           │                                  ▼                  │
│           │                   ┌─────────────────────────────┐  │
│           │                   │   Codex App-Server (SDK)    │  │
│           │                   │                             │  │
│           │                   │  • Thread management        │  │
│           │                   │  • Turn execution           │  │
│           │                   │  • Policy enforcement       │  │
│           │                   └─────────────────────────────┘  │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 /app/data (mounted volume)               │   │
│  │  • baileys-auth/  — WhatsApp credentials                 │   │
│  │  • state.db       — SQLite (sessions, auth state)        │   │
│  │  • home/.codex/   — Codex authentication                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| Sidecar | `sidecar/src/` | WhatsApp protocol, Baileys socket, message I/O |
| Orchestrator | `src/app/main.py` | HTTP endpoints, access policy, request routing |
| Chat Service | `src/app/service.py` | Command handling, session logic, turn execution |
| Codex Client | `src/app/codex_client.py` | SDK wrapper, policy enforcement |
| Store | `src/app/store.py` | SQLite persistence |

## Data Model

### SQLite Schema (`data/state.db`)

```sql
-- Chat to thread mapping
CREATE TABLE chat_sessions (
    chat_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Pending OAuth login state
CREATE TABLE auth_login_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    login_id TEXT,
    auth_url TEXT,
    expected_redirect_uri TEXT,
    updated_at INTEGER NOT NULL
);
```

### Filesystem Persistence

| Path | Purpose |
|------|---------|
| `data/baileys-auth/` | WhatsApp multi-device credentials |
| `data/state.db` | Application state (sessions, auth) |
| `data/home/.codex/` | Codex CLI authentication |

## API Reference

### Python Orchestrator

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Returns `{"status": "ok"}` |
| `/whatsapp/inbound` | POST | Receives messages from sidecar |

### Node.js Sidecar

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Returns `{"status": "ok", "connected": bool}` |
| `/send` | POST | Send message: `{"to": "...", "text": "..."}` |

### Authentication

Both endpoints accept optional `X-Sidecar-Secret` header when `SIDECAR_SHARED_SECRET` is configured.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_HOST` | `0.0.0.0` | FastAPI bind address |
| `APP_PORT` | `8000` | FastAPI port |
| `SIDECAR_PORT` | `3001` | Sidecar port |
| `SIDECAR_URL` | `http://127.0.0.1:3001` | Sidecar base URL |
| `SIDECAR_SHARED_SECRET` | — | Optional auth between components |
| `WHATSAPP_ACCESS_MODE` | `self_chat` | `self_chat` or `approved_senders` |
| `WHATSAPP_APPROVED_NUMBERS` | — | Comma-separated phone allowlist |
| `CODEX_BIN` | `codex` | Path to Codex binary |
| `CODEX_MODEL` | `gpt-5.3-codex` | Model identifier |
| `CODEX_CWD` | — | Working directory for Codex |
| `DATABASE_PATH` | `data/state.db` | SQLite database path |

## Deployment

### Docker

```bash
# Build (from parent directory containing both repos)
docker build -f codex-whatsapp-agent-demo/Dockerfile -t codex-whatsapp-agent .

# Run
docker run -d \
  --name codex-whatsapp \
  -p 8000:8000 \
  -p 3001:3001 \
  -v $(pwd)/data:/app/data \
  -e WHATSAPP_ACCESS_MODE=self_chat \
  -e CODEX_MODEL=gpt-5.3-codex \
  codex-whatsapp-agent
```

### First-Time Setup

1. Start container and watch logs for QR code
2. Scan QR code with WhatsApp mobile app
3. Send `/auth login` to start Codex authentication
4. Complete OAuth flow and send `/auth complete <url>`
5. Verify with `/auth status`

### Data Persistence

Mount `/app/data` to preserve:
- WhatsApp session (no re-pairing needed)
- Chat-to-thread mappings
- Codex authentication

## Limitations & Risks

| Issue | Impact | Mitigation |
|-------|--------|------------|
| Self-chat decrypt failures | Some messages dropped | Retry; Baileys/libsignal instability |
| Stale thread IDs | "Thread not found" errors | Auto-recovery: create new thread, retry |
| Single account model | One bot identity | By design; no multi-tenant support |
| OAuth relay is manual | User must copy URL | Security tradeoff; no exposed callback |
| 3000 char message limit | Long responses chunked | WhatsApp platform constraint |
