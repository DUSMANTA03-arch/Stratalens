import { briefQuality, qualityMarkdown } from "./brief-quality.js";
import { personalNotes } from "./reliability.js";
import { reportNavigation } from "./report-navigation.js";
import { api } from "./api.js";
import {
  el,
  button,
  table,
  badge,
  safeLink,
  viewDocument,
  download,
  section,
} from "./ui.js";
export function documentPassages(result, skipTakeaway = false) {
  const root = el("div");
  for (const p of result.passages || []) {
    if (skipTakeaway && p.text === result.executive_takeaway?.text) continue;
    root.append(el("h3", p.heading));
    const t = el("p", p.text);
    for (const c of p.citations)
      t.append(
        button(
          `p. ${c.page}`,
          () => viewDocument(c.document_id, c.page, c.quote),
          "citation",
        ),
      );
    root.append(t);
  }
  if (!result.passages?.length)
    root.append(
      el("p", "No supported answer was found in the selected evidence."),
    );
  const notes = el("details");
  notes.append(el("summary", "Coverage and limitations"));
  for (const n of result.limitations || []) notes.append(el("p", n, "muted"));
  root.append(notes);
  return root;
}
function markdown(data) {
  let text =
    "# " +
    (data.title || data.report?.title || "Research brief") +
    "\n\n" +
    (data.question || "") +
    "\n\n";
  if (data.mode === "sample")
    text += "**SYNTHETIC DEMONSTRATION — NOT REAL MARKET DATA**\n\n";
  text += qualityMarkdown(data);
  for (const p of data.passages || []) {
    if (p.text !== data.executive_takeaway?.text)
      text += `## ${p.heading}\n\n${p.text}\n\n`;
    for (const c of p.citations)
      text += `> ${c.quote}\n\nDocument ${c.document_id}, page ${c.page}\n\n`;
  }
  for (const original of data.report?.sections || []) {
    const s = {
      ...original,
      findings: original.findings.filter(
        (f) => f.text !== data.executive_takeaway?.text,
      ),
    };
    if (!s.findings.length) continue;
    text += `## ${s.heading}\n\n`;
    for (const f of s.findings)
      text += f.text + " [" + f.claim_ids.join(", ") + "]\n\n";
  }
  for (const c of data.calculations || [])
    text += `${c.label}: ${c.value} ${c.unit}. ${c.formula}. Inputs: ${c.claim_ids.join(", ")}\n\n`;
  if (data.claims?.length) {
    text += "## Evidence\n\n";
    for (const c of data.claims) {
      const s = data.sources.find((s) => s.id === c.source_id);
      text += `[${c.id}] ${c.statement}\n\n> ${c.quote}\n\n${s?.title || ""} ${s?.url || ""}\n\n`;
    }
  }
  text +=
    "## Limitations\n\n" +
    [
      ...(data.limitations || data.report?.limitations || []),
      ...(data.warnings || []),
    ]
      .map((n) => "- " + n)
      .join("\n");
  return text;
}
export function renderBrief(root, data, id = null) {
  root.replaceChildren();
  root.classList.remove("hidden");
  const toolbar = el("div", null, "report-toolbar"),
    exports = el("div", null, "export-actions");
  toolbar.append(el("div", "EVIDENCE / RESEARCH BRIEF", "eyebrow"), exports);
  const article = el("article", null, "card report");
  const imageTasks = [];
  const imageCache = new Map();
  exports.append(
    button("Markdown", () =>
      download(markdown(data), "stratalens.md", "text/markdown"),
    ),
    button("JSON", async () => {
      await Promise.all(imageTasks);
      download(
        JSON.stringify(data, null, 2),
        "stratalens.json",
        "application/json",
      );
    }),
    button("HTML", async () => {
      await Promise.all(imageTasks);
      const clean = article.cloneNode(true);
      clean.querySelector(".brief-tabs")?.remove();
      clean.querySelectorAll(".personal-notes").forEach((n) => n.remove());
      clean
        .querySelectorAll("[hidden]")
        .forEach((n) => n.removeAttribute("hidden"));
      clean
        .querySelectorAll("button")
        .forEach((b) =>
          b.replaceWith(document.createTextNode(" [" + b.textContent + "] ")),
        );
      clean.querySelectorAll("details").forEach((d) => (d.open = true));
      download(
        '<!doctype html><html><meta charset="utf-8"><title>StrataLens brief</title><style>body{max-width:900px;margin:40px auto;padding:24px;font:15px/1.7 system-ui;color:#203c32}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ddd}blockquote{border-left:3px solid #678;padding:14px}img{max-width:100%}</style><body>' +
          clean.outerHTML +
          "</body></html>",
        "stratalens.html",
        "text/html",
      );
    }),
  );
  if (id || data.mode === "sample")
    exports.append(
      button("PDF", async () =>
        download(
          await api(
            id ? `/api/v2/briefs/${id}/export.pdf` : "/api/sample/export.pdf",
          ),
          "stratalens.pdf",
          "application/pdf",
        ),
      ),
    );
  if (data.mode === "sample")
    article.append(
      el(
        "div",
        "FICTIONAL SAMPLE · Synthetic companies and figures",
        "sample-label",
      ),
    );
  article.append(
    el("h2", data.title || data.report?.title || "Research brief"),
    el("p", data.question, "muted"),
  );
  article.append(briefQuality(data));
  if (id) article.append(personalNotes("brief", id));
  if (data.passages) {
    article.append(documentPassages(data, true));
    const refs = el("details");
    refs.append(el("summary", "Quoted source appendix"));
    for (const p of data.passages)
      for (const c of p.citations)
        refs.append(
          el("blockquote", c.quote),
          el("p", `Document ${c.document_id} · page ${c.page}`, "metadata"),
        );
    article.append(refs);
  } else {
    const claims = new Map((data.claims || []).map((c) => [c.id, c])),
      evidence = el("details");
    evidence.append(el("summary", `Inspect ${claims.size} evidence records`));
    for (const original of data.report?.sections || []) {
      const s = {
        ...original,
        findings: original.findings.filter(
          (f) => f.text !== data.executive_takeaway?.text,
        ),
      };
      if (!s.findings.length) continue;
      article.append(el("h3", s.heading));
      for (const f of s.findings) {
        const p = el("p", f.text);
        for (const cid of f.claim_ids)
          p.append(
            button(
              String((data.claims || []).findIndex((c) => c.id === cid) + 1),
              () => {
                const target = document.getElementById("claim-" + cid);
                if (target) {
                  evidence.open = true;
                  target.scrollIntoView({ block: "center" });
                  target.focus();
                }
              },
              "citation",
            ),
          );
        article.append(p);
      }
    }
    const nums = (data.claims || []).filter((c) => Number.isFinite(c.value));
    if (nums.length)
      article.append(
        section("Reported figures"),
        table(
          ["Entity", "Metric", "Period", "Value", "Status"],
          nums.map((c) => [
            c.entity,
            c.metric,
            c.period,
            `${c.precision === "approximate" ? "≈ " : ""}${c.value.toLocaleString("en-IN")} ${c.unit}`,
            badge(
              data.assessments?.find((a) => a.claim_id === c.id)?.status ||
                "single-source",
            ),
          ]),
        ),
      );
    for (const c of data.calculations || [])
      article.append(
        el("h3", c.label),
        el("p", `${c.value} ${c.unit} · ${c.formula}`),
      );
    for (const c of claims.values()) {
      const card = el("div", null, "evidence-card");
      card.id = "claim-" + c.id;
      card.tabIndex = -1;
      card.append(el("h3", c.statement), el("blockquote", c.quote));
      const s = data.sources?.find((s) => s.id === c.source_id);
      card.append(
        el(
          "p",
          `Origin: ${s?.source_tier === "company" ? "Company disclosure" : "External source · " + (s?.source_tier || "unclassified")} · Verification: ${data.assessments?.find((a) => a.claim_id === c.id)?.status || "single-source"}`,
          "metadata",
        ),
      );
      if (id) card.append(personalNotes("brief", id, c.id));
      if (s)
        card.append(
          safeLink(s.url, s.title + (c.page ? ` · page ${c.page}` : "")),
        );
      if (s?.kind === "image" && id) {
        const image = el("img", null, "source-image");
        image.alt = s.title;
        card.append(image);
        if (!imageCache.has(s.id))
          imageCache.set(
            s.id,
            (async () => {
              if (!s.image_data) {
                const signed = await api(`/api/v2/briefs/${id}/images/${s.id}`);
                const response = await fetch(signed.url);
                if (!response.ok)
                  throw new Error("Could not load original chart evidence.");
                const blob = await response.blob();
                const url = await new Promise((resolve, reject) => {
                  const reader = new FileReader();
                  reader.onload = () => resolve(reader.result);
                  reader.onerror = reject;
                  reader.readAsDataURL(blob);
                });
                s.image_data = url.split(",")[1];
                s.image_media_type = blob.type;
              }
            })(),
          );
        const task = imageCache.get(s.id).then(() => {
          image.src = `data:${s.image_media_type};base64,${s.image_data}`;
        });
        task.catch(() =>
          card.append(
            el(
              "p",
              "Original chart unavailable. Reopen the brief after checking storage.",
              "muted",
            ),
          ),
        );
        imageTasks.push(task);
      }
      card.append(
        el(
          "p",
          data.assessments?.find((a) => a.claim_id === c.id)?.reason ||
            "Source claim; not independently established.",
          "muted",
        ),
      );
      evidence.append(card);
    }
    article.append(evidence, section("Limitations"));
    for (const n of [
      ...(data.report?.limitations || []),
      ...(data.warnings || []),
    ])
      article.append(el("p", n, "muted"));
    if (data.sources?.length) {
      const sources = el("details");
      sources.append(
        el("summary", `All ${data.sources.length} retrieved sources`),
      );
      for (const s of data.sources) {
        const d = el("div", null, "evidence-card");
        d.append(
          safeLink(s.url, s.title),
          el(
            "p",
            `${s.source_tier || s.kind} · ${data.source_coverage?.find((c) => c.source_id === s.id)?.status || "retrieved"}`,
            "muted",
          ),
        );
        sources.append(d);
      }
      article.append(sources);
    }
    if (data.graph?.edges?.length) {
      const connections = el("details");
      connections.append(el("summary", "Evidence connections"));
      const nodes = new Map(data.graph.nodes.map((n) => [n.id, n]));
      connections.append(
        table(
          ["From", "Relationship", "To"],
          data.graph.edges.map((e) => [
            nodes.get(e.from)?.label || e.from,
            e.relation,
            nodes.get(e.to)?.label || e.to,
          ]),
        ),
      );
      article.append(connections);
    }
  }
  reportNavigation(article, data);
  root.append(toolbar, article);
  return article;
}
