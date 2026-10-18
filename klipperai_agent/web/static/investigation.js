/* Saved turn conversion and manual proposal review presentation. */
function investigationMessages(record) {
  const messages = record.turns.flatMap(turn => [
    ...(turn.imported_history || []).map(item => ({ role: item.role, text: item.text })),
    { role: "user", text: turn.question },
    investigationAnswer(turn.result),
  ]);
  if (record.pending) messages.push(
    { role: "user", text: record.pending.message },
    { role: "assistant", text: "Investigation in progress or interrupted. After a service restart, KlipperAI resumes it with fresh printer reads. The answer will appear here automatically. Delete this chat to discard it." },
  );
  return messages;
}

function investigationAnswer(result) {
  return {
    role: "assistant", text: result.response_text,
    configProposals: result.config_proposals || [],
    sourceCitations: result.source_citations || [],
    agentEvents: result.agent_events || [], nextActions: result.next_actions || [],
    memorySources: result.memory_sources || [],
    mode: result.mode || "chat", contextIncluded: result.context_included || [],
  };
}

class ContextReceipt {
  static append(article, entries, mode) {
    if (!Array.isArray(entries) || !entries.length) return;
    const details = document.createElement("details");
    details.className = "source-citation context-receipt";
    const summary = document.createElement("summary");
    summary.textContent = `Context included · ${mode === "debug" ? "Debug" : "Chat"}`;
    details.appendChild(summary);
    const list = document.createElement("ul");
    for (const entry of entries) {
      if (!entry || typeof entry !== "object") continue;
      const row = document.createElement("li");
      const delivery = entry.sent_to_model ? "included in model request" : "not sent to model";
      row.textContent = `${entry.source}: ${entry.status} (${entry.phase === "tool" ? "follow-up tool" : "starting context"}; ${delivery}). ${entry.detail || ""} Collected ${entry.observed_at || "unknown"}.`;
      list.appendChild(row);
    }
    details.appendChild(list);
    article.appendChild(details);
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
