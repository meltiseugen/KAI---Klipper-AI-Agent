import assert from "node:assert/strict";
import test from "node:test";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

test("recovery plans and grounded citations render safely and survive history restoration", async () => {
  const ui = await loadUI();
  const citation = { path: "printer.cfg", line_number: 3, end_line: 4, line_basis: "file", section: "extruder", excerpt: "step_pin: PA1", evidence_id: "evidence", observed_at: "2026-10-27T12:00:00Z", config_revision: "revision" };
  const storage = memoryStorage();
  const store = new ui.ConversationStore(storage, "Intro");
  store.restore();
  store.getCurrentConversation().messages.push({ role: "assistant", text: "A command was rejected.",
    findings: [{ summary: "Cold extrusion", source: "upload.log", severity: "high", evidence: "Extrude below minimum temp", citations: [citation], recovery: {
      title: "Extrusion safety rejection", required_evidence: ["Originating macro"], steps: ["<script>inspect</script>", "Check temperature-wait order"], verification: ["Guards remain enabled"], stop_conditions: ["Stop for implausible readings"], source_urls: ["javascript:bad", "https://www.klipper3d.org/Config_Reference.html"] } }],
    answerClaims: [{ claim: "The configured pin is present on disk", citations: [citation] }],
    hypotheses: ["Command order needs checking"], missingEvidence: ["Incident temperature"] });
  store.save();
  const restored = new ui.ConversationStore(storage, "Intro");
  restored.restore();
  const view = new ui.ShellView();
  const app = new ui.ChatApplication(restored, {}, view);
  app.render();
  const text = ui.ids.messages.textContent;
  for (const expected of ["Manual recovery: Extrusion safety rejection", "Evidence to collect", "Manual checks", "Verification", "Stop conditions", "<script>inspect</script>", "file line 3–4 [extruder]", "Config revision revision", "Cited conclusions", "Hypotheses (unconfirmed)", "Missing evidence", "Incident temperature"]) assert.ok(text.includes(expected), expected);
  const descendants = node => [node, ...node.children.flatMap(descendants)];
  assert.ok(!descendants(ui.ids.messages).some(node => node.tag === "script"));
  assert.ok(!descendants(ui.ids.messages).some(node => node.href?.startsWith("javascript:")));
  const sources = descendants(ui.ids.messages).find(node => node.className === "source-citations-list");
  assert.equal(sources.children.length, 1, "raw and normalized references to the same source are deduplicated");
  assert.equal(restored.getCurrentConversation().messages.at(-1).findings[0].citations[0].evidenceId, "evidence");
});
