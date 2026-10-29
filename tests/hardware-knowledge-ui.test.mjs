import assert from "node:assert/strict";
import test from "node:test";
import { loadUI, jsonResponse } from "./ui-harness.mjs";

test("hardware records require explicit checks, retain source identity, and use configured live routes", async () => {
  const ui = await loadUI();
  const payload = {
    setup: { components: [{role:"mainboard",model:"Example",revision:"1",mcu:"mcu",confirmed:true}], revision:1, firmware_repository:"https://github.com/Klipper3d/klipper", firmware_commit:"a".repeat(40), reviewed_bus_mappings:{}, diagram_notes:[], validation:{checked_at:"now",printer_reachable:false,gaps:["Not connected"]} },
    components: [], documents: [{id:"d".repeat(32),digest:"e".repeat(64),title:"Manual",url:"https://example.org/manual.pdf",fetched_at:"now",pages:[{page:2,images:1,vector_paths:3,diagram_labels:["<script>diagram</script>"]}]}],
    connector_inventory:{mainboard:[{role:"mainboard",connector:"FAN1",occupancy:"occupied",attached_device:"Exhaust",electrical_confirmed:false,observed_at:"now",stale:true}]},
    bus_evidence:{mainboard:{candidates:[{bus:"spi1",pins:["PA5","PA6","PA7"],quote:"BUS_PINS_spi1=PA5,PA6,PA7"}],signature:"b".repeat(64),conflicts:[]}},
    job:{state:"idle",message:"Ready",changes:[]}, automatic_research:false, profile_changed:false,
  };
  const calls=[];
  const transport={async request(path,method,body) {
    calls.push({path,method,body});
    if (path === "/providers/probe") return jsonResponse({passed:false,message:"Provider not configured"});
    if (path === "/knowledge/validate") return jsonResponse({printer_reachable:false});
    return jsonResponse(payload);
  }};
  const panel = new ui.PrinterKnowledgePanel(transport);
  await panel.load(true);
  assert.equal(panel.values().firmware_commit, "a".repeat(40));
  assert.match(ui.ids["knowledge-records"].textContent, /stale identity; recheck/);
  assert.match(ui.ids["knowledge-records"].textContent, /Page 2.*Visual review required/);
  assert.match(ui.ids["knowledge-records"].textContent, /provider credits/);
  const descendants=node=>[node,...node.children.flatMap(descendants)];
  const findButton=text=>descendants(panel.records).find(node=>node.tag==="button"&&node.textContent===text);
  const labeled=text=>descendants(panel.records).find(node=>node.tag==="label"&&node.children[0]?.textContent===text)?.children[1];
  await findButton("Record connector observation").click();
  assert.match(panel.status.textContent,/confirmation is required/);
  assert.ok(!calls.some(call=>call.path==="/knowledge/connectors"));
  labeled("I physically checked this connector and confirm this observation").checked=true;
  labeled("Exact connector label").value="FAN2";
  await findButton("Record connector observation").click();
  await new Promise(resolve=>setImmediate(resolve));
  const observation=calls.find(call=>call.path==="/knowledge/connectors").body;
  assert.equal(observation.revision,1); assert.equal(observation.observation.confirmed,true);
  assert.equal(observation.observation.connector,"FAN2");
  await findButton("Record diagram note").click();
  assert.match(panel.status.textContent,/Confirm visual review/);
  labeled("I checked this page in the cached source").checked=true;
  labeled("Diagram description or labels you verified").value="Pinout labels";
  await findButton("Record diagram note").click();
  await new Promise(resolve=>setImmediate(resolve));
  const note=calls.find(call=>call.path==="/knowledge/diagram-notes").body.observation;
  assert.equal(note.page,2); assert.equal(note.digest,"e".repeat(64));
  await findButton("I checked this exact hardware/firmware pinmux").click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.some(call=>call.path==="/knowledge/review-buses"));
  await findButton("Check live printer").click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(panel.status.textContent,/unavailable/);
  await findButton("Check live provider response").click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(panel.status.textContent,/Provider not configured/);
  const count=panel.fields.length;
  await panel.load(false); await panel.load(false);
  assert.equal(panel.fields.length,count,"polling replaces action fields without retaining old DOM controls");
  panel.dirty=true;
  const before=calls.length;
  await panel.actions.submit("/validate",{});
  assert.equal(calls.length,before); assert.match(panel.status.textContent,/Save edited/);
  assert.ok(!descendants(panel.records).some(node=>node.tag==="script"));
});
