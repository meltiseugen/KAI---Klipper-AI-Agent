/* Persistent conversation transport and manual proposal review presentation. */
class InvestigationClient {
  constructor(apiBase, sessionProvider) {
    this.base = `${apiBase}/investigations`;
    this.sessionProvider = sessionProvider;
  }

  async request(path = "", method = "GET") {
    let session = await this.sessionProvider();
    const send = () => fetch(`${this.base}${path}?session_id=${encodeURIComponent(session)}`, { method });
    let response = await send();
    if (response.status === 403) {
      session = await this.sessionProvider(true);
      response = await send();
    }
    if (!response.ok) throw new Error(`Investigation request failed (${response.status}). Please reload and retry.`);
    return response.status === 204 ? null : response.json();
  }

  static messages(record) {
    return record.turns.flatMap(turn => [
      ...(turn.imported_history || []).map(item => ({ role: item.role, text: item.text })),
      { role: "user", text: turn.question },
      InvestigationClient.answer(turn.result),
    ]);
  }

  static answer(result) {
    return {
      role: "assistant", text: result.response_text,
      configProposals: result.config_proposals || [],
      sourceCitations: result.source_citations || [],
      agentEvents: result.agent_events || [], nextActions: result.next_actions || [],
      memorySources: result.memory_sources || [],
    };
  }
}

class InvestigationEvidence {
  static append(article, sources) {
    if (!Array.isArray(sources) || !sources.length) return;
    const details = document.createElement("details");
    details.className = "source-citation";
    const summary = document.createElement("summary");
    summary.textContent = `Historical context supplied (${sources.length})`;
    details.appendChild(summary);
    const list = document.createElement("ul");
    for (const source of sources) {
      const item = document.createElement("li");
      item.textContent = `${source.source} — observed ${source.observed_at}; current state must be rechecked.`;
      list.appendChild(item);
    }
    details.appendChild(list);
    article.appendChild(details);
  }
}

class ProposalReviewCard {
  static append(card, proposal, onRecheck) {
    const review = proposal.review;
    if (!review) return;
    const section = document.createElement("section");
    section.setAttribute("aria-label", "Manual configuration review");
    const heading = document.createElement("h4");
    heading.textContent = {
      needs_information: "Resolve these issues before editing",
      manual_review: "Static checks complete — manual review required",
      stale: "Configuration changed — refresh this proposal",
    }[review.status] || "Manual review required";
    section.appendChild(heading);
    const list = document.createElement("ul");
    for (const message of [...(review.errors || []), ...(review.warnings || [])]) {
      const item = document.createElement("li");
      item.textContent = message;
      list.appendChild(item);
    }
    section.appendChild(list);
    if (review.reviewed_at) {
      const date = document.createElement("p");
      date.textContent = `Reviewed ${review.reviewed_at}. Recheck after changing configuration.`;
      section.appendChild(date);
    }
    if (review.comparison) {
      const details = document.createElement("details");
      const label = document.createElement("summary");
      label.textContent = "Compare proposed sections";
      details.appendChild(label);
      const code = document.createElement("pre");
      code.className = "config-proposal-code";
      code.textContent = review.comparison;
      details.appendChild(code);
      section.appendChild(details);
    }
    if (onRecheck) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Recheck current config";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await onRecheck(review.proposal_id); }
        catch (error) {
          const message = document.createElement("p");
          message.textContent = String(error);
          section.appendChild(message);
        } finally { button.disabled = false; }
      });
      section.appendChild(button);
    }
    card.appendChild(section);
  }
}
