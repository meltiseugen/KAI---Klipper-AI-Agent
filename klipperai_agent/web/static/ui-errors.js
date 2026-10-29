class ChatRequestError extends Error {
  constructor(message, code = "request_failed", status = 0) {
    super(message); this.code = code; this.status = status;
  }
}

function errorPresentation(error) {
  const code = error.code || "request_failed";
  const known = {
    invalid_session: ["Session expired", "The UI session could not be renewed. Reconnect to continue; your question is still here.", "Reconnect"],
    provider_not_configured: ["Provider setup required", "Chat and Debug need an LLM provider and API key. Open Provider settings, select OpenAI, save a key, then manually restart KlipperAI.", "Provider settings"],
    moonraker_unavailable: ["Moonraker unavailable", "Live printer status is unavailable. The agent can still read host logs and saved config when accessible. Check Moonraker, then check the connection again.", "Check connection"],
    status_unavailable: ["Live status disconnected", "Live updates are unavailable. Reconnecting automatically; check the connection to refresh printer status.", "Check connection"],
  };
  const [title, message, action] = known[code] || ["Request failed", String(error.message || error), "Check connection"];
  return { code, title, message, action };
}

class NoticeView {
  constructor(doc) { this.root = doc.getElementById("chat-notices"); this.notices = new Map(); }
  set(code, error) {
    if (error) this.notices.set(code, errorPresentation(error));
    else this.notices.delete(code);
    this.render();
  }
  render(locked = this.locked) {
    this.locked = locked;
    if (!this.root) return;
    this.root.replaceChildren();
    this.root.hidden = !this.notices.size;
    for (const notice of this.notices.values()) {
      const card = document.createElement("section");
      card.className = "notice-card";
      card.setAttribute("role", "status");
      const heading = document.createElement("strong");
      heading.textContent = notice.title;
      const message = document.createElement("p");
      message.textContent = notice.message;
      const button = document.createElement("button");
      button.type = "button"; button.className = "secondary-button";
      button.textContent = notice.action; button.disabled = Boolean(locked);
      button.addEventListener("click", () => this.recover?.(notice.code));
      card.appendChild(heading); card.appendChild(message); card.appendChild(button);
      if (notice.code === "provider_not_configured") {
        const check = document.createElement("button");
        check.type = "button"; check.className = "secondary-button";
        check.textContent = "Check setup"; check.disabled = Boolean(locked);
        check.addEventListener("click", () => this.recover?.("request_failed"));
        card.appendChild(check);
      }
      this.root.appendChild(card);
    }
  }
}
