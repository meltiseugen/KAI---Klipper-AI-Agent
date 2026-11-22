// Hardware source reviews and visually reviewed diagram notes.
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

  async submit(path, body) {
    const panel = this.panel;
    if (panel.busy) return;
    if (panel.dirty) { panel.status.textContent = "Save edited component details before recording source reviews or diagram notes."; return; }
    panel.lock(true);
    try {
      await panel.api(path, "POST", { ...body, revision: panel.setup.revision });
      await panel.load(true);
    } catch (error) { panel.status.textContent = `${error} Current observations were kept.`; panel.lock(false); }
  }

  render(payload) {
    const panel = this.panel, parent = panel.records;
    panel.fields = panel.fields.filter(field => !this.fields.has(field)); this.fields.clear();
    for (const [role, evidence] of Object.entries(payload.bus_evidence || {})) {
      if (!evidence.candidates.length) continue;
      const buses = settingsSection(parent, `${role}: hardware bus pins`, "Source quotes and your review");
      for (const item of evidence.candidates) panel.line(buses, `${item.bus}: ${item.pins.join(", ")} — ${item.quote}`, "blockquote");
      const reviewed = payload.setup.reviewed_bus_mappings?.[role] === evidence.signature;
      this.button(buses, reviewed ? "Bus evidence reviewed" : "I checked this exact hardware/firmware pinmux", () => this.submit("/review-buses", { role, signature: evidence.signature }), reviewed || evidence.conflicts.length > 0 || payload.profile_changed);
      if (evidence.conflicts.length) panel.line(buses, `Conflicting bus definitions: ${evidence.conflicts.join(", ")}. Review MCU variant and source conditions.`);
    }
    this.diagrams(payload, parent);
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
