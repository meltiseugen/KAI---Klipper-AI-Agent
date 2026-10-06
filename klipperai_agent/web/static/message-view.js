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
      item.appendChild(summary);
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
      AgentActivity.appendActions(article, entry.nextActions);
      AgentActivity.append(article, entry.agentEvents);
      InvestigationEvidence.append(article, entry.memorySources);
    }

    if (entry.role === "assistant" && entry.sourceCitations?.length) {
      this.appendSourceCitations(article, entry.sourceCitations);
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
