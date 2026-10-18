import assert from "node:assert/strict";
import { loadUI, memoryStorage, jsonResponse } from "./ui-harness.mjs";

const scheduled = [];
const lifecycle = {};
const { PrinterMemoryPanel, ChatApplication, ConversationStore, ShellView, ids } = await loadUI({
  window: { addEventListener: (name, fn) => { lifecycle[name] = fn; } },
  setTimeout: fn => { scheduled.push(fn); return scheduled.length; }, clearTimeout() {},
});
const observation = { id: "obs", source: "inspect_config", observed_at: "2026-10-18T12:00:00Z", content: "<script>Evidence</script>" };
const entry = { id: "entry", kind: "resolution", confirmed_at: "2026-10-18T13:00:00Z", content: "<script>Fan connector replaced</script>", evidence: [observation] };
const calls = [];
let fail = false;
const transport = {
  async request(path, method = "GET", body) {
    calls.push({ path, method, body });
    if (fail) throw new Error("Save unavailable");
    return jsonResponse(method === "GET" ? [entry] : {});
  },
  async investigation() { return { turns: [{ result: { evidence: [observation, observation] } }] }; },
};
const panel = new PrinterMemoryPanel(transport, () => "chat");
panel.bind();
await panel.open();
assert.equal(panel.fields.length, 1);
assert.equal(ids["memory-save"].disabled, true);
assert.match(ids["memory-records"].textContent, /<script>Fan connector replaced<\/script>/);
assert.match(ids["memory-records"].textContent, /observed 2026-10-18/);
ids["memory-content"].value = "Confirmed physical fix";
ids["memory-kind"].value = "resolution";
await panel.save();
assert.equal(calls.filter(c => c.method === "POST").length, 0);
panel.fields[0].checked = true;
ids["memory-confirmed"].checked = true;
ids["memory-confirmed"].listeners.change();
assert.equal(ids["memory-save"].disabled, false);
ids["memory-content"].listeners.input();
assert.equal(ids["memory-confirmed"].checked, false);
ids["memory-confirmed"].checked = true; panel.update();
await panel.save();
const submitted = calls.find(c => c.method === "POST").body;
assert.equal(submitted.confirmed, true);
assert.equal(submitted.investigation_id, "chat");
assert.deepEqual(Array.from(submitted.evidence_ids), ["obs"]);
assert.equal(ids["memory-content"].value, "");
ids["memory-content"].value = "Keep draft after failure";
ids["memory-confirmed"].checked = true; panel.update(); fail = true;
await panel.save();
assert.equal(ids["memory-content"].value, "Keep draft after failure");
assert.match(ids["memory-status"].textContent, /unavailable/);
fail = false;
const article = ids["memory-records"].children[0];
await article.children.at(-1).click();
assert.equal(ids["memory-records"].children.length, 0);
assert.equal(calls.at(-1).method, "DELETE");
panel.close();
assert.equal(ids["conversation-panel"].inert, false);

const store = new ConversationStore(memoryStorage(), "Hello");
store.restore();
store.getCurrentConversation().threadId = "recover";
store.getCurrentConversation().draft = "Keep this unsent question";
store.save();
let record = { id: "recover", revision: 0, title: "Fan", updated_at: "2026-10-18", turns: [], pending: { id: "run", message: "Fan stopped", attempts: 1, mode: "debug" } };
let reads = 0;
const server = {
  async bootstrap() { return { features: ["persistent-investigations", "confirmed-memory", "investigation-recovery"], agent_modes: ["chat", "debug"] }; },
  async investigation(path) { if (path) { reads++; return record; } return [record]; },
  async chat(request) { calls.push(request); return { thread_id: request.thread_id, response: "Complete" }; },
};
const app = new ChatApplication(store, server, new ShellView());
await app.start();
assert.equal(ids["send-button"].disabled, true);
assert.match(ids.messages.textContent, /resumes it with fresh printer reads/);
assert.equal(store.getCurrentConversation().draft, "Keep this unsent question");
const count = calls.length;
await app.send();
assert.equal(calls.length, count);
record = { ...record, revision: 1, pending: null, turns: [{ question: "Fan stopped", result: { response_text: "Recovered answer", mode: "debug" } }] };
await app.sync.refresh();
assert.match(ids.messages.textContent, /Recovered answer/);
assert.equal(ids["send-button"].disabled, false);
assert.equal(ids["message-input"].value, "Keep this unsent question");
const completedReads = reads;
let renders = 0;
const originalRender = app.render.bind(app);
app.render = () => { renders++; originalRender(); };
await app.sync.refresh();
assert.equal(reads, completedReads);
assert.equal(renders, 0); // Idle polls must not reset the reader's scroll position.
app.busy = true;
await app.sync.refresh();
assert.equal(reads, completedReads);
app.busy = false;
lifecycle.pagehide();
assert.equal(app.sync.stopped, true);
lifecycle.pageshow({ persisted: true });
assert.equal(app.sync.stopped, false);
app.sync.stop();
app.newChat();
ids["message-input"].value = "New question";
const newId = store.getCurrentConversation().id;
await app.send();
assert.equal(calls.at(-1).thread_id, newId);
console.log("Confirmed-memory controls, dated evidence, escaping, failures, forgetting, recovery polling, draft retention and stable request IDs pass.");
