import {
  financialReview,
  coverageTracker,
  stepHistory,
} from "./reliability.js";
import { api, post, notice, action } from "./api.js";
import {
  $,
  el,
  button,
  field,
  input,
  select,
  badge,
  heading,
  empty,
  table,
  safeLink,
  formSubmit,
  submit,
  checks,
  viewDocument,
  section,
  number,
} from "./ui.js";
import { renderBrief, documentPassages } from "./reports.js";
import { financialView } from "./financials.js";

let signedIn = false,
  currentPage = "research",
  companies = [],
  documents = [],
  briefs = [],
  jobs = [],
  conversations = [],
  discoveries = [];
let running = null,
  continueSteps = false,
  selectedCompany = null,
  conversationId = null;
const companyName = (id) =>
  companies.find((c) => c.id === id)?.data.name || "Company";
const companyOptions = () => companies.map((c) => [c.id, c.data.name]);
const indexedDocuments = () =>
  documents.filter((d) => ["ready", "extracting"].includes(d.data.status));
const documentChoices = (docs) =>
  docs.map((d) => ({
    id: d.id,
    label: `${companyName(d.data.company_id)} · ${d.data.title} · ${d.data.fiscal_period}`,
  }));

async function refreshData() {
  [companies, documents, briefs, jobs, conversations, discoveries] =
    await Promise.all(
      [
        "/companies",
        "/documents",
        "/briefs",
        "/jobs",
        "/conversations",
        "/discoveries",
      ].map((p) => api("/api/v2" + p)),
    );
  renderJobs();
}
async function enter() {
  signedIn = true;
  $("#auth-panel").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  $("#logout").classList.remove("hidden");
  $("#session-label").textContent = "Owner account · Signed in";
  await refreshData();
  await navigate(currentPage);
}
async function navigate(page) {
  currentPage = page;
  $("#breadcrumb").textContent =
    "Workspace / " + page[0].toUpperCase() + page.slice(1);
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === page);
    b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false");
  });
  if (!signedIn) {
    notice(
      "Sign in to open your private workspace. You can explore the fictional brief below.",
    );
    return;
  }
  $("#output").classList.add("hidden");
  const root = $("#page-content");
  root.dataset.viewVersion = String(Number(root.dataset.viewVersion || 0) + 1);
  root.replaceChildren();
  await {
    research: researchPage,
    companies: companiesPage,
    library: libraryPage,
    settings: settingsPage,
    activity: async (root) =>
      root.append(
        heading(
          "Recent activity",
          "Resume saved work, inspect progress, or reopen results.",
          "04 / ACTIVITY",
        ),
      ),
  }[page](root);
  renderJobs();
}

function jobSteps(job) {
  if (job.kind === "ingest")
    return [
      ["inspect", "Inspect PDF"],
      ["index", "Index every page"],
      ["financials", "Extract financial evidence"],
    ];
  if (job.kind === "discover") return [["discover", "Search official reports"]];
  if (job.kind === "chat" || job.state.mode === "company")
    return [["answer", "Retrieve evidence & write cited answer"]];
  return [
    ["planner", "Plan research"],
    ["researcher", "Find sources"],
    ["chart_reader", "Read charts"],
    ["analyst", "Analyze evidence"],
    ["validator", "Check claims"],
    ["writer", "Write brief"],
  ];
}
function stepProgress(job) {
  const steps = jobSteps(job),
    phase = job.state.phase;
  const index = Math.max(
    0,
    steps.findIndex(([key]) => key === phase),
  );
  const active = running === job.id || job.status === "running";
  const list = el("ol", null, "job-steps");
  list.setAttribute("aria-label", "Processing steps");
  steps.forEach(([, label], i) => {
    const complete = job.status === "completed" || i < index;
    const current = !complete && i === index;
    const item = el(
      "li",
      null,
      complete ? "step-complete" : current ? "step-current" : "step-pending",
    );
    if (current) item.setAttribute("aria-current", "step");
    if (current && active) item.classList.add("step-animated");
    item.append(
      el("span", complete ? "✓" : i + 1, "step-marker"),
      el("span", label),
    );
    list.append(item);
  });
  return list;
}
function renderJobs() {
  const root = $("#jobs-panel");
  root.replaceChildren();
  const active = Boolean(running) || jobs.some((j) => j.status === "running");
  root.classList.toggle("is-active", active);
  const workspace = $("#workspace");
  if (active) workspace.prepend(root);
  else workspace.append(root);
  root.classList.toggle("hidden", !active && currentPage !== "activity");
  if (!jobs.length) {
    root.append(
      empty(
        "No recent activity",
        "Start research or add a report to see saved progress here.",
      ),
    );
    return;
  }
  const top = section("Processing & recent activity");
  top.append(
    button(
      "Refresh",
      async () => {
        jobs = await api("/api/v2/jobs");
        renderJobs();
      },
      "text-button",
    ),
  );
  root.append(
    top,
    el(
      "p",
      "Each step saves its progress. Keep this tab open to advance; return and select Resume after leaving. Quota failures pause without automatic retries.",
      "muted",
    ),
  );
  for (const job of [...jobs]
    .sort(
      (a, b) =>
        Number(b.id === running || b.status === "running") -
        Number(a.id === running || a.status === "running"),
    )
    .slice(0, 12)) {
    const row = el("div", null, "job"),
      info = el("div"),
      actions = el("div", null, "job-actions");
    const doc = documents.find((d) => d.id === job.state.document_id);
    info.append(
      el(
        "div",
        job.state.question ||
          doc?.data.title ||
          `${job.kind} · ${companyName(job.state.company_id)}`,
        "job-title",
      ),
    );
    const status = el("div", null, "metadata");
    status.append(
      badge(job.status),
      document.createTextNode(
        `  ${job.state.phase || job.kind}${job.state.next_page ? " · page " + job.state.next_page : ""} · ${job.model_calls || 0} AI / ${job.search_calls || 0} searches`,
      ),
    );
    info.append(status, stepHistory(job));
    if (["queued", "running", "paused"].includes(job.status))
      info.append(stepProgress(job));
    if (job.error) info.append(el("p", job.error, "muted"));
    if (["queued", "paused", "running"].includes(job.status)) {
      if (running === job.id)
        actions.append(
          button(
            continueSteps ? "Pause after step" : "Pausing…",
            () => {
              continueSteps = false;
              renderJobs();
            },
            "text-button",
          ),
        );
      else actions.append(button("Resume", () => runJob(job), "text-button"));
      actions.append(
        button(
          "Cancel",
          async () => {
            if (running === job.id) continueSteps = false;
            await post(`/api/v2/jobs/${job.id}/cancel`);
            await refreshData();
          },
          "text-button danger",
        ),
      );
    }
    if (["completed", "paused"].includes(job.status) && job.result)
      actions.append(button("Open", () => openResult(job), "text-button"));
    row.append(info, actions);
    root.append(row);
  }
}
async function runJob(job) {
  if (running) {
    notice("One job is already processing. Pause it before starting another.");
    return;
  }
  running = job.id;
  continueSteps = true;
  renderJobs();
  $("#jobs-panel").scrollIntoView({ block: "start", behavior: "smooth" });
  try {
    while (continueSteps) {
      job = await post(`/api/v2/jobs/${job.id}/advance`);
      jobs = jobs.map((j) => (j.id === job.id ? job : j));
      renderJobs();
      if (job.status !== "queued") {
        if (job.status === "completed") await openResult(job);
        break;
      }
    }
  } finally {
    running = null;
    continueSteps = false;
    await refreshData();
    renderJobs();
    if (currentPage === "library") await libraryPage($("#page-content"));
  }
}
async function startJob(job) {
  jobs.unshift(job);
  renderJobs();
  await runJob(job);
}
async function openResult(job) {
  if (job.kind === "research") {
    renderBrief($("#output"), job.result, job.id);
    $("#output").scrollIntoView({ block: "start" });
  } else if (job.kind === "chat") {
    conversationId = job.state.conversation_id || job.id;
    await refreshData();
    await navigate("library");
  } else if (job.kind === "discover") {
    await refreshData();
    await navigate("library");
  } else if (job.result.document_id) {
    await refreshData();
    notice(
      job.result.duplicate
        ? "This file is already in your library; the duplicate upload was removed."
        : "Report processing finished. Open it from Library.",
    );
  }
}

async function researchPage(root) {
  const viewVersion = root.dataset.viewVersion;
  const templates = await api("/api/v2/templates");
  if (root.dataset.viewVersion !== viewVersion) return;
  root.replaceChildren(
    heading(
      "A clearer point of view.",
      "Research a market, understand a company, or compare the evidence side by side.",
      "01 / RESEARCH",
    ),
  );
  const stats = el("div", null, "stat-grid");
  for (const [n, label] of [
    [companies.length, "Companies followed"],
    [
      documents.filter((d) => d.data.status === "ready").length,
      "Reports ready",
    ],
    [briefs.length, "Saved briefs"],
  ]) {
    const s =
      label === "Saved briefs"
        ? button(
            "",
            () => {
              const saved = $("#saved-research");
              saved.scrollIntoView({ block: "start", behavior: "smooth" });
              saved.focus({ preventScroll: true });
            },
            "stat stat-link",
          )
        : button(
            "",
            async () => {
              if (label === "Companies followed") await navigate("companies");
              else {
                await navigate("library");
                const filter = $("select[name=status]");
                filter.value = "ready";
                filter.dispatchEvent(new Event("change"));
                filter.closest(".filters").scrollIntoView({ block: "start" });
              }
            },
            "stat stat-link",
          );
    s.append(el("strong", n), el("span", label));
    stats.append(s);
  }
  root.append(stats);
  const card = el("div", null, "card"),
    tabs = el("div", null, "segmented"),
    body = el("div");
  card.append(tabs, body);
  root.append(card);
  function modeView(mode) {
    body.replaceChildren();
    tabs.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === mode);
      b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
    });
    const form = el("form");
    body.append(form);
    if (mode === "compare") {
      form.append(
        field(
          "Select up to three companies",
          checks(
            companies.map((c) => ({ id: c.id, label: c.data.name })),
            "companies",
          ),
        ),
        submit("Compare financials ↗"),
      );
      formSubmit(form, async (fd) => {
        const ids = fd.getAll("companies");
        if (ids.length < 1 || ids.length > 3)
          throw new Error("Select one to three companies.");
        const output = $("#output");
        output.replaceChildren(await financialView(ids));
        output.classList.remove("hidden");
        output.scrollIntoView({ block: "start" });
      });
      return;
    }
    const question = el("textarea");
    question.name = "question";
    question.required = true;
    question.minLength = 10;
    question.maxLength = 2000;
    question.placeholder =
      mode === "company"
        ? "What changed in profitability, management outlook, and disclosed risks?"
        : "Analyze India’s EV market: demand, competition, and policy.";
    const template = select("template_id", [
      ["", "Custom question"],
      ...Object.entries(templates)
        .filter(([, t]) => t.mode === mode)
        .map(([id, t]) => [id, t.label]),
    ]);
    template.addEventListener("change", () => {
      if (template.value) question.value = templates[template.value].question;
    });
    form.append(
      field("Research template", template),
      field("What would you like to understand?", question),
    );
    if (mode === "market") {
      const charts = input("charts", "", "file");
      charts.multiple = true;
      charts.accept = "image/png,image/jpeg,image/webp";
      form.append(field("Chart images (optional, up to three)", charts));
    }
    if (mode === "company") {
      const company = select(
          "company",
          companyOptions(),
          selectedCompany || undefined,
        ),
        docs = el("div");
      const draw = () =>
        docs.replaceChildren(
          field(
            "Select reports to use as evidence",
            checks(
              documentChoices(
                indexedDocuments().filter(
                  (d) => d.data.company_id === company.value,
                ),
              ),
              "documents",
            ),
          ),
        );
      company.addEventListener("change", draw);
      draw();
      form.append(field("Company", company), docs);
    }
    form.append(
      el(
        "p",
        mode === "market"
          ? "Searches public sources and preserves quotation-level evidence."
          : "Answers from selected reports only. Company analysis includes business overview, financial performance, management commentary, and disclosed risks.",
        "muted",
      ),
      submit("Start research ↗"),
    );
    formSubmit(form, async (fd) => {
      const data = {
        template_id: fd.get("template_id") || null,
        question: fd.get("question"),
        mode,
        company_ids: mode === "company" ? [fd.get("company")] : [],
        document_ids: fd.getAll("documents"),
        charts: await prepareCharts(fd.getAll("charts").filter((f) => f.size)),
      };
      await startJob(await post("/api/v2/research", data));
    });
  }
  for (const [mode, label] of [
    ["market", "Market research"],
    ["company", "Company analysis"],
    ["compare", "Peer comparison"],
  ]) {
    const b = button(label, () => modeView(mode), "");
    b.dataset.mode = mode;
    tabs.append(b);
  }
  modeView("market");
  const saved = section("Your saved research");
  saved.id = "saved-research";
  saved.tabIndex = -1;
  root.append(saved);
  if (!briefs.length)
    root.append(
      empty(
        "Your research starts here",
        "Completed briefs will stay in this workspace, ready to revisit or export.",
      ),
    );
  else
    root.append(
      table(
        ["Brief", "Created", ""],
        briefs.map((b) => [
          b.data.title || b.data.report?.title || b.data.question,
          new Date(b.created_at).toLocaleDateString(),
          button(
            "Read brief →",
            () => {
              renderBrief($("#output"), b.data, b.id);
              $("#output").scrollIntoView({ block: "start" });
            },
            "text-button",
          ),
        ]),
      ),
    );
  root.append(
    button(
      "Open fictional sample",
      async () => renderBrief($("#output"), await api("/api/sample")),
      "text-button",
    ),
  );
}

async function companiesPage(root) {
  root.replaceChildren(
    heading(
      "Know the company behind the numbers.",
      "A home for reports, financial trends, and your developing point of view.",
      "02 / COMPANIES",
    ),
  );
  const searchCard = el("div", null, "card"),
    searchForm = el("form"),
    query = input("q", "Search an NSE-listed company");
  query.required = true;
  query.minLength = 2;
  const results = el("div");
  searchForm.append(field("Find a company", query), submit("Search listings"));
  searchCard.append(searchForm, results);
  root.append(searchCard);
  const manual = el("details"),
    addForm = el("form"),
    name = input("name", "Company name"),
    symbol = input("symbol", "Exchange symbol"),
    isin = input("isin", "ISIN (optional)"),
    website = input("website", "https://company.com", "url"),
    sector = select("sector", [
      ["non_financial", "Non-financial company"],
      ["bank", "Bank"],
      ["insurance", "Insurance"],
    ]);
  name.required = true;
  symbol.required = true;
  const grid = el("div", null, "form-grid");
  grid.append(
    field("Company name", name),
    field("Exchange symbol", symbol),
    field("ISIN", isin),
    field("Official company website (confirm before saving)", website),
    field("Sector", sector),
  );
  addForm.append(
    grid,
    el(
      "p",
      "Confirm identifiers and the investor-relations website against an official filing. No company is selected automatically.",
      "muted",
    ),
    submit("Add company"),
  );
  manual.append(el("summary", "Add or confirm company details"), addForm);
  searchCard.append(manual);
  formSubmit(searchForm, async (fd) => {
    const data = await api(
      "/api/v2/companies/search?q=" + encodeURIComponent(fd.get("q")),
    );
    results.replaceChildren(el("p", data.note, "muted"));
    for (const c of data.candidates) {
      const row = el("div", null, "job");
      row.append(
        el("span", `${c.name} · ${c.symbol} · ${c.isin}`),
        button(
          "Select",
          () => {
            name.value = c.name;
            symbol.value = c.symbol;
            isin.value = c.isin;
            manual.open = true;
            name.focus();
          },
          "text-button",
        ),
      );
      results.append(row);
    }
    if (!data.candidates.length)
      results.append(
        el("p", "No listing found. Add identifiers manually below.", "muted"),
      );
  });
  formSubmit(addForm, async (fd) => {
    const c = await post("/api/v2/companies", {
      name: fd.get("name"),
      symbol: fd.get("symbol"),
      isin: fd.get("isin"),
      website: fd.get("website") || null,
      sector: fd.get("sector"),
    });
    selectedCompany = c.id;
    await refreshData();
    await companiesPage(root);
  });
  if (!companies.length) {
    root.append(
      section("Your companies"),
      empty(
        "Build your research universe",
        "Search and confirm a company to start collecting reports.",
      ),
    );
    return;
  }
  const selector = select(
    "company",
    companyOptions(),
    selectedCompany || companies[0].id,
  );
  selectedCompany = selector.value;
  selector.addEventListener(
    "change",
    action(async () => {
      selectedCompany = selector.value;
      await companiesPage(root);
    }),
  );
  root.append(
    section("Company dashboard"),
    field("Selected company", selector),
  );
  const c = companies.find((c) => c.id === selectedCompany),
    card = el("div", null, "card"),
    top = el("div", null, "row spread");
  top.append(el("h2", c.data.name), badge(c.data.symbol));
  card.append(
    top,
    el(
      "p",
      `${c.data.isin || "ISIN not provided"} · ${c.data.sector.replaceAll("_", " ")}`,
      "muted",
    ),
  );
  if (c.data.website)
    card.append(safeLink(c.data.website, "Company website ↗"));
  const actions = el("div", null, "row");
  actions.append(
    button("Find official reports", async () =>
      startJob(await post(`/api/v2/companies/${c.id}/discover`)),
    ),
    button("Open library", () => navigate("library")),
    button("Analyze company", async () => {
      await navigate("research");
      $("#page-content [data-mode=company]").click();
    }),
  );
  card.append(actions);
  root.append(card);
  const financials = el("div");
  const refreshFinancials = async () => {
    if (financials.firstElementChild?.refresh)
      await financials.firstElementChild.refresh();
    else financials.append(await financialView([c.id]));
  };
  root.append(
    coverageTracker(c),
    financialReview(c.id, refreshFinancials),
    financials,
  );
  await refreshFinancials();
  // A company change or navigation may replace this dashboard during the request.
  if (!root.contains(card)) return;
  const available = documents.filter((d) => d.data.company_id === c.id);
  root.append(
    section("Reports in your library"),
    table(
      ["Report", "Period", "Status"],
      available.map((d) => [
        button(d.data.title, () => viewDocument(d.id), "text-button"),
        d.data.fiscal_period,
        badge(d.data.status),
      ]),
    ),
  );
  const related = briefs.filter((b) => b.data.company_ids?.includes(c.id));
  if (related.length) {
    root.append(section("Business, commentary & risks"));
    const summary = el("div", null, "card");
    summary.append(documentPassages(related[0].data));
    root.append(summary);
    for (const b of related)
      root.append(
        button(
          b.data.title,
          () => {
            renderBrief($("#output"), b.data, b.id);
            $("#output").scrollIntoView({ block: "start" });
          },
          "text-button",
        ),
      );
  }
}

async function libraryPage(root) {
  root.replaceChildren(
    heading(
      "Your source of understanding.",
      "Collect annual reports and results. Every page stays connected to its evidence.",
      "03 / LIBRARY",
    ),
  );
  if (!companies.length) {
    root.append(
      empty(
        "Add a company first",
        "Visit Companies to choose the company behind your reports.",
      ),
      button("Add a company →", () => navigate("companies")),
    );
    return;
  }
  const add = el("details"),
    form = el("form", null, "card"),
    company = select(
      "company_id",
      companyOptions(),
      selectedCompany || undefined,
    ),
    title = input("title", "e.g. Annual report FY2025"),
    type = select("document_type", [
      ["annual_report", "Annual report"],
      ["financial_results", "Financial results"],
    ]),
    period = input("fiscal_period", "e.g. FY2024–25 or Q1 FY2026"),
    date = input("published_at", "", "date"),
    url = input("url", "https://…/report.pdf", "url"),
    file = input("file", "", "file");
  file.accept = "application/pdf";
  title.required = true;
  period.maxLength = 40;
  const grid = el("div", null, "form-grid");
  grid.append(
    field("Company", company),
    field("Document title", title),
    field("Document type", type),
    field("Fiscal period (optional)", period),
    field("Publication date (optional)", date),
    field("Direct PDF link (or upload below)", url),
  );
  form.append(
    grid,
    field(
      "Upload a PDF (optional with a link) · up to 40 MB / 600 pages",
      file,
    ),
    el(
      "p",
      "Confirm the company. Add a PDF link or upload a file; fiscal period and publication date can be left blank. Reports are private; selected text is sent to Gemini during analysis. Scanned-only PDFs are not supported.",
      "muted",
    ),
    submit("Add report & process ↗"),
  );
  add.append(el("summary", "+ Add a report or upload a PDF"), form);
  root.append(add);
  add.open = documents.length === 0;
  formSubmit(form, async (fd) => {
    const f = fd.get("file"),
      link = fd.get("url");
    if (!link && !f?.size)
      throw new Error("Upload a PDF or provide its direct link.");
    if (link && f?.size)
      throw new Error("Choose either a link or a file, not both.");
    if (f?.size > 40_000_000)
      throw new Error("PDF files must be no larger than 40 MB.");
    const result = await post("/api/v2/documents", {
      company_id: fd.get("company_id"),
      title: fd.get("title"),
      document_type: fd.get("document_type"),
      fiscal_period: fd.get("fiscal_period"),
      published_at: fd.get("published_at") || null,
      size: f?.size || 40_000_000,
      url: link || null,
    });
    if (result.upload_url) {
      notice("Uploading directly to private storage…");
      const r = await fetch(result.upload_url, {
        method: "PUT",
        headers: { "Content-Type": "application/pdf" },
        body: f,
      });
      if (!r.ok)
        throw new Error(
          "Upload failed. Delete the incomplete document and try again.",
        );
      await startJob(
        await post(`/api/v2/documents/${result.document.id}/complete`),
      );
    } else await startJob(result.job);
  });
  if (discoveries.length) {
    const results = el("details");
    results.append(el("summary", "Discovered report candidates"));
    for (const discovery of discoveries.slice(0, 5)) {
      results.append(
        el("h3", companyName(discovery.data.company_id)),
        el("p", discovery.data.note, "muted"),
      );
      for (const item of discovery.data.candidates) {
        const row = el("div", null, "job");
        row.append(
          safeLink(item.url, item.title),
          button(
            "Use this link",
            () => {
              company.value = discovery.data.company_id;
              title.value = item.title.slice(0, 240);
              url.value = item.url;
              file.value = "";
              add.open = true;
              period.focus();
            },
            "text-button",
          ),
        );
        results.append(row);
      }
    }
    root.append(results);
    results.open = true;
  }
  const filters = el("div", null, "filters"),
    companyFilter = select("company", [
      ["", "All companies"],
      ...companyOptions(),
    ]),
    typeFilter = select("type", [
      ["", "All document types"],
      ["annual_report", "Annual reports"],
      ["financial_results", "Financial results"],
    ]),
    statusFilter = select("status", [
      ["", "All statuses"],
      ...[
        "ready",
        "uploading",
        "indexing",
        "extracting",
        "unsupported",
        "duplicate",
        "queued",
        "deleting",
      ].map((s) => [s, s]),
    ]),
    periodFilter = input("period", "Filter fiscal period"),
    list = el("div");
  filters.append(
    field("Company", companyFilter),
    field("Type", typeFilter),
    field("Status", statusFilter),
    field("Fiscal period", periodFilter),
  );
  root.append(filters, list);
  function draw() {
    const docs = documents.filter(
      (d) =>
        (!companyFilter.value || d.data.company_id === companyFilter.value) &&
        (!typeFilter.value || d.data.document_type === typeFilter.value) &&
        (!statusFilter.value || d.data.status === statusFilter.value) &&
        d.data.fiscal_period
          .toLowerCase()
          .includes(periodFilter.value.toLowerCase()),
    );
    list.replaceChildren();
    if (!docs.length) {
      list.append(
        empty("No reports match", "Add a report or adjust the filters."),
      );
      return;
    }
    list.append(
      table(
        ["Report", "Company / period", "Processing", "Actions"],
        docs.map((d) => {
          const actions = el("div", null, "row"),
            description = el("div");
          description.append(
            el("strong", d.data.title),
            el(
              "div",
              `${(d.data.size / 1e6).toFixed(1)} MB · ${d.data.origin}`,
              "muted",
            ),
          );
          if (d.data.notes?.length) {
            const notes = el("details");
            notes.append(el("summary", "Processing notes"));
            d.data.notes.forEach((n) => notes.append(el("p", n, "muted")));
            description.append(notes);
          }
          const progress = el("div");
          progress.append(
            badge(d.data.status),
            el(
              "div",
              `${d.data.indexed_pages || 0} / ${d.data.page_count || "?"} pages`,
              "muted",
            ),
          );
          if (d.data.unreadable_pages?.length)
            progress.append(
              el(
                "div",
                `${d.data.unreadable_pages.length} unreadable pages`,
                "muted",
              ),
            );
          if (
            !["uploading", "queued", "duplicate", "deleting"].includes(
              d.data.status,
            )
          )
            actions.append(
              button("View", () => viewDocument(d.id), "text-button"),
            );
          if (d.data.status === "uploading")
            actions.append(
              button(
                "Process upload",
                async () =>
                  startJob(await post(`/api/v2/documents/${d.id}/complete`)),
                "text-button",
              ),
            );
          actions.append(
            button(
              "Delete",
              async () => {
                if (
                  !confirm(
                    `Delete “${d.data.title}”, its indexed pages, and extracted observations? Saved briefs retain their text, but document links will stop working.`,
                  )
                )
                  return;
                await api("/api/v2/documents/" + d.id, { method: "DELETE" });
                await refreshData();
                await libraryPage(root);
              },
              "text-button danger",
            ),
          );
          return [
            description,
            `${companyName(d.data.company_id)} · ${d.data.fiscal_period}`,
            progress,
            actions,
          ];
        }),
      ),
    );
  }
  for (const control of [companyFilter, typeFilter, statusFilter, periodFilter])
    control.addEventListener("input", draw);
  draw();
  root.append(section("Ask your documents"));
  const chat = el("div", null, "card"),
    chatForm = el("form"),
    selection = checks(
      documentChoices(indexedDocuments()),
      "documents",
      conversationId
        ? conversations.find((c) => c.id === conversationId)?.data
            .document_ids || []
        : [],
    ),
    question = el("textarea");
  question.name = "question";
  question.required = true;
  question.minLength = 3;
  question.maxLength = 2000;
  question.placeholder =
    "What does management say about demand and capital expenditure?";
  chatForm.append(
    field("Use these reports as evidence", selection),
    field("Your question", question),
    submit("Ask with citations ↗"),
  );
  formSubmit(chatForm, async (fd) => {
    await startJob(
      await post("/api/v2/chat", {
        question: fd.get("question"),
        document_ids: fd.getAll("documents"),
        conversation_id: conversationId,
      }),
    );
  });
  chat.append(chatForm);
  root.append(chat);
  const history = el("div");
  if (conversations.length) {
    const picker = select(
      "conversation",
      [
        ["", "Start a new conversation"],
        ...conversations.map((c) => [c.id, c.data.title]),
      ],
      conversationId || "",
    );
    picker.addEventListener(
      "change",
      action(async () => {
        conversationId = picker.value || null;
        await libraryPage(root);
      }),
    );
    chat.prepend(field("Conversation", picker));
  }
  const current = conversations.find((c) => c.id === conversationId);
  for (const turn of current?.data.turns || []) {
    const t = el("div", null, "chat-turn");
    t.append(el("h3", turn.question), documentPassages(turn.answer));
    for (const q of turn.answer.follow_up_questions || [])
      t.append(
        button(
          q,
          () => {
            question.value = q;
            question.focus();
          },
          "text-button",
        ),
      );
    history.append(t);
  }
  chat.append(history);
}

async function settingsPage(root) {
  const viewVersion = root.dataset.viewVersion;
  const data = await api("/api/v2/settings");
  if (root.dataset.viewVersion !== viewVersion) return;
  root.replaceChildren(
    heading(
      "Your workspace, under control.",
      "Private storage, visible usage, and no automatic paid fallback.",
      "04 / SETTINGS",
    ),
  );
  const card = el("div", null, "card");
  card.append(
    el("h2", "Document storage"),
    el(
      "p",
      `${(data.storage_bytes / 1e6).toFixed(1)} MB reserved / ${data.storage_limit / 1e6} MB application limit`,
    ),
  );
  const track = el("div", null, "storage-track"),
    fill = el("div", null, "storage-fill");
  fill.style.width =
    Math.min(100, (data.storage_bytes / data.storage_limit) * 100) + "%";
  track.append(fill);
  card.append(
    track,
    el(
      "p",
      "Pending imports reserve their declared size. Delete unused documents in Library to free space.",
      "muted",
    ),
    button("Manage library", () => navigate("library")),
  );
  root.append(card);
  const providers = el("div", null, "card");
  providers.append(
    el("h2", "Providers & processing"),
    table(
      ["Service", "Configuration"],
      [
        ["Gemini", data.gemini_ready ? "Configured" : "Missing server key"],
        ["Tavily", data.search_ready ? "Configured" : "Missing server key"],
        ["Supabase", "Connected"],
        [
          "Review & notes schema",
          data.reliability_ready
            ? "Ready"
            : "Not verified — apply migration 002 after backup",
        ],
        ["Processing", "One job at a time · resumable saved steps"],
      ],
    ),
  );
  providers.append(
    el("p", data.note, "muted"),
    el(
      "p",
      `Application daily caps: ${data.limits.daily_model_calls} model calls and ${data.limits.daily_search_calls} searches. Providers may impose lower limits. Supabase Free can pause after inactivity. Processing advances only while this tab schedules saved steps; interrupted jobs need explicit resume.`,
      "muted",
    ),
  );
  root.append(
    providers,
    section("Recent usage"),
    table(
      ["UTC date", "Model calls", "Search calls"],
      data.usage.map((u) => [u.day, u.model_calls, u.search_calls]),
    ),
  );
  root.append(button("Sign out", signOut, "secondary"));
}
async function signOut() {
  continueSteps = false;
  await post("/api/auth/logout");
  signedIn = false;
  companies = [];
  documents = [];
  briefs = [];
  jobs = [];
  conversations = [];
  discoveries = [];
  $("#workspace").classList.add("hidden");
  $("#output").replaceChildren();
  $("#output").classList.add("hidden");
  $("#auth-panel").classList.remove("hidden");
  $("#logout").classList.add("hidden");
  $("#session-label").textContent = "Private by design";
}
formSubmit($("#login-form"), async (fd) => {
  await post("/api/auth/login", {
    email: fd.get("email"),
    password: fd.get("password"),
  });
  $("#login-form").reset();
  await enter();
});
$("#logout").addEventListener("click", action(signOut));
$("#sample-button").addEventListener(
  "click",
  action(async () => {
    renderBrief($("#output"), await api("/api/sample"));
    $("#output").scrollIntoView({ block: "start" });
  }),
);
for (const b of document.querySelectorAll(".nav-item"))
  b.addEventListener(
    "click",
    action(() => navigate(b.dataset.page)),
  );
$("#close-viewer").addEventListener("click", () =>
  $("#document-viewer").close(),
);
$("#document-viewer").addEventListener("close", () => {
  $("#viewer-frame").src = "about:blank";
});
async function init() {
  const health = await api("/api/health");
  $("#setup-status").textContent = health.workspace_ready
    ? "Use your provisioned owner account. Public registration is disabled."
    : "Setup needed: connect Supabase and create the owner account. The fictional sample is available.";
  try {
    await api("/api/auth/session");
    await enter();
  } catch (e) {
    if (e.status !== 401 && e.status !== 503) notice(e.message);
  }
}
init().catch((e) => notice(e.message));

async function prepareCharts(files) {
  if (files.length > 3) throw new Error("Choose up to three chart images.");
  const charts = [];
  for (const file of files) {
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > 10_000_000
    )
      throw new Error("Use PNG, JPEG or WebP images up to 10 MB each.");
    const bitmap = await createImageBitmap(file);
    if (
      bitmap.width * bitmap.height > 20_000_000 ||
      Math.min(bitmap.width, bitmap.height) < 40
    ) {
      bitmap.close();
      throw new Error(
        "Chart dimensions must be at least 40 pixels and at most 20 megapixels.",
      );
    }
    const ratio = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height)),
      canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * ratio);
    canvas.height = Math.round(bitmap.height * ratio);
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    let url = canvas.toDataURL("image/jpeg", 0.85);
    if (url.length > 1_150_000) url = canvas.toDataURL("image/jpeg", 0.6);
    if (url.length > 1_150_000)
      throw new Error(
        "Chart is too detailed. Crop it to the relevant section.",
      );
    charts.push({
      filename: file.name.slice(0, 160),
      media_type: "image/jpeg",
      data: url.split(",")[1],
    });
  }
  return charts;
}
