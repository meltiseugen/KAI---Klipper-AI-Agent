function setText(element, text) { if (element) element.textContent = text; }

// Owns shell DOM and event binding. Receives data and callbacks, never fetches.
class ShellView {
  constructor(doc = document) {
    this.doc = doc;
    this.body = doc.body;
    this.input = doc.getElementById("message-input");
    this.messages = doc.getElementById("messages");
    this.history = doc.getElementById("history-list");
    this.send = doc.getElementById("send-button");
    this.newChat = doc.getElementById("new-chat-button");
    this.status = doc.getElementById("composer-status");
    this.formatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    this.messageView = new MessageView(doc.getElementById("message-template"), null);
  }

  bind(actions) {
    this.actions = actions;
    this.send?.addEventListener("click", () => void actions.send());
    this.newChat?.addEventListener("click", () => actions.newChat());
    this.input?.addEventListener("input", () => actions.draft(this.input.value));
    const toggle = this.doc.getElementById("shell-menu-toggle");
    toggle?.addEventListener("click", () => this.navigation(!this.body.classList.contains("nav-open")));
    this.doc.getElementById("shell-scrim")?.addEventListener("click", () => this.navigation(false));
  }

  navigation(open) {
    this.body.classList.toggle("nav-open", open);
    this.doc.getElementById("shell-menu-toggle")?.setAttribute("aria-expanded", String(open));
  }

  setStatus(text) { setText(this.status, text); }

  bootstrap(payload) {
    setText(this.doc.getElementById("provider-badge"), `Provider: ${payload.provider || "unavailable"}`);
    setText(this.doc.getElementById("model-badge"), `Model: ${payload.provider_model || "unavailable"}`);
    for (const [key, label] of [["moonraker", "Moonraker"], ["klipper", "Klipper"]]) {
      const badge = this.doc.getElementById(`${key}-badge`);
      if (!badge) continue;
      const reachable = Boolean(payload[`${key}_reachable`]);
      badge.textContent = `${label}: ${reachable ? "reachable" : "unavailable"}`;
      badge.classList.remove("ok", "warn");
      badge.classList.add(reachable ? "ok" : "warn");
    }
  }

  render(store, { busy, pending, revalidate }) {
    const conversation = store.getCurrentConversation();
    this.messageView.revalidate = revalidate;
    this.renderHistory(store, busy);
    if (this.messages && conversation) {
      this.messages.textContent = "";
      for (const entry of conversation.messages) this.messages.appendChild(this.messageView.buildMessageElement(entry));
      if (pending) this.messages.appendChild(this.messageView.buildMessageElement({ role: "assistant", text: pending }, { pending: true }));
      this.messages.scrollTop = this.messages.scrollHeight;
    }
    if (this.input) this.input.value = conversation?.draft || "";
    for (const element of [this.input, this.send, this.newChat]) if (element) element.disabled = busy;
    setText(this.send, pending ? "Analyzing..." : "Analyze");
  }

  renderHistory(store, busy) {
    if (!this.history) return;
    this.history.textContent = "";
    for (const conversation of store.state.conversations) {
      const row = this.doc.createElement("div");
      row.className = "history-row";
      row.classList.toggle("active", conversation.id === store.state.currentConversationId);
      const button = this.doc.createElement("button");
      button.className = "history-item";
      button.type = "button";
      button.disabled = busy;
      button.addEventListener("click", () => this.actions.select(conversation.id));
      const count = conversation.messages.filter(entry => entry.role === "user").length;
      const preview = [...conversation.messages].reverse().find(entry => entry.text !== store.introMessage)?.text || "Ready for a new question.";
      for (const [name, text] of [["title", conversation.title], ["meta", `${this.formatter.format(new Date(conversation.updatedAt))} · ${count} question${count === 1 ? "" : "s"}`], ["preview", preview]]) {
        const item = this.doc.createElement("div");
        item.className = `history-item-${name}`;
        item.textContent = text;
        button.appendChild(item);
      }
      const remove = this.doc.createElement("button");
      remove.className = "history-delete-button";
      remove.type = "button";
      remove.disabled = busy;
      remove.title = `Delete chat: ${conversation.title}`;
      remove.setAttribute("aria-label", remove.title);
      remove.textContent = "X";
      remove.addEventListener("click", () => void this.actions.remove(conversation.id));
      row.appendChild(button);
      row.appendChild(remove);
      this.history.appendChild(row);
    }
  }
}
