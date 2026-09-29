import asyncio
import base64
import io

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import app
from analyst.charts import prepare_chart, read_chart
from analyst.evidence import calculate, sanitize_assessments
from analyst.models import ChartInput


def image_input():
    buffer = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buffer, format="PNG")
    return ChartInput(filename="chart.png", media_type="image/png", data=base64.b64encode(buffer.getvalue()).decode())


def test_image_ingestion_and_metadata_stripping():
    chart = prepare_chart(image_input())
    assert chart["media_type"] == "image/jpeg"
    assert chart["id"].startswith("Simg")
    assert base64.b64decode(chart["data"]).startswith(b"\xff\xd8")


def test_image_type_and_content_validation():
    bad = image_input()
    bad.media_type = "image/webp"
    with pytest.raises(ValueError, match="file type"):
        prepare_chart(bad)


def test_pdf_graphical_page_candidate():
    from analyst.retrieval import pdf_chart_candidates
    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, format="PDF")
    candidates = pdf_chart_candidates(buffer.getvalue())
    assert len(candidates) == 1
    assert candidates[0]["origin_page"] == 1
    assert candidates[0]["media_type"] == "image/jpeg"
    bad = image_input()
    bad.data = base64.b64encode(b"not an image").decode()
    with pytest.raises(ValueError, match="not a valid"):
        prepare_chart(bad)


def test_chart_readings_are_distinct_from_quotations():
    class FakeVision:
        async def vision(self, chart, question, schema):
            return schema.model_validate({"title": "Test chart", "chart_type": "bar", "observations": [{
                "statement": "Alpha shows approximately 12 units.", "visual_evidence": "Alpha's bar is near 12 on the y axis.",
                "entity": "Alpha", "metric": "sales", "value": 12, "unit": "units", "period": "2025",
                "geography": "Test market", "segment": "Test", "precision": "approximate"}],
                "limitations": ["No printed data labels."]})
    source, claims, warnings = asyncio.run(read_chart(FakeVision(), prepare_chart(image_input()), "Compare sales"))
    assert source["kind"] == "image"
    assert claims[0]["evidence_kind"] == "chart"
    assert claims[0]["statement"].startswith("Approximate visual estimate:")
    assert warnings
    assessments = sanitize_assessments([], claims, [source])
    assert "Visual chart reading" in assessments[0]["reason"]
    second = dict(claims[0], id="second", period="2026", value=15)
    with pytest.raises(ValueError):
        calculate({"input_claim_ids": [claims[0]["id"], "second"], "operation": "growth", "label": "growth"}, claims + [second], [])


def test_request_size_limit():
    with TestClient(app) as client:
        response = client.post("/api/research", content=b"x" * 4_000_001, headers={"content-type": "application/json"})
        assert response.status_code == 413


def test_live_api_with_chart_and_mocked_providers(monkeypatch):
    import json
    import app as server
    import analyst.workflow as workflow
    from analyst.sample import SampleProviders, sample_sources

    class LiveFixtureProvider(SampleProviders):
        async def search(self, query):
            return [{"url": s["url"], "title": s["title"]} for s in sample_sources()]

        async def vision(self, chart, question, schema):
            return schema.model_validate({"title": "Attached fixture", "chart_type": "bar", "observations": [{
                "statement": "Beta reports 100 deliveries in 2025.", "visual_evidence": "Beta bar has the printed label 100.",
                "entity": "Beta", "metric": "deliveries", "value": 100, "unit": "vehicles", "period": "2025",
                "geography": "fictional market", "segment": "electric passenger cars", "precision": "printed"}],
                "limitations": ["Fixture model response; not actual vision."]})

    async def fixture_retrieve(item):
        return next(s for s in sample_sources() if s["url"] == item["url"])

    for key in ("GEMINI_API_KEY", "TAVILY_API_KEY", "APP_ACCESS_CODE"):
        monkeypatch.setenv(key, "fixture-only")
    monkeypatch.setattr(server, "Providers", LiveFixtureProvider)
    monkeypatch.setattr(workflow, "retrieve", fixture_retrieve)
    state = asyncio.run(workflow.build_workflow(LiveFixtureProvider()).ainvoke({
        'question':'Compare fictional companies','mode':'live','charts':[prepare_chart(image_input())]}))
    assert any(c['evidence_kind']=='chart' for c in state['claims'])
    assert any(s['kind']=='image' and s['image_data'] for s in state['sources'])
