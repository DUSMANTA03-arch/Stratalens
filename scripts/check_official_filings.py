"""Opt-in source benchmark. Downloads official PDFs; no AI calls or workspace writes."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyst.documents import inspect_pdf, extract_pages
from analyst.financials import (
    Observation,
    FinancialExtraction,
    verify_observations,
    comparison,
    numbers,
)
from analyst.retrieval import download
from decimal import Decimal


async def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "tmp/official-filings"
    out.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(
        (root / "tests/fixtures/official_financial_benchmarks.json").read_text()
    )
    records = []
    companies = []
    results = []
    for item in fixtures:
        target = out / (item["id"] + ".pdf")
        if target.exists():
            raw = target.read_bytes()
        else:
            raw, _, _ = await download(item["url"], max_bytes=40_000_000)
            target.write_bytes(raw)
        info = inspect_pdf(raw)
        pages = extract_pages(raw, item["id"], item["page"])
        page = pages[0]
        lines = page["text"].splitlines()
        line = next(
            line for line in lines if Decimal(str(item["value"])) in numbers(line)
        )
        observation = Observation(
            metric="revenue",
            label="Revenue from operations",
            value=item["value"],
            currency="INR",
            scale="crore",
            period_start="2024-04-01",
            period_end="2025-03-31",
            period_type="annual",
            basis="consolidated",
            definition="group_total",
            page=item["page"],
            quote=line,
            restated=False,
        )
        accepted, warnings = verify_observations(
            FinancialExtraction(observations=[observation]),
            pages,
            {"id": item["id"], "data": {"company_id": item["id"]}},
        )
        assert len(accepted) == 1 and not warnings
        records += accepted
        companies.append({"id": item["id"], "data": {"name": item["company"]}})
        (out / (item["id"] + "-page.txt")).write_text(page["text"])
        results.append(
            {
                **item,
                "checksum": info["checksum"],
                "page_count": info["page_count"],
                "quote": line,
            }
        )
        print(
            item["company"]
            + ": source benchmark matched on PDF page "
            + str(item["page"])
        )
    result = comparison(records, companies)
    assert len(result["rows"][0]["values"]) == 3
    assert not comparison(records, companies, reviewed_only=True)["rows"]
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(
        "Three-company deterministic benchmark passed. Live model extraction and hosted acceptance are separate checks."
    )


if __name__ == "__main__":
    asyncio.run(main())
