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
    if (!response.ok) throw new Error(`Session bootstrap failed (${response.status}).`);
    this.sessionId = (await response.json()).session_id;
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
    if (!response.ok) throw new Error(`Request failed (${response.status}). Please retry.`);
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
