# StrataLens release setup

Deployment target: Vercel Hobby + existing Supabase. GitHub owner: DUSMANTA03-arch. The prior Render service stays available until Vercel verification succeeds.
Never paste keys into chat or commit `.env`. Deployment keys below are for local setup only; do not copy them into the application environment.

## Vercel move (v0.3.1)

The source uses Vercel's native FastAPI entrypoint (`app.py`) with a 300-second function limit and one Singapore region. Browser-driven processing still saves each bounded step in Supabase. PDF uploads go directly to private Supabase storage; they do not pass through Vercel's 4.5 MB request limit. Temporary PDF cache files are optional and stored only in the platform's temporary directory.

Create a short-lived deployment token at https://vercel.com/account/settings/tokens. Save it through hidden local input:

```sh
.venv/bin/python scripts/configure_deployment.py --vercel
```

Existing values can be retained by pressing Enter. Do not send the token in chat.

Import the private `DUSMANTA03-arch/Stratalens` repository into the intended **Hobby** Vercel account/project. Choose FastAPI, leave Build Command and Output Directory at their framework defaults, and use the repository root. Configure `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY`, `GEMINI_MODEL`, and `COOKIE_SECURE=true` as private environment variables. Never configure deployment tokens as app environment variables.

After the production URL is verified, update Supabase Authentication → URL Configuration → Site URL to the final HTTPS Vercel address. Validate owner sign-in, unauthorized access rejection, signed PDF links, saved jobs, reviews, notes, and exports on that URL. Do not disable the existing Render service until these checks pass.

Vercel migration status: Hobby project created, release build pending. The reported L&T/Alok Industries mix-up was confirmed in saved discovery candidates. Shared exchange domains no longer establish company identity: exchange filenames, candidate names, PDF opening pages, selected company IDs, and cross-company duplicates are checked. Saved discoveries are filtered on read. Documents with unidentified issuers require explicit owner confirmation; detected mismatches are blocked.

Indexing no longer runs unused geometric table detection. Page text is unchanged in the local benchmark (eight Reliance pages: 1.41 seconds before / 1.01 seconds after). New jobs prioritize statement pages and omit unrelated pages from financial extraction while still indexing all pages. Supabase connections are reused within each request. Old checkpoints retain their previous processing scheme.

Version 0.3.1 fixes saved-record responses missing their database timestamps, stale page responses overwriting a newly selected page, and stale financial-filter responses replacing current results. Gemini timeout and invalid-evidence messages are distinct, and financial extraction receives explicit original-label descriptions. Verification: 60 Python tests, database migration tests, JavaScript syntax checks, and Chrome browser regressions passed. Supabase auth and the existing hosted health endpoint responded successfully on 2026-10-14; Supabase management access returned 401 and needs a new management token only if that API is required.

References: https://vercel.com/docs/frameworks/backend/fastapi and https://vercel.com/docs/functions/limitations.

## Account access

1. GitHub: create an empty **private** repository named `stratalens` at https://github.com/new (no generated README). Open https://github.com/settings/personal-access-tokens/new, choose resource owner DUSMANTA03-arch, select only `stratalens`, use a short expiration, and grant repository **Contents: Read and write**. If publishing `.github/workflows`, also grant **Workflows: Read and write**. Save the generated value as `GITHUB_TOKEN` in the local `.env`.
2. Vercel: create a short-lived token in account settings and save it as `VERCEL_TOKEN` using the helper above. Connect GitHub and grant Vercel access to the private Stratalens repository. Select the intended Hobby account/project before publishing.
3. Supabase: open https://supabase.com/dashboard/account/tokens and generate a short-lived personal access token, saved locally as `SUPABASE_ACCESS_TOKEN`. This is management access for applying the migration, not the anon/service-role app key. If the dashboard supports granular permissions, restrict it to this project's database query access and project read access. Alternatively, run the reviewed migration yourself in the Supabase SQL Editor after backup; no management token is required for that route.

Add these lines to the existing local `.env`, replacing the placeholders privately:

```dotenv
GITHUB_TOKEN=
VERCEL_TOKEN=
SUPABASE_ACCESS_TOKEN=
```

For hidden token entry, open a terminal in this project folder and run:

```sh
.venv/bin/python scripts/configure_deployment.py --vercel
```

The helper saves tokens privately in `.env` and does not display them. Press Enter to keep a token unchanged.

Tell the assistant “deployment access ready” after saving. Do not send the values. Revoke temporary deployment tokens after verification.

Official references: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens , https://vercel.com/docs/rest-api , https://supabase.com/docs/reference/api/introduction .

## Release sequence

- Run Python tests, JavaScript syntax checks, database tests and browser tests.
- Back up owner records, workspace records, pages, jobs and usage to a private local file before migration.
- Existing Supabase projects: run only `migrations/002_reliability.sql` once after reviewing. New projects need 001 first. Keep public signup disabled and the single-owner row.
- Publish reviewed source to the private repository; exclude `.env`, virtual environments, local data, screenshots and backup files.
- Import the private repository into Vercel Hobby using the native FastAPI framework and checked-in `vercel.json`. Let Vercel install the Python requirements and discover `app.py`; no separate start command is needed.
- Configure only application secrets: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, TAVILY_API_KEY; set COOKIE_SECURE=true. Preserve configured GEMINI_MODEL.
- Verify HTTPS owner sign-in, unauthorized access rejection, private PDF viewing, uploads, checkpoint recovery, reviews, notes and exports.
- Tag the tested source for rollback. Do not reverse the additive migration when reverting application code; preserve the backup.

Supabase remains the durable store. No keep-alive or paid fallback.

Previous release status (2026-09-29): the private GitHub source was published at https://github.com/DUSMANTA03-arch/Stratalens, migration 002 was applied to Supabase, and the Render Free service was deployed at https://stratalens-uq44.onrender.com. The owner-only auth Site URL was configured for that address and public signup remained disabled.

Verification completed: 55 Python tests, PostgreSQL migration tests, JavaScript syntax checks, Chrome fixture checks, hosted anonymous-access checks, owner-session refresh, private signed PDF viewing, mobile and keyboard navigation, exports, company dashboard navigation, review queue/source viewer, and the Reliance/Infosys/Asian Paints official filing run. Reliance and Infosys indexed all pages but paused during Gemini financial extraction with partial observations retained; Asian Paints indexed all 55 pages and completed extraction. No paused job was automatically retried. A private Supabase backup is under tmp/deployment.

Render Free may sleep after inactivity and its local filesystem is disposable. Durable documents, checkpoints, observations, notes and reviews remain in Supabase. The local development server is stopped.
