// Small text-only Markdown renderer. Never interprets model output as HTML.

function appendStrongText(parent, text) {
  const parts = String(text || "").split(/(\*\*[^*]+\*\*)/g);
  for (const part of parts) {
    if (!part) {
      continue;
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.appendChild(strong);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

function appendInlineMarkdown(parent, text) {
  const parts = String(text || "").split(/(`[^`]*`)/g);
  for (const part of parts) {
    if (!part) {
      continue;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      const code = document.createElement("code");
      code.textContent = part.slice(1, -1);
      parent.appendChild(code);
    } else {
      appendStrongText(parent, part);
    }
  }
}

function isMarkdownListLine(line) {
  return /^\s*(?:[-*]\s+|\d+[.)]\s+)/.test(line);
}

function isMarkdownHeadingLine(line) {
  return /^\s{0,3}#{1,4}\s+/.test(line);
}

function isMarkdownFenceLine(line) {
  return /^\s*```/.test(line);
}

function appendCodeBlock(parent, text, language = "") {
  const block = document.createElement("div");
  block.className = "code-block";
  const toolbar = document.createElement("div");
  toolbar.className = "code-toolbar";
  const label = document.createElement("span");
  label.textContent = { lua: "Lua", ini: "Config", python: "Python", javascript: "JavaScript" }[language.toLowerCase()] || language || "Plain text";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "code-copy";
  button.textContent = "Copy";
  button.setAttribute("aria-label", "Copy code");
  button.addEventListener("click", async () => {
    try {
      if (!globalThis.navigator?.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Select text to copy";
    }
  });
  toolbar.appendChild(label);
  toolbar.appendChild(button);
  const pre = document.createElement("pre");
  pre.className = "markdown-code";
  const code = document.createElement("code");
  if (language) code.dataset.language = language;
  code.textContent = text;
  pre.appendChild(code);
  block.appendChild(toolbar);
  block.appendChild(pre);
  parent.appendChild(block);
}

function renderMarkdown(element, text) {
  element.textContent = "";
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fenceMatch = line.match(/^\s*```([A-Za-z0-9_-]+)?\s*$/);
    if (fenceMatch) {
      index += 1;
      const codeLines = [];
      while (index < lines.length && !isMarkdownFenceLine(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }

      appendCodeBlock(element, codeLines.join("\n"), fenceMatch[1] || "");
      continue;
    }

    const headingMatch = line.match(/^\s{0,3}(#{1,4})\s+(.+?)\s*$/);
    if (headingMatch) {
      const level = Math.min(headingMatch[1].length + 2, 6);
      const heading = document.createElement(`h${level}`);
      appendInlineMarkdown(heading, headingMatch[2]);
      element.appendChild(heading);
      index += 1;
      continue;
    }

    if (isMarkdownListLine(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const itemLine = lines[index];
        const itemMatch = ordered
          ? itemLine.match(/^\s*\d+[.)]\s+(.+?)\s*$/)
          : itemLine.match(/^\s*[-*]\s+(.+?)\s*$/);
        if (!itemMatch) {
          break;
        }
        const item = document.createElement("li");
        appendInlineMarkdown(item, itemMatch[1]);
        list.appendChild(item);
        index += 1;
      }
      element.appendChild(list);
      continue;
    }

    const paragraphLines = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isMarkdownFenceLine(lines[index]) &&
      !isMarkdownHeadingLine(lines[index]) &&
      !isMarkdownListLine(lines[index])
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    appendInlineMarkdown(paragraph, paragraphLines.join(" "));
    element.appendChild(paragraph);
  }
}
