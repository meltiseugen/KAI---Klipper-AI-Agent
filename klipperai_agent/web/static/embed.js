// Composition root; bundled inline for the OctoEverywhere rescued tab.
let browserStorage = null;
try { browserStorage = window.localStorage; } catch (_) { /* Blocked storage. */ }
const intro = document.querySelector("#messages .message.assistant .message-body")?.textContent?.trim() || "Ask what failed or ask for config help.";
const chat = new ChatApplication(
  new ConversationStore(browserStorage, intro),
  new ChatTransport(resolveApiBase(document.body.dataset.apiBase)),
  new ShellView(),
);
void chat.start();
