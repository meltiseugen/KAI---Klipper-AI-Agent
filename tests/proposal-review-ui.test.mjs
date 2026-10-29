import assert from "node:assert/strict";
import { loadUI, memoryStorage } from "./ui-harness.mjs";

const { ConversationStore, ChatApplication, ShellView, ids } = await loadUI();
const storage = memoryStorage();
const store = new ConversationStore(storage, "Intro");
const review = {
  status: "needs_information", mode: "manual_only",
  errors: ["[fan] max_power (line 3): Value must be at most 1."], warnings: ["Preserve other config."],
  firmware: {flavor:"Klipper",version:"v0.13.0",note:"Version is live; fork identity is saved."},
  checks: [
    {code:"option_value",severity:"error",section:"fan",option:"max_power",line:3,message:"Value must be at most 1.",source_url:"https://www.klipper3d.org/Config_Reference.html#fan"},
    {code:"option_unverified",severity:"warning",section:"fan",option:"<script>custom</script>",message:"Check the exact extension.",source_url:"javascript:alert(1)"},
  ],
  manual_steps: ["Back up the target.", "Verify board and fan ratings.", "Check manually."],
};
const server = {
  async bootstrap() { return {features:["persistent-investigations"],provider:"openai",moonraker_reachable:true}; },
  async investigation(path) { return path ? {id:"saved",turns:[{question:"Review",result:{
    response_text:"Review this draft",config_proposals:[{title:"Fan",config:"[fan]\nmax_power: 2",review}]
  }}]} : [{id:"saved"}]; },
};
const app = new ChatApplication(store, server, new ShellView());
await app.start();
await app.select("saved");
const all = node => [node,...node.children.flatMap(all)];
assert.match(ids.messages.textContent, /Firmware basis: Klipper v0.13.0/);
assert.match(ids.messages.textContent, /Option and version checks/);
assert.match(ids.messages.textContent, /Manual verification checklist/);
assert.match(ids.messages.textContent, /Resolve.*line 3/);
assert.equal(ids.messages.textContent.split("Value must be at most 1.").length, 2, "No duplicate summary/error row");
assert.equal(all(ids.messages).find(node=>node.className==="review-checks").open, true);
assert.equal(all(ids.messages).filter(node=>node.tag==="script").length, 0);
assert.ok(all(ids.messages).filter(node=>node.tag==="a").every(node=>node.href.startsWith("https://")));
assert.match(ids.messages.textContent, /<script>custom<\/script>/);
assert.equal(all(ids.messages).filter(node=>node.tag==="button" && /apply|approve|restart/i.test(node.textContent)).length, 0);
store.save();
const restored = new ConversationStore(storage, "Intro");
restored.restore();
assert.equal(restored.getCurrentConversation().messages.at(-1).configProposals[0].review.manual_steps.length, 3);
console.log("Proposal review: saved firmware basis, checks, source links, manual guidance, escaping and manual-only controls pass.");
