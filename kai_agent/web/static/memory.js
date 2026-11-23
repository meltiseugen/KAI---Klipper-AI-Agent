// Review and edit conversational memory. Saving from chat is application-owned.
function memoryDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

class PrinterMemoryPanel {
  constructor(transport) {
    this.transport = transport;
    this.panel = document.getElementById('memory-panel');
    this.toggle = document.getElementById('memory-toggle');
    this.status = document.getElementById('memory-status');
    this.records = document.getElementById('memory-records');
    this.reload = document.getElementById('memory-reload');
    this.busy = false;
  }
  bind() {
    this.toggle.hidden = false;
    this.toggle.addEventListener('click', () => this.open());
    document.getElementById('memory-close').addEventListener('click', () => this.close());
    this.reload.addEventListener('click', () => this.load());
  }
  lock(busy) {
    this.busy = busy; this.reload.disabled = busy;
    for (const control of this.records.querySelectorAll('button, textarea')) control.disabled = busy;
  }
  async open() {
    this.beforeOpen?.(); this.panel.hidden = false;
    this.toggle.setAttribute('aria-expanded', 'true');
    document.getElementById('conversation-panel').inert = true;
    document.getElementById('memory-close').focus();
    await this.load();
  }
  close() {
    this.panel.hidden = true; this.toggle.setAttribute('aria-expanded', 'false');
    document.getElementById('conversation-panel').inert = false;
    focusPanelLauncher(this.toggle);
  }
  async load() {
    if (this.busy) return;
    this.lock(true); this.status.textContent = 'Loading memories…';
    try {
      const entries = await (await this.transport.request('/memory')).json();
      this.records.replaceChildren();
      for (const entry of entries) this.append(entry);
      this.status.textContent = entries.length ? `${entries.length} saved ${entries.length === 1 ? 'memory' : 'memories'}.`
        : 'No saved memories yet. Tell KAI: “Remember that I prefer one troubleshooting step at a time.”';
    } catch (error) { this.status.textContent = String(error); }
    finally { this.lock(false); }
  }
  append(entry) {
    const article = document.createElement('article'); article.className = 'memory-note';
    const text = document.createElement('p'); text.className = 'memory-note-content'; text.textContent = entry.content;
    const meta = document.createElement('p'); meta.className = 'memory-note-meta';
    const origin = { automatic: 'Saved automatically', requested: 'Saved at your request', manual: 'Saved by you' }[entry.origin] || 'Saved by you';
    meta.textContent = `${origin} · ${memoryDate(entry.confirmed_at)}`;
    const actions = document.createElement('div'); actions.className = 'actions';
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'secondary-button'; edit.textContent = 'Edit';
    edit.addEventListener('click', () => this.edit(article, entry, text, meta, actions));
    const forget = document.createElement('button'); forget.type = 'button'; forget.className = 'secondary-button'; forget.textContent = 'Forget';
    forget.addEventListener('click', async () => {
      if (this.busy) return;
      this.lock(true);
      try {
        await this.transport.request(`/memory/${encodeURIComponent(entry.id)}`, 'DELETE');
        article.remove(); this.status.textContent = 'Memory forgotten. Earlier chat messages remain in history.';
      } catch (error) { this.status.textContent = String(error); }
      finally { this.lock(false); }
    });
    actions.append(edit, forget); article.append(text, meta, actions); this.records.appendChild(article);
  }
  edit(article, entry, text, meta, actions) {
    if (this.busy || article.querySelector('textarea')) return;
    const field = document.createElement('label'); field.className = 'field';
    const label = document.createElement('span'); label.textContent = 'What should KAI remember?';
    const input = document.createElement('textarea'); input.rows = 3; input.maxLength = 2000; input.value = entry.content;
    field.append(label, input);
    const controls = document.createElement('div'); controls.className = 'actions';
    const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save changes';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary-button'; cancel.textContent = 'Cancel';
    const finish = () => { field.remove(); controls.remove(); text.hidden = false; actions.hidden = false; };
    cancel.addEventListener('click', finish);
    input.addEventListener('input', () => { save.disabled = !input.value.trim(); });
    save.addEventListener('click', async () => {
      if (this.busy || !input.value.trim()) return;
      this.lock(true);
      try {
        const updated = await (await this.transport.request(`/memory/${encodeURIComponent(entry.id)}`, 'PUT', {
          content: input.value.trim(), revision: entry.revision || 0,
        })).json();
        Object.assign(entry, updated); text.textContent = entry.content;
        meta.textContent = `Edited by you · ${memoryDate(entry.confirmed_at)}`;
        finish(); this.status.textContent = 'Memory updated.';
      } catch (error) { this.status.textContent = String(error); }
      finally { this.lock(false); save.disabled = !input.value.trim(); }
    });
    controls.append(save, cancel); text.hidden = true; actions.hidden = true;
    article.append(field, controls); input.focus();
  }
}
