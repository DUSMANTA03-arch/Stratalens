import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest

from analyst.models import Plan, Extraction, Validation, Report, ChartExtraction
from analyst.providers import Providers, ProviderError, gemini_schema
from analyst.financials import FinancialExtraction


def test_gemini_uses_compatible_schema_transport(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-not-a-real-key")

    async def exercise():
        provider = Providers()
        value = {"scope": "Test", "assumptions": [], "questions": ["What changed?"], "queries": ["test market"]}
        mocked = AsyncMock(return_value=SimpleNamespace(text=json.dumps(value)))
        try:
            with patch.object(provider.client.aio.models, "generate_content", mocked):
                result = await provider.generate("planner", "Plan research", {}, Plan)
                config = mocked.call_args.kwargs["config"]
                assert config.response_schema == gemini_schema(Plan)
                assert config.response_json_schema is None
                assert result.queries == ["test market"]
        finally:
            await provider.close()

    asyncio.run(exercise())


def test_nested_schemas_inline_references_and_remove_unsupported_fields():
    for model in (Plan, Extraction, Validation, Report, ChartExtraction):
        schema = gemini_schema(model).model_dump(exclude_none=True)
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text
        assert "additional_properties" not in text
    schema = gemini_schema(Extraction)
    assert schema.properties["claims"].items.properties["value"].nullable


def test_financial_schema_preserves_original_label_instructions():
    properties = gemini_schema(FinancialExtraction).properties["observations"].items.properties
    assert "Original financial statement row label" in properties["label"].description
    assert "group_total" in properties["definition"].description


@pytest.mark.parametrize("failure,expected", [
    (TimeoutError(), "timed out"),
    (None, "invalid structured evidence"),
])
def test_provider_failures_are_distinct_and_do_not_retry(monkeypatch, failure, expected):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only")
    async def exercise():
        provider = Providers()
        mocked = AsyncMock(side_effect=failure) if failure else AsyncMock(return_value=SimpleNamespace(text='{"scope":"incomplete"}'))
        try:
            with patch.object(provider.client.aio.models, "generate_content", mocked):
                with pytest.raises(ProviderError, match=expected):
                    await provider.generate("planner", "Plan research", {}, Plan)
                assert mocked.await_count == 1
        finally:
            await provider.close()
    asyncio.run(exercise())
