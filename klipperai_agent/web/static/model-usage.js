// Public provider attempts, independent of whether a model was configured.
function normalizeModelUsage(value) {
  if (!value || typeof value !== "object") return null;
  const count = value => Number.isSafeInteger(value) && value > 0 ? value : 0;
  return {
    status: ["not_used", "attempted", "completed"].includes(value.status) ? value.status : "unknown",
    requests_started: count(value.requests_started),
    requests_completed: Math.min(count(value.requests_started), count(value.requests_completed)),
    models: Array.isArray(value.models) ? value.models.filter(item => typeof item === "string").slice(0, 24) : [],
  };
}

class ModelUsageView {
  static append(article, value) {
    const usage = normalizeModelUsage(value);
    if (!usage) return;
    const receipt = document.createElement("details");
    receipt.className = "model-usage";
    receipt.setAttribute("aria-label", "LLM use for this attempt");
    const summary = document.createElement("summary");
    const detail = document.createElement("p");
    if (usage.status === "unknown") {
      summary.textContent = "Usage not recorded";
      detail.textContent = "LLM use was not recorded for this result.";
    } else if (!usage.requests_started) {
      summary.textContent = "LLM not contacted";
      detail.textContent = "No LLM request was sent for this attempt.";
    } else {
      summary.textContent = `${usage.models.join(", ")} · ${usage.requests_started} request${usage.requests_started === 1 ? "" : "s"}${usage.requests_completed ? "" : " attempted"}`;
      detail.textContent = `${usage.requests_completed ? "LLM used" : "LLM request attempted"} · ${usage.models.join(", ")} · ${usage.requests_started} request(s), ${usage.requests_completed} provider response(s) received.`;
    }
    receipt.appendChild(summary);
    receipt.appendChild(detail);
    article.appendChild(receipt);
  }
}
