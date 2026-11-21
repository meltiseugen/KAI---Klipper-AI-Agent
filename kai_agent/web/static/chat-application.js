// Coordinates one in-flight operation; storage, HTTP, and DOM have separate owners.
class ChatApplication {
  constructor(store, transport, view) {
    this.store = store;
    this.transport = transport;
    this.view = view;
    this.busy = true;
    this.pending = "";
    this.persistent = false;
    this.modesEnabled = false;
    this.revisions = new Map();
  }

  render() {
    this.store.sortConversationsInPlace();
    const conversation = this.store.getCurrentConversation();
    this.view.render(this.store, {
      busy: this.busy, pending: this.pending, recovering: Boolean(conversation?.pendingRun),
      modesEnabled: this.modesEnabled,
      providerConfigured: this.providerConfigured !== false,
      followUp: !this.busy && this.providerConfigured !== false && !conversation?.pendingRun ? question => this.followUp(question) : null,
      revalidate: this.persistent && conversation?.threadId && !conversation.pendingRun ? id => this.revalidate(id) : null,
    });
  }

  async start() {
    this.store.restore();
    this.view.bind({
      send: () => this.send(), newChat: () => this.newChat(),
      select: id => this.select(id), remove: id => this.remove(id),
      draft: value => { this.store.getCurrentConversation().draft = value; this.store.save(); this.view.setStatus(""); },
      mode: value => this.setMode(value),
      recover: code => this.recover(code),
      closeSettings: () => this.closeSettings(),
    });
    this.render();
    await this.connect();
  }

  async connect() {
    try {
      const payload = await this.transport.bootstrap();
      this.providerConfigured = payload.provider_configured !== false;
      this.store.historyPairs = normalizeHistoryPairLimit(payload.conversation_history_pairs);
      this.persistent = payload.features?.includes("persistent-investigations") || false;
      this.modesEnabled = payload.agent_modes?.includes("debug") || false;
      this.view.bootstrap(payload);
      this.view.showError(null);
      if (payload.features?.includes("moonraker-events") && !this.moonrakerFeed) {
        this.moonrakerFeed = new MoonrakerStatusFeed(this.transport, this.view);
        void this.moonrakerFeed.start();
        window.addEventListener("pagehide", () => this.moonrakerFeed.stop());
        window.addEventListener("pageshow", event => {
          if (event.persisted) {
            this.moonrakerFeed = new MoonrakerStatusFeed(this.transport, this.view);
            void this.moonrakerFeed.start(true);
          }
        });
      }
      if (payload.features?.includes("provider-management") && !this.providers) {
        this.providers = new ProviderPanel(this.transport);
        this.providers.beforeOpen = () => { this.knowledge?.close(); this.memory?.close(); };
        this.providers.bind();
      }
      if (payload.features?.includes("printer-knowledge") && !this.knowledge) {
        this.knowledge = new PrinterKnowledgePanel(this.transport);
        this.knowledge.beforeOpen = () => { this.providers?.close(); this.memory?.close(); };
        this.knowledge.bind();
      }
      if (this.persistent) await this.restoreInvestigations();
      if (payload.features?.includes("confirmed-memory") && !this.memory) {
        this.memory = new PrinterMemoryPanel(this.transport, () => this.store.getCurrentConversation()?.threadId);
        this.memory.beforeOpen = () => { this.providers?.close(); this.knowledge?.close(); };
        this.memory.bind();
      }
      if (payload.features?.includes("investigation-recovery") && !this.sync) {
        this.sync = new InvestigationSync(this);
        this.sync.start();
        window.addEventListener("pagehide", () => this.sync.stop());
        window.addEventListener("pageshow", event => { if (event.persisted) this.sync.start(); });
      }
    } catch (error) { this.view.showError(error); this.view.setStatus(String(error)); }
    finally { this.busy = false; this.store.save(); this.render(); }
  }

  async recover(code) {
    if (this.busy) return;
    if (code === "provider_not_configured" && this.providers) {
      this.view.doc.getElementById("providers-toggle")?.click();
      return;
    }
    this.busy = true;
    this.view.setStatus("");
    this.render();
    if (code === "invalid_session") this.transport.sessionId = null;
    await this.connect();
  }

  closeSettings() {
    for (const panel of [this.providers, this.knowledge, this.memory]) {
      if (panel && !panel.panel.hidden) panel.close();
    }
  }

  followUp(question) {
    const conversation = this.store.getCurrentConversation();
    if (this.busy || conversation?.pendingRun) return;
    const draft = [conversation.draft.trim(), question].filter(Boolean).join("\n\n");
    if (draft.length > 40000) { this.view.setStatus("Shorten your question before adding a follow-up (40,000 characters maximum)."); return; }
    conversation.draft = draft;
    this.store.save(); this.render(); this.view.input?.focus();
    this.view.setStatus("Follow-up added to your question. Review it, then Ask agent.");
  }

  async restoreInvestigations(refresh = false) {
    const summaries = await this.transport.investigation();
    let changed = false;
    // Bound concurrent work on small hosts; failed reads preserve cached drafts.
    for (const summary of summaries) {
      const revision = `${summary.revision}:${summary.pending?.id || ""}:${summary.pending?.attempts || 0}`;
      if (refresh && this.revisions.get(summary.id) === revision) continue;
      const existing = this.store.state.conversations.find(item => item.threadId === summary.id);
      if (existing?.id !== this.store.state.currentConversationId) {
        // Sidebar titles need no full answers or evidence. Keep cached messages
        // until opened so a failed refresh cannot erase saved browser history.
        const conversation = existing || this.store.createConversation({
          id: summary.id, threadId: summary.id, title: summary.title || "Saved chat",
          mode: summary.pending?.mode,
          updatedAt: summary.updated_at, messages: summary.pending ? investigationMessages({ turns: [], pending: summary.pending }) : [],
        });
        conversation.loaded = false;
        conversation.pendingRun = Boolean(summary.pending);
        if (!existing) this.store.state.conversations.push(conversation);
        this.revisions.set(summary.id, revision);
        changed = true;
        continue;
      }
      const record = await this.transport.investigation(`/${encodeURIComponent(summary.id)}`);
      if (refresh && this.busy) return false;
      const conversation = this.store.createConversation({
        id: existing?.id || record.id, threadId: record.id, title: record.title,
        updatedAt: record.updated_at, draft: existing?.draft || "",
        mode: existing?.mode || record.pending?.mode || record.turns.at(-1)?.result.mode,
        messages: investigationMessages(record),
      });
      conversation.pendingRun = Boolean(record.pending);
      if (existing) Object.assign(existing, conversation);
      else this.store.state.conversations.push(conversation);
      this.revisions.set(summary.id, revision);
      changed = true;
    }
    this.store.ensureConversationState();
    return changed;
  }

  async select(id) {
    if (this.busy || !this.store.state.conversations.some(item => item.id === id)) return;
    this.store.state.currentConversationId = id;
    this.store.save();
    this.view.navigation(false);
    this.render();
    const conversation = this.store.getCurrentConversation();
    if (conversation.loaded !== false) return;
    this.busy = true;
    this.pending = "Loading conversation";
    this.render();
    try {
      const record = await this.transport.investigation(`/${encodeURIComponent(conversation.threadId)}`);
      Object.assign(conversation, this.store.createConversation({
        ...conversation, loaded: true, title: record.title, updatedAt: record.updated_at,
        mode: conversation.messages.some(item => item.role === "user") ? conversation.mode : record.pending?.mode || record.turns.at(-1)?.result.mode || conversation.mode,
        messages: investigationMessages(record),
      }), { pendingRun: Boolean(record.pending) });
      this.revisions.set(record.id, `${record.revision}:${record.pending?.id || ""}:${record.pending?.attempts || 0}`);
    } catch (error) { this.view.showError(error); }
    finally { this.busy = false; this.pending = ""; this.store.save(); this.render(); }
  }

  setMode(value) {
    if (this.busy || !this.modesEnabled) return;
    this.store.getCurrentConversation().mode = normalizeAgentMode(value);
    this.store.save();
    this.render();
  }

  newChat() {
    if (this.busy) return;
    if (!isConversationPristine(this.store.getCurrentConversation())) {
      const conversation = this.store.createConversation();
      this.store.state.conversations.unshift(conversation);
      this.store.state.currentConversationId = conversation.id;
      this.store.save();
      this.render();
    }
    this.view.navigation(false);
    this.view.input?.focus();
  }

  async remove(id) {
    if (this.busy) return;
    const conversation = this.store.state.conversations.find(item => item.id === id);
    if (!conversation) return;
    this.busy = true;
    this.render();
    try {
      if (this.persistent && conversation.threadId) await this.transport.investigation(`/${encodeURIComponent(conversation.threadId)}`, "DELETE");
      this.store.remove(id);
      this.view.setStatus("");
    } catch (error) { this.view.setStatus(String(error)); }
    finally { this.busy = false; this.render(); }
  }

  async send() {
    if (this.busy) return;
    const conversation = this.store.getCurrentConversation();
    if (conversation?.pendingRun) return;
    const message = this.view.input?.value?.trim() || "";
    if (!conversation || !message) { this.view.setStatus("Enter a question first."); return; }
    if (this.providerConfigured === false) { this.view.showError({ code: "provider_not_configured" }); return; }
    // Lock before session creation/network I/O to prevent duplicate submissions.
    this.busy = true;
    this.pending = "Collecting context for the agent";
    const request = { message, mode: this.modesEnabled ? conversation.mode : "chat", history: this.store.buildRequestHistory(conversation.messages) };
    if (this.persistent) conversation.threadId ||= conversation.id;
    if (conversation.threadId) request.thread_id = conversation.threadId;
    const userEntry = { role: "user", text: message };
    conversation.messages.push(userEntry);
    this.store.updateConversationTitle(conversation, message);
    conversation.draft = "";
    this.store.touchConversation(conversation);
    this.store.save();
    this.view.setStatus("");
    this.view.showError(null);
    this.render();
    try {
      const payload = await this.transport.chat(request, event => { this.pending = event.message; this.render(); });
      conversation.threadId = payload.thread_id;
      conversation.messages.push(investigationAnswer({ ...payload, response_text: payload.response }));
      if (payload.moonraker_reachable === false) this.view.notices.set("moonraker", { code: "moonraker_unavailable" });
    } catch (error) {
      // A failed request must remain editable and must not pollute request history.
      conversation.messages = conversation.messages.filter(item => item !== userEntry);
      conversation.messages.push({ role: "assistant", text: String(error), error: true, modelUsage: normalizeModelUsage(error.modelUsage) });
      conversation.draft = message;
      this.view.showError(error);
    } finally { this.finish(conversation); }
  }

  async revalidate(proposalId) {
    if (this.busy) throw new Error("Wait for the current investigation to finish.");
    const conversation = this.store.getCurrentConversation();
    this.busy = true;
    this.pending = "Checking the proposal against current config";
    this.render();
    try {
      const turn = await this.transport.investigation(`/${encodeURIComponent(conversation.threadId)}/proposals/${encodeURIComponent(proposalId)}/revalidate`, "POST");
      conversation.messages.push({ role: "user", text: turn.question }, investigationAnswer(turn.result));
    } catch (error) { this.view.setStatus(String(error)); }
    finally { this.finish(conversation); }
  }

  finish(conversation) {
    this.busy = false;
    this.pending = "";
    this.store.touchConversation(conversation);
    this.store.save();
    this.render();
  }
}
