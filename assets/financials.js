import { api } from "./api.js";
import {
  el,
  button,
  table,
  field,
  select,
  number,
  viewDocument,
  download,
  empty,
  section,
} from "./ui.js";
export async function financialView(companyIds) {
  const root = el("div"),
    basis = select("basis", [
      ["consolidated", "Consolidated"],
      ["standalone", "Standalone"],
    ]),
    period = select("period", [
      ["annual", "Annual"],
      ["quarterly", "Quarterly"],
      ["instant", "Balance sheet"],
      ["ytd", "Year to date"],
    ]),
    filters = el("div", null, "filters"),
    content = el("div");
  filters.append(
    field("Statement basis", basis),
    field("Reporting period", period),
  );
  const reviewed = document.createElement("input");
  reviewed.type = "checkbox";
  filters.append(field("Reviewed only", reviewed));
  reviewed.addEventListener("change", () =>
    load().catch((e) => {
      content.textContent = e.message;
    }),
  );
  root.append(filters, content);
  let data;
  async function load() {
    data = await api(
      "/api/v2/comparison?" +
        companyIds
          .map((id) => "company_ids=" + encodeURIComponent(id))
          .join("&") +
        "&basis=" +
        basis.value +
        "&reviewed_only=" +
        reviewed.checked,
    );
    draw();
  }
  function draw() {
    content.replaceChildren();
    const rows = data.rows.filter((r) => r.period_type === period.value);
    for (const w of data.warnings) content.append(el("p", w, "muted"));
    if (!rows.length) {
      content.append(
        empty(
          "No compatible figures yet",
          "Process reports in Library. Missing or incompatible figures remain blank.",
        ),
      );
      return;
    }
    content.append(
      el(
        "p",
        "INR crore, except EPS (INR/share). Source mappings require review. Select a figure to inspect its page.",
        "muted",
      ),
    );
    content.append(
      table(
        ["Metric / period", ...data.companies.map((c) => c.data.name)],
        rows.map((r) => [
          `${r.metric.replaceAll("_", " ")} · ${r.period_end}`,
          ...data.companies.map((c) => {
            const v = r.values[c.id];
            return v
              ? button(
                  `${number(v.value)}${v.restated ? " ↺" : ""} · ${v.review_status || "unreviewed"}`,
                  () => viewDocument(v.document_id, v.page),
                  "text-button",
                )
              : "—";
          }),
        ]),
      ),
    );
    content.append(
      button(
        "Download financial CSV",
        () => {
          const safe = (x) => {
            const text =
              typeof x === "number"
                ? String(x)
                : String(x ?? "").replace(/^[=+@\-]/, "'$&");
            return '"' + text.replaceAll('"', '""') + '"';
          };
          const matrix = [
            [
              "Metric",
              "Start",
              "End",
              "Type",
              "Basis",
              "Unit",
              ...data.companies.map((c) => c.data.name),
            ],
            ...rows.map((r) => [
              r.metric,
              r.period_start,
              r.period_end,
              r.period_type,
              r.basis,
              r.unit,
              ...data.companies.map((c) => r.values[c.id]?.value ?? ""),
            ]),
          ];
          download(
            matrix.map((row) => row.map(safe).join(",")).join("\r\n"),
            "stratalens-financials.csv",
            "text/csv;charset=utf-8",
          );
        },
        "text-button",
      ),
    );
    const derived = data.derived.filter((d) =>
      rows.some((r) => r.period_end === d.period_end),
    );
    if (derived.length)
      content.append(
        section("Calculated from reported figures"),
        table(
          ["Company", "Metric", "Period", "Result", "Formula"],
          derived.map((d) => [
            data.companies.find((c) => c.id === d.company_id)?.data.name,
            d.label,
            d.period_end,
            number(d.value) + "%",
            (() => {
              const refs = el("div", d.formula);
              for (const c of d.citations || [])
                refs.append(
                  button(
                    `p. ${c.page}`,
                    () => viewDocument(c.document_id, c.page, c.quote),
                    "citation",
                  ),
                );
              return refs;
            })(),
          ]),
        ),
      );
    const revenue = rows
      .filter((r) => r.metric === "revenue")
      .sort((a, b) => a.period_end.localeCompare(b.period_end));
    if (revenue.length > 1)
      for (const company of data.companies) {
        const values = revenue.map((r) => ({
          date: r.period_end,
          value: r.values[company.id]?.value,
        }));
        if (values.filter((v) => v.value != null).length < 2) continue;
        const chart = el("div", null, "chart");
        chart.append(el("h3", `${company.data.name} · Revenue trend`));
        const ns = "http://www.w3.org/2000/svg",
          svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 600 190");
        svg.setAttribute("role", "img");
        svg.setAttribute(
          "aria-label",
          "Revenue in INR crore; exact values are in the table.",
        );
        const min = Math.min(
            0,
            ...values.filter((v) => v.value != null).map((v) => v.value),
          ),
          max = Math.max(
            1,
            ...values.filter((v) => v.value != null).map((v) => v.value),
          );
        let previous = null;
        values.forEach((v, i) => {
          if (v.value == null) {
            previous = null;
            return;
          }
          const x = 35 + (i * 530) / (values.length - 1),
            y = 155 - ((v.value - min) / (max - min)) * 125;
          if (previous) {
            const line = document.createElementNS(ns, "line");
            for (const [k, val] of Object.entries({
              x1: previous.x,
              y1: previous.y,
              x2: x,
              y2: y,
              stroke: "#47794e",
              "stroke-width": 2,
            }))
              line.setAttribute(k, val);
            svg.append(line);
          }
          const circle = document.createElementNS(ns, "circle");
          for (const [k, val] of Object.entries({
            cx: x,
            cy: y,
            r: 4,
            fill: "#47794e",
          }))
            circle.setAttribute(k, val);
          svg.append(circle);
          const t = document.createElementNS(ns, "text");
          t.setAttribute("x", x);
          t.setAttribute("y", y - 10);
          t.setAttribute("text-anchor", "middle");
          t.setAttribute("font-size", "11");
          t.textContent = number(v.value);
          svg.append(t);
          previous = { x, y };
        });
        chart.append(svg);
        const labels = el("div", null, "chart-labels");
        values.forEach((v) => labels.append(el("span", v.date)));
        chart.append(labels);
        content.append(chart);
      }
  }
  basis.addEventListener("change", () =>
    load().catch((e) => {
      content.textContent = e.message;
    }),
  );
  period.addEventListener("change", draw);
  root.refresh = load;
  await load();
  return root;
}
