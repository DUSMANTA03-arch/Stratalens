import asyncio
import copy
import io
from uuid import uuid4
from unittest.mock import AsyncMock

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

import app as server
from analyst.documents import inspect_pdf, extract_pages
from analyst.exports import brief_pdf
from analyst.financials import (
    FinancialExtraction,
    Observation,
    comparison,
    verify_observations,
)
from analyst.workspace_jobs import DocumentAnswer, checked_answer, advance, PauseJob


def pdf(pages=25):
    out = io.BytesIO()
    c = canvas.Canvas(out)
    for i in range(pages):
        c.drawString(
            40,
            700,
            f"Page {i + 1}: Revenue from operations 1,250.00 INR crore. Company report and financial results.",
        )
        c.showPage()
    c.save()
    return out.getvalue()


def observation(**values):
    return {
        "metric": "revenue",
        "label": "Revenue from operations",
        "value": 1250.0,
        "currency": "INR",
        "scale": "crore",
        "period_start": "2024-04-01",
        "period_end": "2025-03-31",
        "period_type": "annual",
        "basis": "consolidated",
        "definition": "group_total",
        "page": 25,
        "quote": "Revenue from operations 1,250.00 INR crore.",
        "restated": False,
        **values,
    }


def row(company="company1", **values):
    return {
        "id": str(uuid4()),
        "data": {
            "company_id": company,
            "document_id": str(uuid4()),
            "published_at": "2025-05-01",
            **observation(**values),
        },
    }


def test_auth_required_for_every_private_surface():
    with TestClient(server.app) as c:
        for path in [
            "/api/v2/companies",
            "/api/v2/documents",
            "/api/v2/jobs",
            "/api/v2/settings",
            "/api/v2/briefs",
            "/api/v2/conversations",
            "/api/v2/observations?company_id=" + str(uuid4()),
        ]:
            assert c.get(path).status_code == 401, path
        assert (
            c.post(
                "/api/v2/research", json={"question": "Analyze a company"}
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/api/research", json={"question": "Analyze a company", "mode": "live"}
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/api/auth/login",
                headers={"Origin": "https://evil.example"},
                json={"email": "owner@example.com", "password": "not-real"},
            ).status_code
            == 403
        )
        assert c.get("/api/sample").json()["mode"] == "sample"
        assert "live_ready" not in c.get("/api/health").json()


def test_unknown_account_rejected(monkeypatch):
    from analyst import auth

    monkeypatch.setattr(
        auth, "auth_request", AsyncMock(return_value={"id": str(uuid4())})
    )
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake")
    monkeypatch.setattr(auth.Store, "request", AsyncMock(return_value=[]))
    with TestClient(server.app) as c:
        c.cookies.set("sl_access", "fake")
        assert c.get("/api/v2/documents").status_code == 403


def test_full_document_page_25_and_pdf_limits():
    raw = pdf()
    assert inspect_pdf(raw)["page_count"] == 25
    pages = extract_pages(raw, "doc", 25)
    assert len(pages) == 1 and "Page 25" in pages[0]["text"]
    with pytest.raises(ValueError):
        inspect_pdf(b"not a pdf")
    with pytest.raises(ValueError):
        inspect_pdf(b"%PDF" + b"x" * 40_000_000)
    with pytest.raises(ValueError):
        inspect_pdf(pdf(601))


def test_financial_provenance_rejects_invented_numbers_and_pages():
    document = {"id": "doc", "data": {"company_id": "company1"}}
    pages = [{"page": 25, "text": observation()["quote"]}]
    valid = FinancialExtraction(observations=[Observation(**observation())])
    accepted, _ = verify_observations(valid, pages, document)
    assert len(accepted) == 1
    for change in (
        {"value": 999},
        {"page": 24},
        {"quote": "A fabricated report says 1250 INR crore."},
    ):
        bad = FinancialExtraction(observations=[Observation(**observation(**change))])
        assert verify_observations(bad, pages, document)[0] == []
    negative = FinancialExtraction(
        observations=[
            Observation(
                **observation(
                    value=-1250, quote="Revenue from operations (1,250.00) INR crore."
                )
            )
        ]
    )
    assert verify_observations(
        negative, [{"page": 25, "text": negative.observations[0].quote}], document
    )[0]


def test_financial_comparison_units_basis_ytd_restatement():
    companies = [
        {"id": c, "data": {"name": c, "sector": "non_financial"}}
        for c in ["company1", "company2"]
    ]
    rows = [
        row(),
        row("company2", value=12500, scale="million"),
        row(metric="net_profit", value=-125),
        row(value=1000, period_start="2023-04-01", period_end="2024-03-31"),
        row(value=99999, basis="standalone"),
        row("company2", value=700, currency="USD"),
    ]
    result = comparison(rows, companies)
    latest = next(
        r
        for r in result["rows"]
        if r["metric"] == "revenue" and r["period_end"] == "2025-03-31"
    )
    assert (
        latest["values"]["company1"]["value"]
        == latest["values"]["company2"]["value"]
        == 1250
    )
    assert any(
        d["label"] == "Net profit margin" and d["value"] == -10
        for d in result["derived"]
    )
    assert any(d["value"] == 25 and "growth" in d["label"] for d in result["derived"])
    conflict = row(value=1300)
    assert not any(
        r["metric"] == "revenue"
        and r["period_end"] == "2025-03-31"
        and "company1" in r["values"]
        for r in comparison(rows + [conflict], companies)["rows"]
    )
    conflict["data"].update(restated=True, published_at="2026-05-01")
    result = comparison(rows + [conflict], companies)
    assert (
        next(
            r
            for r in result["rows"]
            if r["metric"] == "revenue" and r["period_end"] == "2025-03-31"
        )["values"]["company1"]["value"]
        == 1300
    )
    quarterly = row(
        period_start="2024-07-01", period_end="2024-09-30", period_type="quarterly"
    )
    ytd = row(
        "company2",
        period_start="2024-04-01",
        period_end="2024-09-30",
        period_type="ytd",
    )
    assert all(
        len(r["values"]) == 1 for r in comparison([quarterly, ytd], companies)["rows"]
    )


def test_specialized_sectors_and_invalid_periods():
    assert not comparison([row()], [{"id": "company1", "data": {"sector": "bank"}}])[
        "rows"
    ]
    with pytest.raises(ValueError):
        Observation(**observation(period_type="quarterly"))
    with pytest.raises(ValueError):
        Observation(**observation(period_end="unknown"))
    with pytest.raises(ValueError):
        Observation(**observation(metric="assets"))


def test_chat_citations_are_bound_to_selected_page():
    answer = DocumentAnswer(
        title="Answer",
        passages=[
            {
                "heading": "Revenue",
                "text": "Revenue increased.",
                "citations": [
                    {"document_id": "doc", "page": 25, "quote": observation()["quote"]}
                ],
            }
        ],
        limitations=[],
        follow_up_questions=[],
    )
    assert checked_answer(
        answer, [{"document_id": "doc", "page": 25, "text": observation()["quote"]}]
    )["passages"]
    assert not checked_answer(
        answer, [{"document_id": "other", "page": 25, "text": observation()["quote"]}]
    )["passages"]
    assert not checked_answer(
        answer, [{"document_id": "doc", "page": 24, "text": observation()["quote"]}]
    )["passages"]


def test_pdf_preserves_unicode_and_paginated_citations():
    result = {
        "title": "Review — ₹125 crore",
        "question": "What changed?",
        "passages": [
            {
                "heading": "Financials",
                "text": "Revenue ₹125 crore — compared with ₹100 crore. " * 35,
                "citations": [
                    {
                        "document_id": "report",
                        "page": 25,
                        "quote": "Company revenue was ₹125 crore.",
                    }
                ],
            }
            for _ in range(8)
        ],
        "limitations": ["Source claims require review."],
    }
    raw = brief_pdf(result)
    with pdfplumber.open(io.BytesIO(raw)) as doc:
        assert len(doc.pages) > 1
        text = "\n".join(p.extract_text() for p in doc.pages)
        assert "₹125" in text and "—" in text and "page 25" in text


class MemoryStore:
    owner = "owner"

    def __init__(self, job, documents=None, raw=None):
        self.job = copy.deepcopy(job)
        self.documents = documents or {}
        self.raw = raw
        self.calls = []
        self.pages_saved = []
        self.records_saved = []

    async def rpc(self, name, **kw):
        self.calls.append((name, kw))
        if name == "claim_workspace_job":
            if self.job.get("lease_token") or self.job["status"] in [
                "completed",
                "cancelled",
            ]:
                return None
            self.job.update(lease_token=kw["token"], status="running")
            return copy.deepcopy(self.job)
        if name == "commit_workspace_job":
            if self.job.get("lease_token") != kw["token"]:
                return False
            self.job.update(
                state=kw["state"],
                status=kw["status"],
                result=kw.get("result"),
                error=kw.get("error"),
                lease_token=None,
            )
            self.pages_saved += kw.get("pages", [])
            self.records_saved += kw.get("records", [])
            for r in kw.get("records", []):
                if r["kind"] == "document":
                    self.documents[r["id"]] = r
            return True
        return True

    async def record(self, kind, id):
        return self.documents[id]

    async def records(self, kind, **kw):
        return []

    async def blob(self, path):
        return self.raw

    async def pdf_blob(self, path):
        return self.raw

    async def cache_pdf(self, *args):
        pass

    async def jobs(self, id=None):
        return [copy.deepcopy(self.job)]

    async def upload(self, *args):
        pass


def test_ingestion_checkpoint_resume_and_duplicate_advance():
    job = {
        "id": "job",
        "kind": "ingest",
        "status": "queued",
        "state": {"document_id": "doc", "phase": "inspect"},
        "model_calls": 0,
        "search_calls": 0,
    }
    doc = {
        "id": "doc",
        "kind": "document",
        "data": {"path": "report.pdf", "company_id": "company1", "size": 40_000_000},
    }
    store = MemoryStore(job, {"doc": doc}, pdf())

    async def exercise():
        result = await advance(store, "job")
        assert result["state"]["phase"] == "index"
        result = await advance(store, "job")
        assert result["state"]["next_page"] == 9
        result = await advance(store, "job")
        assert result["state"]["next_page"] == 17
        result = await advance(store, "job")
        assert result["state"]["next_page"] == 25
        result = await advance(store, "job")
        assert result["state"]["phase"] == "financials"
        assert len(store.pages_saved) == 25
        store.job["lease_token"] = "other-tab"
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await advance(store, "job")
        assert exc.value.status_code == 409

    asyncio.run(exercise())


def test_quota_pause_preserves_checkpoint(monkeypatch):
    import analyst.workspace_jobs as jobs

    job = {
        "id": "job",
        "kind": "research",
        "status": "queued",
        "state": {"question": "Test a research question", "phase": "planner"},
        "model_calls": 3,
        "search_calls": 0,
    }

    class Provider:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    async def fail(*args):
        raise PauseJob("Quota reached.")

    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(jobs, "BudgetProvider", Provider)
    monkeypatch.setattr(jobs, "market_research", fail)
    store = MemoryStore(job)
    result = asyncio.run(advance(store, "job"))
    assert result["status"] == "paused" and result["state"] == job["state"]
    assert result["error"] == "Quota reached."


def test_document_body_and_company_selection_validation(owner_session):
    with TestClient(server.app) as c:
        assert (
            c.post(
                "/api/v2/research",
                json={"question": "Analyze the company", "mode": "company"},
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/api/v2/chat", json={"question": "Revenue?", "document_ids": []}
            ).status_code
            == 422
        )


def test_duplicate_and_scanned_document_statuses():
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(output, format="PDF")
    job = {
        "id": "job",
        "kind": "ingest",
        "status": "queued",
        "state": {"document_id": "doc", "phase": "inspect"},
        "model_calls": 0,
        "search_calls": 0,
    }
    doc = {
        "id": "doc",
        "kind": "document",
        "data": {"path": "report.pdf", "company_id": "company1", "size": 40_000_000},
    }

    async def exercise():
        store = MemoryStore(job, {"doc": copy.deepcopy(doc)}, output.getvalue())
        await advance(store, "job")
        result = await advance(store, "job")
        assert (
            result["status"] == "completed"
            and store.documents["doc"]["data"]["status"] == "unsupported"
        )
        duplicate = MemoryStore(job, {"doc": copy.deepcopy(doc)}, pdf(1))
        duplicate.records = AsyncMock(return_value=[{"id": "already-present"}])
        duplicate.remove_blob = AsyncMock()
        result = await advance(duplicate, "job")
        assert result["result"] == {"document_id": "already-present", "duplicate": True}
        duplicate.remove_blob.assert_awaited_once()

    asyncio.run(exercise())


def test_job_response_never_exposes_workflow_or_lease():
    from analyst.workspace_api import job_public

    public = job_public(
        {
            "id": "job",
            "lease_token": "secret-fence",
            "state": {
                "question": "question",
                "workflow": {
                    "sources": [{"image_data": "private-bytes", "text": "source text"}]
                },
                "chart_paths": [{"path": "private/object"}],
            },
            "result": None,
        }
    )
    assert (
        "lease_token" not in public
        and "workflow" not in public["state"]
        and "chart_paths" not in public["state"]
    )


def test_supabase_signed_url_contract(monkeypatch):
    from analyst.workspace_store import Store

    monkeypatch.setenv("SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")

    async def exercise():
        store = Store("owner")
        store.request = AsyncMock(
            return_value={
                "url": "/object/upload/sign/reports/owner/report.pdf?token=fixture"
            }
        )
        assert (
            await store.signed_upload("owner/report.pdf")
            == "https://fixture.supabase.co/storage/v1/object/upload/sign/reports/owner/report.pdf?token=fixture"
        )
        store.request = AsyncMock(
            return_value={
                "signedURL": "/object/sign/reports/owner/report.pdf?token=fixture"
            }
        )
        assert (await store.signed_url("owner/report.pdf")).startswith(
            "https://fixture.supabase.co/storage/v1/object/sign/"
        )

    asyncio.run(exercise())


def test_durable_market_stages_preserve_legacy_evidence():
    from analyst.workspace_jobs import market_research
    from analyst.sample import SampleProviders

    async def exercise():
        provider = SampleProviders()
        job = {
            "id": "job",
            "state": {
                "question": "Compare fictional companies",
                "workflow": {
                    "question": "Compare fictional companies",
                    "mode": "sample",
                    "charts": [],
                },
            },
        }
        phases = []
        for _ in range(10):
            phases.append(job["state"].get("phase", "planner"))
            state, status, result, records, pages = await market_research(
                None, job, provider
            )
            job["state"] = state
            if status == "completed":
                break
        assert phases == [
            "planner",
            "researcher",
            "chart_reader",
            "analyst",
            "validator",
            "writer",
        ]
        assert len(result["claims"]) == 4 and len(result["sources"]) == 3
        assert result["calculations"][0]["value"] == 25
        assert records[0]["kind"] == "brief"

    asyncio.run(exercise())


def test_document_metadata_can_be_omitted():
    from analyst.workspace_api import DocumentInput

    payload = dict(company_id="11111111-1111-4111-8111-111111111111",
                   title="Annual report", document_type="annual_report")
    document = DocumentInput(**payload)
    assert document.fiscal_period == ""
    assert document.published_at is None
    assert DocumentInput(**payload, fiscal_period="").fiscal_period == ""
