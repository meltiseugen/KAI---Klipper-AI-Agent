import assert from "node:assert/strict";
import { test } from "node:test";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

test("audit requires provider and agent proposals survive saved chat rendering", async () => {
  const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
  const storage = memoryStorage();
  const store = new ConversationStore(storage, "Intro");
  let request;
  const review = {
    status: "manual_review", checks: [],
    managed_include: "Manually create klipperai/status.cfg and add its include.",
    file_patches: [{target_file:"klipperai/status.cfg",operation:"create",diff:"--- /dev/null\n+++ b/klipperai/status.cfg\n+<script>text only</script>"}],
  };
  const server = {
    async bootstrap() { return {provider:"openai",provider_configured:false}; },
    async chat(value) { request = value; return {response:"Static analysis",config_proposals:[{title:"Status",config:"[gcode_macro STATUS]",review}]}; },
  };
  const app = new ChatApplication(store, server, new ShellView());
  await app.start();
  ids["message-input"].value = "Analyze active config";
  await app.send();
  assert.equal(request, undefined, "Audits require the agent too");
  assert.equal(ids["send-button"].disabled, true);
  server.bootstrap = async () => ({provider:"openai",provider_configured:true});
  await app.connect();
  ids["message-input"].value = "Analyze active config";
  await app.send();
  assert.equal(request.message, "Analyze active config");
  assert.match(ids.messages.textContent, /Manual file patch: klipperai\/status.cfg/);
  assert.match(ids.messages.textContent, /<script>text only<\/script>/);
  assert.match(ids.messages.textContent, /Manually create/);
  const all = node => [node, ...node.children.flatMap(all)];
  assert.equal(all(ids.messages).filter(node => node.tag === "script").length, 0);
  store.save();
  const restored = new ConversationStore(storage, "Intro");
  restored.restore();
  assert.equal(restored.getCurrentConversation().messages.at(-1).configProposals[0].review.file_patches.length, 1);
  store.getCurrentConversation().messages.at(-1).configProposals[0].review.status = "stale";
  app.render();
  assert.doesNotMatch(ids.messages.textContent, /Manual file patch:/);
  request = undefined;
  app.providerConfigured = false;
  ids["message-input"].value = "Generate and check current config";
  await app.send();
  assert.equal(request, undefined, "Generation requires the selected provider");
});
