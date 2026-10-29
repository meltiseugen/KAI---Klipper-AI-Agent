import assert from "node:assert/strict";
import test from "node:test";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

test("the sidebar loads summaries; only opening a chat fetches its answers and keeps drafts", async () => {
  const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
  const store = new ConversationStore(memoryStorage(), "Introduction");
  const reads = [];
  let fail = false;
  const server = {
    async bootstrap() { return { features: ["persistent-investigations"] }; },
    async investigation(path = "") {
      reads.push(path);
      if (!path) return [1, 2, 3].map(id => ({id: String(id), title: `Chat ${id}`, revision: 1}));
      if (fail) throw new Error("Temporary connection failure");
      return {id: path.slice(1), revision: 1, turns: [{ question: "Saved question", result: { response_text: "Saved answer" } }]};
    },
  };
  const app = new ChatApplication(store, server, new ShellView());
  await app.start();
  assert.deepEqual(reads, [""]);
  assert.match(ids["history-list"].textContent, /Chat 3/);
  store.state.conversations.find(item => item.id === "2").draft = "Keep this draft";
  fail = true;
  await app.select("2");
  assert.equal(store.getCurrentConversation().loaded, false);
  assert.equal(ids["message-input"].value, "Keep this draft");
  fail = false;
  await app.select("2");
  assert.equal(store.getCurrentConversation().loaded, true);
  assert.match(ids.messages.textContent, /Saved answer/);
  assert.equal(ids["message-input"].value, "Keep this draft");
  await app.select("2");
  assert.deepEqual(reads, ["", "/2", "/2"]);
});

test("history polling slows when idle, stops for hidden tabs, and resumes visibly without overlap", async () => {
  const { ConversationStore, ShellView, InvestigationSync, document } = await loadUI();
  const store = new ConversationStore(memoryStorage(), "Introduction"); store.restore();
  const delays = [];
  let calls = 0, finish;
  const app = {store, view: new ShellView(), busy: false, render() {},
    restoreInvestigations: async () => { calls++; return new Promise(resolve => { finish = resolve; }); }};
  const sync = new InvestigationSync(app, (fn, delay) => { delays.push(delay); return delay; }, () => {});
  sync.start();
  assert.equal(delays.at(-1), 30000);
  const refreshing = sync.refresh();
  await sync.refresh();
  assert.equal(calls, 1);
  finish(false); await refreshing;
  store.getCurrentConversation().pendingRun = true;
  sync.scheduleNext();
  assert.equal(delays.at(-1), 5000);
  document.hidden = true;
  document.listeners.visibilitychange();
  const count = delays.length;
  await sync.refresh();
  assert.equal(calls, 1);
  assert.equal(delays.length, count);
  document.hidden = false;
  document.listeners.visibilitychange();
  assert.equal(calls, 2);
  finish(false); await new Promise(resolve => setImmediate(resolve));
  sync.stop();
});
