import hashlib
import math
import re
from urllib.parse import urlsplit


def normalized(value):
    return " ".join(str(value).casefold().split())


def verify_claims(claims, sources):
    indexed = {s["id"]: s for s in sources}
    accepted, warnings = [], []
    for claim in claims:
        source = indexed.get(claim["source_id"])
        quote = normalized(claim["quote"])
        if not source or len(quote) < 20 or quote not in normalized(source["text"]):
            warnings.append(
                "An extracted claim was omitted because its quotation could not be matched to the source."
            )
            continue
        if claim.get("page") is not None:
            marker = f"[Page {claim['page']}]"
            page_text = source["text"].split(marker, 1)[-1].split("[Page ", 1)[0]
            if (
                source["kind"] != "pdf"
                or marker not in source["text"]
                or quote not in normalized(page_text)
            ):
                warnings.append(
                    "A claim with an invalid PDF page reference was omitted."
                )
                continue
        claim = dict(claim)
        claim["id"] = (
            "C" + hashlib.sha256((source["id"] + quote).encode()).hexdigest()[:10]
        )
        accepted.append(claim)
    return list({c["id"]: c for c in accepted}.values()), warnings


def comparable(
    a, b, fields=("entity", "metric", "unit", "period", "geography", "segment")
):
    for field in ("metric_definition", "reporting_basis", "value_kind"):
        if normalized(a.get(field, "unknown")) != normalized(b.get(field, "unknown")):
            return False
    return all(
        normalized(a.get(f, "")) not in {"", "unknown", "unspecified"}
        and normalized(a.get(f)) == normalized(b.get(f))
        for f in fields
    )


def independent(a, b, sources):
    x, y = sources[a["source_id"]], sources[b["source_id"]]
    if a["source_id"] == b["source_id"] or normalized(x["publisher"]) == normalized(
        y["publisher"]
    ):
        return False
    hx, hy = (urlsplit(s.get("url", "")).hostname or "" for s in (x, y))
    if hx and hy and (hx == hy or hx.endswith("." + hy) or hy.endswith("." + hx)):
        return False
    if x.get("source_tier") == y.get("source_tier") == "company":
        return False
    for key in ("checksum", "underlying_document_id", "origin_url"):
        if x.get(key) and x.get(key) == y.get(key):
            return False
    q, r = normalized(a["quote"]), normalized(b["quote"])
    if (
        q in r
        or r in q
        or normalized(x.get("text", "")) == normalized(y.get("text", ""))
    ):
        return False

    def shingles(text):
        words = text.split()
        return {tuple(words[i : i + 6]) for i in range(max(0, len(words) - 5))}

    left, right = shingles(q), shingles(r)
    if left and right and len(left & right) / min(len(left), len(right)) >= 0.6:
        return False
    # Syndicated disclosures do not become independent evidence by changing publisher.
    if any(
        marker in q + " " + r
        for marker in (
            "company said",
            "company reported",
            "according to the company",
            "press release",
            "annual report",
        )
    ):
        return False
    return True


def sanitize_assessments(assessments, claims, sources):
    indexed = {c["id"]: c for c in claims}
    source_map = {s["id"]: s for s in sources}
    result = {}
    for item in assessments:
        claim = indexed.get(item["claim_id"])
        if not claim:
            continue
        item = dict(item)
        related = [
            indexed[cid]
            for cid in item["related_claim_ids"]
            if cid in indexed and cid != claim["id"]
        ]
        related = [c for c in related if comparable(claim, c)]
        if item["status"] == "corroborated":
            related = [c for c in related if independent(claim, c, source_map)]
        item["related_claim_ids"] = [c["id"] for c in related]
        if item["status"] in {"corroborated", "disputed"} and not related:
            item.update(
                status="single-source",
                reason="No comparable independent evidence was established.",
            )
        result[claim["id"]] = item
    for claim in claims:
        result.setdefault(
            claim["id"],
            {
                "claim_id": claim["id"],
                "status": "single-source",
                "related_claim_ids": [],
                "reason": "Visual chart reading; independent corroboration not established."
                if claim.get("evidence_kind") == "chart"
                else "Quotation matched; independent corroboration not established.",
            },
        )
    # Numerical disagreement overrides model agreement for like-for-like claims.
    for a in claims:
        for b in claims:
            if (
                a["id"] == b["id"]
                or a["source_id"] == b["source_id"]
                or not comparable(a, b)
            ):
                continue
            if (
                a.get("value") is not None
                and b.get("value") is not None
                and not math.isclose(a["value"], b["value"], rel_tol=0.01, abs_tol=1e-9)
            ):
                item = result[a["id"]]
                item["status"] = "disputed"
                item["related_claim_ids"] = sorted(
                    set(item["related_claim_ids"] + [b["id"]])
                )
                item["reason"] = (
                    "Comparable reported values differ by more than 1%; review definitions and source methodology."
                )
    return list(result.values())


def calculate(request, claims, assessments):
    by_id = {c["id"]: c for c in claims}
    blocked = {
        a["claim_id"]
        for a in assessments
        if a["status"] in {"disputed", "insufficient"}
    }
    blocked |= {c["id"] for c in claims if c.get("precision", "printed") != "printed"}
    ids = request["input_claim_ids"]
    if len(set(ids)) != 2 or any(cid not in by_id or cid in blocked for cid in ids):
        raise ValueError(
            "Calculation needs two distinct, non-disputed evidence inputs."
        )
    a, b = (by_id[cid] for cid in ids)
    x, y = a.get("value"), b.get("value")
    if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Missing finite numerical input.")
    op = request["operation"]
    fields = ("metric", "unit", "geography", "segment")
    if op in {"growth", "cagr"}:
        fields += ("entity",)
        if not re.fullmatch(r"\d{4}", a["period"]) or not re.fullmatch(
            r"\d{4}", b["period"]
        ):
            raise ValueError("Growth calculations require explicit calendar years.")
        years = int(b["period"]) - int(a["period"])
        if years <= 0 or x <= 0 or y < 0:
            raise ValueError(
                "Growth requires chronological periods and a positive base."
            )
        value = (
            (y / x - 1) * 100 if op == "growth" else ((y / x) ** (1 / years) - 1) * 100
        )
        formula = (
            f"({y} / {x} - 1) × 100"
            if op == "growth"
            else f"(({y} / {x}) ^ (1 / {years}) - 1) × 100"
        )
        unit = "%"
    elif op == "share":
        fields += ("period",)
        if y <= 0 or x < 0 or x > y:
            raise ValueError(
                "Share requires a positive total at least as large as the part."
            )
        if normalized(b["entity"]) not in {"market total", "total market"}:
            raise ValueError(
                "Share denominator must explicitly identify the market total."
            )
        value, formula, unit = x / y * 100, f"{x} / {y} × 100", "%"
    else:
        fields += ("entity", "period")
        value, formula, unit = y - x, f"{y} − {x}", a["unit"]
    if not comparable(a, b, fields) or not math.isfinite(value):
        raise ValueError("Calculation inputs have incompatible definitions or units.")
    return {
        "id": "K" + hashlib.sha256(str(request).encode()).hexdigest()[:10],
        "label": request["label"],
        "operation": op,
        "claim_ids": ids,
        "value": round(value, 4),
        "unit": unit,
        "formula": formula,
    }


def clean_report(report, claims, assessments=None):
    blocked = {
        a["claim_id"] for a in (assessments or []) if a["status"] == "insufficient"
    }
    valid = {c["id"] for c in claims} - blocked
    dropped = False
    for section in report["sections"]:
        findings = []
        for finding in section["findings"]:
            if not finding["claim_ids"] or any(
                cid not in valid for cid in finding["claim_ids"]
            ):
                dropped = True
                continue
            findings.append(finding)
        section["findings"] = findings
    report["sections"] = [s for s in report["sections"] if s["findings"]]
    if dropped:
        report["limitations"].append(
            "Some generated findings were omitted because their evidence references were missing or invalid."
        )
    return report


def evidence_graph(sources, claims, assessments, calculations, report):
    nodes = [{"id": s["id"], "type": "source", "label": s["title"]} for s in sources]
    nodes += [{"id": c["id"], "type": "claim", "label": c["statement"]} for c in claims]
    edges = [
        {"from": c["source_id"], "to": c["id"], "relation": "reports"} for c in claims
    ]
    for assessment in assessments:
        if assessment["status"] not in {"corroborated", "disputed"}:
            continue
        for related in assessment["related_claim_ids"]:
            edges.append(
                {
                    "from": related,
                    "to": assessment["claim_id"],
                    "relation": "contradicts"
                    if assessment["status"] == "disputed"
                    else "supports",
                }
            )
    for calculation in calculations:
        nodes.append(
            {
                "id": calculation["id"],
                "type": "calculation",
                "label": calculation["label"],
            }
        )
        edges.extend(
            {"from": cid, "to": calculation["id"], "relation": "input"}
            for cid in calculation["claim_ids"]
        )
    for i, finding in enumerate(
        f for s in report.get("sections", []) for f in s["findings"]
    ):
        fid = f"F{i + 1}"
        nodes.append({"id": fid, "type": "finding", "label": finding["text"]})
        edges.extend(
            {"from": cid, "to": fid, "relation": "informs"}
            for cid in finding["claim_ids"]
        )
    return {"nodes": nodes, "edges": edges}
