import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const template = await readFile(new URL("../integrations/octoeverywhere/navigation.js", import.meta.url), "utf8");
const prefix = "/assistant/printer/";
const html = '<!doctype html><body data-api-base="/assistant/printer/api">KlipperAI</body>';

async function scenario({ connected = true, target = "_blank", pathname = "/", loaded = false, blocked = false, badHistory = false, badHtml = false, failed = false } = {}) {
  const calls = { writes: [], popupWrites: [], fetched: [], assigned: [], replaced: [], logs: [] };
  class Element {
    constructor() { this.dataset = {}; this.classList = { remove() {} }; }
    closest(selector) { return selector.startsWith("a[") ? link : null; }
    removeAttribute() {}
    blur() {}
  }
  class Anchor extends Element {}
  const link = new Anchor();
  const document = {
    body: new Element(), listeners: {}, open() {}, close() {},
    write(value) { calls.writes.push(value); },
    addEventListener(name, fn) { this.listeners[name] = fn; },
  };
  if (loaded) document.body.dataset.apiBase = prefix + "api";
  const popup = {
    opener: {}, focus() {},
    history: { replaceState() { if (badHistory) throw new Error("Denied"); } },
    document: { open() {}, close() {}, write(value) { calls.popupWrites.push(value); } },
    location: { replace(value) { calls.replaced.push(value); } },
  };
  const window = {
    location: { pathname, origin: "https://fixture.octoeverywhere.com", assign(value) { calls.assigned.push(value); } },
    open() { return blocked ? null : popup; },
    requestAnimationFrame(fn) { fn(); }, setTimeout(fn) { fn(); },
  };
  const context = vm.createContext({
    window, document, URL, Element, HTMLElement: Element, HTMLAnchorElement: Anchor,
    oe_is_connected_via_oe: () => connected, oe_log: value => calls.logs.push(value),
    fetch: async (url, options) => {
      calls.fetched.push({ url, ...options });
      return { ok: !failed, status: failed ? 502 : 200, text: async () => badHtml ? "Mainsail" : html };
    },
  });
  vm.runInContext(template.replaceAll("@@PREFIX@@", JSON.stringify(prefix)).replaceAll("@@TARGET@@", JSON.stringify(target)), context);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  await flush();
  const click = async () => {
    document.listeners.click?.({ target: link, preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {} });
    await flush();
  };
  return { calls, click, link, popup };
}

const local = await scenario({ connected: false });
await local.click();
assert.equal(local.calls.fetched.length, 0);
const normal = await scenario();
await normal.click();
assert.equal(normal.link.target, "_blank");
assert.equal(normal.popup.opener, null);
assert.deepEqual(normal.calls.popupWrites, [html]);
assert.ok(normal.calls.fetched[0].url.startsWith("https://fixture.octoeverywhere.com/assistant/printer/direct?"));
assert.equal(normal.calls.fetched[0].credentials, "same-origin");
assert.equal(normal.calls.fetched[0].cache, "no-store");
const self = await scenario({ target: "_self" });
await self.click();
assert.deepEqual(self.calls.assigned, [prefix]);
const rescue = await scenario({ pathname: prefix });
assert.deepEqual(rescue.calls.writes, [html]);
const loaded = await scenario({ pathname: prefix, loaded: true });
assert.equal(loaded.calls.fetched.length, 0);
for (const options of [{ badHtml: true }, { failed: true }, { badHistory: true }]) {
  const failed = await scenario(options);
  await failed.click();
  assert.equal(failed.calls.popupWrites.length, 0);
  assert.ok(failed.calls.replaced[0].startsWith("https://fixture.octoeverywhere.com" + prefix));
}
const blocked = await scenario({ blocked: true });
await blocked.click();
assert.ok(blocked.calls.assigned[0].startsWith("https://fixture.octoeverywhere.com" + prefix));

export const outcome = "OctoEverywhere custom-prefix navigation, popup rescue, blocked popups, bad HTML and local bypass pass.";
console.log(outcome);
