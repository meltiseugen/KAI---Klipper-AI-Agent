// Credential input is transient: never copied into drafts, storage, or status output.
class ProviderPanel {
  constructor(transport) {
    this.transport = transport;
    this.busy = false;
    this.data = null;
    this.inputs = {};
    this.panel = document.getElementById("providers-panel");
    this.toggle = document.getElementById("providers-toggle");
    this.status = document.getElementById("providers-status");
    this.key = document.getElementById("providers-key");
    this.remove = document.getElementById("providers-remove");
  }

  bind() {
    this.toggle.hidden = false;
    this.toggle.addEventListener("click", () => this.show());
    document.getElementById("providers-close").addEventListener("click", () => this.close());
    document.getElementById("providers-reload").addEventListener("click", () => this.load());
    document.getElementById("providers-validate").addEventListener("click", () => this.submit(false));
    document.getElementById("providers-save").addEventListener("click", () => this.submit(true));
    document.addEventListener("pointerdown", event => {
      for (const picker of this.panel.querySelectorAll(".settings-choice")) {
        if (!picker.contains(event.target)) this.closePicker(picker);
      }
    });
    this.panel.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      const open = [...this.panel.querySelectorAll(".settings-choice")].find(picker => !picker.querySelector("[role='menu']").hidden);
      if (open) {
        event.preventDefault(); event.stopPropagation();
        this.closePicker(open);
        open.querySelector(".settings-choice-trigger").focus();
      }
    });
  }

  async show() {
    this.beforeOpen?.();
    this.panel.hidden = false;
    this.toggle.setAttribute("aria-expanded", "true");
    document.getElementById("conversation-panel").inert = true;
    document.getElementById("providers-close").focus();
    await this.load();
  }

  close() {
    this.panel.querySelectorAll(".settings-choice").forEach(picker => this.closePicker(picker));
    this.key.value = "";
    this.panel.hidden = true;
    this.toggle.setAttribute("aria-expanded", "false");
    document.getElementById("conversation-panel").inert = false;
    focusPanelLauncher(this.toggle);
  }

  async request(path = "", method = "GET", body = null) {
    return (await this.transport.request(`/providers${path}`, method, body)).json();
  }

  controls(busy) {
    this.busy = busy;
    for (const id of ["providers-reload", "providers-validate", "providers-save"]) {
      document.getElementById(id).disabled = busy || (!this.data && id !== "providers-reload");
    }
    this.key.disabled = busy || this.data?.credential_storage_available === false;
    this.remove.disabled = busy;
    Object.values(this.inputs).forEach(input => { input.disabled = busy; });
    if (busy) this.panel.querySelectorAll(".settings-choice").forEach(picker => this.closePicker(picker));
  }

  async load() {
    if (this.busy) return;
    this.key.value = "";
    this.controls(true);
    try {
      this.data = await this.request();
      this.render();
    } catch (error) { this.status.textContent = String(error); }
    finally { this.controls(false); }
  }

  field(parent, name, label, value, options = null, bounds = null) {
    const wrapper = document.createElement("label");
    wrapper.className = "field";
    const title = document.createElement("span");
    title.textContent = label;
    const input = document.createElement(options ? "select" : "input");
    input.id = `provider-${name}`;
    if (options) for (const [key, text] of options) {
      const option = document.createElement("option");
      option.value = key; option.textContent = text; input.appendChild(option);
    }
    else {
      input.type = bounds ? "number" : "text";
      if (bounds) { input.min = bounds[0]; input.max = bounds[1]; input.step = "1"; }
      else input.maxLength = 120;
    }
    input.value = String(value);
    wrapper.appendChild(title); wrapper.appendChild(input); parent.appendChild(wrapper);
    this.inputs[name] = input;
  }

  closePicker(picker) {
    picker.querySelector("[role='menu']").hidden = true;
    picker.querySelector(".settings-choice-trigger").setAttribute("aria-expanded", "false");
  }

  choice(parent, name, label, value, options, onChange = null) {
    const wrapper = document.createElement("div");
    wrapper.className = "field settings-choice";
    const title = document.createElement("span");
    title.id = `provider-${name}-label`; title.textContent = label;
    const trigger = document.createElement("button");
    trigger.type = "button"; trigger.id = `provider-${name}`;
    trigger.className = "settings-choice-trigger";
    trigger.value = value;
    trigger.setAttribute("aria-labelledby", `${title.id} ${trigger.id}-value`);
    trigger.setAttribute("aria-haspopup", "menu");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", `${trigger.id}-menu`);
    const selected = document.createElement("span");
    selected.id = `${trigger.id}-value`;
    selected.textContent = options.find(([key]) => key === value)?.[1] || value;
    const arrow = document.createElement("span");
    arrow.textContent = "⌄"; arrow.setAttribute("aria-hidden", "true");
    trigger.append(selected, arrow);
    const menu = document.createElement("div");
    menu.id = `${trigger.id}-menu`; menu.className = "composer-menu settings-choice-menu";
    menu.setAttribute("role", "menu"); menu.setAttribute("aria-labelledby", title.id); menu.hidden = true;
    for (const [key, text] of options) {
      const option = document.createElement("button");
      option.type = "button"; option.value = key; option.textContent = text;
      option.setAttribute("role", "menuitemradio");
      option.setAttribute("aria-checked", String(key === value));
      option.addEventListener("click", () => {
        if (trigger.disabled) return;
        trigger.value = key; selected.textContent = text;
        for (const entry of menu.querySelectorAll("button")) entry.setAttribute("aria-checked", String(entry.value === key));
        this.closePicker(wrapper); trigger.focus(); onChange?.(key);
      });
      menu.appendChild(option);
    }
    const open = last => {
      if (trigger.disabled) return;
      this.panel.querySelectorAll(".settings-choice").forEach(picker => this.closePicker(picker));
      menu.hidden = false; trigger.setAttribute("aria-expanded", "true");
      const choices = [...menu.querySelectorAll("button")];
      (last ? choices.at(-1) : choices.find(entry => entry.value === trigger.value) || choices[0])?.focus();
    };
    trigger.addEventListener("click", () => menu.hidden ? open(false) : this.closePicker(wrapper));
    trigger.addEventListener("keydown", event => {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); open(event.key === "ArrowUp"); }
    });
    menu.addEventListener("keydown", event => {
      const choices = [...menu.querySelectorAll("button")];
      const index = choices.indexOf(document.activeElement);
      const next = { ArrowDown: (index + 1) % choices.length, ArrowUp: (index - 1 + choices.length) % choices.length, Home: 0, End: choices.length - 1 }[event.key];
      if (next !== undefined) { event.preventDefault(); choices[next]?.focus(); }
    });
    wrapper.addEventListener("focusout", event => {
      if (!wrapper.contains(event.relatedTarget)) this.closePicker(wrapper);
    });
    wrapper.append(title, trigger, menu); parent.appendChild(wrapper);
    this.inputs[name] = trigger;
  }

  render() {
    const form = document.getElementById("providers-form");
    form.textContent = "";
    this.inputs = {};
    const policy = this.data.policy;
    const models = settingsSection(form, "Models", "Choose a model for each kind of work");
    const options = document.createElement("div");
    options.className = "settings-fields";
    models.appendChild(options);
    this.field(options, "provider", "Provider", policy.provider, [["openai", "OpenAI"]]);
    this.field(options, "web_search_enabled", "Hosted web search", policy.web_search_enabled, [["true", "Enabled"], ["false", "Disabled"]]);
    for (const [role, title] of [["agent", "Chat and Debug"], ["search", "Web search"], ["knowledge", "Knowledge extraction"], ["legacy", "Legacy compatibility"]]) {
      const content = settingsSection(models, title, policy[role].model, role === "agent");
      const group = document.createElement("div");
      group.className = "settings-fields model-fields";
      content.appendChild(group);
      const catalog = [...new Set([policy[role].model, ...OPENAI_CHAT_MODELS])];
      this.choice(group, `${role}-model`, "Model", policy[role].model,
        catalog.map(model => [model, model]), model => {
          content.parentElement.querySelector(".settings-section-description").textContent = model;
        });
      const levels = ["minimal", "low", "medium", "high"];
      const effort = levels.includes(policy[role].reasoning_effort) ? policy[role].reasoning_effort : "medium";
      this.choice(group, `${role}-reasoning_effort`, "Thinking level", effort,
        levels.map(level => [level, level[0].toUpperCase() + level.slice(1)]));
    }
    this.remove.checked = false;
    this.status.textContent = this.data.credential_storage_available === false
      ? "Credential storage is locked. Rerun the secure installer to restore key storage."
      : `${this.data.active_credential_configured ? "API key active." : "No active API key."} ${this.data.usage.requests ? `${this.data.usage.requests} requests today. ` : ""}${this.data.restart_required ? "Saved changes pending. Restart KAI manually to activate them." : ""}`;
  }

  policy() {
    const value = name => this.inputs[name].value;
    const policy = { provider: value("provider"), web_search_enabled: value("web_search_enabled") === "true" };
    for (const role of ["agent", "search", "knowledge", "legacy"]) policy[role] = {
      model: value(`${role}-model`).trim(),
      max_output_tokens: 16000,
      reasoning_effort: value(`${role}-reasoning_effort`),
    };
    for (const name of ["requests_per_minute", "requests_per_day", "tokens_per_day", "max_concurrent_requests"]) policy[name] = this.data.policy[name] || 0;
    return policy;
  }

  async submit(save) {
    if (this.busy || !this.data) return;
    const body = { revision: this.data.revision, policy: this.policy(), remove_key: this.remove.checked };
    if (this.key.value) body.api_key = this.key.value;
    this.key.value = "";
    this.controls(true);
    this.status.textContent = "Checking provider access…";
    try {
      const result = await this.request(save ? "" : "/validate", save ? "PUT" : "POST", body);
      if (save) { this.data = result; this.render(); }
      else this.status.textContent = `${result.validation} Settings have not been saved. Re-enter a replacement key before saving. This check does not test generation, billing or tool compatibility.`;
    } catch (error) {
      this.status.textContent = `${error} Settings were not changed. Re-enter any replacement key before retrying.`;
    } finally { delete body.api_key; this.controls(false); }
  }
}
