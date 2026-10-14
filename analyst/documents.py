"""Incremental PDF reading: no first-20-page or global text truncation."""

import hashlib
import io

import pdfplumber

MAX_BYTES = 40_000_000
MAX_PAGES = 600
PAGE_BATCH = 8


def inspect_pdf(content):
    if len(content) > MAX_BYTES or not content.startswith(b"%PDF"):
        raise ValueError("Upload a PDF no larger than 40 MB.")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            count = len(pdf.pages)
            if not 1 <= count <= MAX_PAGES:
                raise ValueError("PDFs must contain between 1 and 600 pages.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "This PDF is damaged or encrypted. Upload an unlocked copy."
        ) from exc
    return {
        "page_count": count,
        "size": len(content),
        "checksum": hashlib.sha256(content).hexdigest(),
    }


def extract_pages(content, document_id, start, count=PAGE_BATCH):
    pages = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for index in range(start - 1, min(start - 1 + count, len(pdf.pages))):
            page = pdf.pages[index]
            text = page.extract_text(layout=False) or ""
            # Statement rows remain in page text. Geometric table detection is
            # expensive and its cell arrays are not consumed by this workflow.
            tables = []
            pages.append(
                {
                    "document_id": document_id,
                    "page": index + 1,
                    "text": text[:60000],
                    "tables": tables,
                    "truncated": len(text) > 60000,
                }
            )
            page.close()
    return pages


def financial_page(page):
    text = page["text"].lower()
    return (
        any(
            term in text
            for term in (
                "balance sheet",
                "financial results",
                "statement of profit",
                "cash flows",
                "cash flow statement",
                "revenue from operations",
                "earnings per share",
            )
        )
        and sum(c.isdigit() for c in text) > 20
    )
