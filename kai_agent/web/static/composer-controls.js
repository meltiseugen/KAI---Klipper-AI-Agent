// Composer disclosures; selections are owned by the active browser conversation.
// General-purpose Responses models from OpenAI's catalog, reviewed 2026-11-22.
// Access depends on the configured API key.
const OPENAI_CHAT_MODELS = Object.freeze([
  "gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra", "gpt-6-luna",
  "gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol",
  "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
  "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.2",
]);

class ComposerControls {
  constructor(doc) {
    this.doc = doc;
    this.mode = doc.getElementById("agent-mode");
    this.model = doc.getElementById("chat-model");
    this.thinking = doc.getElementById("chat-thinking");
    this.modeMenu = doc.getElementById("mode-menu");
    this.modelMenu = doc.getElementById("model-menu");
    this.thinkingMenu = doc.getElementById("thinking-menu");
    this.defaultModel = null;
    this.catalog = [];
  }

  pickers() {
    return [[this.mode, this.modeMenu, "mode-picker"], [this.model, this.modelMenu, "model-picker"], [this.thinking, this.thinkingMenu, "thinking-picker"]];
  }

  bind(actions) {
    this.actions = actions;
    for (const [button, menu, pickerId] of this.pickers()) {
      button?.addEventListener("click", () => this.toggle(button, menu));
      button?.addEventListener("keydown", event => {
        if (["ArrowDown", "ArrowUp"].includes(event.key)) {
          event.preventDefault();
          this.open(button, menu, event.key === "ArrowUp");
        }
      });
      this.doc.getElementById(pickerId)?.addEventListener("focusout", event => {
        if (!this.doc.getElementById(pickerId).contains(event.relatedTarget)) this.close(button, menu);
      });
    }
    for (const option of this.modeMenu?.querySelectorAll("[data-mode]") || []) {
      option.addEventListener("click", () => {
        if (this.mode.disabled) return;
        actions.mode(option.dataset.mode);
        this.close(this.mode, this.modeMenu, true);
      });
    }
    for (const [, menu] of this.pickers()) menu?.addEventListener("keydown", event => {
      const options = [...menu.querySelectorAll("button")];
      const index = options.indexOf(this.doc.activeElement);
      let next;
      if (event.key === "ArrowDown") next = (index + 1) % options.length;
      if (event.key === "ArrowUp") next = (index - 1 + options.length) % options.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = options.length - 1;
      if (next !== undefined) { event.preventDefault(); options[next]?.focus(); }
    });
    for (const option of this.thinkingMenu?.querySelectorAll("[data-thinking]") || []) option.addEventListener("click", () => {
      if (!this.thinking.disabled && actions.thinking(option.dataset.thinking || null)) this.close(this.thinking, this.thinkingMenu, true);
    });
    this.doc.addEventListener("pointerdown", event => {
      for (const [button, menu, pickerId] of this.pickers()) {
        if (!this.doc.getElementById(pickerId)?.contains(event.target)) this.close(button, menu);
      }
    });
    this.doc.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      for (const [button, menu] of this.pickers()) {
        if (menu && !menu.hidden) { event.preventDefault(); this.close(button, menu, true); }
      }
    });
  }

  close(button, menu, focus = false) {
    if (menu) menu.hidden = true;
    button?.setAttribute("aria-expanded", "false");
    if (focus) button?.focus();
  }

  open(button, menu, last = false) {
    if (!button || button.disabled || !menu) return;
    for (const [trigger, popup] of this.pickers()) this.close(trigger, popup);
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    const options = [...menu.querySelectorAll("button")];
    (last ? options.at(-1) : options[0])?.focus();
  }

  toggle(button, menu) {
    if (!menu) return;
    if (menu.hidden) this.open(button, menu);
    else this.close(button, menu, true);
  }

  bootstrap(payload) {
    this.defaultModel = normalizeChatModel(payload.provider_model);
    this.catalog = payload.provider === "openai" ? OPENAI_CHAT_MODELS : [];
    this.provider = payload.provider === "openai" ? "OpenAI" : payload.provider || "Provider";
    setText(this.doc.getElementById("llm-provider"), this.provider);
  }

  render(store, { busy, providerConfigured }) {
    const conversation = store.getCurrentConversation();
    this.selectedModel = normalizeChatModel(conversation?.model);
    const thinking = normalizeThinkingLevel(conversation?.thinkingLevel);
    setText(this.doc.getElementById("chat-thinking-label"), `Thinking: ${thinking ? thinking[0].toUpperCase() + thinking.slice(1) : "Default"}`);
    if (this.thinking) {
      this.thinking.disabled = busy || !providerConfigured || Boolean(conversation?.pendingRun);
      if (this.thinking.disabled) this.close(this.thinking, this.thinkingMenu);
    }
    for (const option of this.thinkingMenu?.querySelectorAll("[data-thinking]") || []) option.setAttribute("aria-checked", String((option.dataset.thinking || null) === thinking));
    const model = this.selectedModel || this.defaultModel;
    setText(this.doc.getElementById("chat-model-label"), providerConfigured ? model || "Choose model" : "Not connected");
    setText(this.doc.getElementById("model-badge"), `Model: ${model || "unavailable"}`);
    setText(this.doc.getElementById("agent-mode-label"), this.mode?.value === "debug" ? "Debug" : "Chat");
    if (this.model) {
      this.model.disabled = busy || !providerConfigured || Boolean(conversation?.pendingRun);
      this.model.title = `Model for this chat: ${model || "not selected"}. Click to change.`;
    }
    if (this.mode?.disabled) this.close(this.mode, this.modeMenu);
    if (this.model?.disabled) this.close(this.model, this.modelMenu);
    for (const option of this.modeMenu?.querySelectorAll("[data-mode]") || []) option.setAttribute("aria-checked", String(option.dataset.mode === this.mode?.value));
    const options = this.doc.getElementById("chat-model-options");
    if (!options) return;
    // Preserve focused controls while a disclosure is open.
    const recent = [...new Set([this.selectedModel, ...store.state.conversations.map(item => normalizeChatModel(item.model))].filter(Boolean))].slice(0, 8);
    const models = [...new Set([this.defaultModel, ...recent, ...this.catalog].filter(Boolean))];
    const key = JSON.stringify([this.defaultModel, this.selectedModel, models]);
    if (options.dataset.models === key) return;
    options.dataset.models = key;
    options.textContent = "";
    for (const value of models) {
      const button = this.doc.createElement("button");
      button.type = "button";
      button.textContent = value;
      button.setAttribute("aria-pressed", String(value === model));
      button.addEventListener("click", () => {
        if (!this.model.disabled && this.actions.model(value)) this.close(this.model, this.modelMenu, true);
      });
      options.appendChild(button);
    }
  }
}
