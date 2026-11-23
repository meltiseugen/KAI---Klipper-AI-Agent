// Component-linked references and the shared library; all actions are user-triggered.
class KnowledgeReferences {
  constructor(panel) { this.panel = panel; this.slots = []; }

  attach(parent, fields) {
    const container = this.panel.line(parent, "", "div");
    container.className = "component-references";
    const summary = parent.parentElement.querySelector(".settings-section-description");
    this.slots.push({ fields, container, summary, description: summary.textContent });
  }

  button(parent, label, action, blocked = false) {
    const button = this.panel.line(parent, label, "button");
    button.type = "button";
    button.className = "secondary-button";
    button.dataset.blocked = String(blocked);
    button.addEventListener("click", action);
    this.panel.reviewButtons.push(button);
    return button;
  }

  card(parent, doc) {
    const state = doc.confirmed ? "Confirmed reference" : doc.confirmation_stale ? "Source changed · confirm again" : "Discovered reference · needs review";
    const content = settingsSection(parent, doc.title, state);
    content.parentElement.dataset.settingsSection = `reference:${doc.id}`;
    const roles = doc.component_roles || [];
    this.panel.line(content, roles.length ? `Linked to: ${roles.join(", ")}` : "Other reference");
    this.panel.line(content, `Retrieved ${doc.fetched_at} · SHA-256 ${doc.digest.slice(0, 12)}`);
    if (doc.excerpt) {
      const preview = this.panel.line(content, doc.excerpt, "blockquote");
      preview.className = "reference-preview";
    }
    const actions = this.panel.line(content, "", "div"); actions.className = "actions";
    const source = this.panel.line(actions, "Open source", "a");
    source.href = doc.url; source.target = "_blank"; source.rel = "noopener noreferrer";
    this.button(actions, "Download", () => this.panel.download(doc.id));
    this.button(actions, doc.confirmed ? "Confirmed" : "Confirm reference", () => this.change(doc, false), doc.confirmed);
    const remove = this.button(actions, "Delete", () => this.change(doc, true));
    remove.setAttribute("aria-label", `Delete reference: ${doc.title}`);
  }

  renderComponents(payload) {
    for (const slot of this.slots) {
      const state = settingsSectionState(slot.container);
      const role = slot.fields.role.value.trim();
      const docs = payload.documents.filter(doc => doc.component_roles?.includes(role));
      slot.container.textContent = "";
      this.panel.line(slot.container, `References (${docs.length})`, "h3");
      const confirmed = docs.filter(doc => doc.confirmed).length;
      slot.summary.textContent = `${slot.description}${docs.length ? ` · ${docs.length} references · ${confirmed} confirmed` : ""}`;
      if (!docs.length) this.panel.line(slot.container, "No references yet. Use Research to find documentation for this component.");
      for (const doc of docs) this.card(slot.container, doc);
      const item = payload.components.find(entry => entry.role === role);
      if (item) {
        for (const gap of item.gaps || []) this.panel.line(slot.container, gap);
        this.evidence(slot.container, item, payload);
      }
      restoreSettingsSections(slot.container, state);
    }
  }

  evidence(parent, item, payload) {
    const evidence = item.fan_evidence;
    if (!evidence?.candidates.length) return;
    const content = settingsSection(parent, "Connector evidence", "Review quoted mappings for this hardware");
    for (const candidate of evidence.candidates) {
      this.panel.line(content, `${candidate.connector}: ${candidate.pin} — ${candidate.electrical || "Verify electrical limits in the source."}`);
      this.panel.line(content, candidate.quote, "blockquote");
      const link = this.panel.line(content, "Review source", "a");
      link.href = candidate.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    }
    if (evidence.conflicts.length) this.panel.line(content, `Conflicting connectors: ${evidence.conflicts.join(", ")}. Resolve the source/variant mismatch first.`);
    const component = payload.setup.components.find(entry => entry.role === item.role);
    this.button(content, item.fan_mappings_reviewed ? "Connector evidence reviewed" : "I verified these sources and connector mappings",
      () => this.panel.review(item.role, evidence.signature),
      item.fan_mappings_reviewed || evidence.conflicts.length > 0 || !component.confirmed || !component.revision || payload.profile_changed);
  }

  renderLibrary(parent, payload) {
    const library = settingsSection(parent, "Reference library", `${payload.documents.length} cached documents · Linked component and other references`);
    this.panel.line(library, "Confirm references you have reviewed. Changed sources need confirmation again. Deleted references stay excluded from subsequent research for the same component.");
    if (!payload.automatic_research) this.panel.line(library, "Connect the configured model provider and enable web search for automatic discovery.");
    if (payload.profile_changed) this.panel.line(library, "The saved printer profile changed. Recheck component identities, then save these details.");
    for (const doc of payload.documents) this.card(library, doc);
    for (const change of payload.job.changes || []) this.panel.line(library, change);
  }

  async change(doc, remove) {
    const panel = this.panel;
    if (panel.busy) return;
    if (panel.dirty) { panel.status.textContent = "Save edited details before confirming or deleting references."; return; }
    panel.lock(true);
    try {
      panel.setup = await panel.api(`/documents/${encodeURIComponent(doc.id)}${remove ? "" : "/confirm"}`, remove ? "DELETE" : "POST", { digest: doc.digest, revision: panel.setup.revision });
      await panel.load(false);
      panel.status.textContent = remove ? "Reference deleted. Future research will keep this source excluded for the same component." : "Reference confirmed for this cached version.";
    } catch (error) { panel.status.textContent = `${error} Reload references before retrying.`; panel.lock(false); }
  }
}
