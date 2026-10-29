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
      this.field(group, `${role}-model`, "Model ID", policy[role].model);
      this.field(group, `${role}-max_output_tokens`, "Maximum output tokens", policy[role].max_output_tokens, null, [256, 16000]);
      this.field(group, `${role}-reasoning_effort`, "Reasoning effort", policy[role].reasoning_effort,
        ["default", "none", "minimal", "low", "medium", "high"].map(value => [value, value === "default" ? "Model default" : value]));
    }
    const limits = settingsSection(form, "Usage limits", "Request frequency and daily token budgets");
    const budgets = document.createElement("div");
    budgets.className = "settings-fields";
    limits.appendChild(budgets);
    for (const [name, title, min, max] of [
      ["requests_per_minute", "Requests per minute", 1, 120],
      ["requests_per_day", "Requests per UTC day", 1, 10000],
      ["tokens_per_day", "Token budget per UTC day", 1000, 100000000],
      ["max_concurrent_requests", "Concurrent provider requests", 1, 8],
    ]) this.field(budgets, name, title, policy[name], null, [min, max]);
    const help = document.createElement("p");
    help.className = "field-help";
    help.textContent = "Limits cover all model requests and research, including failed or interrupted calls. Token budgets are not a dollar spending cap. Hosted search may add charges; set spending limits at OpenAI.";
    limits.appendChild(help);
    this.remove.checked = false;
    this.status.textContent = this.data.credential_storage_available === false
      ? "Credential storage is locked. Rerun the secure installer to restore key storage."
      : `${this.data.active_credential_configured ? "API key active." : "No active API key."} ${this.data.usage.requests ? `${this.data.usage.requests} requests today. ` : ""}${this.data.restart_required ? "Saved changes pending. Restart KlipperAI manually to activate them." : ""}`;
  }

  policy() {
    const value = name => this.inputs[name].value;
    const policy = { provider: value("provider"), web_search_enabled: value("web_search_enabled") === "true" };
    for (const role of ["agent", "search", "knowledge", "legacy"]) policy[role] = {
      model: value(`${role}-model`).trim(),
      max_output_tokens: Number(value(`${role}-max_output_tokens`)),
      reasoning_effort: value(`${role}-reasoning_effort`),
    };
    for (const name of ["requests_per_minute", "requests_per_day", "tokens_per_day", "max_concurrent_requests"]) policy[name] = Number(value(name));
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
