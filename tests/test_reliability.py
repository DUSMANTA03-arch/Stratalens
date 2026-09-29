import io
from datetime import date
from uuid import uuid4

import pdfplumber
import pytest
from fastapi.testclient import TestClient
import app
from analyst.reliability import (
    coverage,
    period_end,
    candidate_period,
    review_status,
    step_summary,
)
from analyst.brief_quality import enrich_brief
from analyst.evidence import sanitize_assessments
from analyst.workspace_api import ResearchInput
from analyst.financials import comparison
from analyst.exports import brief_pdf
from test_workspace import row


def test_coverage_calendar_and_unknown_period():
    company = {"id": "c", "data": {}}
    docs = [
        {
            "id": "d",
            "data": {
                "document_type": "annual_report",
                "status": "ready",
                "fiscal_period": "FY2024–25",
            },
        },
        {
            "id": "u",
            "data": {
                "title": "Unknown",
                "published_at": "2026-03-31",
                "status": "ready",
            },
        },
    ]
    result = coverage(company, docs, today=date(2025, 4, 1))
    assert len(result["rows"]) == 11
    assert result["rows"][0]["period_end"] == "2025-03-31"
    assert result["rows"][0]["status"] == "indexed"
    assert result["unassigned"][0]["id"] == "u"
    assert period_end("Q1 FY2025") == "2024-06-30"
    assert period_end("FY2023-24") == "2024-03-31"
    company["data"]["year_end_month"] = 12
    result = coverage(company, [], today=date(2026, 1, 1))
    assert result["rows"][0]["period_end"] == "2025-12-31"
    assert result["rows"][3]["period_end"] == "2025-12-31"
    assert candidate_period("Annual Report 2024-25") == {
        "fiscal_period": "FY2024-25",
        "period_type": "annual",
    }
    assert candidate_period("uploaded May 2025") == {}


def test_versioned_review_and_comparison_conflicts():
    d = {"review": {"status": "reviewed", "version": 1}}
    assert review_status(d) == "reviewed"
    d["observation_version"] = 2
    assert review_status(d) == "unreviewed"
    company = [{"id": "company1", "data": {}}]
    reviewed = row(review={"status": "reviewed", "version": 1})
    assert comparison([reviewed], company, reviewed_only=True)["rows"]
    assert not comparison([reviewed, row(value=1500)], company, reviewed_only=True)[
        "rows"
    ]
    reviewed["data"]["review"]["status"] = "excluded"
    assert not comparison([reviewed], company)["rows"]


def brief():
    claims = [
        {
            "id": str(i),
            "source_id": str(i),
            "entity": entity,
            "statement": f"{entity} revenue was {v} crore.",
            "quote": f"{entity} revenue was {v} crore.",
            "metric": "revenue",
            "metric_definition": "revenue from operations",
            "value": v,
            "unit": "INR crore",
            "period": "FY2025",
            "geography": "India",
            "segment": "total",
            "reporting_basis": "consolidated",
            "value_kind": "historical",
        }
        for i, (entity, v) in enumerate([("A", -20), ("B", 40)])
    ]
    return {
        "claims": claims,
        "sources": [
            {
                "id": c["id"],
                "text": c["quote"],
                "url": "https://example.com/" + c["id"],
                "title": "Report",
                "publisher": c["entity"],
            }
            for c in claims
        ],
        "report": {
            "title": "Test brief",
            "sections": [
                {
                    "heading": "Executive summary",
                    "findings": [
                        {
                            "text": "A reports a negative value; B reports a positive value.",
                            "claim_ids": ["0", "1"],
                        }
                    ],
                }
            ],
            "limitations": [],
        },
    }


def test_charts_require_compatible_cited_values():
    data = enrich_brief(brief())
    assert data["executive_takeaway"]["claim_ids"] == ["0", "1"]
    assert data["evidence_charts"][0]["points"][0]["value"] == -20
    assert data["positioning"][0]["cells"][1]["text"] == "Not established"
    for field, value in [
        ("period", "FY2024"),
        ("reporting_basis", "standalone"),
        ("value_kind", "target"),
        ("metric_definition", "gross revenue"),
        ("unit", "USD"),
        ("quote", "Not actually in source"),
        ("value", 300),
    ]:
        data = brief()
        data["claims"][1][field] = value
        assert not enrich_brief(data)["evidence_charts"], field
    data = brief()
    data["assessments"] = [{"claim_id": "1", "status": "disputed"}]
    assert not enrich_brief(data)["evidence_charts"]


def test_syndicated_disclosure_not_independent():
    data = brief()
    for c in data["claims"]:
        c["entity"] = "A"
        c["value"] = 40
        c["quote"] = "The company said revenue was 40 crore this year."
    assessments = [
        {
            "claim_id": "0",
            "status": "corroborated",
            "related_claim_ids": ["1"],
            "reason": "Two publishers",
        }
    ]
    assert (
        sanitize_assessments(assessments, data["claims"], data["sources"])[0]["status"]
        == "single-source"
    )


def test_progress_counts_unique_saved_records():
    data = brief()
    data["sources"] *= 2
    data["claims"] *= 2
    state = {"workflow": data, "observation_ids": ["a", "a"]}
    result = step_summary(state, [], "analyst")
    assert (
        result["claims"] == 2 and result["sources"] == 2 and result["observations"] == 1
    )
    assert result["at"] and result["step"] == "analyst"
    assert result["supported"] == 2
    assert result["gaps"]


def test_template_requires_matching_mode_and_documents():
    with pytest.raises(ValueError):
        ResearchInput(
            question="Analyze this company", mode="market", template_id="risk_review"
        )
    with pytest.raises(ValueError):
        ResearchInput(
            question="Analyze this company", mode="company", template_id="risk_review"
        )
    r = ResearchInput(question="Analyze this market", template_id="market_landscape")
    assert r.template_id == "market_landscape"


def test_new_endpoints_are_private():
    ident = str(uuid4())
    with TestClient(app.app) as client:
        for path in [
            "/api/v2/templates",
            "/api/v2/notes?target_id=" + ident,
            "/api/v2/companies/" + ident + "/coverage",
        ]:
            assert client.get(path).status_code == 401
        assert (
            client.post(
                "/api/v2/observations/" + ident + "/review", json={}
            ).status_code
            == 401
        )
        assert (
            client.patch("/api/v2/documents/" + ident + "/period", json={}).status_code
            == 401
        )


def test_rich_pdf_preserves_evidence_and_charts():
    data = enrich_brief(brief())
    with pdfplumber.open(io.BytesIO(brief_pdf(data))) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages)
    for expected in [
        "Executive takeaway",
        "Competitive positioning",
        "Not established",
        "historical",
        "-20",
        "Evidence appendix",
        "[0]",
    ]:
        assert expected in text


def test_public_brief_enrichment_uses_private_source_text_without_exposing_it():
    data = brief()
    sources = data["sources"]
    data["sources"] = [{k: v for k, v in s.items() if k != "text"} for s in sources]
    result = enrich_brief(data, sources)
    assert result["evidence_charts"]
    assert all("text" not in s for s in result["sources"])


def test_completed_steps_are_checkpointed_and_failed_retries_do_not_mutate(monkeypatch):
    import asyncio
    from test_workspace import MemoryStore
    import analyst.workspace_jobs as jobs

    job = {
        "id": "job",
        "kind": "research",
        "status": "queued",
        "state": {"question": "Compare fixture companies", "phase": "planner"},
        "model_calls": 0,
        "search_calls": 0,
    }

    class Provider:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    async def success(store, job, provider):
        state = copy_state(job["state"])
        state["phase"] = "researcher"
        state["workflow"] = {"sources": [{"id": "S1"}], "claims": []}
        return state, "queued", None, [], []

    async def fail(store, job, provider):
        raise jobs.PauseJob("Quota exhausted")

    def copy_state(state):
        import copy

        return copy.deepcopy(state)

    monkeypatch.setenv("GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(jobs, "BudgetProvider", Provider)
    monkeypatch.setattr(jobs, "market_research", success)
    store = MemoryStore(job)
    first = asyncio.run(jobs.advance(store, "job"))
    assert first["state"]["step_summaries"][0]["sources"] == 1
    assert first["state"]["step_summaries"][0]["step"] == "planner"
    monkeypatch.setattr(jobs, "market_research", fail)
    second = asyncio.run(jobs.advance(store, "job"))
    assert second["status"] == "paused"
    assert first["state"]["step_summaries"] == second["state"]["step_summaries"]


def test_company_positioning_cites_only_its_own_reports():
    data = {
        "company_labels": {"a": "Company A", "b": "Company B"},
        "document_companies": {"doc-a": "a"},
        "passages": [
            {
                "heading": "Financial performance",
                "text": "Reported results",
                "citations": [
                    {
                        "document_id": "doc-a",
                        "page": 25,
                        "quote": "Original result passage.",
                    }
                ],
            }
        ],
    }
    result = enrich_brief(data)
    assert result["positioning"][0]["cells"][0]["citations"][0]["page"] == 25
    assert result["positioning"][1]["cells"][0]["text"] == "Not established"


def test_coverage_failure_and_extraction_pause():
    doc = {
        "id": "d",
        "data": {
            "fiscal_period": "FY2025",
            "document_type": "annual_report",
            "status": "extracting",
            "indexed_pages": 40,
            "page_count": 40,
        },
    }
    jobs = [{"kind": "ingest", "status": "paused", "state": {"document_id": "d"}}]
    assert (
        coverage({"data": {}}, [doc], today=date(2025, 4, 1), jobs=jobs)["rows"][0][
            "status"
        ]
        == "extraction incomplete"
    )
    jobs[0]["status"] = "failed"
    assert (
        coverage({"data": {}}, [doc], today=date(2025, 4, 1), jobs=jobs)["rows"][0][
            "status"
        ]
        == "failed/unsupported"
    )
