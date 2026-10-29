// Explicit physical observations and live checks. No printer commands are sent.
class KnowledgeActions {
  constructor(panel) { this.panel = panel; this.fields = new Set(); }

  field(parent, label, value = "", options = null, type = "text") {
    const panel = this.panel;
    const wrapper = panel.line(parent, "", "label"); wrapper.className = "field";
    panel.line(wrapper, label, "span");
    const input = document.createElement(options ? "select" : "input");
    if (!options) { input.type = type; input.maxLength = 2000; }
    if (options) for (const value of options) {
      const option = panel.line(input, value, "option"); option.value = value;
    }
    if (type === "checkbox") input.checked = Boolean(value); else input.value = value;
    wrapper.appendChild(input); panel.fields.push(input); this.fields.add(input);
    return input;
  }

  button(parent, label, action, blocked = false) {
    const button = this.panel.line(parent, label, "button"); button.type = "button";
    button.className = "secondary-button";
    button.dataset.blocked = String(blocked);
    button.addEventListener("click", action); this.panel.reviewButtons.push(button);
    return button;
  }

  async submit(path, body, provider = false) {
    const panel = this.panel;
    if (panel.busy) return;
    if (panel.dirty) { panel.status.textContent = "Save edited component details before recording observations or running validation."; return; }
    panel.lock(true);
    try {
      const result = provider ? await (await panel.transport.request("/providers/probe", "POST", {})).json() : await panel.api(path, "POST", { ...body, ...(!["/validate"].includes(path) ? { revision: panel.setup.revision } : {}) });
      if (path === "/validate" || provider) this.lastCheck = result;
      await panel.load(true);
      if (this.lastCheck) panel.status.textContent = this.lastCheck.message || `Live printer read: ${this.lastCheck.printer_reachable ? "reachable" : "unavailable"}. Physical wiring remains user-verified.`;
    } catch (error) { panel.status.textContent = `${error} Current observations were kept.`; panel.lock(false); }
  }

  render(payload) {
    const panel = this.panel, parent = panel.records;
    panel.fields = panel.fields.filter(field => !this.fields.has(field)); this.fields.clear();
    const checks = settingsSection(parent, "Connection checks", "Read printer status or test provider access");
    panel.line(checks, "Checks use the configured connections. The provider check sends a fixed public prompt, uses provider credits, and sends no printer data. Printer checks only read state.");
    const actions = panel.line(checks, "", "div"); actions.className = "actions";
    this.button(actions, "Check live printer", () => this.submit("/validate", {}));
    this.button(actions, "Check live provider response", () => this.submit("/probe", {}, true));
    const report = payload.setup.validation;
    if (report?.checked_at) {
      panel.line(checks, `Last printer check: ${report.checked_at}; reachable: ${report.printer_reachable}.`);
      for (const gap of report.gaps || []) panel.line(checks, gap);
    }
    for (const [role, evidence] of Object.entries(payload.bus_evidence || {})) {
      if (!evidence.candidates.length) continue;
      const buses = settingsSection(parent, `${role}: hardware bus pins`, "Source quotes and your review");
      for (const item of evidence.candidates) panel.line(buses, `${item.bus}: ${item.pins.join(", ")} — ${item.quote}`, "blockquote");
      const reviewed = payload.setup.reviewed_bus_mappings?.[role] === evidence.signature;
      this.button(buses, reviewed ? "Bus evidence reviewed" : "I checked this exact hardware/firmware pinmux", () => this.submit("/review-buses", { role, signature: evidence.signature }), reviewed || evidence.conflicts.length > 0 || payload.profile_changed);
      if (evidence.conflicts.length) panel.line(buses, `Conflicting bus definitions: ${evidence.conflicts.join(", ")}. Review MCU variant and source conditions.`);
    }
    this.inventory(payload, parent);
    this.diagrams(payload, parent);
  }

  inventory(payload, parent) {
    const panel = this.panel;
    parent = settingsSection(parent, "Physical connector inventory", "Record connectors you have checked on the printer");
    panel.line(parent, "Unused config pins do not prove a connector is free. Record what you physically checked, with power off where appropriate.");
    for (const entries of Object.values(payload.connector_inventory || {})) for (const item of entries) panel.line(parent,
      `${item.role} / ${item.connector}: ${item.stale ? "stale identity; recheck" : item.occupancy}; ${item.attached_device || "no device recorded"}; electrical: ${item.electrical_confirmed ? item.electrical_notes : "unconfirmed"}; observed ${item.observed_at}`);
    const group = panel.line(parent, "", "fieldset"); group.className = "settings-fields";
    panel.line(group, "Confirm a physical observation", "legend");
    const roles = payload.setup.components.map(item => item.role);
    const role = this.field(group, "Component", roles[0] || "", roles);
    const connector = this.field(group, "Exact connector label");
    const occupancy = this.field(group, "Observed occupancy", "unknown", ["unknown", "free", "occupied"]);
    const device = this.field(group, "Attached device (required when occupied)");
    const electrical = this.field(group, "Checked voltage/current, connector and device requirements");
    const electricalConfirmed = this.field(group, "I verified these electrical requirements", false, null, "checkbox");
    const confirmed = this.field(group, "I physically checked this connector and confirm this observation", false, null, "checkbox");
    this.button(group, "Record connector observation", () => {
      if (!confirmed.checked) { panel.status.textContent = "Explicit physical observation confirmation is required."; return; }
      void this.submit("/connectors", { observation: { role: role.value, connector: connector.value.trim(), occupancy: occupancy.value, attached_device: device.value.trim(), electrical_notes: electrical.value.trim(), electrical_confirmed: electricalConfirmed.checked, confirmed: true } });
    }, !roles.length);
  }

  diagrams(payload, parent) {
    const panel = this.panel;
    for (const doc of payload.documents.filter(item => item.pages?.length)) {
      const diagrams = settingsSection(parent, `${doc.title}: diagrams`, "PDF page index and visually reviewed notes");
      for (const page of doc.pages) panel.line(diagrams, `Page ${page.page}: ${page.images} image/form references, ${page.vector_paths} drawing paths. ${(page.diagram_labels || []).join("; ") || "No diagram caption detected."} Visual review required.`);
      for (const note of payload.setup.diagram_notes || []) if (note.document_id === doc.id) panel.line(diagrams, `User-confirmed page ${note.page} note${note.digest !== doc.digest ? " (stale source)" : ""}: ${note.text}`);
      const group = panel.line(diagrams, "", "fieldset"); group.className = "settings-fields";
      panel.line(group, "Index a visually reviewed diagram", "legend");
      const page = this.field(group, "PDF page", String(doc.pages[0].page), doc.pages.map(item => String(item.page)));
      const text = this.field(group, "Diagram description or labels you verified");
      const confirmed = this.field(group, "I checked this page in the cached source", false, null, "checkbox");
      this.button(group, "Record diagram note", () => {
        if (!confirmed.checked) { panel.status.textContent = "Confirm visual review of the cached page first."; return; }
        void this.submit("/diagram-notes", { observation: { document_id: doc.id, digest: doc.digest, page: Number(page.value), text: text.value.trim(), confirmed: true } });
      });
    }
  }
}
