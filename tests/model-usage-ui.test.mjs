import assert from "node:assert/strict";
import test from "node:test";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

test("the primary agent action discloses the provider before sending and actual use survives reload", async () => {
  const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
  const storage = memoryStorage();
  const store = new ConversationStore(storage, "Introduction");
  let release;
  const receipt = { status: "completed", requests_started: 2, requests_completed: 2, models: ["OpenAI / selected-model"] };
  const server = {
    async bootstrap() { return { provider: "openai", provider_model: "selected-model", provider_configured: true, agent_modes: ["chat", "debug"] }; },
    async chat(request, onEvent) {
      assert.equal(request.message, "Audit active configuration");
      await onEvent({kind:"model_started",message:"Calling OpenAI · selected-model"});
      return new Promise(resolve => { release = resolve; });
    },
  };
  const app = new ChatApplication(store, server, new ShellView());
  await app.start();
  assert.equal(ids["send-button"].attributes["aria-label"], "Ask agent");
  assert.match(ids["llm-request-info"].textContent, /OpenAI \/ selected-model/);
  assert.match(ids["llm-request-info"].textContent, /sent to the LLM/);
  ids["message-input"].value = "Audit active configuration";
  const sending = app.send();
  await Promise.resolve();
  assert.match(ids.messages.textContent, /Calling OpenAI/);
  assert.equal(ids["message-input"].disabled, true);
  release({thread_id:"saved",response:"The agent reviewed the evidence.",model_usage:receipt});
  await sending;
  assert.match(ids.messages.textContent, /LLM used.*selected-model.*2 request\(s\), 2 provider response/);
  const restored = new ConversationStore(storage, "Introduction");
  restored.restore();
  assert.equal(restored.getCurrentConversation().messages.at(-1).modelUsage.requests_started, 2);
});

test("failed attempts, early stops and older results have distinct truthful receipts", async () => {
  const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
  const store = new ConversationStore(memoryStorage(), "Introduction");
  let result = {response:"Stopped before a model request",agent_status:"limited",model_usage:{status:"not_used"}};
  const server = {
    async bootstrap() { return {provider:"openai",provider_configured:true}; },
    async chat() { if (result instanceof Error) throw result; return result; },
  };
  const app = new ChatApplication(store, server, new ShellView());
  await app.start();
  ids["message-input"].value = "Investigate";
  await app.send();
  assert.match(ids.messages.textContent, /No LLM request was sent for this attempt/);
  result = {response:"Older saved answer"};
  ids["message-input"].value = "Continue";
  await app.send();
  assert.match(ids.messages.textContent, /LLM use was not recorded/);
  result = Object.assign(new Error("The investigation failed"), {modelUsage:{status:"attempted",requests_started:1,requests_completed:0,models:["<script>plain text</script>"]}});
  ids["message-input"].value = "Keep my question";
  await app.send();
  assert.match(ids.messages.textContent, /LLM request attempted.*1 request\(s\), 0 provider response/);
  assert.match(ids.messages.textContent, /<script>plain text<\/script>/);
  assert.equal(ids["message-input"].value, "Keep my question");
});

test("stream errors retain the provider attempt receipt", async () => {
  const { ChatStreamReader } = await loadUI();
  const receipt = {status:"attempted",requests_started:1,requests_completed:0,models:["OpenAI / selected"]};
  const response = {body:new ReadableStream({start(controller) {
    controller.enqueue(new TextEncoder().encode(`event: error\ndata: ${JSON.stringify({message:"Request failed",model_usage:receipt})}\n\n`));
    controller.close();
  }})};
  await assert.rejects(() => new ChatStreamReader().read(response, () => {}), error => error.modelUsage.requests_started === 1);
});
