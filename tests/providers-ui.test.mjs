import test from "node:test";
import assert from "node:assert/strict";
import { loadUI } from "./ui-harness.mjs";

function status(revision = 0) {
  const profile = { model: "gpt-5.4-mini", max_output_tokens: 6000, reasoning_effort: "default" };
  return {
    revision, credential_configured: false, credential_source: "none", restart_required: revision > 0,
    validation: "API key removal checked.",
    active_policy: { provider: "openai" }, usage: { requests: 0, tokens: 0 },
    policy: { provider: "openai", web_search_enabled: true, agent: profile, search: profile, knowledge: profile, legacy: profile,
      requests_per_minute: 20, requests_per_day: 200, tokens_per_day: 2000000, max_concurrent_requests: 2 },
  };
}

test("provider panel loads, submits transient credentials, and shows pending restart", async () => {
  const { ProviderPanel, ids } = await loadUI();
  const calls = [];
  const panel = new ProviderPanel({ request: async (path, method, body) => {
    calls.push({ path, method, body: body && JSON.parse(JSON.stringify(body)) });
    return { json: async () => status(method === "PUT" ? 1 : 0) };
  } });
  panel.bind();
  await ids["providers-toggle"].click();
  assert.equal(ids["providers-panel"].hidden, false);
  assert.equal(ids["conversation-panel"].inert, true);
  assert.equal(panel.inputs["agent-model"].value, "gpt-5.4-mini");
  panel.inputs.provider.value = "openai";
  panel.inputs["search-model"].value = "search-model";
  ids["providers-key"].value = "private-replacement";
  await ids["providers-save"].click();
  assert.equal(calls[1].body.api_key, "private-replacement");
  assert.equal(calls[1].body.policy.search.model, "search-model");
  assert.equal(ids["providers-key"].value, "");
  assert.match(ids["providers-status"].textContent, /Restart KlipperAI manually/);
  assert.doesNotMatch(ids["providers-status"].textContent, /private-replacement/);
  ids["providers-key"].value = "another-key";
  await ids["providers-validate"].click();
  assert.equal(calls[2].path, "/providers/validate");
  assert.match(ids["providers-status"].textContent, /not been saved/);
  assert.equal(ids["providers-key"].value, "");
  ids["providers-key"].value = "unsaved-key";
  ids["providers-close"].click();
  assert.equal(ids["providers-key"].value, "");
  assert.equal(ids["providers-panel"].hidden, true);
  assert.equal(ids["conversation-panel"].inert, false);
  assert.equal(ids["providers-toggle"].focused, true);
});

test("settings and knowledge panels switch without covering each other or retaining a key", async () => {
  const { ProviderPanel, PrinterKnowledgePanel, ids } = await loadUI();
  const provider = new ProviderPanel({ request: async () => ({ json: async () => status() }) });
  const knowledge = new PrinterKnowledgePanel({});
  knowledge.saving = true; // Keep the switch test independent of knowledge HTTP.
  provider.beforeOpen = () => knowledge.close();
  knowledge.beforeOpen = () => provider.close();
  await knowledge.open();
  await provider.show();
  assert.equal(ids["knowledge-panel"].hidden, true);
  assert.equal(ids["providers-panel"].hidden, false);
  ids["providers-key"].value = "unsaved-key";
  await knowledge.open();
  assert.equal(ids["providers-panel"].hidden, true);
  assert.equal(ids["knowledge-panel"].hidden, false);
  assert.equal(ids["providers-key"].value, "");
  assert.equal(ids["conversation-panel"].inert, true);
});

test("locked credential storage disables key input and explains recovery", async () => {
  const { ProviderPanel, ids } = await loadUI();
  const panel = new ProviderPanel({ request: async () => ({ json: async () => ({ ...status(), credential_storage_available: false }) }) });
  await panel.show();
  assert.equal(ids["providers-key"].disabled, true);
  assert.match(ids["providers-status"].textContent, /locked\. Rerun the secure installer/);
  assert.equal(ids["providers-key"].value, "");
});

test("provider panel failures preserve edits, clear keys and prevent duplicate requests", async () => {
  const { ProviderPanel, ids } = await loadUI();
  let reject;
  let count = 0;
  const panel = new ProviderPanel({ request: async () => {
    count++;
    if (count === 1) return { json: async () => status() };
    return new Promise((_resolve, fail) => { reject = fail; });
  } });
  panel.bind();
  await panel.show();
  panel.inputs.provider.value = "openai";
  ids["providers-key"].value = "transient-key";
  const pending = panel.submit(true);
  assert.equal(panel.busy, true);
  assert.equal(ids["providers-key"].value, "");
  assert.equal(ids["providers-save"].disabled, true);
  await panel.submit(true);
  await panel.load();
  assert.equal(count, 2);
  reject(new Error("Request failed (409)"));
  await pending;
  assert.match(ids["providers-status"].textContent, /Settings were not changed/);
  assert.equal(panel.inputs.provider.value, "openai");
  assert.equal(panel.busy, false);
  const empty = new ProviderPanel({ request: async () => { throw new Error("disconnected"); } });
  await empty.load();
  await empty.submit(true);
  assert.match(ids["providers-status"].textContent, /disconnected/);
  assert.equal(ids["providers-save"].disabled, true);
});
