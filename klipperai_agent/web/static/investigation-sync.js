// Refresh recovered turns without overwriting drafts or an active streamed response.
class InvestigationSync {
  constructor(app, schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id)) {
    this.app = app;
    this.schedule = schedule;
    this.cancel = cancel;
    this.stopped = true;
    this.timer = null;
    this.refreshing = false;
    this.app.view.doc?.addEventListener("visibilitychange", () => {
      if (this.stopped) return;
      this.cancel(this.timer);
      if (!this.app.view.doc.hidden) void this.refresh();
    });
  }
  start() {
    this.stop();
    this.stopped = false;
    this.scheduleNext();
  }
  stop() { this.stopped = true; this.cancel(this.timer); }
  scheduleNext() {
    if (this.stopped || this.app.view.doc?.hidden) return;
    const pending = this.app.store.state.conversations.some(item => item.pendingRun);
    this.timer = this.schedule(() => this.refresh(), pending ? 5000 : 30000);
  }
  async refresh() {
    if (this.refreshing) return;
    this.cancel(this.timer);
    this.refreshing = true;
    try {
      if (!this.app.busy && !this.stopped && !this.app.view.doc?.hidden) {
        const changed = await this.app.restoreInvestigations(true);
        if (changed && !this.app.busy && !this.stopped) { this.app.store.save(); this.app.render(); }
      }
    } catch (_) { /* Session renewal and temporary restart failures retry on the next poll. */ }
    finally { this.refreshing = false; this.scheduleNext(); }
  }
}
