const fs = require("node:fs");
const path = require("node:path");
const express = require("express");
const axios = require("axios");
const pino = require("pino");
const qrcode = require("qrcode-terminal");

const { extractText, normalizeToJid } = require("./normalizers");

const logger = pino({ level: process.env.SIDECAR_LOG_LEVEL || "info" });
const app = express();
app.use(express.json({ limit: "1mb" }));

const port = Number(process.env.SIDECAR_PORT || 3001);
const pythonInboundUrl = process.env.PYTHON_INBOUND_URL || "http://127.0.0.1:8000/whatsapp/inbound";
const sharedSecret = process.env.SIDECAR_SHARED_SECRET || "";
const authDir = path.resolve(process.env.BAILEYS_AUTH_DIR || "./data/baileys-auth");
const mockMode = (process.env.WHATSAPP_MOCK || "false").toLowerCase() === "true";
const accessMode = String(process.env.WHATSAPP_ACCESS_MODE || "self_chat").trim().toLowerCase();
const outboundMessageTtlMs = 2 * 60 * 1000;
const inboundMessageTtlMs = 2 * 60 * 1000;
const credsPath = path.join(authDir, "creds.json");
const credsBackupPath = path.join(authDir, "creds.json.bak");

let socket = null;
let whatsappConnected = false;
let activeSocketId = 0;
let reconnectTimer = null;
let startQueue = Promise.resolve();
let credsSaveQueue = Promise.resolve();
const outboundMessageIds = new Map();
const inboundMessageKeys = new Map();
const lidToPnJids = new Map();

function normalizeBareJid(jid) {
  if (typeof jid !== "string") {
    return null;
  }
  const clean = jid.trim().toLowerCase();
  if (!clean) {
    return null;
  }
  const at = clean.indexOf("@");
  if (at < 0) {
    return clean;
  }
  const local = clean.slice(0, at).split(":", 1)[0];
  const domain = clean.slice(at + 1);
  return `${local}@${domain}`;
}

function getStatusCode(error) {
  return error?.output?.statusCode ?? error?.status;
}

function readCredsJsonRaw(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return null;
    }
    const stats = fs.statSync(filePath);
    if (!stats.isFile() || stats.size <= 1) {
      return null;
    }
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
}

function maybeRestoreCredsFromBackup() {
  try {
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      JSON.parse(raw);
      return;
    }

    const backupRaw = readCredsJsonRaw(credsBackupPath);
    if (!backupRaw) {
      return;
    }
    JSON.parse(backupRaw);
    fs.copyFileSync(credsBackupPath, credsPath);
    try {
      fs.chmodSync(credsPath, 0o600);
    } catch {
      // best effort
    }
    logger.warn({ credsPath }, "restored corrupted WhatsApp creds.json from backup");
  } catch {
    // ignore restore failure
  }
}

async function safeSaveCreds(saveCreds) {
  try {
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      try {
        JSON.parse(raw);
        fs.copyFileSync(credsPath, credsBackupPath);
        try {
          fs.chmodSync(credsBackupPath, 0o600);
        } catch {
          // best effort
        }
      } catch {
        // keep last good backup
      }
    }
  } catch {
    // ignore backup failures
  }

  try {
    await Promise.resolve(saveCreds());
    try {
      fs.chmodSync(credsPath, 0o600);
    } catch {
      // best effort
    }
  } catch (error) {
    logger.warn({ error: String(error) }, "failed saving WhatsApp creds");
  }
}

function enqueueSaveCreds(saveCreds) {
  credsSaveQueue = credsSaveQueue
    .then(() => safeSaveCreds(saveCreds))
    .catch((error) => {
      logger.warn({ error: String(error) }, "WhatsApp creds save queue error");
    });
}

async function clearBaileysAuthState() {
  try {
    const entries = await fs.promises.readdir(authDir, { withFileTypes: true });
    const shouldDelete = (name) => {
      if (name === "oauth.json") {
        return false;
      }
      if (name === "creds.json" || name === "creds.json.bak") {
        return true;
      }
      if (!name.endsWith(".json")) {
        return false;
      }
      return /^(app-state-sync|session|sender-key|pre-key)-/.test(name);
    };

    await Promise.all(
      entries.map(async (entry) => {
        if (!entry.isFile() || !shouldDelete(entry.name)) {
          return;
        }
        await fs.promises.rm(path.join(authDir, entry.name), { force: true });
      }),
    );
    logger.warn("Cleared WhatsApp auth state after loggedOut/401 disconnect");
  } catch (error) {
    logger.error({ error: String(error) }, "Failed to clear WhatsApp auth state");
  }
}

function pruneExpiringEntries(map) {
  const now = Date.now();
  for (const [key, expiresAt] of map) {
    if (expiresAt <= now) {
      map.delete(key);
    }
  }
}

function rememberOutboundMessageId(messageId) {
  if (!messageId) {
    return;
  }
  pruneExpiringEntries(outboundMessageIds);
  outboundMessageIds.set(messageId, Date.now() + outboundMessageTtlMs);
}

function isRecentOutboundMessageId(messageId) {
  if (!messageId) {
    return false;
  }
  pruneExpiringEntries(outboundMessageIds);
  const now = Date.now();
  const expiresAt = outboundMessageIds.get(messageId);
  if (!expiresAt || expiresAt <= now) {
    return false;
  }
  return true;
}

function rememberInboundMessage(remoteJid, messageId) {
  if (!remoteJid || !messageId) {
    return;
  }
  pruneExpiringEntries(inboundMessageKeys);
  inboundMessageKeys.set(`${remoteJid}:${messageId}`, Date.now() + inboundMessageTtlMs);
}

function isRecentInboundMessage(remoteJid, messageId) {
  if (!remoteJid || !messageId) {
    return false;
  }
  pruneExpiringEntries(inboundMessageKeys);
  const key = `${remoteJid}:${messageId}`;
  const expiresAt = inboundMessageKeys.get(key);
  return Boolean(expiresAt && expiresAt > Date.now());
}

function rememberLidToPnMapping(lidJid, pnJid) {
  const lid = normalizeBareJid(lidJid);
  const pn = normalizeBareJid(pnJid);
  if (!lid || !pn || !lid.endsWith("@lid")) {
    return;
  }
  lidToPnJids.set(lid, pn);
}

function resolveInboundSenderJid(jid) {
  const bare = normalizeBareJid(jid);
  if (!bare) {
    return null;
  }
  if (!bare.endsWith("@lid")) {
    return bare;
  }
  return lidToPnJids.get(bare) || bare;
}

function rememberMappingFromChatLike(record) {
  if (!record || typeof record !== "object") {
    return;
  }
  const lid = record.lid || record.lidJid;
  const jid = record.id || record.jid;
  rememberLidToPnMapping(lid, jid);
}

async function postInbound(payload) {
  const headers = {};
  if (sharedSecret) {
    headers["x-sidecar-secret"] = sharedSecret;
  }
  await axios.post(pythonInboundUrl, payload, { headers, timeout: 10000 });
}

function closeSocket(candidate) {
  try {
    candidate?.ws?.close();
  } catch {
    // ignore
  }
}

function scheduleReconnect(reason, delayMs) {
  if (mockMode) {
    return;
  }
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    queueStart(`reconnect:${reason}`);
  }, delayMs);
}

function queueStart(reason) {
  startQueue = startQueue
    .then(() => startBaileys(reason))
    .catch((error) => {
      logger.error({ error: String(error), reason }, "Failed to initialize Baileys sidecar");
      scheduleReconnect("start-failed", 1500);
    });
}

async function startBaileys(reason = "initial") {
  const baileys = require("@whiskeysockets/baileys");
  const makeWASocket = baileys.default;
  const {
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
    makeCacheableSignalKeyStore,
  } = baileys;

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  fs.mkdirSync(authDir, { recursive: true });
  maybeRestoreCredsFromBackup();

  const socketId = ++activeSocketId;
  whatsappConnected = false;
  closeSocket(socket);

  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion();
  const socketLogger = pino({ level: "silent" });
  const nextSocket = makeWASocket({
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, socketLogger),
    },
    version,
    printQRInTerminal: false,
    logger: socketLogger,
    browser: ["codex-whatsapp-agent", "docker", "0.1.0"],
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });
  socket = nextSocket;

  logger.info({ reason }, "Starting WhatsApp socket");

  let reconnectScheduled = false;
  const scheduleForSocket = (closeReason, delayMs) => {
    if (reconnectScheduled || socketId !== activeSocketId) {
      return;
    }
    reconnectScheduled = true;
    scheduleReconnect(closeReason, delayMs);
  };

  nextSocket.ev.on("creds.update", () => enqueueSaveCreds(saveCreds));

  nextSocket.ev.on("chats.phoneNumberShare", ({ lid, jid }) => {
    rememberLidToPnMapping(lid, jid);
  });

  nextSocket.ev.on("chats.upsert", (chats) => {
    for (const chat of chats || []) {
      rememberMappingFromChatLike(chat);
    }
  });

  nextSocket.ev.on("chats.update", (updates) => {
    for (const update of updates || []) {
      rememberMappingFromChatLike(update);
    }
  });

  nextSocket.ev.on("messaging-history.set", ({ chats }) => {
    for (const chat of chats || []) {
      rememberMappingFromChatLike(chat);
    }
  });

  nextSocket.ev.on("connection.update", async (update) => {
    if (socketId !== activeSocketId) {
      return;
    }
    try {
      if (update.qr) {
        qrcode.generate(update.qr, { small: true });
        logger.info("Scan the QR code shown above to link WhatsApp session");
      }

      if (update.connection === "open") {
        whatsappConnected = true;
        logger.info(
          {
            userId: normalizeBareJid(nextSocket?.user?.id || ""),
            userLid: normalizeBareJid(nextSocket?.user?.lid || ""),
          },
          "WhatsApp connected",
        );
        return;
      }

      if (update.connection !== "close") {
        return;
      }

      whatsappConnected = false;
      const statusCode = getStatusCode(update?.lastDisconnect?.error);
      logger.warn({ statusCode }, "WhatsApp connection closed");

      if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
        await clearBaileysAuthState();
        scheduleForSocket("logged-out", 1000);
        return;
      }

      if (statusCode === 515) {
        scheduleForSocket("restart-515", 500);
        return;
      }

      scheduleForSocket("closed", 1500);
    } catch (error) {
      logger.error({ error: String(error) }, "connection.update handler error");
      scheduleForSocket("handler-error", 1500);
    }
  });

  nextSocket.ev.on("messages.upsert", async (event) => {
    if (socketId !== activeSocketId) {
      return;
    }
    try {
      if (event.type !== "notify" && event.type !== "append") {
        return;
      }
      const isHistory = event.type === "append";
      const messages = event.messages || [];
      for (const message of messages) {
        if (!message || !message.key) {
          continue;
        }

        const fromMe = Boolean(message.key.fromMe);
        const messageId = message.key.id || null;
        const remoteJid = resolveInboundSenderJid(message.key.remoteJid || "");
        const selfJid = normalizeBareJid(nextSocket?.user?.id || "");
        const selfLidJid = normalizeBareJid(nextSocket?.user?.lid || "");
        let senderIdentityJid = remoteJid;
        if (
          accessMode === "self_chat" &&
          fromMe &&
          senderIdentityJid &&
          senderIdentityJid.endsWith("@lid") &&
          (!selfLidJid || senderIdentityJid === selfLidJid) &&
          selfJid
        ) {
          senderIdentityJid = selfJid;
        }

        if (
          !remoteJid ||
          remoteJid.endsWith("@g.us") ||
          remoteJid.endsWith("@status") ||
          remoteJid.endsWith("@broadcast")
        ) {
          continue;
        }

        if (isRecentInboundMessage(remoteJid, messageId)) {
          continue;
        }
        rememberInboundMessage(remoteJid, messageId);

        if (isRecentOutboundMessageId(messageId)) {
          continue;
        }

        const text = extractText(message);
        if (!text) {
          continue;
        }

        if (isHistory) {
          continue;
        }

        await postInbound({
          from: remoteJid,
          from_identity: senderIdentityJid,
          text,
          message_id: messageId,
          from_me: fromMe,
          is_group: false,
          self_jid: selfJid,
        });
      }
    } catch (error) {
      logger.error({ error: String(error) }, "Failed to forward inbound message to Python orchestrator");
    }
  });
}

app.get("/health", (_, res) => {
  res.json({ status: "ok", mockMode, connected: whatsappConnected || mockMode });
});

app.post("/send", async (req, res) => {
  try {
    if (sharedSecret && req.headers["x-sidecar-secret"] !== sharedSecret) {
      res.status(401).json({ ok: false, error: "invalid sidecar secret" });
      return;
    }

    const to = normalizeToJid(req.body?.to);
    const text = String(req.body?.text || "").trim();
    if (!to || !text) {
      res.status(400).json({ ok: false, error: "to and text are required" });
      return;
    }

    if (mockMode) {
      logger.info({ to, text }, "MOCK send");
      res.json({ ok: true, mock: true });
      return;
    }

    if (!socket) {
      res.status(503).json({ ok: false, error: "whatsapp socket not connected" });
      return;
    }

    const targetJid = to;
    const sent = await socket.sendMessage(targetJid, { text });
    logger.info({ to: targetJid }, "WhatsApp message sent");
    rememberOutboundMessageId(sent?.key?.id || null);
    res.json({ ok: true });
  } catch (error) {
    logger.error({ error: String(error) }, "Failed to send outbound WhatsApp message");
    res.status(500).json({ ok: false, error: "send failed" });
  }
});

app.listen(port, async () => {
  logger.info({ port, pythonInboundUrl, mockMode }, "WhatsApp sidecar listening");
  if (!mockMode) {
    queueStart("initial");
  }
});
