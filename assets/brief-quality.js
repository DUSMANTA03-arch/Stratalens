import { el, button, table, viewDocument } from "./ui.js";
function references(node, item) {
  for (const id of item.claim_ids || [])
    node.append(
      button(
        id,
        () => {
          const target = document.getElementById("claim-" + id);
          if (target) {
            const details = target.closest("details");
            if (details) details.open = true;
            details?.dispatchEvent(new Event("toggle"));
            target.scrollIntoView({ block: "center" });
            target.focus();
          }
        },
        "citation",
      ),
    );
  for (const c of item.citations || [])
    node.append(
      button(
        `p. ${c.page}`,
        () => viewDocument(c.document_id, c.page, c.quote),
        "citation",
      ),
    );
  return node;
}
export function briefQuality(data) {
  const root = el("div", null, "brief-quality");
  if (data.executive_takeaway) {
    const box = el("section", null, "executive-takeaway");
    box.append(
      el("div", "EXECUTIVE TAKEAWAY", "eyebrow"),
      references(
        el("p", data.executive_takeaway.text),
        data.executive_takeaway,
      ),
    );
    root.append(box);
  }
  if (data.positioning?.length) {
    root.append(
      el("h3", "Competitive positioning"),
      el(
        "p",
        "Evidence-backed disclosures, not a ranking. Unavailable information remains “Not established.”",
        "muted",
      ),
      table(
        ["Entity", "Disclosed scale", "Capabilities", "Constraints"],
        data.positioning.map((row) => [
          row.entity,
          ...row.cells.map((cell) => references(el("div", cell.text), cell)),
        ]),
      ),
    );
  }
  for (const chart of data.evidence_charts || []) {
    const box = el("figure", null, "evidence-chart");
    box.append(
      el(
        "figcaption",
        `${chart.metric} · ${chart.period} · ${chart.unit} · ${chart.reporting_basis} · ${chart.value_kind}`,
      ),
    );
    const ns = "http://www.w3.org/2000/svg",
      svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 700 ${chart.points.length * 48 + 20}`);
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      `${chart.metric}. Exact values and citations follow.`,
    );
    const lo = Math.min(0, ...chart.points.map((p) => p.value)),
      hi = Math.max(0, ...chart.points.map((p) => p.value)),
      scale = (v) => 230 + ((v - lo) / (hi - lo || 1)) * 340,
      zero = scale(0);
    const line = document.createElementNS(ns, "line");
    for (const [k, v] of Object.entries({
      x1: zero,
      x2: zero,
      y1: 0,
      y2: chart.points.length * 48,
      stroke: "#9aa99d",
    }))
      line.setAttribute(k, v);
    svg.append(line);
    chart.points.forEach((p, i) => {
      const y = i * 48;
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", 0);
      label.setAttribute("y", y + 23);
      label.setAttribute("font-size", 13);
      label.textContent =
        p.entity.length > 28 ? p.entity.slice(0, 27) + "…" : p.entity;
      svg.append(label);
      const rect = document.createElementNS(ns, "rect");
      for (const [k, v] of Object.entries({
        x: Math.min(zero, scale(p.value)),
        y: y + 6,
        width: Math.abs(scale(p.value) - zero),
        height: 26,
        fill: chart.value_kind === "historical" ? "#1e5b46" : "#938155",
        rx: 3,
      }))
        rect.setAttribute(k, v);
      svg.append(rect);
      const value = document.createElementNS(ns, "text");
      value.setAttribute("x", 590);
      value.setAttribute("y", y + 23);
      value.setAttribute("font-size", 13);
      value.textContent = p.value.toLocaleString("en-IN");
      svg.append(value);
    });
    box.append(
      svg,
      table(
        ["Entity", "Value", "Evidence"],
        chart.points.map((p) => [
          p.entity,
          p.value + " " + chart.unit,
          references(el("div"), p),
        ]),
      ),
    );
    root.append(box);
  }
  if (data.chart_note)
    root.append(
      el(
        "p",
        data.evidence_charts?.length
          ? data.chart_note
          : "No compatible evidence chart available. " + data.chart_note,
        "muted",
      ),
    );
  return root;
}
export function qualityMarkdown(data) {
  let text = "";
  const cite = (x) =>
    (x.claim_ids || []).map((id) => `[${id}]`).join(" ") +
    (x.citations || [])
      .map((c) => `[Document ${c.document_id}, p. ${c.page}]`)
      .join(" ");
  if (data.executive_takeaway)
    text += `## Executive takeaway\n\n${data.executive_takeaway.text} ${cite(data.executive_takeaway)}\n\n`;
  if (data.positioning?.length) {
    text += "## Competitive positioning\n\n";
    for (const row of data.positioning) {
      text += `### ${row.entity}\n\n`;
      for (const cell of row.cells)
        text += `${cell.label}: ${cell.text} ${cite(cell)}\n\n`;
    }
  }
  for (const chart of data.evidence_charts || []) {
    text += `## ${chart.metric} · ${chart.period} · ${chart.reporting_basis} · ${chart.value_kind}\n\n`;
    for (const p of chart.points)
      text += `${p.entity}: ${p.value} ${chart.unit} ${cite(p)}\n\n`;
  }
  if (data.chart_note) text += data.chart_note + "\n\n";
  return text;
}
