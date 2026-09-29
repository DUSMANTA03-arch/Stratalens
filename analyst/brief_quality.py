"""Deterministic presentation of cited claims; never fabricate missing figures."""

from collections import defaultdict
from decimal import Decimal
from analyst.evidence import normalized
from analyst.financials import numbers


def enrich_brief(data, source_records=None):
    claims = {c["id"]: c for c in data.get("claims", [])}
    blocked = {
        a["claim_id"]
        for a in data.get("assessments", [])
        if a["status"] in {"disputed", "insufficient"}
    }
    supported = {k: c for k, c in claims.items() if k not in blocked}
    findings = [
        f for s in data.get("report", {}).get("sections", []) for f in s["findings"]
    ]
    takeaway = next(
        (
            f
            for f in findings
            if f["claim_ids"] and all(i in supported for i in f["claim_ids"])
        ),
        None,
    )
    if takeaway:
        data["executive_takeaway"] = takeaway
    elif data.get("passages"):
        data["executive_takeaway"] = data["passages"][0]
    entities = defaultdict(list)
    for c in supported.values():
        if normalized(c.get("entity", "")) not in {"", "unknown", "unspecified"}:
            entities[c["entity"]].append(c)
    categories = [
        ("Disclosed scale", ("revenue", "capacity", "sales", "share", "profit")),
        (
            "Capabilities",
            ("product", "technology", "distribution", "manufactur", "portfolio"),
        ),
        ("Constraints", ("risk", "debt", "delay", "cost", "constraint")),
    ]
    data["positioning"] = [
        {
            "entity": entity,
            "cells": [
                {
                    "label": label,
                    "text": " ".join(c["statement"] for c in selected)
                    if selected
                    else "Not established",
                    "claim_ids": [c["id"] for c in selected],
                }
                for label, words in categories
                for selected in [
                    [
                        c
                        for c in group
                        if any(w in normalized(c["metric"]) for w in words)
                    ][:2]
                ]
            ],
        }
        for entity, group in list(entities.items())[:12]
    ]
    if not data["positioning"] and data.get("company_labels"):
        for cid, name in data["company_labels"].items():
            passages = [
                p
                for p in data.get("passages", [])
                if p.get("citations")
                and all(
                    data.get("document_companies", {}).get(c["document_id"]) == cid
                    for c in p["citations"]
                )
            ]
            cells = []
            for label, words in [
                ("Disclosed scale", ("financial", "performance")),
                ("Capabilities", ("business", "management")),
                ("Constraints", ("risk", "constraint")),
            ]:
                selected = next(
                    (
                        p
                        for p in passages
                        if any(w in normalized(p["heading"]) for w in words)
                    ),
                    None,
                )
                cells.append(
                    {
                        "label": label,
                        "text": selected["text"] if selected else "Not established",
                        "claim_ids": [],
                        "citations": selected["citations"] if selected else [],
                    }
                )
            data["positioning"].append({"entity": name, "cells": cells})
    groups = defaultdict(list)
    sources = {
        s["id"]: s
        for s in (
            source_records if source_records is not None else data.get("sources", [])
        )
    }
    fields = (
        "metric",
        "metric_definition",
        "unit",
        "period",
        "geography",
        "segment",
        "reporting_basis",
        "value_kind",
    )
    for c in supported.values():
        if (
            c.get("value") is None
            or c.get("precision", "printed") != "printed"
            or c.get("evidence_kind") == "chart"
        ):
            continue
        if any(
            normalized(c.get(f, "")) in {"", "unknown", "unspecified"} for f in fields
        ):
            continue
        if c["value_kind"] not in {"historical", "target", "forecast"} or c[
            "reporting_basis"
        ] not in {"consolidated", "standalone", "industry"}:
            continue
        if Decimal(str(c["value"])) not in numbers(c["quote"]):
            continue
        if normalized(c["quote"]) not in normalized(
            sources.get(c["source_id"], {}).get("text", "")
        ):
            continue
        groups[tuple(normalized(c[f]) for f in fields)].append(c)
    charts = []
    for group in groups.values():
        by_entity = defaultdict(list)
        for c in group:
            by_entity[c["entity"]].append(c)
        points = [
            {
                "entity": entity,
                "value": items[0]["value"],
                "claim_ids": [c["id"] for c in items],
            }
            for entity, items in by_entity.items()
            if len({c["value"] for c in items}) == 1
        ]
        if len(points) < 2:
            continue
        first = group[0]
        charts.append({**{f: first[f] for f in fields}, "points": points[:12]})
    data["evidence_charts"] = charts[:4]
    data["chart_note"] = (
        "Charts require compatible cited numeric observations, explicit definitions and reporting basis. Historical observations, targets and forecasts are kept separate."
    )
    return data
