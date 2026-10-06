// Coordinates one in-flight operation; storage, HTTP, and DOM have separate owners.
class ChatApplication {
  constructor(store, transport, view) {
    this.store = store;
    this.transport = transport;
    this.view = view;
    this.busy = true;
    this.pending = "";
    this.persistent = false;
  }

  render() {
    this.store.sortConversationsInPlace();
    const conversation = this.store.getCurrentConversation();
    this.view.render(this.store, {
      busy: this.busy, pending: this.pending,
      revalidate: this.persistent && conversation?.threadId ? id => this.revalidate(id) : null,
    });
  }

  async start() {
    this.store.restore();
    this.view.bind({
      send: () => this.send(), newChat: () => this.newChat(),
      select: id => this.select(id), remove: id => this.remove(id),
      draft: value => { this.store.getCurrentConversation().draft = value; this.store.save(); },
    });
    this.render();
    try {
      const payload = await this.transport.bootstrap();
      this.store.historyPairs = normalizeHistoryPairLimit(payload.conversation_history_pairs);
      this.persistent = payload.features?.includes("persistent-investigations") || false;
      this.view.bootstrap(payload);
      if (this.persistent) await this.restoreInvestigations();
    } catch (error) { this.view.setStatus(String(error)); }
    finally { this.busy = false; this.store.save(); this.render(); }
  }

  async restoreInvestigations() {
    const summaries = await this.transport.investigation();
    // Bound concurrent work on small hosts; failed reads preserve cached drafts.
    for (const summary of summaries) {
      const record = await this.transport.investigation(`/${encodeURIComponent(summary.id)}`);
      const existing = this.store.state.conversations.find(item => item.threadId === record.id);
      const conversation = this.store.createConversation({
        id: existing?.id || record.id, threadId: record.id, title: record.title,
        updatedAt: record.updated_at, draft: existing?.draft || "",
        messages: InvestigationClient.messages(record),
      });
      if (existing) Object.assign(existing, conversation);
      else this.store.state.conversations.push(conversation);
    }
    this.store.ensureConversationState();
  }

  select(id) {
    if (this.busy || !this.store.state.conversations.some(item => item.id === id)) return;
    this.store.state.currentConversationId = id;
    this.store.save();
    this.view.navigation(false);
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
    const message = this.view.input?.value?.trim() || "";
    if (!conversation || !message) { this.view.setStatus("Enter a question first."); return; }
    // Lock before session creation/network I/O to prevent duplicate submissions.
    this.busy = true;
    this.pending = "Investigating";
    const request = { message, artifacts: [], history: this.store.buildRequestHistory(conversation.messages) };
    if (conversation.threadId) request.thread_id = conversation.threadId;
    conversation.messages.push({ role: "user", text: message });
    this.store.updateConversationTitle(conversation, message);
    conversation.draft = "";
    this.store.touchConversation(conversation);
    this.store.save();
    this.view.setStatus("");
    this.render();
    try {
      const payload = await this.transport.chat(request, event => { this.pending = event.message; this.render(); });
      conversation.threadId = payload.thread_id;
      conversation.messages.push(InvestigationClient.answer({ ...payload, response_text: payload.response }));
    } catch (error) {
      conversation.messages.push({ role: "assistant", text: String(error) });
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
      conversation.messages.push({ role: "user", text: turn.question }, InvestigationClient.answer(turn.result));
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
