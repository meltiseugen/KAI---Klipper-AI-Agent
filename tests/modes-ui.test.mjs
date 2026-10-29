import assert from "node:assert/strict";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
const storage = memoryStorage();
const store = new ConversationStore(storage, "Introduction");
let release;
const requests = [];
const receipt = { source: "printer.cfg", status: "partial", detail: "Section index only <script>unsafe</script>", phase: "initial", observed_at: "2026-10-15", sent_to_model: true };
const server = {
  async bootstrap() { return { agent_modes: ["chat", "debug"], features: ["persistent-investigations"] }; },
  async investigation(path = "") {
    return path ? { id: "saved", turns: [{ question: "Why?", result: { response_text: "Earlier answer", mode: "debug", context_included: [receipt] } }] } : [{ id: "saved" }];
  },
  async chat(request) {
    requests.push(request);
    return new Promise(resolve => { release = resolve; });
  },
};
const app = new ChatApplication(store, server, new ShellView());
await app.start();
await app.select("saved");
assert.equal(ids["agent-mode"].value, "debug");
assert.match(ids.messages.textContent, /Context included · Debug/);
assert.match(ids.messages.textContent, /Section index only <script>unsafe<\/script>/);
assert.match(ids.messages.textContent, /included in model request/);
ids["agent-mode"].value = "chat";
ids["agent-mode"].listeners.change();
assert.equal(store.getCurrentConversation().mode, "chat");
assert.match(ids.messages.textContent, /Earlier answer/);
assert.match(ids["mode-description"].textContent, /earlier conversation stays available/);
ids["message-input"].value = "Follow up";
const sending = app.send();
assert.equal(ids["agent-mode"].disabled, true);
app.setMode("debug");
assert.equal(store.getCurrentConversation().mode, "chat");
assert.equal(requests[0].mode, "chat");
assert.equal(requests[0].thread_id, "saved");
assert.equal(requests[0].history.at(-1).text, "Earlier answer");
release({ thread_id: "saved", response: "Answer", mode: "chat", context_included: [receipt, { ...receipt, source: "Logs", status: "omitted", sent_to_model: false }] });
await sending;
assert.match(ids.messages.textContent, /Context included · Chat/);
assert.match(ids.messages.textContent, /not sent to model/);
assert.equal(ids["agent-mode"].disabled, false);
const restored = new ConversationStore(storage, "Introduction");
restored.restore();
assert.equal(restored.getCurrentConversation().mode, "chat");
assert.equal(restored.getCurrentConversation().messages.at(-1).contextIncluded.length, 2);
app.newChat();
assert.equal(store.getCurrentConversation().mode, "chat");
app.setMode("debug");
await app.select("saved");
assert.equal(ids["agent-mode"].value, "chat");
server.bootstrap = async () => ({ agent_modes: [], features: [] });
await app.start();
app.setMode("debug");
assert.equal(ids["agent-mode"].disabled, true);
assert.match(ids["mode-description"].textContent, /Modes require the tool-using agent/);
console.log("Mode selection, switching, requests, busy state, saved receipts and reloads pass.");
