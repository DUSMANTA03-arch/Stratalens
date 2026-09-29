"""Bounded chart-image ingestion and vision extraction; no image values are facts by default."""

import base64
import binascii
import hashlib
import io
from datetime import datetime, timezone

from PIL import Image, UnidentifiedImageError

from analyst.models import ChartExtraction, Claim, Source


def prepare_chart(chart):
    try:
        raw = base64.b64decode(chart.data, validate=True)
        if len(raw) > 1_000_000:
            raise ValueError("Each prepared chart must be at most 1 MB.")
        with Image.open(io.BytesIO(raw)) as image:
            expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[
                chart.media_type
            ]
            if image.format != expected:
                raise ValueError("Chart image content does not match its file type.")
            if image.width * image.height > 20_000_000 or min(image.size) < 40:
                raise ValueError(
                    "Chart dimensions must be at least 40 pixels and no more than 20 megapixels."
                )
            image.load()
            # Strip metadata and bound payload/context. Keep enough resolution for labels.
            image.thumbnail((1600, 1600))
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90)
        cleaned = output.getvalue()
        return {
            "filename": chart.filename,
            "media_type": "image/jpeg",
            "data": base64.b64encode(cleaned).decode(),
            "id": "Simg" + hashlib.sha256(cleaned).hexdigest()[:10],
        }
    except (
        binascii.Error,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("Chart is not a valid PNG, JPEG, or WebP image.") from exc


async def read_chart(provider, chart, question):
    extraction = await provider.vision(chart, question, ChartExtraction)
    source = Source(
        id=chart["id"],
        url=chart.get("origin_url", ""),
        title=extraction.title or chart["filename"],
        publisher=chart.get(
            "publisher", "User-provided image (original publisher unverified)"
        ),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        kind="image",
        text="",
        image_data=chart["data"],
        image_media_type=chart["media_type"],
        origin_page=chart.get("origin_page"),
    ).model_dump()
    claims = []
    for index, observation in enumerate(extraction.observations):
        data = observation.model_dump()
        if data["precision"] == "unknown":
            data["value"] = None
        if data["value"] is not None and data["precision"] == "approximate":
            data["statement"] = "Approximate visual estimate: " + data["statement"]
        claims.append(
            Claim(
                id=f"Cimg{chart['id'][4:]}_{index + 1}",
                source_id=source["id"],
                quote=data.pop("visual_evidence"),
                page=chart.get("origin_page"),
                evidence_kind="chart",
                **data,
            ).model_dump()
        )
    return (
        source,
        claims,
        [f"{chart['filename']}: {item}" for item in extraction.limitations],
    )
