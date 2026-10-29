// Renders one message; network/state changes belong to the application.
class MessageView {
  constructor(template, revalidate) {
    this.template = template;
    this.revalidate = revalidate;
  }

  appendConfigProposals(article, configProposals) {
    for (const proposal of configProposals) {
      const card = document.createElement("section");
      card.className = "config-proposal";

      const title = document.createElement("h3");
      title.textContent = proposal.title;
      card.appendChild(title);

      const target = document.createElement("p");
      target.className = "config-proposal-target";
      target.textContent = `Target file: ${proposal.target_file}`;
      card.appendChild(target);

      const rationale = document.createElement("p");
      rationale.className = "config-proposal-rationale";
      rationale.textContent = proposal.rationale;
      card.appendChild(rationale);

      const code = document.createElement("pre");
      code.className = "config-proposal-code";
      code.textContent = proposal.config;
      card.appendChild(code);

      if (proposal.assumptions?.length) {
        const assumptions = document.createElement("ul");
        assumptions.className = "config-proposal-list";
        for (const item of proposal.assumptions) {
          const li = document.createElement("li");
          li.textContent = item;
          assumptions.appendChild(li);
        }
        card.appendChild(assumptions);
      }

      if (proposal.warnings?.length) {
        const warnings = document.createElement("ul");
        warnings.className = "config-proposal-list warnings";
        for (const item of proposal.warnings) {
          const li = document.createElement("li");
          li.textContent = item;
          warnings.appendChild(li);
        }
        card.appendChild(warnings);
      }

      ProposalReviewCard.append(card, proposal, this.revalidate);
      article.appendChild(card);
    }
  }

  formatSourceCitationLabel(citation) {
    if (citation.label) {
      return citation.label;
    }
    const section = citation.section ? ` [${citation.section}]` : "";
    if (citation.path && citation.lineNumber) {
      return `${citation.path}:${citation.lineNumber}${section}`;
    }
    return citation.path ? `${citation.path}${section}` : citation.section || "Config source";
  }

  appendSourceCitations(article, sourceCitations) {
    const citations = normalizeSourceCitations(sourceCitations);
    if (!citations.length) {
      return;
    }

    const section = document.createElement("section");
    section.className = "source-citations";
    section.setAttribute("aria-label", "Sources");

    const title = document.createElement("div");
    title.className = "source-citations-title";
    title.textContent = "Sources";
    section.appendChild(title);

    const list = document.createElement("div");
    list.className = "source-citations-list";

    for (const citation of citations) {
      const item = document.createElement("details");
      item.className = "source-citation";

      const summary = document.createElement("summary");
      summary.textContent = this.formatSourceCitationLabel(citation);
      if (citation.pageNumber) summary.textContent += ` · PDF page ${citation.pageNumber}`;
      if (citation.lineNumber) {
        const range = citation.endLine && citation.endLine !== citation.lineNumber ? `–${citation.endLine}` : "";
        summary.textContent += ` · ${citation.lineBasis === "excerpt" ? "excerpt" : citation.lineBasis === "file" ? "file" : "source"} line ${citation.lineNumber}${range}${citation.section ? ` [${citation.section}]` : ""}`;
      }
      item.appendChild(summary);
      if (citation.observedAt || citation.configRevision || citation.sourceDigest || citation.firmwareCommit) {
        const provenance = document.createElement("p");
        provenance.textContent = [citation.observedAt ? `Collected ${citation.observedAt}` : "", citation.configRevision ? `Config revision ${citation.configRevision}` : "", citation.sourceDigest ? `Source SHA-256 ${citation.sourceDigest}` : "", citation.firmwareCommit ? `Firmware commit ${citation.firmwareCommit}` : ""].filter(Boolean).join(" · ");
        item.appendChild(provenance);
      }
      if (citation.url) {
        const link = document.createElement("a");
        link.href = citation.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = citation.label || citation.url;
        item.appendChild(link);
      }

      const excerpt = document.createElement("pre");
      excerpt.className = "source-citation-excerpt";
      excerpt.textContent = citation.excerpt?.trim() || "No section excerpt was available in the collected config.";
      item.appendChild(excerpt);
      questionButton(item, "Analyze this source",
        `Analyze this source in more detail: ${this.formatSourceCitationLabel(citation)}\n${citation.excerpt?.slice(0, 2000) || ""}\nExplain how it relates to the problem and what evidence is still missing.`, this.followUp);

      list.appendChild(item);
    }

    section.appendChild(list);
    article.appendChild(section);
  }

  buildMessageElement(entry, options = {}) {
    const fragment = this.template?.content?.cloneNode(true) || document.createDocumentFragment();
    const article = fragment.querySelector(".message") || document.createElement("article");
    let meta = article.querySelector(".message-meta") || fragment.querySelector(".message-meta");
    let content = article.querySelector(".message-body") || fragment.querySelector(".message-body");

    article.classList.add("message");

    if (!meta) {
      meta = document.createElement("div");
      meta.className = "message-meta";
      article.appendChild(meta);
    }

    if (!content) {
      content = document.createElement("div");
      content.className = "message-body";
      article.appendChild(content);
    }

    article.classList.add(entry.role);
    article.setAttribute("aria-label", entry.role === "user" ? "Your message" : "Agent response");
    setText(meta, entry.role === "user" ? "You" : "KlipperAI");
    content.classList.toggle("markdown", entry.role === "assistant");
    if (entry.role === "assistant") {
      renderMarkdown(content, entry.text);
    } else {
      setText(content, entry.text);
    }

    if (options.pending) {
      article.classList.add("pending");
      content.appendChild(this.buildLoadingDots());
    }

    if (entry.role === "assistant" && entry.configProposals?.length) {
      this.appendConfigProposals(article, entry.configProposals);
    }

    if (entry.role === "assistant") {
      ModelUsageView.append(article, entry.modelUsage);
      const findings = normalizeFindings(entry.findings);
      appendFindingCards(article, findings, this.followUp);
      appendAnswerDetails(article, entry);
      const claimCitations = (entry.answerClaims || []).flatMap(item => item.citations || []);
      if (findings.some(item => item.evidence) || entry.sourceCitations?.length || claimCitations.length) {
        const evidence = resultCard("Evidence", "evidence-card");
        appendFindingEvidence(evidence, findings);
        const sources = normalizeSourceCitations([...(entry.sourceCitations || []), ...findings.flatMap(item => item.citations), ...claimCitations]);
        const seen = new Set();
        this.appendSourceCitations(evidence, sources.filter(item => {
          const key = JSON.stringify([item.path, item.lineNumber, item.endLine, item.section]);
          if (seen.has(key)) return false;
          seen.add(key); return true;
        }));
        article.appendChild(evidence);
      }
      AgentActivity.appendActions(article, [...new Set([...(entry.nextActions || []), ...findings.map(item => item.proposed_fix).filter(Boolean)])], this.followUp);
      if (entry.agentStatus === "limited" || entry.agentStatus === "error") {
        const status = document.createElement("p");
        status.className = "result-status";
        status.textContent = entry.agentStatus === "limited" ? "Partial result · Some investigation steps could not be completed." : "Investigation error · Review the available evidence before continuing.";
        article.appendChild(status);
      }
      AgentActivity.append(article, entry.agentEvents);
      InvestigationEvidence.append(article, entry.memorySources);
      ContextReceipt.append(article, entry.contextIncluded, entry.mode);
    }

    if (entry.role === "user" && entry.attachments?.length) {
      const receipt = document.createElement("p");
      receipt.className = "attachment-receipt";
      receipt.textContent = `Attached: ${entry.attachments.join(", ")}`;
      article.appendChild(receipt);
    }

    return article;
  }

  buildLoadingDots() {
    const dots = document.createElement("span");
    dots.className = "loading-dots";
    dots.setAttribute("aria-hidden", "true");

    for (let index = 0; index < 3; index += 1) {
      dots.appendChild(document.createElement("span"));
    }

    return dots;
  }
}
