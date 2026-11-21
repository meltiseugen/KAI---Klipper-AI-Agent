// Public findings and suggested questions. All source/model text stays text-only.
function normalizeFindings(value) {
  return Array.isArray(value) ? value.filter(item => item && typeof item.summary === "string").map(item => ({
    summary: item.summary, code: String(item.code || ""), source: String(item.source || ""),
    severity: ["low", "medium", "high", "critical"].includes(item.severity) ? item.severity : "medium",
    evidence: String(item.evidence || ""), proposed_fix: String(item.proposed_fix || ""),
    citations: normalizeSourceCitations(item.citations),
    recovery: item.recovery && typeof item.recovery === "object" ? item.recovery : null,
  })) : [];
}

function resultCard(title, className) {
  const collapsed = className === "evidence-card" || className === "answer-details";
  const section = document.createElement(collapsed ? "details" : "section");
  section.className = `result-card ${className}`;
  section.setAttribute("aria-label", title);
  const heading = document.createElement(collapsed ? "summary" : "h3");
  heading.textContent = title;
  section.appendChild(heading);
  return section;
}

function questionButton(parent, label, question, followUp) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button follow-up-button";
  button.textContent = label;
  button.disabled = !followUp;
  button.addEventListener("click", () => followUp?.(question));
  parent.appendChild(button);
}

function appendFindingCards(article, findings, followUp) {
  if (!findings.length) return;
  const section = resultCard("Findings", "findings-card");
  for (const finding of findings) {
    const row = document.createElement("div");
    row.className = `finding finding-${finding.severity}`;
    const severity = document.createElement("span");
    severity.className = "finding-severity";
    severity.textContent = finding.severity;
    row.appendChild(severity);
    const title = document.createElement("h4");
    title.textContent = finding.summary;
    row.appendChild(title);
    const source = document.createElement("p");
    source.textContent = [finding.source, finding.code].filter(Boolean).join(" · ");
    row.appendChild(source);
    appendRecoveryPlaybook(row, finding.recovery);
    questionButton(row, "Investigate finding",
      `Investigate this finding in more detail: ${finding.summary}\nSource: ${finding.source}\nWhat evidence supports it, what else could explain it, and what should I check manually?`, followUp);
    section.appendChild(row);
  }
  article.appendChild(section);
}

function appendTextList(parent, title, values, ordered = false) {
  if (!Array.isArray(values) || !values.length) return;
  const heading = document.createElement("h4");
  heading.textContent = title;
  parent.appendChild(heading);
  const list = document.createElement(ordered ? "ol" : "ul");
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = String(value);
    list.appendChild(item);
  }
  parent.appendChild(list);
}

function appendRecoveryPlaybook(parent, plan) {
  if (!plan) return;
  const details = document.createElement("details");
  details.className = "source-citation recovery-playbook";
  const summary = document.createElement("summary");
  summary.textContent = `Manual recovery: ${String(plan.title || "Investigation steps")}`;
  details.appendChild(summary);
  appendTextList(details, "Evidence to collect", plan.required_evidence);
  appendTextList(details, "Manual checks", plan.steps, true);
  appendTextList(details, "Verification", plan.verification);
  appendTextList(details, "Stop conditions", plan.stop_conditions);
  for (const url of Array.isArray(plan.source_urls) ? plan.source_urls : []) {
    if (!/^https?:\/\//i.test(String(url))) continue;
    const link = document.createElement("a");
    link.href = String(url); link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = "Reference documentation";
    details.appendChild(link);
  }
  parent.appendChild(details);
}

function appendAnswerDetails(article, entry) {
  const claims = Array.isArray(entry.answerClaims) ? entry.answerClaims : [];
  if (!claims.length && !entry.hypotheses?.length && !entry.missingEvidence?.length) return;
  const section = resultCard("Conclusions and gaps", "answer-details");
  appendTextList(section, "Cited conclusions", claims.map(item => item.claim));
  appendTextList(section, "Hypotheses (unconfirmed)", entry.hypotheses);
  appendTextList(section, "Missing evidence", entry.missingEvidence);
  article.appendChild(section);
}

function appendFindingEvidence(section, findings) {
  for (const finding of findings.filter(item => item.evidence)) {
    const details = document.createElement("details");
    details.className = "source-citation";
    const summary = document.createElement("summary");
    summary.textContent = `${finding.source || "Finding evidence"}: ${finding.summary}`;
    const excerpt = document.createElement("pre");
    excerpt.className = "source-citation-excerpt";
    excerpt.textContent = finding.evidence;
    details.appendChild(summary);
    details.appendChild(excerpt);
    section.appendChild(details);
  }
}

