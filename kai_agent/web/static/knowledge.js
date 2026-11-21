// Application-owned knowledge details and explicit public-document refreshes.
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
    this.dirty = false;
    this.printerModel = this.input(this.form, "Printer model (helps distinguish vendor variants)", setup.printer_model);
    this.components = setup.components.map((item, index) => {
      const role = item.role;
      const content = settingsSection(this.form, role, item.model || "Add hardware identity and connection");
      const group = this.line(content, "", "div");
      group.className = "settings-fields";
      const fields = {
        role: this.input(group, "Component name (unique, lowercase, no spaces)", role, null, "text", 40),
        category: this.input(group, "Component type", item.category || "board", ["board", "probe", "device"]),
        manufacturer: this.input(group, "Manufacturer", item.manufacturer, null, "text", 80),
        model: this.input(group, "Exact model", item.model),
        revision: this.input(group, "Hardware revision", item.revision, null, "text", 30),
        mcu: this.input(group, "Klipper MCU name (mcu for [mcu])", item.mcu, null, "text", 60),
        connection: this.input(group, "Connection", item.connection || "unknown", ["unknown", "USB", "CAN", "UART", "I2C", "SPI"]),
        confirmed: this.input(group, "I checked this identity and connection", item.confirmed, null, "checkbox"),
        references: this.input(group, "Optional public documentation URLs (up to 3, one per line)", (item.reference_urls || []).join("\n"), null, "textarea", 6146),
      };
      const remove = this.line(group, "Remove component", "button");
      remove.type = "button";
      remove.className = "quiet-button";
      remove.addEventListener("click", () => {
        if (this.busy) return;
        const values = this.values();
        values.components.splice(index, 1);
        this.renderForm(values);
        this.dirty = true;
        this.lock(false);
      });
      this.fields.push(remove);
      return fields;
    });
    const firmware = this.line(settingsSection(this.form, "Firmware", setup.firmware_flavor || "Installed version and exact source"), "", "div");
    firmware.className = "settings-fields";
    this.flavor = this.input(firmware, "Installed firmware / fork", setup.firmware_flavor, null, "text", 80);
    this.version = this.input(firmware, "Installed firmware version / commit", setup.firmware_version);
    this.firmwareRepository = this.input(firmware, "Optional exact firmware source repository (https://github.com/owner/repo)", setup.firmware_repository, null, "text", 200);
    this.firmwareCommit = this.input(firmware, "Full 40-character firmware commit (no branch/tag fallback)", setup.firmware_commit, null, "text", 40);
    this.facts = this.input(settingsSection(this.form, "Wiring and past resolutions", "Details you have confirmed"), "Confirmed wiring details and past resolutions", setup.facts, null, "textarea", 3000);
    restoreSettingsSections(this.form, sections);
  }

  values() {
    return { ...this.setup,
      printer_model: this.printerModel.value.trim(),
      components: this.components.map(item => ({ role: item.role.value.trim(), category: item.category.value, manufacturer: item.manufacturer.value.trim(), model: item.model.value.trim(),
        revision: item.revision.value.trim(), mcu: item.mcu.value.trim(),
        connection: item.connection.value, confirmed: item.confirmed.checked,
        reference_urls: item.references.value.split("\n").map(value => value.trim()).filter(Boolean) })),
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

  async save(refresh) {
    if (this.busy || !this.setup) return;
    this.saving = true;
    this.lock(true);
    this.status.textContent = "Saving printer knowledge details…";
    try {
      this.setup = await this.api("/details", "PUT", { setup: this.values() });
      this.dirty = false;
      if (refresh) await this.api("/refresh", "POST", {});
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
    const library = settingsSection(this.records, "Reference library", `${payload.documents.length} cached document${payload.documents.length === 1 ? "" : "s"} · Component research and sources`);
    if (!payload.automatic_research) this.line(library, "Automatic discovery requires the configured agent and web-search provider. You can supply public documentation URLs to cache references without search.");
    if (payload.profile_changed) this.line(library, "The saved printer profile changed. Recheck component identities, then save these details.");
    if (payload.setup.updated_at) this.line(library, `Details confirmed/saved: ${payload.setup.updated_at}`);
    for (const item of payload.components) {
      const record = this.line(library, "", "section");
      record.className = "component-record";
      this.line(record, `${item.role}: ${item.model || "Not specified"} — ${item.status}`, "h3");
      for (const gap of item.gaps) this.line(record, gap);
      if (!item.document_ids.length) this.line(record, "No documents cached for this identity yet.");
      const evidence = item.fan_evidence;
      if (evidence.candidates.length) {
        this.line(record, "Candidate fan mappings: check the original sources match this board and revision before confirming.");
        for (const candidate of evidence.candidates) {
          this.line(record, `${candidate.connector}: ${candidate.pin} — ${candidate.electrical || "Verify electrical limits in the source."}`);
          this.line(record, candidate.quote, "blockquote");
          const link = this.line(record, "Review source", "a");
          link.href = candidate.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
        if (evidence.conflicts.length) this.line(record, `Conflicting connectors: ${evidence.conflicts.join(", ")}. Resolve the source/variant mismatch first.`);
        const button = this.line(record, item.fan_mappings_reviewed ? "Connector evidence reviewed" : "I verified these sources and connector mappings", "button");
        button.className = "secondary-button";
        button.type = "button";
        const component = payload.setup.components.find(component => component.role === item.role);
        button.dataset.blocked = String(item.fan_mappings_reviewed || evidence.conflicts.length > 0 || !component.confirmed || !component.revision || payload.profile_changed);
        button.addEventListener("click", () => this.review(item.role, evidence.signature));
        this.reviewButtons.push(button);
      }
    }
    for (const doc of payload.documents) {
      const row = this.line(library, "", "section");
      row.className = "component-record";
      this.line(row, doc.title, "h3");
      this.line(row, `Retrieved ${doc.fetched_at} · SHA-256 ${doc.digest.slice(0, 12)}`);
      const actions = this.line(row, "", "div"); actions.className = "actions";
      const source = this.line(actions, "Source document", "a");
      source.href = doc.url;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      const button = this.line(actions, "Download cached copy", "button");
      button.type = "button";
      button.className = "secondary-button";
      button.addEventListener("click", () => this.download(doc.id));
    }
    for (const change of job.changes) this.line(library, change);
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
