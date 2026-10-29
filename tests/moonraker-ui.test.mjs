import assert from "node:assert/strict";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

const sources = [];
class Source {
  constructor(url) { this.url = url; this.listeners = {}; sources.push(this); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  close() { this.closed = true; }
  status(data) { this.listeners.status({ data: JSON.stringify(data) }); }
}
const events = {};
const { MoonrakerStatusFeed, ShellView, ChatApplication, ConversationStore, ids } = await loadUI({
  EventSource: Source, window: { addEventListener: (name, fn) => { events[name] = fn; } },
});
const view = new ShellView();
const sessions = [];
const transport = { base: "/klipperai/api", session: async refresh => { sessions.push(refresh); return "a b"; } };
const timers = [];
const cancelled = [];
const feed = new MoonrakerStatusFeed(transport, view, url => new Source(url),
  (fn, delay) => { timers.push({ fn, delay }); return timers.length; }, id => cancelled.push(id));
await Promise.all([feed.start(), feed.start()]);
assert.equal(sources.length, 1);
assert.equal(sources[0].url, "/klipperai/api/moonraker/events?session_id=a%20b");
sources[0].status({ connected: true, subscribed: true, stale: false, klippy_state: "ready", status: { print_stats: { state: "printing" } } });
assert.equal(ids["moonraker-events-badge"].textContent, "Events: live");
assert.match(ids["klipper-badge"].textContent, /ready.*printing/);
assert.ok(ids["klipper-badge"].classList.contains("ok"));
sources[0].onerror();
assert.ok(sources[0].closed);
assert.equal(ids["klipper-badge"].textContent, "Klipper: unknown");
assert.equal(timers[0].delay, 1000);
await timers[0].fn();
assert.deepEqual(sessions, [false, true]);
sources[0].status({ connected: true, stale: false });
sources[0].listeners.expired();
sources[0].onerror();
assert.equal(timers.length, 1); // Obsolete sources cannot change the new connection.
sources[1].listeners.status({ data: "bad json" });
assert.equal(timers[1].delay, 2000);
await timers[1].fn();
sources[2].status({ connected: true, subscribed: false, stale: true, klippy_state: "shutdown" });
assert.equal(ids["moonraker-events-badge"].textContent, "Events: waiting for Klipper");
assert.equal(ids["klipper-badge"].textContent, "Klipper: shutdown");
sources[2].listeners.expired();
assert.equal(timers[2].delay, 1000);
await timers[2].fn();
sources[3].status({ connected: "invalid" });
assert.equal(timers.length, 4);
feed.stop();
await timers[3].fn();
assert.equal(sources.length, 4);
assert.ok(cancelled.length);

let resolve;
const waiting = new MoonrakerStatusFeed({ session: () => new Promise(done => { resolve = done; }) }, view, () => assert.fail("Stopped feed connected"));
const started = waiting.start();
waiting.stop();
resolve("session");
await started;
const failure = new MoonrakerStatusFeed({ session: async () => { throw new Error("disconnected"); } }, view, null, (fn, delay) => { assert.equal(delay, 1000); return 1; }, () => {});
await failure.start();
failure.stop();

// Page lifecycle closes streams and restores one fresh stream on bfcache return.
transport.bootstrap = async () => ({ features: ["moonraker-events"] });
const app = new ChatApplication(new ConversationStore(memoryStorage(), "Welcome"), transport, view);
await app.start();
const initial = sources.at(-1);
events.pagehide();
assert.ok(initial.closed);
events.pageshow({ persisted: false });
assert.equal(sources.at(-1), initial);
events.pageshow({ persisted: true });
await new Promise(setImmediate);
assert.notEqual(sources.at(-1), initial);
events.pagehide();
assert.ok(sources.at(-1).closed);
console.log("Moonraker UI: status, stale state, session renewal, reconnect and page lifecycle passed.");
