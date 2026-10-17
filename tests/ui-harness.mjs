import { readFile } from "node:fs/promises";
import vm from "node:vm";

// Minimal DOM for deterministic rendering checks, not a browser/layout substitute.
export function element(tag) {
  let text = "";
  const classes = new Set();
  return {
    tag, children: [], listeners: {}, attributes: {}, dataset: {}, value: "",
    classList: {
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      contains(name) { return classes.has(name); },
      toggle(name, force = !classes.has(name)) {
        if (force) classes.add(name); else classes.delete(name);
      },
    },
    set className(value) { classes.clear(); value.split(" ").forEach(name => classes.add(name)); },
    get className() { return [...classes].join(" "); },
    set textContent(value) { text = String(value); this.children = []; },
    get textContent() { return text + this.children.map(child => child.textContent).join(""); },
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    querySelector(selector) {
      for (const child of this.children) {
        if (selector.startsWith(".") && child.classList.contains(selector.slice(1))) return child;
        const nested = child.querySelector(selector);
        if (nested) return nested;
      }
      return null;
    },
    focus() { this.focused = true; },
    click() { this.clicked = true; return this.listeners.click?.(); },
  };
}

export async function loadUI(globals = {}) {
  const ids = Object.fromEntries([
    "message-input", "messages", "history-list", "send-button", "new-chat-button",
    "composer-status", "shell-menu-toggle", "shell-scrim", "provider-badge",
    "model-badge", "moonraker-badge", "klipper-badge", "moonraker-events-badge",
    "agent-mode", "mode-description", "conversation-panel",
    "knowledge-toggle", "knowledge-panel", "knowledge-form", "knowledge-status",
    "knowledge-records", "knowledge-save", "knowledge-refresh", "knowledge-reload", "knowledge-close", "knowledge-add",
    "providers-toggle", "providers-panel", "providers-form", "providers-status", "providers-key", "providers-remove",
    "providers-close", "providers-reload", "providers-validate", "providers-save",
  ].map(id => [id, element("div")]));
  const document = {
    body: element("body"), getElementById: id => ids[id], createElement: element,
    createDocumentFragment: () => element("fragment"),
    createTextNode: value => { const node = element("text"); node.textContent = value; return node; },
  };
  const context = vm.createContext({ TextDecoder, document, console, setTimeout, clearTimeout, URL, ...globals });
  const manifest = JSON.parse(await readFile(new URL("../klipperai_agent/web/static/scripts.json", import.meta.url), "utf8"));
  for (const name of manifest.filter(name => name !== "embed.js")) {
    vm.runInContext(await readFile(new URL(`../klipperai_agent/web/static/${name}`, import.meta.url), "utf8"), context);
  }
  vm.runInContext("globalThis.UI = { ConversationStore, ChatTransport, ChatApplication, ShellView, resolveApiBase, PrinterKnowledgePanel, ProviderPanel, MoonrakerStatusFeed };", context);
  return { ...context.UI, document, ids };
}

export function memoryStorage() {
  const data = new Map();
  return { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value) };
}

export function jsonResponse(payload, status = 200) {
  return { ok: status < 400, status, json: async () => payload };
}
