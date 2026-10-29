// User-confirmed statements are separate from model answers and dated observations.
class PrinterMemoryPanel {
  constructor(transport, currentThread) {
    this.transport = transport;
    this.currentThread = currentThread;
    this.panel = document.getElementById("memory-panel");
    this.toggle = document.getElementById("memory-toggle");
    this.status = document.getElementById("memory-status");
    this.records = document.getElementById("memory-records");
    this.evidence = document.getElementById("memory-evidence");
    this.content = document.getElementById("memory-content");
    this.kind = document.getElementById("memory-kind");
    this.confirmed = document.getElementById("memory-confirmed");
    this.link = document.getElementById("memory-link");
    this.saveButton = document.getElementById("memory-save");
    this.busy = false;
    this.fields = [];
  }

  bind() {
    this.toggle.hidden = false;
    this.toggle.addEventListener("click", () => this.open());
    document.getElementById("memory-close").addEventListener("click", () => this.close());
    document.getElementById("memory-reload").addEventListener("click", () => this.load());
    this.saveButton.addEventListener("click", () => this.save());
    this.confirmed.addEventListener("change", () => this.update());
    this.content.addEventListener("input", () => { this.confirmed.checked = false; this.update(); });
    this.kind.addEventListener("change", () => { this.confirmed.checked = false; this.update(); });
    this.link.addEventListener("change", () => {
      this.confirmed.checked = false;
      this.evidence.hidden = !this.link.checked;
      this.update();
    });
    this.update();
  }

  update() {
    this.saveButton.disabled = this.busy || !this.confirmed.checked || !this.content.value.trim();
    this.content.disabled = this.kind.disabled = this.confirmed.disabled = this.busy;
    this.link.disabled = this.busy || !this.threadId;
    for (const field of this.fields) field.disabled = this.busy;
  }

  async open() {
    this.beforeOpen?.();
    this.panel.hidden = false;
    this.toggle.setAttribute("aria-expanded", "true");
    document.getElementById("conversation-panel").inert = true;
    document.getElementById("memory-close").focus();
    await this.load();
  }

  close() {
    this.panel.hidden = true;
    this.toggle.setAttribute("aria-expanded", "false");
    document.getElementById("conversation-panel").inert = false;
    focusPanelLauncher(this.toggle);
  }

  async load() {
    if (this.busy) return;
    this.busy = true;
    this.confirmed.checked = false;
    this.update();
    try {
      const entries = await (await this.transport.request("/memory")).json();
      this.records.replaceChildren();
      for (const entry of entries) this.append(entry);
      this.threadId = this.currentThread();
      const record = this.threadId ? await this.transport.investigation(`/${encodeURIComponent(this.threadId)}`) : null;
      this.evidence.replaceChildren();
      this.fields = [];
      const seen = new Set();
      for (const item of (record?.turns || []).flatMap(turn => turn.result.evidence || []).reverse()) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.id;
        input.addEventListener("change", () => { this.confirmed.checked = false; this.update(); });
        const text = document.createElement("span");
        text.textContent = `${item.source} — ${item.observed_at}: ${item.content.slice(0, 180)}`;
        label.appendChild(input); label.appendChild(text);
        this.evidence.appendChild(label);
        this.fields.push(input);
      }
      this.link.checked = Boolean(record);
      this.evidence.hidden = !record;
      this.status.textContent = `${entries.length} confirmed entries. Select up to six supporting observations, if available.`;
    } catch (error) {
      this.status.textContent = String(error);
      this.threadId = null; this.link.checked = false; this.evidence.hidden = true; this.fields = [];
    }
    finally { this.busy = false; this.update(); }
  }

  append(entry) {
    const article = document.createElement("article");
    article.className = "source-citation";
    const heading = document.createElement("h3");
    heading.textContent = `${{ fact: "Printer fact", preference: "Preference", resolution: "Incident resolution" }[entry.kind]} — confirmed ${entry.confirmed_at}`;
    const text = document.createElement("p");
    text.textContent = entry.content;
    article.appendChild(heading); article.appendChild(text);
    for (const item of entry.evidence || []) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${item.source} — observed ${item.observed_at}`;
      const content = document.createElement("pre");
      content.textContent = item.content;
      details.appendChild(summary); details.appendChild(content); article.appendChild(details);
    }
    const button = document.createElement("button");
    button.type = "button"; button.textContent = "Forget entry";
    button.addEventListener("click", async () => {
      if (this.busy) return;
      this.busy = true; button.disabled = true; this.update();
      try {
        await this.transport.request(`/memory/${encodeURIComponent(entry.id)}`, "DELETE");
        article.remove();
        this.status.textContent = "Entry forgotten. Earlier chat messages remain in history.";
      } catch (error) { this.status.textContent = String(error); }
      finally { this.busy = false; button.disabled = false; this.update(); }
    });
    article.appendChild(button); this.records.appendChild(article);
  }

  async save() {
    if (this.busy || this.saveButton.disabled) return;
    const evidenceIds = this.link.checked ? this.fields.filter(item => item.checked).map(item => item.value) : [];
    if (evidenceIds.length > 6) { this.status.textContent = "Select at most six observations."; return; }
    this.busy = true; this.update();
    try {
      await this.transport.request("/memory", "POST", {
        kind: this.kind.value, content: this.content.value.trim(), confirmed: this.confirmed.checked,
        investigation_id: this.link.checked ? this.threadId : null, evidence_ids: evidenceIds,
      });
      this.content.value = ""; this.confirmed.checked = false;
    } catch (error) { this.status.textContent = String(error); return; }
    finally { this.busy = false; this.update(); }
    await this.load();
  }
}
