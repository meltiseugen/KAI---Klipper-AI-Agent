import assert from "node:assert/strict";
import { loadUI, jsonResponse } from "./ui-harness.mjs";

// Browser timers reject an application instance as their receiver.
// Node's permissive timers previously hid these failures in UI tests.
const scheduled = [];
const cancelled = [];
const { PrinterKnowledgePanel, InvestigationSync, MoonrakerStatusFeed, document } = await loadUI({
  setTimeout: function (callback, delay) {
    assert.equal(this, undefined, "Timer must not receive a panel/feed as this");
    scheduled.push({ callback, delay });
    return scheduled.length;
  },
  clearTimeout: function (id) {
    assert.equal(this, undefined, "Cancellation must not receive a panel/feed as this");
    cancelled.push(id);
  },
});

const knowledge = new PrinterKnowledgePanel({
  request: async () => jsonResponse({
    setup: { components: [], revision: 0, firmware_flavor: "Klipper", facts: "" },
    job: { state: "running", message: "Researching", completed: 0, total: 1, changes: [] },
    components: [], documents: [],
  }),
});
await knowledge.open();
assert.equal(scheduled.at(-1).delay, 1500);
knowledge.close();
assert.equal(cancelled.at(-1), 1);

let restored = false;
const sync = new InvestigationSync({
  view: { doc: document }, store: { state: { conversations: [] } },
  busy: false, restoreInvestigations: async () => { restored = true; return false; },
});
sync.start();
assert.equal(scheduled.at(-1).delay, 30000);
await scheduled.at(-1).callback();
assert.ok(restored);
sync.stop();
assert.equal(cancelled.at(-1), 3);

let state;
const feed = new MoonrakerStatusFeed(
  { session: async () => { throw new Error("disconnected"); } },
  { moonraker: value => { state = value; } },
);
await feed.start();
assert.equal(state.connected, false);
assert.equal(scheduled.at(-1).delay, 1000);
feed.stop();
assert.equal(cancelled.at(-1), 4);
console.log("Browser timer receivers: knowledge polling, recovery and status reconnect pass.");
