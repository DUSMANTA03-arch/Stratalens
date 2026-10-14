import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app
from analyst.company_documents import candidate_matches, report_identity, validate_company_document
from analyst.documents import extract_pages
from analyst.workspace_jobs import ingest
from analyst.financials import FinancialExtraction
from analyst.workspace_api import get_store
from test_workspace import MemoryStore, pdf


LT = {"id": "lt", "data": {"name": "Larsen & Toubro Limited", "symbol": "LT", "isin": "INE018A01030"}}


def test_exchange_filename_and_issuer_reject_alok_for_lt():
    candidate = {"title": "Annual Report for the financial year 2025-26", "content": "Larsen & Toubro Limited", "url": "https://nsearchives.nseindia.com/annual_reports/AR_29475_ALOKINDS_2025_2026_A_21005951.pdf"}
    assert not candidate_matches(candidate, LT)
    assert not candidate_matches({"title": "JSW INFRASTRUCTURE LIMITED", "url": "https://nsearchives.nseindia.com/example.pdf"}, LT)
    assert candidate_matches({"title": "[PDF] LARSEN & TOUBRO - NSE", "url": "https://nsearchives.nseindia.com/example.pdf"}, LT)
    identity = report_identity(LT, [{"text": "Alok Industries Limited\nAnnual Report 2025-26\nCustomer: Larsen & Toubro Limited"}])
    assert identity["status"] == "mismatch" and identity["issuer"] == "Alok Industries Limited"
    assert report_identity(LT, [{"text": "LARSEN & TOUBRO LIMITED\nAnnual Report"}])["status"] == "matched"
    assert report_identity(LT, [{"text": "L&T\nIntegrated Annual Report"}])["status"] == "matched"
    assert report_identity(LT, [{"text": "Annual report 2025-26"}])["status"] == "unverified"
    reliance = {"id": "r", "data": {"name": "Reliance Industries Limited"}}
    assert report_identity(reliance, [{"text": "To The Members of Reliance Industries Limited Basis for Opinion\nReliance Petroleum Limited\nSubsidiary"}])["status"] == "matched"


def test_legacy_report_identity_rechecked_before_analysis():
    store = type("Store", (), {})()
    store.record = AsyncMock(return_value=LT)
    store.pages = AsyncMock(return_value=[{"text": "Alok Industries Limited\nAnnual Report"}])
    doc = {"id": "d", "data": {"company_id": "lt", "title": "Wrong report"}}
    with pytest.raises(ValueError, match="not verified"):
        asyncio.run(validate_company_document(store, doc))
    store.pages.return_value = [{"text": "Larsen & Toubro Limited\nAnnual Report"}]
    asyncio.run(validate_company_document(store, doc))


def test_duplicate_cannot_cross_company_boundary():
    job = {"state": {"phase": "inspect", "document_id": "doc"}}
    doc = {"id": "doc", "data": {"path": "report.pdf", "company_id": "company1", "size": 40_000_000}}
    store = MemoryStore(job, {"doc": doc}, pdf(1))
    store.records = AsyncMock(return_value=[{"id": "other", "data": {"company_id": "another-company"}}])
    with pytest.raises(ValueError, match="another company"):
        asyncio.run(ingest(store, job, None))


def test_text_indexing_does_not_run_unused_geometric_table_detection(monkeypatch):
    import pdfplumber.page
    monkeypatch.setattr(pdfplumber.page.Page, "extract_tables", lambda *a, **k: pytest.fail("Unused table detection ran"))
    result = extract_pages(pdf(25), "doc", 25)
    assert "Revenue from operations" in result[0]["text"]


def test_financial_plan_fetches_only_candidates_and_completes():
    job = {"state": {"phase": "financials", "document_id": "doc", "financial_page_numbers": [25], "next_financial_index": 0, "next_page": 1}}
    doc = {"id": "doc", "data": {"company_id": "lt", "page_count": 100, "status": "extracting"}}
    store = MemoryStore(job, {"doc": doc})
    store.selected_pages = AsyncMock(return_value=[{"page": 25, "text": "Statement of profit and loss: Revenue from operations 1250.00 1100.00 INR crore. Year ended 31 March 2025 and 31 March 2024."}])
    provider = type("Provider", (), {})()
    provider.generate = AsyncMock(return_value=FinancialExtraction(observations=[]))
    state, status, _, _, _ = asyncio.run(ingest(store, job, provider))
    assert status == "completed" and state["next_financial_index"] == 1
    store.selected_pages.assert_awaited_once_with("doc", [25])
    assert provider.generate.await_count == 1


def test_old_index_checkpoint_does_not_plan_only_remaining_pages():
    job = {"state": {"phase": "index", "document_id": "doc", "next_page": 25}}
    doc = {"id": "doc", "data": {"path": "report.pdf", "company_id": "lt", "page_count": 25}}
    store = MemoryStore(job, {"doc": doc}, pdf(25))
    state, _, _, _, _ = asyncio.run(ingest(store, job, None))
    assert state["phase"] == "financials" and "financial_page_numbers" not in state


def test_mismatched_report_cannot_be_owner_confirmed(owner_session):
    store = type("Store", (), {})()
    store.record = AsyncMock(return_value={"id": "d", "data": {"status": "identity_mismatch"}})
    app.app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app.app) as client:
            r = client.post("/api/v2/documents/22222222-2222-4222-8222-222222222222/confirm-company", json={"expected_updated_at": "2026-10-14T00:00:00Z", "reason": "Attempting to override a different issuer"})
            assert r.status_code == 422
    finally:
        app.app.dependency_overrides.pop(get_store, None)
