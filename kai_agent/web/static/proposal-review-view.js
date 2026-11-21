// Optional review fields preserve rendering of investigations saved before these checks.
function appendReviewDetails(section, review) {
  if (review.managed_include) {
    const plan = document.createElement("p");
    plan.className = "managed-include-plan";
    plan.textContent = review.managed_include;
    section.appendChild(plan);
  }
  if (review.status === "manual_review") {
    for (const patch of review.file_patches || []) {
      const details = document.createElement("details");
      details.className = "file-patch";
      const summary = document.createElement("summary");
      summary.textContent = `Manual file patch: ${patch.target_file} (${patch.operation})`;
      const code = document.createElement("pre");
      code.className = "config-proposal-code";
      code.textContent = patch.diff;
      details.appendChild(summary);
      details.appendChild(code);
      section.appendChild(details);
    }
  }
  if (review.firmware) {
    const firmware = document.createElement("p");
    firmware.className = "review-firmware";
    const basis = review.firmware;
    firmware.textContent = `Firmware basis: ${basis.flavor || "unknown fork"} ${basis.version || "unknown version"}. ${basis.note || "Identity not verified."}${basis.observed_at ? ` Checked ${basis.observed_at}.` : ""}`;
    section.appendChild(firmware);
  }
  if (Array.isArray(review.checks) && review.checks.length) {
    const details = document.createElement("details");
    details.className = "review-checks";
    details.open = review.checks.some(check => check.severity === "error");
    const summary = document.createElement("summary");
    summary.textContent = `Option and version checks (${review.checks.length})`;
    details.appendChild(summary);
    const list = document.createElement("ul");
    for (const check of review.checks) {
      const item = document.createElement("li");
      const message = document.createElement("p");
      const location = [check.section ? `[${check.section}]` : "", check.option, check.line ? `line ${check.line}` : ""].filter(Boolean).join(" · ");
      message.textContent = `${check.severity === "error" ? "Resolve" : check.severity === "warning" ? "Verify" : "Checked"}${location ? ` — ${location}` : ""}: ${check.message}`;
      item.appendChild(message);
      if (/^https?:\/\//i.test(String(check.source_url || ""))) {
        const link = document.createElement("a");
        link.href = check.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
        link.textContent = "Reference";
        item.appendChild(link);
      }
      list.appendChild(item);
    }
    details.appendChild(list);
    section.appendChild(details);
  }
  if (Array.isArray(review.manual_steps) && review.manual_steps.length) {
    const details = document.createElement("details");
    details.className = "review-manual-steps";
    const summary = document.createElement("summary");
    summary.textContent = "Manual verification checklist";
    details.appendChild(summary);
    const list = document.createElement("ol");
    for (const step of review.manual_steps) {
      const item = document.createElement("li");
      item.textContent = String(step);
      list.appendChild(item);
    }
    details.appendChild(list);
    const link = document.createElement("a");
    link.href = "https://www.klipper3d.org/Config_checks.html";
    link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = "Klipper configuration-check guide (confirm your fork/version)";
    details.appendChild(link);
    section.appendChild(details);
  }
}
