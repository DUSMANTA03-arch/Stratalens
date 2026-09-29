"""Unicode PDF export from saved evidence, never from browser-supplied HTML."""

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, LongTable, TableStyle


def brief_pdf(data):
    font = Path(__file__).resolve().parent.parent / "assets/fonts/NotoSans-Regular.ttf"
    if "NotoSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NotoSans", str(font)))
    normal = ParagraphStyle(
        "Body",
        fontName="NotoSans",
        fontSize=9,
        leading=14,
        spaceAfter=9,
        wordWrap="CJK",
    )
    heading = ParagraphStyle(
        "Heading", parent=normal, fontSize=14, leading=20, spaceBefore=14, spaceAfter=9
    )
    title = ParagraphStyle(
        "Title", parent=heading, fontSize=24, leading=31, spaceAfter=18
    )
    small = ParagraphStyle("Small", parent=normal, fontSize=7, leading=10)

    def p(text, style=normal):
        return Paragraph(escape(str(text)), style)

    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=(595, 842),
        rightMargin=42,
        leftMargin=42,
        topMargin=45,
        bottomMargin=45,
        title=data.get("title")
        or data.get("report", {}).get("title", "StrataLens brief"),
    )
    story = [
        p("STRATALENS / RESEARCH BRIEF", small),
        p(
            data.get("title") or data.get("report", {}).get("title", "Research brief"),
            title,
        ),
    ]
    if data.get("mode") == "sample":
        story.append(p("SYNTHETIC DEMONSTRATION - NOT REAL MARKET DATA"))
    story.append(p(data.get("question", "")))
    takeaway = data.get("executive_takeaway")
    if takeaway:
        refs = ", ".join(takeaway.get("claim_ids", [])) or "; ".join(
            f"Document {c['document_id']}, page {c['page']}"
            for c in takeaway.get("citations", [])
        )
        story.extend(
            [p("Executive takeaway", heading), p(takeaway["text"] + " [" + refs + "]")]
        )
    if data.get("positioning"):
        story.append(p("Competitive positioning", heading))
        rows = [
            [
                p(x, small)
                for x in ["Entity", "Disclosed scale", "Capabilities", "Constraints"]
            ]
        ]
        for row in data["positioning"]:
            rows.append(
                [p(row["entity"], small)]
                + [
                    p(
                        cell["text"]
                        + (
                            " [" + ", ".join(cell["claim_ids"]) + "]"
                            if cell["claim_ids"]
                            else " ["
                            + "; ".join(
                                f"Document {c['document_id']}, page {c['page']}"
                                for c in cell.get("citations", [])
                            )
                            + "]"
                            if cell.get("citations")
                            else ""
                        ),
                        small,
                    )
                    for cell in row["cells"]
                ]
            )
        grid = LongTable(rows, colWidths=[95, 139, 139, 138], repeatRows=1)
        grid.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1eb")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(grid)
    from reportlab.graphics.shapes import Drawing, Rect, String, Line

    for chart in data.get("evidence_charts", []):
        story.append(
            p(
                f"{chart['metric']} · {chart['period']} · {chart['unit']} · {chart['reporting_basis']} · {chart['value_kind']}",
                heading,
            )
        )
        points = chart["points"]
        drawing = Drawing(510, len(points) * 28 + 10)
        lo = min(0, *[point["value"] for point in points])
        hi = max(0, *[point["value"] for point in points])
        scale = lambda value: 150 + (value - lo) / (hi - lo or 1) * 240
        zero = scale(0)
        drawing.add(
            Line(
                zero, 0, zero, len(points) * 28, strokeColor=colors.HexColor("#aabbab")
            )
        )
        for i, point in enumerate(points):
            y = (len(points) - 1 - i) * 28 + 5
            x = scale(point["value"])
            drawing.add(
                String(0, y + 5, point["entity"][:24], fontName="NotoSans", fontSize=8)
            )
            drawing.add(
                Rect(
                    min(zero, x),
                    y,
                    abs(x - zero),
                    19,
                    fillColor=colors.HexColor("#205d48"),
                    strokeColor=None,
                )
            )
            drawing.add(
                String(405, y + 5, str(point["value"]), fontName="NotoSans", fontSize=8)
            )
        story.append(drawing)
        for point in points:
            story.append(
                p(
                    f"{point['entity']}: {point['value']} {chart['unit']} [{', '.join(point['claim_ids'])}]",
                    small,
                )
            )
    if data.get("chart_note"):
        story.append(p(data["chart_note"], small))
    appendix = []
    if "passages" in data:
        for passage in data["passages"]:
            if passage["text"] != (takeaway or {}).get("text"):
                story.extend([p(passage["heading"], heading), p(passage["text"])])
            for cite in passage["citations"]:
                number = len(appendix) + 1
                story.append(
                    p(
                        f"[{number}] Document {cite['document_id']} · page {cite['page']}",
                        small,
                    )
                )
                appendix.append(
                    f"[{number}] {cite['quote']}\nDocument {cite['document_id']}, page {cite['page']}"
                )
        limitations = data.get("limitations", [])
    else:
        for section in data.get("report", {}).get("sections", []):
            findings = [
                f
                for f in section["findings"]
                if f["text"] != (takeaway or {}).get("text")
            ]
            if not findings:
                continue
            story.append(p(section["heading"], heading))
            for finding in findings:
                story.append(
                    p(finding["text"] + " [" + ", ".join(finding["claim_ids"]) + "]")
                )
        numeric = [c for c in data.get("claims", []) if c.get("value") is not None]
        if numeric:
            story.append(p("Reported figures", heading))
            table = [
                [
                    p(x, small)
                    for x in ["Entity / metric", "Period", "Value", "Evidence"]
                ]
            ]
            table += [
                [
                    p(c["entity"] + " / " + c["metric"], small),
                    p(c["period"], small),
                    p(str(c["value"]) + " " + c["unit"], small),
                    p(c["id"], small),
                ]
                for c in numeric
            ]
            grid = LongTable(
                table, colWidths=[200, 65, 125, 121], repeatRows=1, hAlign="LEFT"
            )
            grid.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1eb")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        (
                            "LINEBELOW",
                            (0, 0),
                            (-1, -1),
                            0.3,
                            colors.HexColor("#d7e1da"),
                        ),
                    ]
                )
            )
            story.append(grid)
        for c in data.get("claims", []):
            source = next(
                (s for s in data.get("sources", []) if s["id"] == c["source_id"]), {}
            )
            appendix.append(
                f"[{c['id']}] {c['quote']}\n{source.get('title', '')} {source.get('url', '')}"
                + (f" · page {c['page']}" if c.get("page") else "")
            )
        limitations = data.get("report", {}).get("limitations", []) + data.get(
            "warnings", []
        )
        for calc in data.get("calculations", []):
            story.append(
                p(
                    f"{calc['label']}: {calc['value']} {calc['unit']} · {calc['formula']} · inputs: {', '.join(calc['claim_ids'])}"
                )
            )
    story.append(p("Limitations", heading))
    story.extend(p(x) for x in limitations)
    story.append(p("Evidence appendix", heading))
    story.extend(p(x, small) for x in appendix)

    def footer(canvas, doc):
        canvas.setFont("NotoSans", 8)
        canvas.setFillColor(colors.HexColor("#5c6e64"))
        canvas.drawString(42, 25, "StrataLens · Source claims require human review")
        canvas.drawRightString(553, 25, str(doc.page))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
