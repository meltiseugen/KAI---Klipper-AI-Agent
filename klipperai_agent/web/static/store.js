// Owns browser drafts/history. Server investigations remain authoritative.
class ConversationStore {
  constructor(storage, introMessage, sessionId = null) {
    this.storage = storage;
    this.introMessage = introMessage;
    this.sessionId = sessionId;
    this.key = "klipperai.embed.state.v2";
    this.legacyKey = "klipperai.embed.state.v1";
    this.historyPairs = 10;
    this.state = { currentConversationId: null, conversations: [] };
  }

  restore() {
    const persisted = this.loadPersistedState();
    if (Array.isArray(persisted?.conversations)) {
      this.state = {
        currentConversationId: persisted.currentConversationId,
        conversations: persisted.conversations.filter(item => item && typeof item === "object").map(item => this.createConversation(item)),
      };
    }
    this.ensureConversationState();
  }

  save() {
    try { this.storage?.setItem(this.key, JSON.stringify(this.state)); }
    catch (_) { /* Keep chat usable when browser storage is unavailable. */ }
  }

  remove(id) {
    this.state.conversations = this.state.conversations.filter(item => item.id !== id);
    this.ensureConversationState();
    this.save();
  }
  createIntroEntry() {
    return {
      role: "assistant",
      text: this.introMessage,
      configProposals: [],
      sourceCitations: [],
    };
  }

  createConversation(seed = {}) {
    const messages = normalizeConversationEntries(seed.messages);
    const normalizedMessages = messages.length ? messages : [this.createIntroEntry()];
    return {
      id: typeof seed.id === "string" && seed.id.trim() ? seed.id : generateId(),
      title: deriveConversationTitle(normalizedMessages, seed.title),
      sessionId: typeof seed.sessionId === "string" && seed.sessionId.trim() ? seed.sessionId : null,
      threadId: typeof seed.threadId === "string" && seed.threadId.trim() ? seed.threadId : null,
      draft: typeof seed.draft === "string" ? seed.draft : "",
      updatedAt: normalizeTimestamp(seed.updatedAt),
      messages: normalizedMessages,
    };
  }

  sortConversationsInPlace() {
    this.state.conversations.sort((left, right) => {
      return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
    });
  }

  ensureConversationState() {
    if (!Array.isArray(this.state.conversations) || this.state.conversations.length === 0) {
      const hintedSessionId = this.sessionId;
      const initialConversation = this.createConversation({ sessionId: hintedSessionId });
      this.state = {
        currentConversationId: initialConversation.id,
        conversations: [initialConversation],
      };
      return;
    }

    this.sortConversationsInPlace();
    if (!this.state.conversations.some((conversation) => conversation.id === this.state.currentConversationId)) {
      this.state.currentConversationId = this.state.conversations[0].id;
    }
  }

  migrateLegacyState(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }

    const conversation = this.createConversation({
      sessionId: raw.sessionId || this.sessionId,
      threadId: raw.currentThreadId || null,
      draft: raw.draft || "",
      messages: raw.messages || [],
      updatedAt: raw.updatedAt,
    });

    return {
      currentConversationId: conversation.id,
      conversations: [conversation],
    };
  }

  loadPersistedState() {
    try {
      const raw = this.storage.getItem(this.key);
      if (raw) {
        return JSON.parse(raw);
      }
    } catch (_error) {
      return null;
    }

    try {
      const legacyRaw = this.storage.getItem(this.legacyKey);
      if (!legacyRaw) {
        return null;
      }
      return this.migrateLegacyState(JSON.parse(legacyRaw));
    } catch (_error) {
      return null;
    }
  }

  getCurrentConversation() {
    return this.state.conversations.find((conversation) => conversation.id === this.state.currentConversationId) || null;
  }

  updateConversationTitle(conversation, messageText) {
    if (!conversation) {
      return;
    }

    if (conversation.title === "New chat") {
      conversation.title = buildConversationTitle(messageText);
    }
  }

  touchConversation(conversation) {
    if (!conversation) {
      return;
    }
    conversation.updatedAt = new Date().toISOString();
  }

  buildRequestHistory(entries, pairLimit = this.historyPairs) {
    const messageLimit = normalizeHistoryPairLimit(pairLimit) * 2;
    if (messageLimit <= 0) {
      return [];
    }

    return entries
      .filter((entry) => {
        const role = String(entry.role || "").trim();
        const text = String(entry.text || "").trim();
        return (role === "user" || role === "assistant") && text && text !== this.introMessage;
      })
      .slice(-messageLimit)
      .map((entry) => ({
        role: entry.role,
        text: String(entry.text || "").slice(0, 8000),
      }));
  }
}
