# StrataLens v2

A private, hosted research workspace for Indian listed companies. Built with FastAPI, LangGraph, Gemini, Tavily, and Supabase. The current deployment target is **Vercel Hobby + Supabase Free**. Durable data stays in Supabase; the existing Render deployment remains available during the move. See [DEPLOYMENT.md](DEPLOYMENT.md) for setup and verification status.

## What is implemented

- Owner-only email/password sign-in, private document storage, and saved research.
- Market research with up to three chart images and the original evidence validation workflow.
- NSE company lookup, explicit company selection, manual identifiers for BSE-only/unavailable listings, and owner-confirmed company websites.
- Official-domain report discovery targeting three annual periods and eight completed quarters. Candidates require user confirmation; coverage is not guaranteed.
- Direct PDF uploads or public PDF URLs, checksum deduplication, separate revised filings, and an indexed library with company/type/period/status filters.
- Full-document indexing in eight-page steps, up to 40 MB and 600 pages. Unreadable and truncated pages remain visible. Scanned-only reports are marked unsupported.
- Financial extraction with original labels/values/units, statement basis, reporting dates, restatement metadata, and document/page evidence.
- INR-crore financial tables, revenue trends, deterministic growth/margins, and comparisons of up to three companies. Missing values are never filled with zero.
- Manual value corrections with optimistic concurrency and an audit trail preserving the original extraction.
- Selected-document company briefs and follow-up chat with matched quotations and page citations.
- A source viewer beside extracted evidence; signed document URLs expire after five minutes.
- Markdown, HTML, JSON, Unicode PDF brief exports, and financial CSV exports.
- Browser-advanced durable jobs with database leases, fenced commits, cancellation, quota pauses, and saved checkpoints.

Financial mappings remain model-assisted and need human review. Quotation/value matching establishes provenance, not semantic correctness or factual truth. Bank/insurance-specific ratios, valuation models, live prices, alerts, and comprehensive OCR are not implemented.

## Local development

Use Python 3.12 or 3.13 and Node.js 20+ for development checks.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app:app --reload --port 8001
```

Set `COOKIE_SECURE=false` **only for local HTTP development**. Open http://127.0.0.1:8001. Without Supabase configuration, the app shows its setup state and the fictional sample still works without provider calls.

Environment variables:

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project URL, e.g. `https://project.supabase.co` |
| `SUPABASE_ANON_KEY` | Project's legacy anon JWT key (Auth requests) |
| `SUPABASE_SERVICE_ROLE_KEY` | Legacy service-role JWT key; server-only database/storage access |
| `GEMINI_API_KEY` | Gemini Developer API key from your free-tier project |
| `GEMINI_MODEL` | Structured-output and vision model available to that project; existing default `gemini-3.1-flash-lite` |
| `TAVILY_API_KEY` | Your Tavily free-tier key |
| `COOKIE_SECURE` | `true` on hosted HTTPS; `false` only for local HTTP |

Do not commit `.env`, paste keys into chat, or expose the service-role key in browser configuration. Provider availability/free quotas vary; verify the selected model in your own account. The application does not activate billing, purchase credits, or fall back to paid providers. It cannot determine whether an existing account already has paid billing enabled.

## Supabase setup — required before private use

1. Create a **Free** Supabase project.
2. In the SQL editor, run `migrations/001_workspace.sql` **once**. This creates the tables, read-only owner RLS policies, service-only processing functions, and private `reports` bucket. It is an initial migration, not a rerunnable seed script.
3. In Authentication settings, disable **Allow new users to sign up**. Leave email/password sign-in enabled.
4. In Authentication → Users, create one owner with your email and a strong password, marking the email confirmed.
5. Copy that user's UUID and run:

   ```sql
   insert into public.workspace_owners(user_id)
   values ('YOUR-AUTH-USER-UUID');
   ```

   The singleton constraint permits one owner. A valid Supabase account without this owner entry cannot use the app.
6. Copy the project URL and legacy anon/service-role keys into your local environment or Render's secret settings. The REST adapter expects the legacy JWT keys, not a publishable/secret key substituted into a Bearer header.
7. Keep the `reports` bucket private. Do not add public read/upload policies. The server issues narrowly scoped signed upload/view URLs after owner authorization.

Browser sessions only have read access under RLS. All mutations pass through the authenticated backend; job commits are additionally guarded by database lease tokens. New auth users, even if accidentally allowed to register, cannot access the workspace without the owner row.

## Deploy on Render Free

1. Put this folder in a private Git repository and connect it to Render. This supplied workspace is not currently a Git checkout; create the repository before importing it.
2. Choose a **Blueprint** using `render.yaml`, or create a Python Web Service with:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers`
   - Plan: **Free**
   - Health check: `/api/health`
   - Python: `3.12.12`
3. Add the six provider/Supabase variables above in Render's environment settings and set `COOKIE_SECURE=true`.
4. Deploy and open the HTTPS URL. Confirm the sample, owner sign-in, company creation, PDF upload, and processing checkpoints.
5. Review the hosted acceptance checklist below before relying on the extracted financials.

No Render disk, paid worker, scheduled cron, or Render Postgres instance is required. Render Free sleeps after idle periods and its filesystem is ephemeral; Supabase Free may pause after inactivity. Data lives in Supabase. Resume paused services in their dashboards and use **Resume** on saved jobs when returning.

References: [Render free services](https://render.com/docs/free), [Supabase free allowances](https://supabase.com/docs/guides/platform/billing-on-supabase), [Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing).

For your own server instead, the included `Dockerfile` runs the same app with Supabase as its persistence layer:

```sh
docker build -t stratalens .
docker run --env-file .env -p 8000:8000 stratalens
```

Use an HTTPS reverse proxy and secure cookies for remote access. The Docker build excludes `.env` and development artifacts.

## Processing and free-tier limits

Each job moves through short, explicitly requested steps. A step has a 180-second application timeout and a 240-second database lease. One lease can be active per owner. All page, observation, and checkpoint writes commit together only while the lease is valid. Expired/cancelled workers cannot publish their result.

Keeping the tab open schedules the next step. **Pause after step** stops further scheduling; closing the tab stops it as well. An already dispatched step may finish or expire. Reopening the app lists saved jobs; select **Resume**. Provider requests already sent cannot be undone, and an interrupted step may consume another call on retry. Calls are reserved in the database before dispatch, including failed attempts.

| Bound | Default |
| --- | --- |
| Document | 40 MB / 600 pages |
| Indexing/extraction batch | 8 pages |
| Original-file reservations | 800 MB across reports and chart assets |
| Database guard | 350 MB across indexed pages, records and jobs, checked before commits |
| Model calls per UTC day | 100 attempted calls |
| Searches per UTC day | 20 attempted calls |
| Model calls per ingestion/research/other job | 80 / 20 / 4 |
| Search calls per job | 6 |
| Retrieved chat context | Up to 12 ranked pages across selected documents |
| Conversation length | 50 questions |

These application caps do not guarantee provider availability or remaining free quota. A quota failure pauses the job without an automatic retry. Daily application caps reset at UTC midnight; a permanently exhausted job budget requires a new, narrower run. Settings shows application attempt counts, not provider quota balances.

A disposable, bounded 80 MB PDF cache reduces repeated Supabase downloads while indexing. Losing that cache affects speed/egress only, not saved data. Very complex PDFs can exceed runtime/memory limits even within the file/page limits; split such documents or use a smaller machine-readable report. PDF text exceeding 60,000 characters on a single page is explicitly marked truncated. Financial page selection is heuristic, and selected model contexts are bounded.

## Financial behavior

Supported reported fields: revenue from operations, profit after tax for the period, total assets, total equity, explicitly stated total borrowings, cash/equivalents, operating cash flow, capex, and basic EPS.

Every observation retains original value, currency/scale, label, definition, basis, period start/end/type, document ID, page, quote, publication date, and restatement status. EPS remains INR/share. INR scale normalization is deterministic; cross-currency conversion is not performed.

- Consolidated is the default; standalone is explicitly selectable.
- Annual, quarterly, YTD and instant balance-sheet periods are separate.
- No standalone quarter is inferred by subtracting cumulative results.
- Different fiscal dates/definitions are not aligned silently.
- Conflicting versions are withheld unless a later, explicitly restated filing resolves them. Missing publication dates do not establish version precedence.
- Year-on-year growth requires matching dates one year apart and a positive base. Net profit margins require matching period/basis/definition and positive revenue.
- Banks/insurers stay readable but are excluded from generic comparisons.
- Corrections alter the displayed value in its original units; they preserve the original extraction and record the reason, timestamp, and owner. Definition errors should be treated as evidence gaps, not solved by editing a number.

Company websites are owner-confirmed. Generic domains do not receive primary-source status merely because a search result claims to be an annual report. Redirect destinations are checked before source classification.

## API and code map

- `app.py`: FastAPI entrypoint, limits, security headers, static frontend, fixture sample.
- `analyst/auth.py`: owner-only Auth integration, HttpOnly cookies, refresh/logout.
- `analyst/workspace_api.py`: companies, documents, saved research, chat, corrections, exports, and jobs.
- `analyst/workspace_store.py`: Supabase REST/storage adapter and disposable PDF cache.
- `analyst/workspace_jobs.py`: bounded ingestion, discovery, research and chat steps.
- `analyst/documents.py`, `analyst/financials.py`: page extraction, financial provenance and comparison rules.
- `analyst/workflow.py`: existing LangGraph market workflow; durable execution uses its same stage handlers.
- `assets/`: ES modules for API access, UI primitives, reports, financials, and workspace navigation.
- `migrations/001_workspace.sql`: owner RLS, records/pages/jobs, full-text search and fenced transactional functions.

Public: `GET /api/health` and `GET /api/sample` (deterministic fictional fixture only).

Auth: `POST /api/auth/login`, `/refresh`, `/logout`; `GET /api/auth/session`.

Owner-only `/api/v2` interfaces:

- Company search/list/create and `POST /companies/{id}/discover`.
- Document list/create, `POST /documents/{id}/complete`, page view, and deletion.
- `POST /research` and `/chat` create saved jobs.
- Job list/get, `POST /jobs/{id}/advance`, and `/cancel`.
- Briefs, conversations, discoveries, observations, comparisons, and settings.
- `PATCH /observations/{id}` requires the last `updated_at` plus correction reason.
- `GET /briefs/{id}/export.pdf` renders a saved brief with embedded Unicode font.

The obsolete `/api/research` live route returns 410 so it cannot bypass durable budgets. Its authenticated sample stream remains for regression tests.

## Verification

```sh
pytest -q
python -m compileall -q app.py analyst
pip check
npm install
npm run check:js
npm run test:database
npx playwright install chromium
# Start the app separately before this command:
npm run test:browser
```

Database tests execute the real migration in PGlite/PostgreSQL, including owner access, leases, fencing, cancellation, FTS, storage reservations, correction audit, and deletion. Browser tests use explicitly synthetic API fixtures and verify sign-in, navigation, financial trends, citations, exports and mobile layout; they do not contact live providers.

The bundled Noto Sans font is openly licensed; its license is in `assets/fonts/OFL.txt`. PDF tests verify retained rupee symbols, punctuation, multi-page output and citations; rendered output is visually inspected during development. Noto Sans covers the Latin-script reporting workflow, not every script in every Unicode language.

### Hosted acceptance

The private workspace is deployed at https://stratalens-uq44.onrender.com on Render Free with Supabase persistence. Release verification status is recorded in [DEPLOYMENT.md](DEPLOYMENT.md). Use this checklist for subsequent releases:

1. Verify anonymous requests cannot list documents, run jobs, or obtain signed URLs; sign in with the provisioned owner.
2. Use three non-financial Indian companies: Reliance Industries, Infosys, and Asian Paints. Confirm exact company identities and official reports yourself.
3. Upload a machine-readable annual report with financial statements after page 20; verify those pages are indexed and opened by citations.
4. Try duplicate, revised, scanned, malformed and oversized files. Confirm their statuses and messages.
5. Close/reopen during indexing, resume, and open a second tab. Verify one active step, retained progress and no duplicate observations.
6. Manually check revenue, net profit, operating cash flow, units, fiscal dates and statement basis against the filings. Compare only genuinely compatible periods.
7. Ask document questions, verify quotations and gaps, correct a figure with a reason, and inspect the audit history.
8. Download all export types and verify PDF text/table layout. Inspect mobile and keyboard navigation.
9. Exercise provider quota errors and storage failures; confirm saved work remains and no paid fallback occurs.

Deployment success does not establish financial accuracy. Review extracted observations against their cited pages; incomplete or paused extraction remains visibly incomplete.


## Research reliability release (v0.3)

New research includes a cited executive takeaway, an evidence-backed positioning matrix, and deterministic charts when compatible numeric observations exist. Older saved briefs remain unchanged. Progress summaries are saved with each successful job checkpoint.

Company dashboards include report coverage (three completed annual periods and eight quarters), editable financial year-end, explicit period assignment, and a financial review queue beside the original PDF. Corrections invalidate review; observations remain available with unreviewed labels unless the owner selects Reviewed only. Personal notes remain separate from evidence and exports.

Existing Supabase projects must back up workspace tables, then apply `migrations/002_reliability.sql` once. Settings shows schema readiness. See [DEPLOYMENT.md](DEPLOYMENT.md) for private GitHub and Render Free setup, secure token entry, migration order, and rollback.

Verification commands:

```sh
.venv/bin/python -m pytest -q
npm ci
npm run check:js
npm run test:database
CHROME_CHANNEL=chrome npm run test:browser
.venv/bin/python scripts/check_official_filings.py
```

Browser tests use explicit fixtures and require a local server. The official-filings benchmark downloads public reports and checks known source-page figures without AI calls or database writes; it does not replace live extraction or hosted acceptance.
