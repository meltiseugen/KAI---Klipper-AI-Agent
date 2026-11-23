// Application-owned knowledge details and explicit public-document refreshes.
function knowledgeComponentDescription(component, components) {
  if (!component.integrated_into) return component.model || "Add hardware identity and connection";
  const board = components.find(entry => entry.role === component.integrated_into);
  const model = component.model && !/^(none|unknown)$/i.test(component.model.trim()) ? component.model : "";
  return `Built into ${component.integrated_into}${board?.model ? ` · ${board.model}` : ""}${model ? ` · ${model}` : ""}`;
}

class PrinterKnowledgePanel {
  constructor(transport, schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id)) {
    this.transport = transport;
    this.schedule = schedule;
    this.cancel = cancel;
    this.panel = document.getElementById("knowledge-panel");
    this.toggle = document.getElementById("knowledge-toggle");
    this.form = document.getElementById("knowledge-form");
    this.status = document.getElementById("knowledge-status");
    this.records = document.getElementById("knowledge-records");
    this.saveButton = document.getElementById("knowledge-save");
    this.refreshButton = document.getElementById("knowledge-refresh");
    this.reloadButton = document.getElementById("knowledge-reload");
    this.addButton = document.getElementById("knowledge-add");
    this.reviewButtons = [];
    this.references = new KnowledgeReferences(this);
    this.actions = new KnowledgeActions(this);
    this.busy = false;
    this.setup = null;
    this.fields = [];
    this.timer = null;
    this.loading = false;
    this.saving = false;
  }

  bind() {
    this.toggle.hidden = false;
    this.toggle.addEventListener("click", () => this.open());
    document.getElementById("knowledge-close").addEventListener("click", () => this.close());
    this.saveButton.addEventListener("click", () => this.save(false));
    this.refreshButton.addEventListener("click", () => this.save(true));
    this.reloadButton.addEventListener("click", () => this.load(true));
    this.addButton.addEventListener("click", () => this.addComponent());
  }

  async api(path = "", method = "GET", body = null) {
    return (await this.transport.request(`/knowledge${path}`, method, body)).json();
  }

  async open() {
    this.beforeOpen?.();
    this.panel.hidden = false;
    this.toggle.setAttribute("aria-expanded", "true");
    document.getElementById("conversation-panel").inert = true;
    document.getElementById("knowledge-close").focus();
    if (!this.saving) await this.load(!this.setup);
  }

  close() {
    this.panel.hidden = true;
    this.toggle.setAttribute("aria-expanded", "false");
    this.cancel(this.timer);
    document.getElementById("conversation-panel").inert = false;
    focusPanelLauncher(this.toggle);
  }

  lock(value) {
    this.busy = value;
    for (const field of this.fields) field.disabled = value;
    this.saveButton.disabled = value || !this.setup;
    this.refreshButton.disabled = value || !this.setup;
    this.reloadButton.disabled = value;
    this.addButton.disabled = value || !this.setup || this.components?.length >= 12;
    for (const button of this.reviewButtons) button.disabled = value || button.dataset.blocked === "true";
  }

  async load(replaceForm = false) {
    if (this.loading) return;
    this.loading = true;
    this.cancel(this.timer);
    this.lock(true);
    try {
      const payload = await this.api();
      if (replaceForm) this.renderForm(payload.setup);
      this.renderStatus(payload);
      this.lock(payload.job.state === "running");
      if (payload.job.state === "running" && !this.panel.hidden) {
        this.timer = this.schedule(() => this.load(false), 1500);
      }
    } catch (error) {
      this.status.textContent = `${error} Details were kept. Reload to check the refresh status.`;
      this.lock(false);
    } finally { this.loading = false; }
  }

  input(parent, label, value, options = null, type = "text", maxLength = 120) {
    const wrapper = document.createElement("label");
    wrapper.className = "field";
    const caption = document.createElement("span");
    caption.textContent = label;
    const input = document.createElement(options ? "select" : type === "textarea" ? "textarea" : "input");
    if (options) {
      for (const item of options) {
        const option = document.createElement("option");
        option.value = item;
        option.textContent = item;
        input.appendChild(option);
      }
    } else {
      if (type !== "textarea") input.type = type;
      input.maxLength = maxLength;
    }
    if (type === "checkbox") input.checked = Boolean(value);
    else input.value = value || "";
    wrapper.appendChild(caption);
    wrapper.appendChild(input);
    parent.appendChild(wrapper);
    this.fields.push(input);
    input.addEventListener("input", () => { this.dirty = true; });
    input.addEventListener("change", () => { this.dirty = true; });
    return input;
  }

  renderForm(setup) {
    const sections = settingsSectionState(this.form);
    this.setup = setup;
    this.form.textContent = "";
    this.fields = [];
    this.references.slots = [];
    this.dirty = false;
    this.printerModel = this.input(this.form, "Printer model (helps distinguish vendor variants)", setup.printer_model);
    this.components = setup.components.map((item, index) => {
      const role = item.role;
      const content = settingsSection(this.form, role, knowledgeComponentDescription(item, setup.components));
      const group = this.line(content, "", "div");
      group.className = "settings-fields";
      let installation;
      if (role === "accelerometer" || item.integrated_into) {
        installation = this.input(group, "Installation", "", []);
        const separate = this.line(installation, "Separate / not specified", "option"); separate.value = "";
        for (const board of setup.components.filter(entry => entry.category === "board" && entry.role !== role)) {
          const option = this.line(installation, `Built into ${board.role}${board.model ? ` · ${board.model}` : ""}`, "option"); option.value = board.role;
        }
        installation.value = item.integrated_into || "";
      }
      const fields = {
        role: this.input(group, "Component name (unique, lowercase, no spaces)", role, null, "text", 40),
        category: this.input(group, "Component type", item.category || "board", ["board", "probe", "device"]),
        manufacturer: this.input(group, "Manufacturer", item.manufacturer, null, "text", 80),
        model: this.input(group, item.integrated_into ? "Sensor model (if known)" : "Exact model", item.model),
        revision: this.input(group, "Hardware revision", item.revision, null, "text", 30),
        mcu: this.input(group, "Klipper MCU name (mcu for [mcu])", item.mcu, null, "text", 60),
        connection: this.input(group, "Connection", item.connection || "unknown", ["unknown", "USB", "CAN", "UART", "I2C", "SPI"]),
        confirmed: this.input(group, "I checked this identity and connection", item.confirmed, null, "checkbox"),
        details: this.input(group, "Component details", item.details || "", null, "textarea", 3000),
      };
      fields.details.classList.add("component-details-input");
      fields.details.placeholder = "Describe this component's setup, modifications, or details KAI should consider when researching documentation and answering questions.";
      if (installation) {
        fields.integratedInto = installation;
        installation.addEventListener("change", () => {
          if (installation.value && /^(none|unknown|not installed)$/i.test(fields.model.value.trim())) fields.model.value = "";
          fields.model.parentElement.querySelector("span").textContent = installation.value ? "Sensor model (if known)" : "Exact model";
          content.parentElement.querySelector(".settings-section-description").textContent = knowledgeComponentDescription({ model: fields.model.value, integrated_into: installation.value }, setup.components);
        });
      }
      const actions = this.line(group, "", "div"); actions.className = "actions component-actions";
      const research = this.line(actions, "Research", "button");
      research.type = "button";
      research.className = "secondary-button";
      research.title = "Save current details and research only this component";
      research.addEventListener("click", () => this.save(true, fields.role.value.trim()));
      this.fields.push(research);
      const remove = this.line(actions, "Remove component", "button");
      remove.type = "button";
      remove.className = "quiet-button";
      remove.addEventListener("click", () => {
        if (this.busy) return;
        const values = this.values();
        const dependent = values.components.find(entry => entry.integrated_into === values.components[index].role);
        if (dependent) { this.status.textContent = `Change ${dependent.role}'s installation before removing this board.`; return; }
        values.components.splice(index, 1);
        this.renderForm(values);
        this.dirty = true;
        this.lock(false);
      });
      this.fields.push(remove);
      this.references.attach(content, fields);
      return fields;
    });
    const firmware = this.line(settingsSection(this.form, "Firmware", setup.firmware_flavor || "Installed version and exact source"), "", "div");
    firmware.className = "settings-fields";
    this.flavor = this.input(firmware, "Installed firmware / fork", setup.firmware_flavor, null, "text", 80);
    this.version = this.input(firmware, "Installed firmware version / commit", setup.firmware_version);
    this.firmwareRepository = this.input(firmware, "Optional exact firmware source repository (https://github.com/owner/repo)", setup.firmware_repository, null, "text", 200);
    this.firmwareCommit = this.input(firmware, "Full 40-character firmware commit (no branch/tag fallback)", setup.firmware_commit, null, "text", 40);
    this.facts = this.input(settingsSection(this.form, "Personal touches", "Describe custom modifications"), "Custom modifications and improvements", setup.facts, null, "textarea", 3000);
    this.facts.classList.add("personal-touches-input");
    this.facts.placeholder = "Describe modifications, upgrades, or custom improvements you have added to your printer.";
    restoreSettingsSections(this.form, sections);
  }

  values() {
    const roles = new Map(this.setup.components.map((item, index) => [item.role, this.components[index].role.value.trim()]));
    return { ...this.setup,
      printer_model: this.printerModel.value.trim(),
      components: this.components.map((item, index) => ({ role: item.role.value.trim(), category: item.category.value, manufacturer: item.manufacturer.value.trim(), model: item.model.value.trim(),
        revision: item.revision.value.trim(), mcu: item.mcu.value.trim(),
        connection: item.connection.value, confirmed: item.confirmed.checked,
        integrated_into: roles.get(item.integratedInto?.value) || item.integratedInto?.value || "",
        details: item.details.value.trim(),
        reference_urls: [...(this.setup.components[index]?.reference_urls || [])] })),
      firmware_flavor: this.flavor.value.trim(), firmware_version: this.version.value.trim(), facts: this.facts.value.trim(),
      firmware_repository: this.firmwareRepository.value.trim(), firmware_commit: this.firmwareCommit.value.trim(),
    };
  }

  addComponent() {
    if (this.busy || !this.setup || this.components.length >= 12) return;
    const values = this.values();
    let number = 1;
    while (values.components.some(item => item.role === `component_${number}`)) number++;
    values.components.push({ role: `component_${number}`, category: "device", model: "" });
    this.renderForm(values);
    this.dirty = true;
    this.lock(false);
  }

  async review(role, signature) {
    if (this.busy) return;
    if (this.dirty) { this.status.textContent = "Save your edited details before reviewing connector evidence."; return; }
    this.lock(true);
    try {
      this.setup = await this.api("/review-mappings", "POST", { role, signature, revision: this.setup.revision });
      await this.load(false);
    } catch (error) { this.status.textContent = `${error} Reload details and review the current sources.`; this.lock(false); }
  }

  async save(refresh, role = null) {
    if (this.busy || !this.setup) return;
    this.saving = true;
    this.lock(true);
    this.status.textContent = "Saving printer knowledge details…";
    try {
      this.setup = await this.api("/details", "PUT", { setup: this.values() });
      this.renderForm(this.setup);
      this.lock(true);
      if (refresh) await this.api("/refresh", "POST", role ? { role } : {});
      await this.load(false);
      if (!refresh) this.status.textContent = "Details saved. Build or refresh documentation when ready.";
    } catch (error) {
      this.status.textContent = `${error} Details were kept. If another window changed them, Reload details before saving again.`;
      this.lock(false);
    } finally { this.saving = false; }
  }

  line(parent, text, tag = "p") {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  renderStatus(payload) {
    const sections = settingsSectionState(this.records);
    const job = payload.job;
    this.status.textContent = `${job.message} ${job.state === "running" ? `${job.completed}/${job.total}` : ""}`;
    this.refreshButton.textContent = payload.documents.length ? "Refresh knowledge" : "Build printer knowledge";
    this.records.textContent = "";
    this.reviewButtons = [];
    this.references.renderComponents(payload);
    this.references.renderLibrary(this.records, payload);
    this.actions.render(payload);
    restoreSettingsSections(this.records, sections);
  }

  async download(id) {
    try {
      const response = await this.transport.request(`/knowledge/documents/${encodeURIComponent(id)}`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] || `${id}.txt`;
      link.click();
      this.schedule(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { this.status.textContent = String(error); }
  }
}
