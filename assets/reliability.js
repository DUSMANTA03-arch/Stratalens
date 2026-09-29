import { api, post } from "./api.js";
import {
  el,
  button,
  field,
  input,
  select,
  table,
  viewDocument,
  $,
} from "./ui.js";
const patch = (path, data) =>
  api(path, { method: "PATCH", body: JSON.stringify(data) });
export const reviewStatus = (d) =>
  d.review?.version === (d.observation_version || 1)
    ? d.review.status
    : "unreviewed";
function lazy(title, load) {
  const root = el("details", null, "reliability-panel");
  const body = el("div");
  root.append(el("summary", title), body);
  root.addEventListener("toggle", () => {
    if (root.open && !root.dataset.loaded) {
      root.dataset.loaded = "yes";
      load(body).catch((e) => {
        body.textContent = e.message;
        delete root.dataset.loaded;
      });
    }
  });
  return root;
}
export function personalNotes(kind, id, evidenceId = null) {
  const root = lazy("Your notes", async (body) => {
    async function draw() {
      const rows = (await api(`/api/v2/notes?target_id=${id}`)).filter(
        (r) => (r.data.evidence_id || null) === evidenceId,
      );
      body.replaceChildren(
        el(
          "p",
          "Private working notes. Excluded from factual evidence and corroboration counts.",
          "muted",
        ),
      );
      for (const row of rows) {
        const box = el("div", null, "note-card"),
          text = el("textarea");
        text.value = row.data.text;
        text.maxLength = 4000;
        box.append(
          field("Your note", text),
          button("Save note", async () => {
            await patch(`/api/v2/notes/${row.id}`, {
              text: text.value,
              expected_updated_at: row.updated_at,
            });
            await draw();
          }),
          button("Delete note", async () => {
            await api(
              `/api/v2/notes/${row.id}?expected_updated_at=${encodeURIComponent(row.updated_at)}`,
              { method: "DELETE" },
            );
            await draw();
          }),
        );
        body.append(box);
      }
      const text = el("textarea");
      text.maxLength = 4000;
      body.append(
        field("Add your note", text),
        button("Add note", async () => {
          if (!text.value.trim()) throw new Error("Enter a note.");
          await post("/api/v2/notes", {
            target_kind: kind,
            target_id: id,
            evidence_id: evidenceId,
            text: text.value,
          });
          await draw();
        }),
      );
    }
    await draw();
  });
  root.classList.add("personal-notes");
  return root;
}
export function financialReview(companyId, onChange = async () => {}) {
  return lazy("Financial review queue", async (body) => {
    let rows = await api(`/api/v2/observations?company_id=${companyId}`);
    const filter = select("review_filter", [
      ["unreviewed", "Unreviewed"],
      ["all", "All figures"],
      ["reviewed", "Reviewed"],
      ["excluded", "Excluded"],
    ]);
    const list = el("div");
    body.append(field("Review status", filter), list);
    async function inspect(row) {
      const d = row.data;
      await viewDocument(d.document_id, d.page, d.quote);
      const panel = $("#viewer-evidence");
      panel.prepend(
        el("h3", "Review financial observation"),
        table(
          ["Field", "Extracted value"],
          [
            ["Label", d.label],
            ["Value", d.value],
            ["Currency / scale", `${d.currency} / ${d.scale}`],
            [
              "Reporting dates",
              `${d.period_start || "Instant"} → ${d.period_end}`,
            ],
            ["Period type", d.period_type],
            ["Basis", d.basis],
            ["Definition", d.definition],
            ["Original value", d.original_value ?? d.value],
            ["Review status", reviewStatus(d)],
          ],
        ),
      );
      const reason = input("reason", "Explain your decision or correction");
      reason.maxLength = 1000;
      const value = input("corrected_value", "", "number");
      value.step = "any";
      value.value = d.value;
      const status = el("p");
      status.setAttribute("role", "status");
      const save = async (fn) => {
        try {
          row = await fn();
          rows = rows.map((r) => (r.id === row.id ? row : r));
          draw();
          await onChange();
          await inspect(row);
        } catch (e) {
          status.textContent = e.message;
        }
      };
      panel.append(
        field("Reason", reason),
        field("Corrected value", value),
        button("Save correction", () =>
          save(() => {
            if (
              reason.value.trim().length < 10 ||
              !value.value ||
              !Number.isFinite(Number(value.value))
            )
              throw new Error(
                "Enter a valid value and a reason of at least 10 characters.",
              );
            return patch(`/api/v2/observations/${row.id}`, {
              value: Number(value.value),
              reason: reason.value,
              expected_updated_at: row.updated_at,
            });
          }),
        ),
        el(
          "p",
          "A correction requires a new review. The original extraction is retained.",
          "muted",
        ),
      );
      for (const [decision, label] of [
        ["reviewed", "Mark reviewed"],
        ["unreviewed", "Mark unreviewed"],
        ["excluded", "Exclude from comparisons"],
      ])
        panel.append(
          button(label, () =>
            save(() =>
              post(`/api/v2/observations/${row.id}/review`, {
                status: decision,
                reason: reason.value,
                expected_updated_at: row.updated_at,
              }),
            ),
          ),
        );
      const history = el("details");
      history.append(
        el("summary", "Correction and review history"),
        el(
          "pre",
          JSON.stringify(
            {
              original: d.original_extraction || {
                value: d.original_value ?? d.value,
              },
              corrections: d.corrections || [],
              reviews: d.review_history || [],
            },
            null,
            2,
          ),
        ),
      );
      panel.append(status, history, personalNotes("observation", row.id));
    }
    function draw() {
      const visible = rows.filter(
        (r) => filter.value === "all" || reviewStatus(r.data) === filter.value,
      );
      list.replaceChildren(
        visible.length
          ? table(
              ["Figure", "Period / basis", "Value / unit", "Status", "Review"],
              visible.map((r) => [
                r.data.label,
                `${r.data.period_end} · ${r.data.basis}`,
                `${r.data.value} ${r.data.currency} ${r.data.scale}`,
                reviewStatus(r.data),
                button("Inspect source", () => inspect(r)),
              ]),
            )
          : el("p", "No figures match this review filter."),
      );
    }
    filter.addEventListener("change", draw);
    draw();
  });
}
export function coverageTracker(company) {
  return lazy(
    "Report coverage · 3 annual periods / 8 quarters",
    async (body) => {
      async function draw() {
        const data = await api(`/api/v2/companies/${company.id}/coverage`);
        const months = select(
          "year_end",
          Array.from({ length: 12 }, (_, i) => [
            String(i + 1),
            new Date(2020, i, 1).toLocaleString("en", { month: "long" }),
          ]),
          String(data.year_end_month),
        );
        body.replaceChildren(
          el("p", data.note, "muted"),
          field("Financial year-end month", months),
          button("Save year-end", async () => {
            company = await patch(`/api/v2/companies/${company.id}/year-end`, {
              month: Number(months.value),
              expected_updated_at: company.updated_at,
            });
            await draw();
          }),
          table(
            ["Period", "Ends", "Coverage"],
            data.rows.map((r) => [r.period_type, r.period_end, r.status]),
          ),
        );
        if (data.unassigned.length) body.append(el("h3", "Period unassigned"));
        for (const item of data.unassigned) {
          const date = input("period_end", "", "date"),
            type = select("period_type", [
              ["annual", "Annual"],
              ["quarterly", "Quarterly"],
            ]);
          const box = el("div", null, "note-card");
          box.append(
            el("h4", item.title),
            field("Period end", date),
            field("Period type", type),
            button("Assign period", async () => {
              if (!date.value)
                throw new Error("Choose the reporting period end.");
              const docs = await api("/api/v2/documents");
              const doc = docs.find((d) => d.id === item.id);
              await patch(`/api/v2/documents/${item.id}/period`, {
                period_end: date.value,
                period_type: type.value,
                expected_updated_at: doc.updated_at,
              });
              await draw();
            }),
          );
          body.append(box);
        }
      }
      await draw();
    },
  );
}
export function stepHistory(job) {
  const root = el("div", null, "step-history"),
    summaries = job.state.step_summaries || [];
  if (!summaries.length) {
    root.append(
      el(
        "p",
        "Detailed step summaries are available for newly completed steps.",
        "metadata",
      ),
    );
    return root;
  }
  const describe = (s) =>
    [
      `${s.sources} sources`,
      `${s.claims} claims`,
      s.supported != null ? `${s.supported} supported, undisputed` : null,
      `${s.corroborated} corroborated`,
      `${s.disputed} disputed`,
      s.pages_total != null
        ? `${s.pages_indexed}/${s.pages_total} pages indexed`
        : null,
      s.observations ? `${s.observations} financial observations` : null,
      s.candidates ? `${s.candidates} report candidates` : null,
      s.pages_retrieved != null
        ? `${s.pages_retrieved} pages retrieved · ${s.supported_passages} supported passages`
        : null,
    ]
      .filter(Boolean)
      .join(" · ");
  root.append(el("p", describe(summaries.at(-1)), "metadata"));
  const history = el("details");
  history.append(el("summary", `${summaries.length} saved step summaries`));
  for (const s of summaries) {
    history.append(
      el("h4", `${s.step} · ${new Date(s.at).toLocaleString()}`),
      el("p", describe(s)),
    );
    for (const gap of s.gaps || []) history.append(el("p", gap, "muted"));
  }
  root.append(history);
  return root;
}
