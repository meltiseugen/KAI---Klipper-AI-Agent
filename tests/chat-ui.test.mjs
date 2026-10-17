import assert from "node:assert/strict";
import { loadUI, memoryStorage, jsonResponse } from "./ui-harness.mjs";

const { ConversationStore, ChatTransport, ChatApplication, ShellView, resolveApiBase, ids } = await loadUI();
for (const [configured, path, expected] of [
  ["/api", "/", "/api"], ["/api", "/embed", "/api"],
  ["/api", "/klipperai/", "/klipperai/api"], ["", "/klipperai/direct", "/klipperai/api"],
  ["/assistant/printer/api/", "/assistant/printer/direct", "/assistant/printer/api"],
  ["/klipperai/api", "blank", "/klipperai/api"],
]) assert.equal(resolveApiBase(configured, path), expected);

// All API operations share session renewal and retain the public remote prefix.
const requests = [];
const replies = [jsonResponse({ session_id: "old" }), jsonResponse({}, 403),
  jsonResponse({ session_id: "new session" }), jsonResponse({ provider: "stub" }),
  jsonResponse(null, 204), jsonResponse({}, 409)];
const transport = new ChatTransport("/assistant/printer/api", async (url, options) => {
  requests.push({ url, ...options });
  return replies.shift();
});
assert.equal((await transport.bootstrap()).provider, "stub");
assert.ok(requests[3].url.endsWith("/bootstrap?session_id=new%20session"));
assert.equal(await transport.investigation("/thread", "DELETE"), null);
await assert.rejects(() => transport.request("/chat/stream", "POST", { message: "Question" }), /409/);
assert.equal(JSON.parse(requests[5].body).session_id, "new session");
assert.ok(requests.every(item => item.url.startsWith("/assistant/printer/api/")));
let attempts = 0;
await assert.rejects(() => new ChatTransport("/api", async () => {
  attempts++;
  return jsonResponse({}, 503);
}).bootstrap(), /503/);
assert.equal(attempts, 1);

const storage = memoryStorage();
const store = new ConversationStore(storage, "Introduction");
store.restore();
const original = store.getCurrentConversation();
original.threadId = "persisted";
original.draft = "Keep my draft";
store.save();
const restored = new ConversationStore(storage, "Introduction");
restored.restore();
assert.equal(restored.getCurrentConversation().draft, "Keep my draft");
const unavailable = new ConversationStore(null, "Introduction");
unavailable.restore();
unavailable.save();
assert.equal(unavailable.state.conversations.length, 1);
const legacy = memoryStorage();
legacy.setItem("klipperai.embed.state.v1", JSON.stringify({ currentThreadId: "legacy", draft: "Draft", messages: [{ role: "user", text: "Old question" }] }));
const migrated = new ConversationStore(legacy, "Introduction");
migrated.restore();
assert.equal(migrated.getCurrentConversation().threadId, "legacy");

let releaseChat;
let chatCalls = 0;
let lastRequest;
let failDelete = false;
const server = {
  async bootstrap() { return { provider: "stub", conversation_history_pairs: 2, features: ["persistent-investigations"], moonraker_reachable: true }; },
  async investigation(path = "", method = "GET") {
    if (method === "DELETE") { if (failDelete) throw new Error("Delete failed"); return null; }
    if (method === "POST") return { question: "Recheck", result: { response_text: "Config changed" } };
    return path ? { id: "persisted", updated_at: "2026-01-01", turns: [{ question: "Stored question", result: { response_text: "Stored answer" } }] } : [{ id: "persisted" }];
  },
  async chat(request, event) {
    chatCalls++;
    lastRequest = request;
    event({ message: "Reading config" });
    return new Promise(resolve => { releaseChat = resolve; });
  },
};
const view = new ShellView();
const app = new ChatApplication(store, server, view);
await app.start();
assert.equal(store.getCurrentConversation().draft, "Keep my draft");
assert.match(ids.messages.textContent, /Stored answer/);
assert.match(ids["moonraker-badge"].textContent, /reachable/);
assert.equal(ids["message-input"].disabled, false);
ids["message-input"].value = "Follow up";
const sending = app.send();
await app.send();
app.newChat();
assert.equal(chatCalls, 1);
assert.equal(store.state.conversations.length, 1);
assert.equal(lastRequest.thread_id, "persisted");
assert.equal(lastRequest.history.length, 2);
assert.match(ids.messages.textContent, /Reading config/);
assert.equal(ids["send-button"].disabled, true);
releaseChat({ thread_id: "persisted", response: "**Evidence** <script>unsafe</script>", next_actions: ["Check manually"] });
await sending;
assert.match(ids.messages.textContent, /Check manually/);
assert.match(ids.messages.textContent, /<script>unsafe<\/script>/);
assert.equal(ids["send-button"].disabled, false);
await app.revalidate("proposal");
assert.match(ids.messages.textContent, /Config changed/);
failDelete = true;
await app.remove(original.id);
assert.equal(store.state.conversations.length, 1);
assert.match(ids["composer-status"].textContent, /Delete failed/);
failDelete = false;
await app.remove(original.id);
assert.equal(store.getCurrentConversation().threadId, null);
assert.doesNotMatch(ids.messages.textContent, /Stored answer/);
ids["message-input"].value = "Offline?";
server.chat = async () => { throw new Error("Connection lost"); };
await app.send();
assert.match(ids.messages.textContent, /Connection lost/);
assert.equal(ids["send-button"].disabled, false);
view.navigation(true);
assert.equal(ids["shell-menu-toggle"].attributes["aria-expanded"], "true");
ids["shell-scrim"].listeners.click();
assert.equal(ids["shell-menu-toggle"].attributes["aria-expanded"], "false");

export const outcome = "Chat composition, DOM rendering, draft migration, restored history, session retry, duplicate sends, errors, reviews and deletion pass.";
console.log(outcome);
