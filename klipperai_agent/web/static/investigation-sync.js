// Refresh recovered turns without overwriting drafts or an active streamed response.
class InvestigationSync {
  constructor(app, schedule = setTimeout, cancel = clearTimeout) {
    this.app = app;
    this.schedule = schedule;
    this.cancel = cancel;
    this.stopped = true;
    this.timer = null;
  }
  start() {
    this.stop();
    this.stopped = false;
    this.timer = this.schedule(() => this.refresh(), 5000);
  }
  stop() { this.stopped = true; this.cancel(this.timer); }
  async refresh() {
    try {
      if (!this.app.busy && !this.stopped) {
        const changed = await this.app.restoreInvestigations(true);
        if (changed && !this.app.busy && !this.stopped) { this.app.store.save(); this.app.render(); }
      }
    } catch (_) { /* Session renewal and temporary restart failures retry on the next poll. */ }
    finally { if (!this.stopped) this.timer = this.schedule(() => this.refresh(), 5000); }
  }
}
