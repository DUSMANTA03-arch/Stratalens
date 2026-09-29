import asyncio
import base64
import hashlib
import io
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import pdfplumber
import trafilatura

from analyst.models import Source
from analyst.source_quality import classify_source


def canonical_url(url):
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


async def public_address(url):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("Only public HTTP(S) source URLs are allowed.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Non-standard source port blocked.")
    infos = await asyncio.get_running_loop().getaddrinfo(
        parts.hostname, port, type=socket.SOCK_STREAM
    )
    addresses = {info[4][0] for info in infos}
    if not addresses or any(
        not ipaddress.ip_address(addr).is_global for addr in addresses
    ):
        raise ValueError("Non-public source destination blocked.")
    return sorted(addresses)[0]


async def download(url, max_bytes=10 * 1024 * 1024):
    # Connect to the validated IP itself to prevent a DNS-rebinding race. TLS
    # SNI and the HTTP Host header retain the original public hostname.
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        for _ in range(4):
            address = await public_address(url)
            parsed = httpx.URL(url)
            target = parsed.copy_with(host=address)
            async with client.stream(
                "GET",
                target,
                headers={
                    "Host": parsed.netloc.decode(),
                    "User-Agent": "ResearchAnalyst/0.1 (public-source research)",
                },
                extensions={"sni_hostname": parsed.host},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError("Source exceeds the download size limit.")
                return bytes(content), response.headers.get("content-type", ""), url
    raise ValueError("Too many redirects.")


def extract_document(content, content_type):
    if content.startswith(b"%PDF") or "application/pdf" in content_type:
        texts, tables = [], []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for number, page in enumerate(pdf.pages[:20], 1):
                texts.append(f"[Page {number}]\n{(page.extract_text() or '')[:7000]}")
                # Only simple machine-readable tables. Preserve cells, don't infer.
                if len(tables) < 5:
                    for table in page.extract_tables()[:2]:
                        tables.append(
                            [
                                [str(cell or "")[:300] for cell in row[:12]]
                                for row in table[:30]
                            ]
                        )
        return "\n".join(texts)[:22000], tables[:5], "pdf", "Unknown"
    if content_type and not any(
        t in content_type for t in ("html", "text/plain", "xhtml")
    ):
        raise ValueError("Unsupported source type.")
    document = trafilatura.bare_extraction(
        content, include_tables=True, include_comments=False
    )
    if document is None:
        raise ValueError("No readable source text.")
    text = document.text if hasattr(document, "text") else document.get("text", "")
    published = getattr(document, "date", None) or "Unknown"
    return (text or "")[:22000], [], "html", published


async def retrieve(item):
    content, kind, final_url = await asyncio.wait_for(download(item["url"]), 18)
    text, tables, source_kind, published = await asyncio.wait_for(
        asyncio.to_thread(extract_document, content, kind), 12
    )
    charts = []
    if source_kind == "pdf":
        try:
            charts = await asyncio.wait_for(
                asyncio.to_thread(pdf_chart_candidates, content), 8
            )
        except (ValueError, OSError, TimeoutError):
            charts = []
    if len(text.strip()) < 80 and not charts:
        raise ValueError(
            "Source has too little readable text (possibly scanned or blocked)."
        )
    normalized = canonical_url(final_url)
    tier, quality = classify_source(normalized)
    source = Source(
        id="S" + hashlib.sha256(normalized.encode()).hexdigest()[:10],
        url=normalized,
        title=item.get("title") or urlsplit(normalized).hostname,
        publisher=urlsplit(normalized).hostname,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        published_at=published,
        text=text,
        tables=tables,
        kind=source_kind,
        source_tier=tier,
        source_quality=quality,
    ).model_dump()
    for chart in charts:
        chart.update(
            origin_url=normalized,
            publisher=source["publisher"],
            filename=f"{source['title']} · page {chart['origin_page']}",
        )
    source["chart_candidates"] = charts
    return source


def pdf_chart_candidates(content):
    """Render at most one likely graphical page per PDF; vision decides if it is a chart."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages[:20], 1):
            if page.width > 1800 or page.height > 1800:
                continue
            if not page.images and len(page.rects) + len(page.curves) < 6:
                continue
            image = page.to_image(resolution=110).original.convert("RGB")
            image.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            raw = buffer.getvalue()
            if len(raw) > 900_000:
                continue
            return [
                {
                    "id": "Simg" + hashlib.sha256(raw).hexdigest()[:10],
                    "data": base64.b64encode(raw).decode(),
                    "media_type": "image/jpeg",
                    "origin_page": number,
                }
            ]
    return []
