import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { loadUI, memoryStorage, jsonResponse } from "./ui-harness.mjs";

const descendants = node => [node, ...node.children.flatMap(descendants)];
const button = (node, text) => descendants(node).find(item => item.tag === "button" && item.textContent === text);

async function fixture() {
  const ui = await loadUI();
  const storage = memoryStorage();
  const store = new ui.ConversationStore(storage, "Introduction");
  const server = {
    async bootstrap() { return { provider: "openai", provider_configured: true, moonraker_reachable: true, agent_modes: ["chat", "debug"], features: [] }; },
    async chat(request) {
      server.lastRequest = request;
      return { thread_id: "thread", response: "The MCU disconnected.", agent_status: "limited",
        findings: [{ summary: "MCU timeout", severity: "high", source: "klippy.log:42", code: "mcu_timeout",
          evidence: "<script>not executable</script>", proposed_fix: "Inspect the cable manually." }],
        next_actions: ["Inspect the cable manually."],
        source_citations: [{ label: "Log excerpt", path: "klippy.log", line_number: 42, excerpt: "Lost communication", url: "javascript:alert(1)" }],
      };
    },
  };
  const view = new ui.ShellView();
  const app = new ui.ChatApplication(store, server, view);
  await app.start();
  return { ...ui, app, view, store, storage, server };
}

test("the composer asks only for a question and relies on automatic printer evidence", async () => {
  const { app, ids, server } = await fixture();
  const html = await readFile(new URL("../klipperai_agent/web/templates/embed.html", import.meta.url), "utf8");
  assert.doesNotMatch(html, /type="file"|Attach files|Paste a log|artifact-dropzone|snippet-editor/);
  assert.match(html, /configuration and recent logs automatically/);
  assert.match(ids["mode-description"].textContent, /read automatically/);
  ids["message-input"].value = "Why did my printer stop?";
  await app.send();
  assert.equal(server.lastRequest.message, "Why did my printer stop?");
  assert.equal("artifacts" in server.lastRequest, false);
  assert.equal(typeof app.attachFiles, "undefined");
  assert.equal(typeof app.attachSnippet, "undefined");
});

test("findings, evidence, actions and partial status survive reload and seed editable follow-ups", async () => {
  const { app, ids, store, storage, ConversationStore } = await fixture();
  ids["message-input"].value = "Why did it stop?";
  await app.send();
  for (const label of ["Findings", "Evidence", "Next actions"]) {
    assert.ok(descendants(ids.messages).some(node => node.attributes["aria-label"] === label));
  }
  assert.match(ids.messages.textContent, /Partial result/);
  assert.match(ids.messages.textContent, /<script>not executable<\/script>/);
  assert.equal(descendants(ids.messages).filter(node => node.tag === "script").length, 0);
  assert.equal(descendants(ids.messages).filter(node => node.tag === "a").length, 0);
  const restored = new ConversationStore(storage, "Introduction");
  restored.restore();
  assert.equal(restored.getCurrentConversation().messages.at(-1).findings[0].severity, "high");
  assert.equal(restored.getCurrentConversation().messages.at(-1).agentStatus, "limited");
  store.getCurrentConversation().draft = "Keep my question";
  button(ids.messages, "Investigate finding").click();
  assert.match(ids["message-input"].value, /^Keep my question\n\nInvestigate this finding/);
  assert.match(ids["message-input"].value, /MCU timeout/);
  assert.equal(store.getCurrentConversation().messages.filter(item => item.role === "user").length, 1);
  button(ids.messages, "Analyze this source").click();
  assert.match(ids["message-input"].value, /Log excerpt/);
  app.busy = true; app.render();
  assert.equal(button(ids.messages, "Investigate finding").disabled, true);
});

test("failed sends retain question drafts; error text is excluded from future model history", async () => {
  const { app, store, ids, server } = await fixture();
  server.chat = async () => { throw Object.assign(new Error("Session expired"), { code: "invalid_session" }); };
  ids["message-input"].value = "Please inspect";
  await app.send();
  assert.equal(ids["message-input"].value, "Please inspect");
  assert.equal(store.buildRequestHistory(store.getCurrentConversation().messages).length, 0);
  assert.match(ids["chat-notices"].textContent, /Session expired/);
  await app.recover("invalid_session");
  assert.equal(ids["message-input"].value, "Please inspect");
  assert.equal(ids["chat-notices"].hidden, true);
});

test("missing provider disables the assistant while connection information remains available", async () => {
  const { app, server, view, ids } = await fixture();
  server.bootstrap = async () => ({ provider: "openai", provider_configured: false, moonraker_reachable: false });
  await app.recover("request_failed");
  assert.match(ids["welcome-title"].textContent, /Connect your AI provider/);
  assert.equal(ids["connect-provider"].hidden, false);
  assert.match(ids["connection-label"].textContent, /Printer unavailable/);
  ids["message-input"].value = "Question";
  await app.send();
  assert.equal(server.lastRequest, undefined);
  view.moonraker({ connected: true, stale: false, klippy_state: "ready" });
  assert.doesNotMatch(ids["chat-notices"].textContent, /Moonraker unavailable/);
  assert.match(ids["moonraker-badge"].textContent, /reachable/);
  server.bootstrap = async () => ({ provider: "openai", provider_configured: false, moonraker_reachable: false });
  await app.recover("request_failed");
  assert.match(ids["welcome-title"].textContent, /Connect your AI provider/);
  assert.equal(ids["send-button"].disabled, true);
  assert.equal(ids["message-input"].disabled, true);
  assert.match(ids["llm-request-info"].textContent, /Configure an LLM provider/);
});

test("transport renews only once and retains typed setup errors, without treating origin failures as sessions", async () => {
  const { ChatTransport } = await loadUI();
  for (const [detail, status, expected] of [
    ["Invalid or expired session.", 403, "invalid_session"],
    [{ code: "provider_not_configured", message: "Set up a key" }, 503, "provider_not_configured"],
    ["Cross-origin API access is not allowed.", 403, "request_failed"],
  ]) {
    let requests = 0;
    const transport = new ChatTransport("/printer/api", async url => {
      requests++;
      return url.endsWith("ui-sessions") ? jsonResponse({ session_id: "fresh" }) : jsonResponse({ detail }, status);
    });
    await assert.rejects(() => transport.bootstrap(), error => error.code === expected);
    assert.ok(requests <= 4);
  }
});
