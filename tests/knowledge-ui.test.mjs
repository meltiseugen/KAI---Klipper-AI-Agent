import assert from "node:assert/strict";
import { Blob } from "node:buffer";
import { loadUI, jsonResponse, memoryStorage } from "./ui-harness.mjs";

const { PrinterKnowledgePanel, ChatApplication, ConversationStore, ShellView, document, ids } = await loadUI();
const payload = {
  setup: { components: [{ role: "mainboard", model: "BTT Manta E3EZ", revision: "1.0", mcu: "mcu", connection: "USB", confirmed: false }], revision: 0, firmware_flavor: "Klipper", firmware_version: "v0.13.0", facts: "<script>untrusted</script>" },
  job: { state: "idle", message: "Build local documentation", completed: 0, total: 0, changes: [] },
  components: [{ role: "mainboard", model: "BTT Manta E3EZ", status: "Needs details", gaps: ["Confirm hardware identity"], document_ids: [], fan_evidence: { candidates: [], conflicts: [], signature: "" }, fan_mappings_reviewed: false }], documents: [], profile_changed: false, automatic_research: true,
};
let fail = false;
let pending = null;
const calls = [];
let scheduled = null;
const cancellations = [];
const transport = {
  async bootstrap() { return { features: ["printer-knowledge"] }; },
  async request(path, method, body) {
    calls.push({ path, method, body });
    if (fail) throw new Error("409 Changed in another window");
    if (pending) await pending;
    if (path === "/knowledge/details") {
      payload.setup = { ...body.setup, revision: payload.setup.revision + 1, updated_at: "2026-10-16" };
      return jsonResponse(payload.setup);
    }
    if (path === "/knowledge/refresh") {
      payload.job = { state: "running", message: "Downloading", completed: 0, total: 3, changes: [] };
    }
    if (path === "/knowledge/review-mappings") {
      payload.setup = { ...payload.setup, revision: payload.setup.revision + 1 };
      payload.components[0].fan_mappings_reviewed = true;
      return jsonResponse(payload.setup);
    }
    if (path.startsWith("/knowledge/documents/")) return {
      blob: async () => new Blob(["cached manual"]),
      headers: { get: () => 'attachment; filename="manta-manual.pdf"' },
    };
    return jsonResponse(payload);
  },
};
const app = new ChatApplication(new ConversationStore(memoryStorage(), "Intro"), transport, new ShellView());
await app.start();
assert.ok(app.knowledge);
const panel = new PrinterKnowledgePanel(transport, callback => { scheduled = callback; return "timer"; }, timer => cancellations.push(timer));
panel.bind();
await ids["knowledge-toggle"].listeners.click();
assert.equal(ids["knowledge-panel"].hidden, false);
assert.equal(ids["knowledge-toggle"].attributes["aria-expanded"], "true");
assert.equal(panel.components[0].model.value, "BTT Manta E3EZ");
assert.equal(panel.facts.value, "<script>untrusted</script>");
assert.match(ids["knowledge-records"].textContent, /Confirm hardware identity/);
assert.equal(ids["knowledge-refresh"].textContent, "Build printer knowledge");
panel.components[0].confirmed.checked = true;
await ids["knowledge-add"].listeners.click();
assert.equal(panel.components[1].role.value, "component_1");
panel.components[1].model.value = "An unfamiliar vendor board";
panel.components[1].category.value = "board";
panel.components[1].mcu.value = " th ";
panel.components[1].references.value = " https://example.org/reference \n";
await ids["knowledge-save"].listeners.click();
assert.equal(payload.setup.components[0].confirmed, true);
assert.equal(payload.setup.components[1].mcu, "th");
assert.equal(payload.setup.components[1].reference_urls[0], "https://example.org/reference");
assert.equal(panel.setup.revision, 1);
assert.match(ids["knowledge-status"].textContent, /Details saved/);
payload.components[0].fan_evidence = { candidates: [{ connector: "FAN0", pin: "PA8", quote: "FAN0 pin PA8", url: "https://example.org/manual" }], conflicts: [], signature: "a".repeat(64) };
await panel.load();
assert.match(ids["knowledge-records"].textContent, /FAN0 pin PA8/);
assert.equal(panel.reviewButtons[0].disabled, false);
panel.components[0].model.listeners.input();
const reviewCalls = calls.length;
await panel.reviewButtons[0].listeners.click();
assert.equal(calls.length, reviewCalls);
assert.match(ids["knowledge-status"].textContent, /Save your edited details/);
await panel.save(false);
await panel.reviewButtons[0].listeners.click();
assert.equal(calls.find(call => call.path === "/knowledge/review-mappings").body.signature, "a".repeat(64));
assert.equal(panel.setup.revision, 3);
assert.equal(panel.reviewButtons[0].disabled, true);
assert.match(ids["knowledge-records"].textContent, /Connector evidence reviewed/);
await ids["knowledge-refresh"].listeners.click();
assert.equal(panel.busy, true);
assert.equal(ids["knowledge-save"].disabled, true);
assert.match(ids["knowledge-status"].textContent, /0\/3/);
assert.ok(scheduled);
const before = calls.length;
await panel.save(true);
assert.equal(calls.length, before); // No overlapping saves/refreshes.
payload.job = { state: "partial", message: "One source unavailable", completed: 3, total: 3, changes: ["Existing cached copy retained."] };
payload.profile_changed = true;
payload.documents = [{ id: "manta-manual", title: "Manta manual", url: "https://example.org/manual", digest: "a".repeat(64), fetched_at: "2026-10-16" }];
await scheduled();
assert.equal(panel.busy, false);
assert.equal(ids["knowledge-refresh"].textContent, "Refresh knowledge");
assert.match(ids["knowledge-records"].textContent, /saved printer profile changed/);
assert.match(ids["knowledge-records"].textContent, /cached copy retained/);
assert.match(ids["knowledge-records"].textContent, /Download cached copy/);
await panel.download("manta-manual");
scheduled(); // Revoke the download URL.
panel.components[0].model.value = "Unsubmitted model";
fail = true;
await panel.review("mainboard", "a".repeat(64));
assert.match(ids["knowledge-status"].textContent, /Reload details and review/);
await panel.save(false);
assert.equal(panel.components[0].model.value, "Unsubmitted model");
assert.match(ids["knowledge-status"].textContent, /Reload details/);
assert.equal(panel.busy, false);
await panel.download("manta-manual");
assert.match(ids["knowledge-status"].textContent, /409/);
await panel.load();
assert.match(ids["knowledge-status"].textContent, /Details were kept/);
fail = false;
await ids["knowledge-reload"].listeners.click();
assert.equal(panel.components[0].model.value, "BTT Manta E3EZ");
const remove = panel.fields.find(field => field.textContent === "Remove component");
remove.listeners.click();
assert.equal(panel.components.length, 1);
assert.equal(panel.components[0].model.value, "An unfamiliar vendor board");
while (panel.components.length < 12) panel.addComponent();
panel.addComponent();
assert.equal(panel.components.length, 12);
assert.equal(ids["knowledge-add"].disabled, true);
ids["knowledge-close"].listeners.click();
assert.equal(ids["knowledge-panel"].hidden, true);
assert.equal(ids["knowledge-toggle"].focused, true);
assert.ok(cancellations.includes("timer"));

// Closing during I/O must not restart a background UI poll.
payload.job.state = "running";
let release;
pending = new Promise(resolve => { release = resolve; });
scheduled = null;
const opening = panel.open();
panel.close();
release();
await opening;
assert.equal(scheduled, null);
assert.equal(document.getElementById("knowledge-panel").hidden, true);
console.log("Printer knowledge UI checks passed");
