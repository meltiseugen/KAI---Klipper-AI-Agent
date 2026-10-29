// Composition root; bundled inline for the OctoEverywhere rescued tab.
let browserStorage = null;
try { browserStorage = window.localStorage; } catch (_) { /* Blocked storage. */ }
const intro = document.getElementById("chat-intro")?.textContent?.trim() || "Ask about your printer.";
const chat = new ChatApplication(
  new ConversationStore(browserStorage, intro),
  new ChatTransport(resolveApiBase(document.body.dataset.apiBase)),
  new ShellView(),
);
void chat.start();
