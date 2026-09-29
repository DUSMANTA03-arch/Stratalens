# StrataLens release setup

Deployment target: Render Free + existing Supabase. GitHub owner: DUSMANTA03-arch.
Never paste keys into chat or commit `.env`. Deployment keys below are for local setup only; do not copy them into the Render service.

## Account access

1. GitHub: create an empty **private** repository named `stratalens` at https://github.com/new (no generated README). Open https://github.com/settings/personal-access-tokens/new, choose resource owner DUSMANTA03-arch, select only `stratalens`, use a short expiration, and grant repository **Contents: Read and write**. If publishing `.github/workflows`, also grant **Workflows: Read and write**. Save the generated value as `GITHUB_TOKEN` in the local `.env`.
2. Render: open https://dashboard.render.com/u/settings → API Keys → Create API Key. Save it as `RENDER_API_KEY` in the local `.env`. In Render, connect GitHub and grant the Render integration access to the private stratalens repository. API keys alone do not grant access to private GitHub source.
3. Supabase: open https://supabase.com/dashboard/account/tokens and generate a short-lived personal access token, saved locally as `SUPABASE_ACCESS_TOKEN`. This is management access for applying the migration, not the anon/service-role app key. If the dashboard supports granular permissions, restrict it to this project's database query access and project read access. Alternatively, run the reviewed migration yourself in the Supabase SQL Editor after backup; no management token is required for that route.

Add these lines to the existing local `.env`, replacing the placeholders privately:

```dotenv
GITHUB_TOKEN=
RENDER_API_KEY=
SUPABASE_ACCESS_TOKEN=
```

For hidden token entry, open a terminal in this project folder and run:

```sh
.venv/bin/python scripts/configure_deployment.py
```

The helper saves tokens privately in `.env` and does not display them. Press Enter to keep a token unchanged.

Tell the assistant “deployment access ready” after saving. Do not send the values. Revoke temporary deployment tokens after verification.

Official references: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens , https://render.com/docs/api , https://supabase.com/docs/reference/api/introduction .

## Release sequence

- Run Python tests, JavaScript syntax checks, database tests and browser tests.
- Back up owner records, workspace records, pages, jobs and usage to a private local file before migration.
- Existing Supabase projects: run only `migrations/002_reliability.sql` once after reviewing. New projects need 001 first. Keep public signup disabled and the single-owner row.
- Publish reviewed source to the private repository; exclude `.env`, virtual environments, local data, screenshots and backup files.
- Create a Render Free Python web service from the repository using `render.yaml`: build `pip install -r requirements.txt`, start `uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers`.
- Configure only application secrets: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, TAVILY_API_KEY; set COOKIE_SECURE=true. Preserve configured GEMINI_MODEL.
- Verify HTTPS owner sign-in, unauthorized access rejection, private PDF viewing, uploads, checkpoint recovery, reviews, notes and exports.
- Tag the tested source for rollback. Do not reverse the additive migration when reverting application code; preserve the backup.

Render Free may sleep after inactivity; local disk is disposable. Supabase remains the durable store. No keep-alive or paid fallback.

Status: implementation complete locally; 55 Python tests, PostgreSQL migration tests, JavaScript syntax checks and Chrome fixture checks passed. Official source benchmarks for Reliance, Infosys and Asian Paints passed and source pages were visually checked. A private backup of the current Supabase tables is under tmp/deployment.

No live migration, GitHub publication or Render deployment is confirmed. Live AI extraction and hosted acceptance remain release gates. The local application is available at http://127.0.0.1:8001/; database-dependent writes require migration 002 first.
