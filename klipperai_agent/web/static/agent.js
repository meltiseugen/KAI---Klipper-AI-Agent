/* Public tool activity only; never render model reasoning or raw tool output. */
class AgentActivity {
  static normalize(events) {
    return Array.isArray(events) ? events.filter(event => event && typeof event.message === "string") : [];
  }

  static append(article, events) {
    const completed = AgentActivity.normalize(events).filter(event => event.kind !== "tool_started");
    if (!completed.length) return;
    const details = document.createElement("details");
    details.className = "source-citation agent-activity";
    const summary = document.createElement("summary");
    summary.textContent = `Investigation activity (${completed.length})`;
    details.appendChild(summary);
    const list = document.createElement("ul");
    for (const event of completed) {
      const item = document.createElement("li");
      item.textContent = event.message;
      list.appendChild(item);
    }
    details.appendChild(list);
    article.appendChild(details);
  }

  static appendActions(article, actions, followUp) {
    if (!Array.isArray(actions) || !actions.length) return;
    const section = document.createElement("section");
    section.className = "result-card next-actions-card";
    section.setAttribute("aria-label", "Next actions");
    const heading = document.createElement("h4");
    heading.textContent = "Next actions";
    section.appendChild(heading);
    const list = document.createElement("ul");
    for (const action of actions) {
      const item = document.createElement("li");
      item.textContent = String(action);
      if (followUp) questionButton(item, "Explain this check",
        `Explain this suggested manual check: ${action}\nWhy is it useful, what should I look for, and what precautions apply?`, followUp);
      list.appendChild(item);
    }
    section.appendChild(list);
    article.appendChild(section);
  }
}

class ChatStreamReader {
  async read(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let result = null;
    try {
      while (true) {
        const { value, done } = await reader.read();
        pending += decoder.decode(value, { stream: !done });
        let boundary;
        while ((boundary = pending.indexOf("\n\n")) >= 0) {
          const block = pending.slice(0, boundary);
          pending = pending.slice(boundary + 2);
          const name = block.split("\n").find(line => line.startsWith("event: "))?.slice(7);
          const data = block.split("\n").filter(line => line.startsWith("data: ")).map(line => line.slice(6)).join("\n");
          if (!data) continue;
          const payload = JSON.parse(data);
          if (name === "agent") onEvent(payload);
          if (name === "error") {
            const error = new Error(payload.message);
            error.code = payload.code;
            error.modelUsage = payload.model_usage;
            throw error;
          }
          if (name === "result") result = payload;
        }
        if (done) break;
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    if (!result) throw new Error("The investigation ended without a response. Please try again.");
    return result;
  }
}
