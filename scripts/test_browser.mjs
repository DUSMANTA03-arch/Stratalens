// Start uvicorn separately. This UI test uses explicit API fixtures, never live provider calls.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE || "playwright"
);
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_CHANNEL
    ? { channel: process.env.CHROME_CHANNEL }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }),
  errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const company = "11111111-1111-4111-8111-111111111111",
  doc = "22222222-2222-4222-8222-222222222222",
  brief = "33333333-3333-4333-8333-333333333333";
const companies = [
  {
    id: company,
    data: {
      name: "Northstar Industries (fixture)",
      symbol: "NORTHSTAR",
      isin: "INE000A01001",
      sector: "non_financial",
    },
    created_at: "2026-09-01",
  },
];
const documents = [
  {
    id: doc,
    data: {
      company_id: company,
      title: "Annual report FY2025 (fixture)",
      fiscal_period: "FY2024–25",
      document_type: "annual_report",
      status: "ready",
      page_count: 25,
      indexed_pages: 25,
      size: 1000000,
      origin: "fixture",
    },
    created_at: "2026-09-01",
  },
];
const answer = {
  title: "Northstar business review",
  question: "How did the business perform?",
  company_ids: [company],
  document_ids: [doc],
  passages: [
    {
      heading: "Financial performance",
      text: "Reported revenue increased in the selected period.",
      citations: [
        {
          document_id: doc,
          page: 25,
          quote: "Revenue from operations reached INR 125 crore.",
        },
      ],
    },
  ],
  limitations: ["Synthetic browser fixture."],
  follow_up_questions: [],
};
const briefs = [{ id: brief, data: answer, created_at: "2026-09-01" }];
const financials = {
  companies,
  rows: [2023, 2024, 2025].map((year, i) => ({
    metric: "revenue",
    period_start: `${year - 1}-04-01`,
    period_end: `${year}-03-31`,
    period_type: "annual",
    basis: "consolidated",
    unit: "INR crore",
    values: { [company]: { value: 100 + i * 25, document_id: doc, page: 25 } },
  })),
  derived: [],
  warnings: [],
};
let signedIn = false;
let notes = [];
let observation = {
  id: "44444444-4444-4444-8444-444444444444",
  updated_at: "2026-01-01",
  data: {
    company_id: company,
    document_id: doc,
    page: 25,
    label: "Revenue from operations",
    value: 125,
    original_value: 125,
    currency: "INR",
    scale: "crore",
    period_start: "2024-04-01",
    period_end: "2025-03-31",
    period_type: "annual",
    basis: "consolidated",
    definition: "group_total",
    quote: "Revenue from operations reached INR 125 crore.",
    observation_version: 1,
  },
};
let assigned = false,
  lastComparison = "";

const activity = [
  {
    id: "activity-fixture",
    kind: "research",
    status: "running",
    state: { phase: "analyst", question: "Research progress fixture" },
  },
];
await page.route("**/api/**", async (route) => {
  const req = route.request(),
    u = new URL(req.url()),
    p = u.pathname;
  let data;
  if (p === "/api/v2/templates")
    return route.fulfill({
      json: {
        market_landscape: {
          label: "Market landscape",
          mode: "market",
          question: "Analyze this market and its evidence gaps.",
        },
        risk_review: {
          label: "Risk review",
          mode: "company",
          question: "Analyze disclosed risks in selected reports.",
        },
      },
    });
  if (p.endsWith("/coverage"))
    return route.fulfill({
      json: {
        year_end_month: 3,
        note: "Missing means absent from this workspace.",
        rows: [
          {
            period_type: "annual",
            period_end: "2025-03-31",
            status: assigned ? "indexed" : "missing",
          },
        ],
        unassigned: assigned ? [] : [{ id: doc, title: "Unassigned fixture" }],
      },
    });
  if (p.endsWith("/period") && req.method() === "PATCH") {
    assigned = true;
    return route.fulfill({ json: documents[0] });
  }
  if (p === "/api/v2/observations")
    return route.fulfill({ json: [observation] });
  if (p.startsWith("/api/v2/observations/")) {
    const body = req.postDataJSON();
    observation.updated_at = String(Date.now());
    if (p.endsWith("/review"))
      observation.data.review = {
        status: body.status,
        version: observation.data.observation_version,
      };
    else {
      observation.data.value = body.value;
      observation.data.observation_version++;
      delete observation.data.review;
    }
    return route.fulfill({ json: observation });
  }
  if (p === "/api/v2/notes") {
    if (req.method() === "POST") {
      notes.push({ id: "note1", updated_at: "now", data: req.postDataJSON() });
      return route.fulfill({ json: notes.at(-1) });
    }
    return route.fulfill({ json: notes });
  }
  if (p.startsWith("/api/v2/notes/")) {
    if (req.method() === "DELETE") notes = [];
    else notes[0].data.text = req.postDataJSON().text;
    return route.fulfill({ json: notes[0] || { ok: true } });
  }
  if (p === "/api/sample") {
    data = {
      mode: "sample",
      question: "Fixture market",
      sources: [
        {
          id: "S1",
          title: "Official fixture report",
          url: "https://example.com/report",
          kind: "web",
        },
      ],
      claims: [
        {
          id: "C1",
          source_id: "S1",
          statement: "Fixture revenue is 125 crore",
          quote: "Revenue is 125 crore",
          entity: "Northstar",
          metric: "Revenue",
          value: 125,
          unit: "INR crore",
          period: "2025",
        },
      ],
      report: {
        title: "Market fixture",
        sections: [
          {
            heading: "Executive summary",
            findings: [
              { text: "Fixture revenue is 125 crore", claim_ids: ["C1"] },
            ],
          },
        ],
        limitations: [],
      },
      graph: {
        nodes: [
          { id: "S1", type: "source", label: "Official fixture report" },
          { id: "C1", type: "claim", label: "Fixture revenue is 125 crore" },
        ],
        edges: [{ from: "S1", to: "C1", relation: "reports" }],
      },
    };
  } else if (p === "/api/auth/logout") {
    signedIn = false;
    data = {};
  } else if (p === "/api/health") data = { workspace_ready: true };
  else if (p === "/api/auth/session") {
    if (!signedIn)
      return route.fulfill({ status: 401, json: { detail: "Sign in" } });
    data = { owner_id: company };
  } else if (p === "/api/auth/refresh")
    return route.fulfill({ status: 401, json: { detail: "Sign in" } });
  else if (p === "/api/auth/login") {
    signedIn = true;
    data = { email: "fixture@example.com" };
  } else if (p === "/api/v2/companies") data = companies;
  else if (p === "/api/v2/documents") data = documents;
  else if (p === "/api/v2/briefs") data = briefs;
  else if (p === "/api/v2/jobs") data = activity;
  else if (
    [
      "/api/v2/jobs",
      "/api/v2/conversations",
      "/api/v2/discoveries",
      "/api/v2/observations",
    ].includes(p)
  )
    data = [];
  else if (p === "/api/v2/comparison") {
    lastComparison = u.search;
    data = financials;
  } else if (p === `/api/v2/documents/${doc}/view`)
    data = {
      document: documents[0],
      url: "/assets/favicon.svg",
      page: {
        page: 25,
        text: "Revenue from operations reached INR 125 crore.",
      },
    };
  else if (p === "/api/v2/settings")
    data = {
      storage_bytes: 1000000,
      storage_limit: 800000000,
      usage: [],
      gemini_ready: true,
      search_ready: true,
      limits: { daily_model_calls: 100, daily_search_calls: 20 },
      note: "Fixture counters.",
    };
  else throw new Error("Unexpected API call: " + p);
  await route.fulfill({ json: data });
});
try {
  await page.goto(process.env.APP_URL || "http://127.0.0.1:8001");
  await page.getByLabel("Email", { exact: true }).fill("fixture@example.com");
  await page.getByLabel("Password", { exact: true }).fill("fixture-only");
  await page.getByRole("button", { name: "Sign in", exact: false }).click();
  await page
    .getByRole("heading", { name: "A clearer point of view." })
    .waitFor();
  await page.getByLabel("Research template").selectOption("market_landscape");
  assert.equal(
    await page.getByLabel("What would you like to understand?").inputValue(),
    "Analyze this market and its evidence gaps.",
  );
  await page.locator("#jobs-panel.is-active").waitFor();
  assert.equal(
    await page.locator("#workspace > :first-child").getAttribute("id"),
    "jobs-panel",
  );
  assert.equal(
    await page.locator(".step-animated").innerText(),
    "4\nAnalyze evidence",
  );
  await page.getByRole("button", { name: /Saved briefs/ }).click();
  assert.equal(
    await page.evaluate(() => document.activeElement.id),
    "saved-research",
  );
  activity[0].status = "paused";
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page
    .locator("#jobs-panel:not(.is-active)")
    .waitFor({ state: "attached" });
  assert.equal(await page.locator(".step-animated").count(), 0);
  assert.equal(await page.locator("#jobs-panel").isVisible(), false);
  await page.locator("[data-page=activity]").click();
  await page
    .getByRole("heading", { name: "Recent activity", exact: true })
    .waitFor();
  assert.equal(await page.locator("#jobs-panel").isVisible(), true);
  await page.locator("[data-page=research]").click();
  await page.getByRole("button", { name: /Companies followed/ }).click();
  await page.getByRole("heading", { name: "Company dashboard" }).waitFor();
  await page.getByText("Financial review queue", { exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect source", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "Review financial observation" })
    .waitFor();
  await page
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await page
    .locator("#viewer-evidence td")
    .getByText("reviewed", { exact: true })
    .waitFor();
  await page.getByLabel("Corrected value").fill("130");
  await page
    .getByLabel("Reason", { exact: true })
    .fill("Checked source table for transcription");
  await page
    .getByRole("button", { name: "Save correction", exact: true })
    .click();
  await page.waitForFunction(
    () =>
      document.querySelector("#viewer-evidence input[name=corrected_value]")
        .value === "130",
  );
  assert.equal(observation.data.review, undefined);
  await page.getByRole("button", { name: "Close source viewer" }).click();
  await page
    .getByText("Report coverage · 3 annual periods / 8 quarters", {
      exact: true,
    })
    .click();
  await page.getByLabel("Period end", { exact: true }).fill("2025-03-31");
  await page
    .getByRole("button", { name: "Assign period", exact: true })
    .click();
  await page.waitForFunction(
    () =>
      !document
        .querySelector("#page-content")
        .textContent.includes("Unassigned fixture"),
  );
  assert.equal(assigned, true);
  await page.getByLabel("Reviewed only", { exact: true }).check();
  await page.waitForTimeout(100);
  assert.ok(lastComparison.includes("reviewed_only=true"));
  await page.locator("[data-page=research]").click();
  await page.getByRole("button", { name: /Reports ready/ }).click();
  assert.equal(await page.locator("select[name=status]").inputValue(), "ready");
  await page.getByRole("button", { name: "View", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  await page.locator("[data-page=research]").click();
  await page
    .getByRole("button", { name: "Peer comparison", exact: true })
    .click();
  await page.locator("input[name=companies]").check();
  await page.getByRole("button", { name: "Compare financials ↗" }).click();
  await page.getByRole("button", { name: "Download financial CSV" }).waitFor();
  await page.locator("[data-page=research]").click();
  await fs.mkdir("tmp/browser", { recursive: true });
  await page.screenshot({
    path: "tmp/browser/research-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Read brief →" }).click();
  await page.getByRole("tab", { name: "Sources", exact: true }).click();
  await page
    .getByRole("heading", { name: "Selected document sources" })
    .waitFor();
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await page.getByText("Quoted source appendix", { exact: true }).waitFor();
  await page.getByRole("tab", { name: "Brief", exact: true }).click();
  await page.getByRole("button", { name: "p. 25", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "Close source viewer" }).click();
  await page.getByText("Your notes", { exact: true }).click();
  await page
    .getByLabel("Add your note", { exact: true })
    .fill("My hypothesis, not evidence.");
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await page
    .getByLabel("Your note", { exact: true })
    .fill("Updated hypothesis");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await page.waitForTimeout(100);
  assert.equal(notes[0].data.text, "Updated hypothesis");
  await page.getByRole("button", { name: "Delete note", exact: true }).click();
  await page
    .getByLabel("Your note", { exact: true })
    .waitFor({ state: "detached" });
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Markdown", exact: true }).click();
  assert.equal((await dl).suggestedFilename(), "stratalens.md");
  await page.locator("[data-page=companies]").click();
  await page.getByRole("heading", { name: "Company dashboard" }).waitFor();
  await page.locator("svg[role=img]").waitFor();
  assert.equal(await page.locator("svg[role=img]").count(), 1);
  await page.screenshot({
    path: "tmp/browser/company-desktop.png",
    fullPage: true,
  });
  const csv = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download financial CSV" }).click();
  assert.equal((await csv).suggestedFilename(), "stratalens-financials.csv");
  await page.locator("[data-page=library]").click();
  await page
    .getByRole("heading", { name: "Your source of understanding." })
    .waitFor();
  await page.getByRole("button", { name: "View", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  await page.locator("summary").filter({ hasText: "+ Add a report" }).click();
  assert.equal(await page.locator("input[type=file]").count(), 1);
  for (const name of ["fiscal_period", "published_at", "file"]) {
    assert.equal(
      await page.locator(`input[name=${name}]`).evaluate((i) => i.required),
      false,
    );
  }
  await page.screenshot({
    path: "tmp/browser/library-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "tmp/browser/library-mobile.png",
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "mobile horizontal overflow",
  );
  await page.locator("[data-page=research]").click();
  await page
    .getByRole("button", { name: "Open fictional sample", exact: true })
    .click();
  await page.getByRole("tab", { name: "Connections", exact: true }).click();
  await page.locator(".connection-map svg").waitFor();
  await page.screenshot({
    path: "tmp/browser/connections-mobile.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "Brief", exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect evidence", exact: true })
    .click();
  assert.equal(
    await page
      .getByRole("tab", { name: "Evidence", exact: true })
      .getAttribute("aria-selected"),
    "true",
  );
  await page.getByRole("tab", { name: "Sources", exact: true }).click();
  await page
    .getByRole("link", { name: "Official fixture report", exact: true })
    .waitFor();
  const htmlDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "HTML", exact: true }).click();
  const htmlPath = await (await htmlDownload).path();
  const exported = await fs.readFile(htmlPath, "utf8");
  assert.equal(exported.includes(" hidden"), false);
  assert.equal(exported.includes("Fixture revenue is 125 crore"), true);
  const rich = JSON.parse(
    await fs.readFile(
      new URL("../tests/fixtures/rich_brief.json", import.meta.url),
      "utf8",
    ),
  );
  await page.evaluate(async (data) => {
    const { renderBrief } = await import("/assets/reports.js");
    renderBrief(document.querySelector("#output"), data);
  }, rich);
  await page.locator(".executive-takeaway").waitFor();
  await page.locator(".evidence-chart svg").waitFor();
  assert.equal(await page.locator(".evidence-chart").count(), 1);
  await page.screenshot({
    path: "tmp/browser/rich-brief-mobile.png",
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.getByRole("tab", { name: "Brief", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  assert.equal(
    await page
      .getByRole("tab", { name: "Sources", exact: true })
      .getAttribute("aria-selected"),
    "true",
  );
  const richHtml = page.waitForEvent("download");
  await page.getByRole("button", { name: "HTML", exact: true }).click();
  const richExport = await fs.readFile(await (await richHtml).path(), "utf8");
  for (const expected of [
    "EXECUTIVE TAKEAWAY",
    "Competitive positioning",
    "<svg",
    "historical",
    "Not established",
  ])
    assert.ok(richExport.includes(expected), expected);
  assert.ok(!richExport.includes("personal-notes"));
  // A delayed company response must not append reports after navigation away.
  let captureComparison;
  const pendingComparison = new Promise((resolve) => { captureComparison = resolve; });
  await page.route("**/api/v2/comparison?*", (route) => captureComparison(route));
  await page.locator("[data-page=companies]").click();
  const delayedComparison = await pendingComparison;
  await page.locator("[data-page=research]").click();
  await page.getByRole("heading", { name: "A clearer point of view." }).waitFor();
  const responseFinished = page.waitForResponse((r) => r.url().includes("/api/v2/comparison?"));
  await delayedComparison.fulfill({ json: financials });
  await (await responseFinished).finished();
  await page.waitForTimeout(100);
  assert.equal(await page.getByRole("heading", { name: "Reports in your library" }).count(), 0);
  await page.locator("[data-page=settings]").click();
  await page
    .getByRole("heading", { name: "Your workspace, under control." })
    .waitFor();
  await page.locator("#logout").click();
  await page.locator("#auth-panel:not(.hidden)").waitFor();
  assert.equal(await page.locator("#workspace").isVisible(), false);
  assert.deepEqual(errors, []);
  console.log(
    "Browser fixture checks passed: login, navigation, dashboard trends, citations/viewer, exports, library and mobile layout.",
  );
} finally {
  await browser.close();
}
