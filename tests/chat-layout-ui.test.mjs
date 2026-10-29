import assert from "node:assert/strict";
import test from "node:test";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

const descendants = node => [node, ...node.children.flatMap(descendants)];

test("welcome text stays in saved history while the conversation shows only real turns", async () => {
  const { ConversationStore, ShellView, ids } = await loadUI();
  const storage = memoryStorage();
  const store = new ConversationStore(storage, "Current introduction");
  store.restore();
  const view = new ShellView();
  const render = () => view.render(store, { busy: false, modesEnabled: true });
  render();
  assert.equal(ids["chat-welcome"].hidden, false);
  assert.equal(ids.messages.hidden, true);
  const conversation = store.getCurrentConversation();
  conversation.messages.push({ role: "assistant", text: "Your LLM agent investigates printer problems and configuration. Start here." });
  render();
  assert.equal(ids["chat-welcome"].hidden, false);
  conversation.messages.push({ role: "user", text: "Check my printer" },
    { role: "assistant", text: "Current introduction", followUpAvailable: true });
  store.save();
  render();
  assert.equal(ids["chat-welcome"].hidden, true);
  assert.equal(ids.messages.children.length, 2);
  assert.match(ids.messages.textContent, /Check my printer/);
  const restored = new ConversationStore(storage, "Current introduction");
  restored.restore();
  assert.equal(restored.getCurrentConversation().messages.length, 4);
  assert.equal(restored.getCurrentConversation().messages[0].intro, true);
});

test("composer shortcuts respect multiline text, IME and disabled sends; starters only fill a draft", async () => {
  const { ShellView, ids } = await loadUI();
  let sends = 0, draft = "", prevented = 0;
  const view = new ShellView();
  view.bind({ send: () => sends++, draft: value => { draft = value; } });
  const key = ids["message-input"].listeners.keydown;
  key({ key: "Enter", shiftKey: true });
  key({ key: "Enter", isComposing: true });
  assert.equal(sends, 0);
  key({ key: "Enter", preventDefault: () => prevented++ });
  assert.equal(sends, 1);
  ids["send-button"].disabled = true;
  key({ key: "Enter", preventDefault: () => prevented++ });
  assert.equal(sends, 1);
  assert.equal(prevented, 2);
  ids["starter-diagnose"].click();
  assert.equal(draft, "Why did my printer stop?");
  assert.equal(ids["message-input"].value, draft);
  assert.equal(sends, 1);
});

test("progress preserves reading position and jump to latest follows the conversation", async () => {
  const { ConversationStore, ShellView, ids } = await loadUI();
  const store = new ConversationStore(memoryStorage(), "Introduction");
  store.restore();
  store.getCurrentConversation().messages.push({ role: "user", text: "Investigate" });
  const view = new ShellView();
  view.bind({});
  ids.messages.scrollHeight = 1800;
  ids.messages.clientHeight = 500;
  view.render(store, { busy: false });
  ids.messages.scrollTop = 200;
  view.render(store, { busy: true, pending: "Reading recent logs" });
  assert.equal(ids.messages.scrollTop, 200);
  assert.equal(ids["scroll-to-bottom"].hidden, false);
  ids["scroll-to-bottom"].click();
  assert.equal(ids.messages.scrollTop, 1800);
  assert.equal(ids["scroll-to-bottom"].hidden, true);
});

test("code copy is explicit, copies literal text and handles unavailable clipboard access", async () => {
  for (const available of [true, false]) {
    let copied;
    const { ConversationStore, ShellView, ids } = await loadUI(available
      ? { navigator: { clipboard: { writeText: async text => { copied = text; } } } } : {});
    const store = new ConversationStore(memoryStorage(), "Introduction");
    store.restore();
    store.getCurrentConversation().messages.push({ role: "assistant", text: "```ini\n[mcu]\n# <script> literal text\n```" });
    new ShellView().render(store, { busy: false });
    assert.equal(copied, undefined);
    const button = descendants(ids.messages).find(node => node.classList.contains("code-copy"));
    await button.click();
    assert.equal(button.textContent, available ? "Copied" : "Select text to copy");
    assert.equal(copied, available ? "[mcu]\n# <script> literal text" : undefined);
    assert.equal(descendants(ids.messages).some(node => node.tag === "script"), false);
  }
});
