// Conversation value normalization; no DOM or storage access.

function generateId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function normalizeTimestamp(value) {
  if (typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString();
    }
  }
  return new Date().toISOString();
}

function buildConversationTitle(text) {
  const firstLine = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);

  if (!firstLine) {
    return "New chat";
  }

  return firstLine.length > 56 ? `${firstLine.slice(0, 56).trimEnd()}...` : firstLine;
}

function normalizeConversationEntries(entries) {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }

      const role = entry.role === "user" ? "user" : "assistant";
      const text = typeof entry.text === "string" ? entry.text : "";
      const configProposals = Array.isArray(entry.configProposals) ? entry.configProposals : [];
      const sourceCitations = normalizeSourceCitations(entry.sourceCitations || entry.source_citations || []);
      if (!text.trim()) {
        return null;
      }
      return { role, text, configProposals, sourceCitations, agentEvents: AgentActivity.normalize(entry.agentEvents), nextActions: Array.isArray(entry.nextActions) ? entry.nextActions : [], memorySources: Array.isArray(entry.memorySources) ? entry.memorySources : [] };
    })
    .filter(Boolean);
}

function deriveConversationTitle(messages, fallbackTitle) {
  const firstUserMessage = messages.find((entry) => entry.role === "user");
  if (firstUserMessage) {
    return buildConversationTitle(firstUserMessage.text);
  }
  if (typeof fallbackTitle === "string" && fallbackTitle.trim()) {
    return fallbackTitle.trim();
  }
  return "New chat";
}

function isConversationPristine(conversation) {
  if (!conversation) {
    return false;
  }
  const hasUserMessage = conversation.messages.some((entry) => entry.role === "user");
  return !hasUserMessage && !conversation.threadId && !conversation.draft.trim();
}

function normalizeHistoryPairLimit(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 10;
  }
  return Math.min(parsed, 50);
}

function normalizeSourceCitations(citations) {
  if (!Array.isArray(citations)) {
    return [];
  }

  return citations
    .map((citation) => {
      if (!citation || typeof citation !== "object") {
        return null;
      }

      const label = String(citation.label || "").trim();
      const path = String(citation.path || "").trim();
      const section = String(citation.section || "").trim();
      const excerpt = String(citation.excerpt || "");
      const rawLineNumber = citation.lineNumber ?? citation.line_number;
      const parsedLineNumber = Number.parseInt(rawLineNumber, 10);
      const lineNumber = Number.isFinite(parsedLineNumber) && parsedLineNumber > 0 ? parsedLineNumber : null;

      if (!label && !path && !section && !excerpt.trim()) {
        return null;
      }

      return {
        label,
        path,
        lineNumber,
        section,
        excerpt,
        url: /^https?:\/\//i.test(String(citation.url || "")) ? String(citation.url) : null,
      };
    })
    .filter(Boolean);
}
