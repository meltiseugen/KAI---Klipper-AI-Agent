// Coalesced server observations; disconnects immediately make printer state unknown.
class MoonrakerStatusFeed {
  constructor(transport, view, factory = url => new EventSource(url), schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id)) {
    this.transport = transport; this.view = view; this.factory = factory;
    this.schedule = schedule; this.cancel = cancel;
    this.source = null; this.timer = null; this.stopped = false;
    this.connecting = false; this.delay = 1000;
  }

  async start(refresh = false) {
    if (this.stopped || this.connecting || this.source) return;
    this.connecting = true;
    try {
      const session = await this.transport.session(refresh);
      if (this.stopped) return;
      const source = this.factory(`${this.transport.base}/moonraker/events?session_id=${encodeURIComponent(session)}`);
      this.source = source;
      source.addEventListener("status", event => {
        if (this.source !== source) return;
        try {
          const state = JSON.parse(event.data);
          if (!state || typeof state.connected !== "boolean" || typeof state.stale !== "boolean") throw new Error("Invalid status");
          this.delay = 1000;
          this.view.moonraker(state);
        } catch { this.retry(); }
      });
      source.addEventListener("expired", () => { if (this.source === source) this.retry(); });
      source.onerror = () => { if (this.source === source) this.retry(); };
    } catch { this.retry(); }
    finally { this.connecting = false; }
  }

  retry() {
    this.source?.close(); this.source = null;
    this.view.moonraker({ connected: false, stale: true, klippy_state: "unknown", transport_unavailable: true });
    this.cancel(this.timer);
    if (!this.stopped) {
      this.timer = this.schedule(() => this.start(true), this.delay);
      this.delay = Math.min(30000, this.delay * 2);
    }
  }

  stop() {
    this.stopped = true; this.cancel(this.timer);
    this.source?.close(); this.source = null;
  }
}
