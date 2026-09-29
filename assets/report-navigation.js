import { el, button, select, field, viewDocument } from "./ui.js";

function connectionMap(graph) {
  const root = el("div", null, "connection-map");
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const choose = select(
    "connection",
    graph.nodes.map((n) => [n.id, `${n.type}: ${n.label}`]),
  );
  const canvas = el("div");
  root.append(field("Explore a source, claim or finding", choose), canvas);
  function draw() {
    canvas.replaceChildren();
    const links = graph.edges.filter(
      (e) => e.from === choose.value || e.to === choose.value,
    );
    const shown = links.slice(0, 10);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const height = Math.max(160, shown.length * 72);
    svg.setAttribute("viewBox", `0 0 800 ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      `Connections for ${nodes.get(choose.value)?.label}. Arrows follow the relationships listed below.`,
    );
    function shape(tag, attrs, text) {
      const n = document.createElementNS(svg.namespaceURI, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      if (text) n.textContent = text;
      svg.append(n);
      return n;
    }
    const defs = shape("defs", {});
    const marker = document.createElementNS(svg.namespaceURI, "marker");
    for (const [k, v] of Object.entries({
      id: "connection-arrow",
      viewBox: "0 0 10 10",
      refX: 9,
      refY: 5,
      markerWidth: 5,
      markerHeight: 5,
      orient: "auto-start-reverse",
    }))
      marker.setAttribute(k, v);
    const arrow = document.createElementNS(svg.namespaceURI, "path");
    arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    arrow.setAttribute("fill", "#648b78");
    marker.append(arrow);
    defs.append(marker);
    shown.forEach((e, i) => {
      const y = i * 72 + 36,
        outgoing = e.from === choose.value;
      const other = nodes.get(outgoing ? e.to : e.from);
      shape("path", {
        d: outgoing
          ? `M 255 ${height / 2} C 370 ${height / 2}, 380 ${y}, 510 ${y}`
          : `M 510 ${y} C 380 ${y}, 370 ${height / 2}, 255 ${height / 2}`,
        fill: "none",
        stroke: e.relation === "contradicts" ? "#ad4242" : "#648b78",
        "stroke-width": 2,
        "marker-end": "url(#connection-arrow)",
        class: "connection-line",
      });
      shape("rect", {
        x: 515,
        y: y - 24,
        width: 280,
        height: 48,
        rx: 8,
        fill: "#eaf1eb",
      });
      shape(
        "text",
        { x: 530, y: y - 3, "font-size": 12, fill: "#203c32" },
        other?.type || "evidence",
      );
      const label = other?.label || (outgoing ? e.to : e.from);
      const t = shape(
        "text",
        { x: 530, y: y + 14, "font-size": 12, fill: "#203c32" },
        label.length > 34 ? label.slice(0, 34) + "…" : label,
      );
      const title = document.createElementNS(svg.namespaceURI, "title");
      title.textContent = label;
      t.append(title);
      shape(
        "text",
        { x: 385, y: y - 6, "font-size": 11, fill: "#526b5e" },
        e.relation,
      );
    });
    shape("rect", {
      x: 5,
      y: height / 2 - 34,
      width: 250,
      height: 68,
      rx: 10,
      fill: "#205d48",
    });
    shape(
      "text",
      { x: 20, y: height / 2 - 6, "font-size": 12, fill: "white" },
      nodes.get(choose.value)?.type || "Selected evidence",
    );
    const label = nodes.get(choose.value)?.label || choose.value;
    shape(
      "text",
      { x: 20, y: height / 2 + 16, "font-size": 12, fill: "white" },
      label.length > 30 ? label.slice(0, 30) + "…" : label,
    );
    const diagram = el("div", null, "connection-diagram");
    diagram.append(svg);
    canvas.append(
      diagram,
      el(
        "p",
        `${shown.length} of ${links.length} connections shown for the selection. Full relationships are listed below.`,
        "muted",
      ),
    );
    const list = el("ul", null, "connection-list");
    links.forEach((e) =>
      list.append(
        el(
          "li",
          `${nodes.get(e.from)?.label || e.from} → ${e.relation} → ${nodes.get(e.to)?.label || e.to}`,
        ),
      ),
    );
    canvas.append(list);
  }
  choose.addEventListener("change", draw);
  draw();
  return root;
}

export function reportNavigation(article, data) {
  const overview = el("section", null, "brief-panel");
  overview.append(...article.childNodes);
  const panels = [overview, el("section"), el("section"), el("section")];
  const labels = ["Brief", "Sources", "Evidence", "Connections"];
  for (const details of [...overview.querySelectorAll(":scope > details")]) {
    const label = details.querySelector("summary")?.textContent || "";
    const index = /retrieved sources/.test(label)
      ? 1
      : /evidence records|Quoted source appendix/.test(label)
        ? 2
        : /Evidence connections/.test(label)
          ? 3
          : 0;
    if (index) {
      details.open = true;
      panels[index].append(details);
    }
  }
  if (data.passages) {
    panels[1].append(el("h3", "Selected document sources"));
    const refs = new Map();
    for (const p of data.passages)
      for (const c of p.citations) refs.set(`${c.document_id}:${c.page}`, c);
    for (const c of refs.values())
      panels[1].append(
        button(
          `Document ${c.document_id} · page ${c.page}`,
          () => viewDocument(c.document_id, c.page, c.quote),
          "text-button",
        ),
      );
  }
  if (data.graph?.nodes?.length && data.graph?.edges?.length)
    panels[3].prepend(connectionMap(data.graph));
  panels.forEach((panel, i) => {
    panel.id = `brief-panel-${i}`;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `brief-tab-${i}`);
    panel.tabIndex = 0;
    if (!panel.childNodes.length)
      panel.append(
        el(
          "p",
          `No ${labels[i].toLowerCase()} available for this brief.`,
          "muted",
        ),
      );
  });
  const tabs = el("div", null, "brief-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Research brief views");
  function show(index) {
    panels.forEach((panel, i) => {
      panel.hidden = i !== index;
      const b = tabs.children[i];
      b.setAttribute("aria-selected", String(i === index));
      b.tabIndex = i === index ? 0 : -1;
    });
  }
  labels.forEach((label, i) => {
    const b = button(label, () => show(i), "brief-tab");
    b.id = `brief-tab-${i}`;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", panels[i].id);
    b.addEventListener("keydown", (e) => {
      let n;
      if (e.key === "ArrowRight") n = (i + 1) % 4;
      else if (e.key === "ArrowLeft") n = (i + 3) % 4;
      else if (e.key === "Home") n = 0;
      else if (e.key === "End") n = 3;
      else return;
      e.preventDefault();
      show(n);
      tabs.children[n].focus();
    });
    tabs.append(b);
  });
  article.append(tabs, ...panels);
  show(0);
  // Citation buttons expose their target before scrolling and focusing it.
  article.addEventListener(
    "click",
    (e) => {
      if (
        e.target.closest(".citation") &&
        !e.target.textContent.startsWith("p.")
      )
        show(2);
    },
    true,
  );
  const stats = el("div", null, "brief-metrics");
  for (const [value, label] of [
    [
      data.sources?.length ||
        new Set(
          (data.passages || []).flatMap((p) =>
            p.citations.map((c) => c.document_id),
          ),
        ).size,
      "Sources",
    ],
    [
      data.claims?.length ||
        (data.passages || []).flatMap((p) => p.citations).length,
      "Evidence records",
    ],
    [
      data.report?.sections?.length || data.passages?.length || 0,
      "Analysis sections",
    ],
  ]) {
    const card = el("div");
    card.append(el("strong", value), el("span", label));
    stats.append(card);
  }
  overview.insertBefore(stats, overview.children[2] || null);
  const figures = (data.claims || [])
    .filter((c) => Number.isFinite(c.value))
    .slice(0, 4);
  if (figures.length) {
    const grid = el("div", null, "brief-highlights");
    for (const c of figures) {
      const card = el("div");
      card.append(
        el("span", c.entity, "eyebrow"),
        el(
          "strong",
          `${c.precision === "approximate" ? "≈ " : ""}${c.value.toLocaleString("en-IN")} ${c.unit}`,
        ),
        el("p", `${c.metric} · ${c.period}`),
        button(
          "Inspect evidence",
          () => {
            show(2);
            const target = article.querySelector(`#claim-${CSS.escape(c.id)}`);
            if (target) {
              target.closest("details").open = true;
              target.scrollIntoView({ block: "center" });
              target.focus();
            }
          },
          "text-button",
        ),
      );
      grid.append(card);
    }
    stats.after(grid);
  }
}
