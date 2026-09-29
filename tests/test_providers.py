import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from analyst.models import Plan, Extraction, Validation, Report, ChartExtraction
from analyst.providers import Providers, gemini_schema


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
