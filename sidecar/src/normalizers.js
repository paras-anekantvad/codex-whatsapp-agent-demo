const { extractMessageContent, normalizeMessageContent } = require("@whiskeysockets/baileys");

function normalizeToJid(raw) {
  const value = String(raw || "").replace(/^whatsapp:/i, "").trim();
  if (!value) {
    return null;
  }
  if (value.includes("@")) {
    const [local, domain] = value.split("@", 2);
    const cleanLocal = String(local || "").trim().split(":", 1)[0];
    const cleanDomain = String(domain || "").trim().toLowerCase();
    if (!cleanLocal || !cleanDomain) {
      return null;
    }
    if (cleanDomain === "lid") {
      return `${cleanLocal}@lid`;
    }
    return `${cleanLocal}@${cleanDomain}`;
  }
  const digits = value.replace(/[^0-9]/g, "");
  if (!digits) {
    return null;
  }
  return `${digits}@s.whatsapp.net`;
}

function extractText(message) {
  if (!message) {
    return null;
  }

  const base = normalizeMessageContent(message.message || message);
  if (!base) {
    return null;
  }

  const extracted = extractMessageContent(base);
  const candidates = [base, extracted && extracted !== base ? extracted : null];

  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    const conversation = typeof candidate.conversation === "string" ? candidate.conversation.trim() : "";
    if (conversation) {
      return conversation;
    }
    const extended =
      typeof candidate.extendedTextMessage?.text === "string"
        ? candidate.extendedTextMessage.text.trim()
        : "";
    if (extended) {
      return extended;
    }
    const caption =
      candidate.imageMessage?.caption ||
      candidate.videoMessage?.caption ||
      candidate.documentMessage?.caption ||
      "";
    if (typeof caption === "string" && caption.trim()) {
      return caption.trim();
    }
  }
  return null;
}

module.exports = {
  extractText,
  normalizeToJid,
};
