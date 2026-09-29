import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import app as server
from analyst.evidence import calculate, clean_report, sanitize_assessments, verify_claims
from analyst.models import Extraction, Validation
from analyst.providers import ProviderError
from analyst.retrieval import extract_document, public_address
from analyst.source_quality import classify_source, quality_score
from analyst.sample import SampleProviders, sample_sources
from analyst.workflow import build_workflow

pytestmark = pytest.mark.usefixtures('owner_session')


def sample_state():
    return asyncio.run(build_workflow(SampleProviders()).ainvoke({"question": "Compare fictional companies", "mode": "sample"}))


def test_complete_sample_graph():
    state = sample_state()
    assert state["rounds"] == 1
    assert len(state["claims"]) == 4
    assert len(state["sources"]) == 3
    assert len(state["source_coverage"]) == 3
    assert all(item["status"] == "used" for item in state["source_coverage"])
    assert sum(a["status"] == "disputed" for a in state["assessments"]) == 2
    assert state["calculations"][0]["value"] == 25
    assert state["report"]["sections"]


def test_quotation_and_page_provenance():
    state = sample_state()
    claim = dict(state["claims"][0])
    claim["quote"] = "Invented evidence that never appeared in any source document."
    assert verify_claims([claim], state["sources"])[0] == []
    claim = dict(state["claims"][0], page=2)
    assert verify_claims([claim], state["sources"])[0] == []


def test_different_segments_are_not_contradictions():
    state = sample_state()
    claims = [dict(c) for c in state["claims"] if c["entity"] == "Meridian"]
    claims[1]["segment"] = "electric two-wheelers"
    assessments = sanitize_assessments([], claims, state["sources"])
    assert all(a["status"] == "single-source" for a in assessments)


def test_incompatible_and_disputed_calculations_rejected():
    state = sample_state()
    north = [dict(c) for c in state["claims"] if c["entity"] == "Northstar"]
    request = {"operation": "growth", "input_claim_ids": [c["id"] for c in north], "label": "Growth", "years": 1}
    north[1]["unit"] = "USD"
    with pytest.raises(ValueError, match="incompatible"):
        calculate(request, north, [])
    north[1]["unit"] = "vehicles"
    with pytest.raises(ValueError, match="non-disputed"):
        calculate(request, north, [{"claim_id": north[0]["id"], "status": "disputed"}])
    request["input_claim_ids"].reverse()
    with pytest.raises(ValueError, match="chronological"):
        calculate(request, north, [])


def test_unknown_citations_removed():
    report = {"title": "test", "sections": [{"heading": "Summary", "findings": [{"text": "Unfounded fact", "claim_ids": ["made-up"]}]}], "limitations": []}
    clean = clean_report(report, [])
    assert clean["sections"] == []
    assert clean["limitations"]


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://169.254.169.254", "http://[::1]/", "file:///etc/passwd", "https://user:password@example.com", "https://example.com:8080/"])
def test_private_and_unsafe_addresses_blocked(url):
    with pytest.raises(ValueError):
        asyncio.run(public_address(url))


def test_html_extraction():
    content = b'<html><head><title>Company report</title></head><body><article><h1>Annual results</h1><p>Northstar reported strong electric passenger car deliveries in the fictional market. Deliveries reached 15000 vehicles during calendar year 2025, compared with 12000 in 2024.</p></article></body></html>'
    text, tables, kind, date = extract_document(content, "text/html")
    assert "15000" in text
    assert kind == "html"


def test_stream_and_provider_configuration(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_CODE", "deprecated-test-only-code")
    with TestClient(server.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        # The obsolete live route cannot bypass durable budgets and checkpoints.
        assert client.post("/api/research", json={"question": "Analyze India's EV market"}).status_code == 410
        response = client.post("/api/research", json={"question": "A fictional company comparison", "mode": "sample"})
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [e["stage"] for e in events if e["type"] == "stage"] == ["planner", "researcher", "chart_reader", "analyst", "validator", "writer"]
        result = events[-1]["data"]
        assert result["mode"] == "sample" and not result["partial"]
        assert all("text" not in s for s in result["sources"])
        node_ids = {n["id"] for n in result["graph"]["nodes"]}
        assert all(e["from"] in node_ids and e["to"] in node_ids for e in result["graph"]["edges"])


def test_provider_failure_preserves_evidence(monkeypatch):
    class FailingProvider(SampleProviders):
        async def generate(self, role, instructions, data, schema):
            if schema is Validation:
                raise ProviderError("Gemini quota reached.")
            return await super().generate(role, instructions, data, schema)
    monkeypatch.setattr(server, "SampleProviders", FailingProvider)
    with TestClient(server.app) as client:
        response = client.post("/api/research", json={"question": "A fictional company comparison", "mode": "sample"})
        result = json.loads(response.text.splitlines()[-1])["data"]
        assert result["partial"]
        assert len(result["claims"]) == 4
        assert result["report"]["sections"]
        assert "Gemini quota reached." in result["warnings"]


def test_one_follow_up_loop_only():
    class FollowupProvider(SampleProviders):
        async def generate(self, role, instructions, data, schema):
            answer = await super().generate(role, instructions, data, schema)
            if schema is Validation:
                answer.follow_up_queries = ["Resolve delivery conflict"]
            return answer
    state = asyncio.run(build_workflow(FollowupProvider()).ainvoke({"question": "Compare fictional companies", "mode": "sample"}))
    assert state["rounds"] == 2
    assert state["follow_up_queries"] == []
    assert len(state["claims"]) == 4
    assert state["report"]


def test_whitespace_and_extra_fields_rejected():
    with TestClient(server.app) as client:
        assert client.post("/api/research", json={"question": " " * 30, "mode": "sample"}).status_code == 422
        assert client.post("/api/research", json={"question": "A fictional comparison", "mode": "sample", "api_key": "not-accepted"}).status_code == 422


def test_source_quality_prioritizes_authoritative_domains():
    assert classify_source("https://heavyindustry.gov.in/report.pdf") == ("government", "primary")
    assert classify_source("https://www.mckinsey.com/industries/automotive/report") == ("consulting", "expert")
    assert classify_source("https://example.com/ev-blog") == ("other", "unclassified")
    assert quality_score({"source_tier": "government"}) > quality_score({"source_tier": "news"})


def test_deadline_returns_partial_result(monkeypatch):
    class SlowProvider(SampleProviders):
        async def generate(self, *args):
            await asyncio.sleep(1)
            return await super().generate(*args)
    monkeypatch.setattr(server, "RUN_TIMEOUT", .02)
    monkeypatch.setattr(server, "SampleProviders", SlowProvider)
    with TestClient(server.app) as client:
        response = client.post("/api/research", json={"question": "A fictional comparison", "mode": "sample"})
        result = json.loads(response.text.splitlines()[-1])["data"]
        assert result["partial"]
        assert "Time limit" in result["warnings"][0]


def test_closing_stream_closes_provider(monkeypatch):
    instances = []

    class TrackedProvider(SampleProviders):
        closed = False
        def __init__(self):
            instances.append(self)
        async def close(self):
            self.closed = True

    monkeypatch.setattr(server, "SampleProviders", TrackedProvider)

    async def exercise():
        response = await server.research(server.ResearchRequest(question="A fictional comparison", mode="sample"), "")
        stream = response.body_iterator
        await anext(stream)
        await stream.aclose()

    asyncio.run(exercise())
    assert instances[0].closed
