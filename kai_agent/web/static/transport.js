// Same-origin transport for local, nginx, and OctoEverywhere access.
function resolveApiBase(configured, pathname = window.location.pathname) {
  const value = String(configured || "").trim().replace(/\/+$/, "");
  if (value && value !== "/api") return value;
  const root = pathname.replace(/\/+$/, "").replace(/\/(?:embed|direct)$/i, "");
  return root && root !== "/api" ? `${root}/api` : "/api";
}

class ChatTransport {
  constructor(base, fetcher = (...args) => fetch(...args)) {
    this.base = base;
    this.fetcher = fetcher;
    this.sessionId = null;
  }

  async session(refresh = false) {
    if (this.sessionId && !refresh) return this.sessionId;
    const response = await this.fetcher(`${this.base}/ui-sessions`, { method: "POST" });
    if (!response.ok) throw new ChatRequestError(`Session bootstrap failed (${response.status}).`, response.status === 403 ? "invalid_session" : "request_failed", response.status);
    this.sessionId = (await response.json()).session_id;
    if (!this.sessionId || typeof this.sessionId !== "string") throw new ChatRequestError("Invalid session response.", "invalid_session");
    return this.sessionId;
  }

  async request(path, method = "GET", body = null) {
    const send = async (refresh = false) => {
      const session = await this.session(refresh);
      const url = `${this.base}${path}${body ? "" : `?session_id=${encodeURIComponent(session)}`}`;
      return this.fetcher(url, {
        method, credentials: "same-origin", cache: "no-store",
        ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, session_id: session }) } : {}),
      });
    };
    let response = await send();
    if (response.status === 403) response = await send(true);
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch { /* Proxies may return HTML. */ }
      const invalidSession = response.status === 403 && (!detail || /session/i.test(String(detail)));
      const code = invalidSession ? "invalid_session" : detail?.code || "request_failed";
      const message = typeof detail === "string" ? detail : detail?.message;
      throw new ChatRequestError(message || `Request failed (${response.status}). Please retry.`, code, response.status);
    }
    return response;
  }

  async bootstrap() { return (await this.request("/bootstrap")).json(); }

  async chat(request, onEvent) {
    const response = await this.request("/chat/stream", "POST", request);
    return new ChatStreamReader().read(response, onEvent);
  }

  async investigation(path = "", method = "GET") {
    const response = await this.request(`/investigations${path}`, method);
    return response.status === 204 ? null : response.json();
  }
}
