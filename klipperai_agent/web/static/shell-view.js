function setText(element, text) { if (element) element.textContent = text; }

function sidebarIsOverlay(doc = document) {
  return Boolean(doc.defaultView?.matchMedia?.("(max-width: 800px)").matches);
}

function focusPanelLauncher(launcher) {
  const hiddenSidebar = sidebarIsOverlay() || document.body.classList.contains("sidebar-collapsed");
  (hiddenSidebar ? document.getElementById("shell-menu-toggle") : launcher)?.focus();
}

function settingsSection(parent, title, description = "", open = false) {
  const section = document.createElement("details");
  section.className = "settings-section";
  section.dataset.settingsSection = title;
  section.open = open;
  const summary = document.createElement("summary");
  const heading = document.createElement("span");
  heading.className = "settings-section-title";
  heading.textContent = title;
  summary.appendChild(heading);
  if (description) {
    const help = document.createElement("span");
    help.className = "settings-section-description";
    help.textContent = description;
    summary.appendChild(help);
  }
  section.appendChild(summary);
  const content = document.createElement("div");
  content.className = "settings-section-content";
  section.appendChild(content);
  parent.appendChild(section);
  return content;
}

function settingsSectionState(parent) {
  return new Map(Array.from(parent.querySelectorAll?.("details[data-settings-section]") || [], section => [section.dataset.settingsSection, section.open]));
}

function restoreSettingsSections(parent, state) {
  for (const section of parent.querySelectorAll?.("details[data-settings-section]") || []) {
    if (state.has(section.dataset.settingsSection)) section.open = state.get(section.dataset.settingsSection);
  }
}

// Shell presentation and keyboard behavior. Networking stays in ChatApplication.
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
    this.mode = doc.getElementById("agent-mode");
    this.messageView = new MessageView(doc.getElementById("message-template"), null);
    this.notices = new NoticeView(doc);
  }

  bind(actions) {
    this.actions = actions;
    this.notices.recover = actions.recover;
    this.send?.addEventListener("click", () => void actions.send());
    this.newChat?.addEventListener("click", () => actions.newChat());
    this.input?.addEventListener("input", () => { this.resizeInput(); actions.draft(this.input.value); });
    this.input?.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!this.send?.disabled) void actions.send();
      }
    });
    this.mode?.addEventListener("change", () => actions.mode(this.mode.value));
    const toggle = this.doc.getElementById("shell-menu-toggle");
    toggle?.addEventListener("click", () => {
      const overlay = sidebarIsOverlay(this.doc);
      this.navigation(overlay ? !this.body.classList.contains("nav-open") : this.body.classList.contains("sidebar-collapsed"), !overlay);
    });
    this.doc.getElementById("shell-scrim")?.addEventListener("click", () => this.navigation(false));
    this.doc.getElementById("settings-scrim")?.addEventListener("click", () => actions.closeSettings?.());
    this.doc.getElementById("connect-provider")?.addEventListener("click", () => actions.recover("provider_not_configured"));
    for (const [id, prompt] of [["starter-diagnose", "Why did my printer stop?"], ["starter-config", "Review my printer configuration"]]) {
      this.doc.getElementById(id)?.addEventListener("click", () => {
        if (this.input?.disabled) return;
        this.input.value = prompt;
        actions.draft(prompt);
        this.resizeInput();
        this.input.focus();
      });
    }
    this.messages?.addEventListener("scroll", () => this.updateScrollControl());
    this.doc.getElementById("scroll-to-bottom")?.addEventListener("click", () => {
      this.messages.scrollTop = this.messages.scrollHeight;
      this.updateScrollControl();
    });
    for (const id of ["providers-toggle", "knowledge-toggle", "memory-toggle"]) {
      this.doc.getElementById(id)?.addEventListener("click", () => this.navigation(false));
    }
    this.doc.addEventListener?.("keydown", event => {
      const panel = this.doc.querySelector?.(".knowledge-panel:not([hidden])");
      if (event.key === "Escape" && panel) {
        event.preventDefault?.();
        actions.closeSettings?.();
      } else if (event.key === "Escape" && this.body.classList.contains("nav-open")) {
        this.navigation(false);
        toggle?.focus();
      } else if (event.key === "Tab" && panel) {
        const fields = [...panel.querySelectorAll("button, input, select, textarea, summary, a[href], [tabindex]")]
          .filter(item => !item.disabled && item.tabIndex !== -1 && item.getClientRects().length);
        const target = event.shiftKey ? fields.at(-1) : fields[0];
        const edge = event.shiftKey ? fields[0] : fields.at(-1);
        if (target && (this.doc.activeElement === edge || !panel.contains(this.doc.activeElement))) {
          event.preventDefault(); target.focus();
        }
      }
    });
  }

  navigation(open, desktop = false) {
    this.body.classList.toggle("nav-open", desktop ? false : open);
    if (desktop) this.body.classList.toggle("sidebar-collapsed", !open);
    const expanded = sidebarIsOverlay(this.doc) ? open : !this.body.classList.contains("sidebar-collapsed");
    this.doc.getElementById("shell-menu-toggle")?.setAttribute("aria-expanded", String(expanded));
    if (open && sidebarIsOverlay(this.doc)) this.newChat?.focus();
  }

  resizeInput() {
    if (!this.input?.style) return;
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 200)}px`;
  }

  updateScrollControl() {
    const button = this.doc.getElementById("scroll-to-bottom");
    if (button) button.hidden = this.messages?.hidden || this.nearBottom();
  }

  nearBottom() {
    return (this.messages?.scrollHeight || 0) - (this.messages?.scrollTop || 0) - (this.messages?.clientHeight || 0) < 80;
  }

  setStatus(text) { setText(this.status, text); }
  showError(error) { this.notices.set(error?.code === "provider_not_configured" ? "provider" : "request", error); }

  connection(label, connected) {
    setText(this.doc.getElementById("connection-label"), label);
    this.doc.getElementById("connection-dot")?.classList.toggle("connected", connected);
  }

  moonraker(state) {
    const reachable = this.doc.getElementById("moonraker-badge");
    if (reachable) {
      reachable.textContent = state.connected ? "Moonraker: reachable" : "Moonraker: unavailable";
      reachable.classList.toggle("ok", Boolean(state.connected));
      reachable.classList.toggle("warn", !state.connected);
    }
    const badge = this.doc.getElementById("moonraker-events-badge");
    if (badge) {
      badge.hidden = false;
      badge.textContent = state.connected ? (state.subscribed ? "Events: live" : "Events: waiting for Klipper") : "Events: reconnecting";
      badge.classList.toggle("ok", Boolean(state.connected && state.subscribed));
      badge.classList.toggle("warn", !state.connected || !state.subscribed);
      badge.title = state.error || "Moonraker agent subscription";
    }
    const live = state.connected && !state.stale;
    const printer = this.doc.getElementById("klipper-badge");
    if (printer) {
      const job = live && state.status?.print_stats?.state;
      printer.textContent = `Klipper: ${state.connected ? state.klippy_state : "unknown"}${job ? ` · ${job}` : ""}`;
      printer.classList.toggle("ok", Boolean(live && state.klippy_state === "ready"));
      printer.classList.toggle("warn", !live || state.klippy_state !== "ready");
    }
    this.connection(state.connected ? (state.stale ? "Status reconnecting" : `Printer ${state.klippy_state || "connected"}`) : "Printer unavailable", Boolean(live && state.klippy_state === "ready"));
  }

  bootstrap(payload) {
    this.notices.set("moonraker", null);
    this.notices.set("provider", null);
    const provider = payload.provider === "openai" ? "OpenAI" : payload.provider || "your provider";
    setText(this.doc.getElementById("provider-badge"), `Provider: ${provider}`);
    setText(this.doc.getElementById("model-badge"), `Model: ${payload.provider_model || "unavailable"}`);
    setText(this.doc.getElementById("llm-summary"), payload.provider_configured === false ? "OpenAI not connected" : `${provider}${payload.provider_model ? ` · ${payload.provider_model}` : ""}`);
    setText(this.doc.getElementById("llm-request-info"), payload.provider_configured === false
      ? "Configure an LLM provider and API key to use Chat and Debug. Saved information remains available."
      : `Chat and Debug use ${provider}${payload.provider_model ? ` / ${payload.provider_model}` : ""}. Your question, printer config and recent logs are sent to the LLM. Provider credits may be used. Config changes remain manual.`);
    for (const [key, label] of [["moonraker", "Moonraker"], ["klipper", "Klipper"]]) {
      const badge = this.doc.getElementById(`${key}-badge`);
      if (!badge) continue;
      const reachable = Boolean(payload[`${key}_reachable`]);
      badge.textContent = `${label}: ${reachable ? "reachable" : "unavailable"}`;
      badge.classList.remove("ok", "warn");
      badge.classList.add(reachable ? "ok" : "warn");
    }
    const connected = Boolean(payload.moonraker_reachable && payload.klipper_reachable);
    this.connection(connected ? "Printer connected" : "Printer unavailable", connected);
  }

  render(store, { busy, pending, revalidate, followUp, modesEnabled, recovering = false, providerConfigured = true }) {
    const conversation = store.getCurrentConversation();
    const entries = (conversation?.messages || []).filter(entry => !isWelcomeEntry(entry, store.introMessage));
    const empty = !entries.length && !pending && !recovering;
    this.doc.getElementById("conversation-panel")?.classList.toggle("is-empty", empty);
    const welcome = this.doc.getElementById("chat-welcome");
    if (welcome) welcome.hidden = !empty;
    setText(this.doc.getElementById("welcome-title"), providerConfigured ? "What can I help with?" : "Connect your AI provider");
    setText(this.doc.getElementById("welcome-description"), providerConfigured
      ? "I can read your printer config and recent logs. Just ask."
      : "Add your OpenAI API key to start investigating your printer.");
    const connect = this.doc.getElementById("connect-provider");
    if (connect) { connect.hidden = providerConfigured; connect.disabled = busy; }
    const starters = this.doc.getElementById("chat-starters");
    if (starters) starters.hidden = !empty || !providerConfigured || busy;
    const title = this.doc.getElementById("conversation-title");
    setText(title, conversation?.title || "New chat");
    if (title) title.title = conversation?.title || "New chat";
    this.messageView.revalidate = revalidate;
    this.messageView.followUp = followUp;
    this.notices.render(busy);
    this.renderHistory(store, busy);
    if (this.messages && conversation) {
      const stick = this.lastConversation !== conversation.id || this.nearBottom();
      const previousScroll = this.messages.scrollTop || 0;
      this.messages.hidden = empty;
      this.messages.textContent = "";
      for (const entry of entries) this.messages.appendChild(this.messageView.buildMessageElement(entry));
      if (pending) this.messages.appendChild(this.messageView.buildMessageElement({ role: "assistant", text: pending }, { pending: true }));
      this.messages.scrollTop = stick ? this.messages.scrollHeight : previousScroll;
      this.lastConversation = conversation.id;
      this.updateScrollControl();
    }
    if (this.input) {
      this.input.value = conversation?.draft || "";
      this.input.disabled = busy || !providerConfigured;
      this.input.placeholder = providerConfigured ? "Ask about your printer" : "Connect a provider to start";
      this.resizeInput();
    }
    if (this.mode) {
      this.mode.value = modesEnabled ? normalizeAgentMode(conversation?.mode) : "chat";
      this.mode.disabled = busy || !modesEnabled || !providerConfigured;
    }
    const description = !providerConfigured ? "Chat and Debug require a configured LLM provider."
      : !modesEnabled ? "Modes require the tool-using agent. Context is selected from your question."
      : conversation?.mode === "debug" ? "Config and recent logs, plus live status and service diagnostics."
      : "Config and recent logs are read automatically; earlier conversation stays available.";
    setText(this.doc.getElementById("mode-description"), description);
    if (this.mode) this.mode.title = description;
    if (this.newChat) this.newChat.disabled = busy;
    if (this.send) {
      this.send.disabled = busy || recovering || !providerConfigured;
      this.send.setAttribute("aria-label", pending ? "Investigating" : "Ask agent");
      this.send.title = providerConfigured ? "Send message (Enter)" : "Connect OpenAI to send messages";
    }
    setText(this.doc.getElementById("send-label") || this.send, pending ? "Investigating" : "Ask agent");
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
      button.title = conversation.title;
      button.setAttribute("aria-current", conversation.id === store.state.currentConversationId ? "page" : "false");
      button.addEventListener("click", () => this.actions.select(conversation.id));
      const label = this.doc.createElement("div");
      label.className = "history-item-title";
      label.textContent = conversation.title;
      button.appendChild(label);
      const remove = this.doc.createElement("button");
      remove.className = "history-delete-button";
      remove.type = "button";
      remove.disabled = busy;
      remove.title = `Delete chat: ${conversation.title}`;
      remove.setAttribute("aria-label", remove.title);
      remove.textContent = "\u00d7";
      remove.addEventListener("click", () => void this.actions.remove(conversation.id));
      row.appendChild(button);
      row.appendChild(remove);
      this.history.appendChild(row);
    }
  }
}
