// Optional JS checks: node tests/agent-ui.test.mjs (no npm dependencies).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../klipperai_agent/web/static/agent.js", import.meta.url), "utf8");
const investigation = await readFile(new URL("../klipperai_agent/web/static/investigation.js", import.meta.url), "utf8");
const manifest = JSON.parse(await readFile(new URL("../klipperai_agent/web/static/scripts.json", import.meta.url), "utf8"));
const bundle = await Promise.all(manifest.map(name => readFile(new URL(`../klipperai_agent/web/static/${name}`, import.meta.url), "utf8")));
new vm.Script(bundle.join("\n"));

function element(tag) {
  return { tag, children: [], listeners: {}, appendChild(child) { this.children.push(child); }, setAttribute() {}, addEventListener(name, fn) { this.listeners[name] = fn; } };
}
const context = vm.createContext({ TextDecoder, document: { createElement: element } });
vm.runInContext(await readFile(new URL("../klipperai_agent/web/static/model-usage.js", import.meta.url), "utf8"), context);
vm.runInContext(`${source}\nglobalThis.Reader = ChatStreamReader; globalThis.Activity = AgentActivity;`, context);
vm.runInContext(`${investigation}\nglobalThis.messages = investigationMessages; globalThis.Review = ProposalReviewCard; globalThis.Evidence = InvestigationEvidence;`, context);

function responseFor(chunks) {
  let index = 0;
  const reader = {
    cancelled: false, released: false,
    async read() { return index < chunks.length ? { value: chunks[index++], done: false } : { done: true }; },
    async cancel() { this.cancelled = true; },
    releaseLock() { this.released = true; },
  };
  return { body: { getReader: () => reader }, reader };
}

const wire = ': keep-alive\n\nevent: agent\ndata: {"message":"Read config"}\n\nevent: result\ndata: {"response":"Température: 22 °C"}\n\n';
const bytes = new TextEncoder().encode(wire);
const response = responseFor(Array.from(bytes, byte => new Uint8Array([byte])));
const events = [];
const result = await new context.Reader().read(response, event => events.push(event));
assert.equal(result.response, "Température: 22 °C");
assert.equal(events[0].message, "Read config");
assert.ok(response.reader.cancelled && response.reader.released);

for (const text of ['event: error\ndata: {"message":"failed"}\n\n', ': heartbeat\n\n']) {
  const response = responseFor([new TextEncoder().encode(text)]);
  await assert.rejects(() => new context.Reader().read(response, () => {}));
  assert.ok(response.reader.cancelled && response.reader.released);
}

const article = element("article");
context.Activity.append(article, [null, { kind: "tool_started", message: "Start" }, { kind: "tool_completed", message: "<script>untrusted</script>" }]);
assert.equal(article.children.length, 1);
assert.equal(article.children[0].children[1].children[0].textContent, "<script>untrusted</script>");
context.Activity.appendActions(article, ["Review the pin"]);
assert.equal(article.children[1].children[1].children[0].textContent, "Review the pin");
context.Activity.append(element("article"), null);
context.Activity.appendActions(element("article"), []);

const entries = context.messages({ turns: [{ question: "Fan?", imported_history: [{ role: "user", text: "Earlier question" }], result: { response_text: "Evidence", config_proposals: [{ title: "Draft" }] } }] });
assert.equal(entries[0].text, "Earlier question");
assert.equal(entries[2].configProposals[0].title, "Draft");

const reviewed = element("article");
let rechecked;
context.Review.append(reviewed, { review: { proposal_id: "p", status: "stale", errors: ["<script>error</script>"], comparison: "-old\n+new" } }, async id => { rechecked = id; });
const section = reviewed.children[0];
assert.match(section.children[0].textContent, /Configuration or firmware changed/);
assert.equal(section.children[1].children[0].textContent, "<script>error</script>");
assert.equal(section.children[2].children[1].textContent, "-old\n+new");
await section.children[3].listeners.click();
assert.equal(rechecked, "p");
assert.equal(section.children[3].disabled, false);
const failedReview = element("article");
context.Review.append(failedReview, { review: {} }, async () => { throw new Error("retry"); });
await failedReview.children[0].children[2].listeners.click();
assert.match(failedReview.children[0].children[3].textContent, /retry/);
const memory = element("article");
context.Evidence.append(memory, [{ source: "config", observed_at: "yesterday" }]);
assert.match(memory.children[0].children[1].children[0].textContent, /yesterday/);

export const outcome = "Full browser bundle parses; SSE, saved turns, manual reviews, dated memory and text escaping pass.";
console.log(outcome);
