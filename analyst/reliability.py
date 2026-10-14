"""Saved-record-derived progress, explicit reporting coverage and review state."""

import calendar
import re
from datetime import date, datetime, timezone

TEMPLATES = {
    "market_landscape": {
        "label": "Market landscape",
        "mode": "market",
        "question": "Analyze the market landscape: demand drivers, market structure, competitors, and evidence gaps.",
    },
    "competitive_positioning": {
        "label": "Competitive positioning",
        "mode": "market",
        "question": "Compare competitive positioning, disclosed scale, capabilities, constraints, and uncertainties in this market.",
    },
    "company_overview": {
        "label": "Company overview",
        "mode": "company",
        "question": "Review the selected reports: business model, financial performance, management priorities, and disclosed risks.",
    },
    "management_execution": {
        "label": "Management execution",
        "mode": "company",
        "question": "Compare management commitments with reported execution in the selected reports. Identify achievements, delays, and unverified promises.",
    },
    "risk_review": {
        "label": "Risk review",
        "mode": "company",
        "question": "Analyze disclosed operational, financial, and regulatory risks in the selected reports, mitigations, and remaining evidence gaps.",
    },
}


def review_status(data):
    review = data.get("review", {})
    return (
        review.get("status", "unreviewed")
        if review.get("version") == data.get("observation_version", 1)
        else "unreviewed"
    )


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def shift_end(end, months):
    year, month = divmod(end.year * 12 + end.month - 1 + months, 12)
    return month_end(year, month + 1)


def period_end(label, year_end=3):
    label = label.strip().upper()
    # Only explicit FY labels; no upload/publication dates are used.
    match = re.fullmatch(
        r"(?:Q([1-4])\s*)?FY\s*(20\d{2})(?:[-–/](\d{2}|20\d{2}))?", label
    )
    if not match:
        return None
    quarter, year, last = match.groups()
    year = int(last if last and len(last) == 4 else "20" + last) if last else int(year)
    if last and year != int(match[2]) + 1:
        return None
    end = month_end(year, year_end)
    return (shift_end(end, (int(quarter) - 4) * 3) if quarter else end).isoformat()


def candidate_period(title):
    # Discovery titles are candidates, never confirmation of a filing's contents.
    quarter = re.search(
        r"\b(Q[1-4])\s*(?:FY\s*)?(20\d{2}(?:[-–/]\d{2,4})?)\b", title, re.I
    )
    annual = re.search(
        r"(?:annual report|financial year|FY)\s*(?:for\s*)?(?:the\s*)?(?:financial year\s*)?(20\d{2}(?:[-–/]\d{2,4})?)\b",
        title,
        re.I,
    )
    if quarter:
        return {
            "fiscal_period": quarter[1].upper() + " FY" + quarter[2],
            "period_type": "quarterly",
        }
    if annual:
        return {"fiscal_period": "FY" + annual[1], "period_type": "annual"}
    return {}


def coverage(company, documents, discoveries=(), today=None, jobs=()):
    today = today or date.today()
    month = company["data"].get("year_end_month", 3)
    annual = month_end(today.year, month)
    if annual > today:
        annual = shift_end(annual, -12)
    quarter = shift_end(annual, 9)
    while quarter > today:
        quarter = shift_end(quarter, -3)
    rows = []
    for kind, ends in (
        ("annual", [shift_end(annual, -12 * i) for i in range(3)]),
        ("quarterly", [shift_end(quarter, -3 * i) for i in range(8)]),
    ):
        for end in ends:
            matching = []
            for doc in documents:
                d = doc["data"]
                dtype = d.get("period_type") or (
                    "annual"
                    if d.get("document_type") == "annual_report"
                    else "quarterly"
                )
                if (
                    dtype == kind
                    and (
                        d.get("period_end")
                        or period_end(d.get("fiscal_period", ""), month)
                    )
                    == end.isoformat()
                ):
                    matching.append(doc)
            statuses = []
            for doc in matching:
                d = doc["data"]
                s = d.get("status", "")
                job = next(
                    (
                        j
                        for j in jobs
                        if j.get("kind") == "ingest"
                        and j.get("state", {}).get("document_id") == doc["id"]
                    ),
                    None,
                )
                if job and job.get("status") == "failed":
                    s = "failed"
                incomplete = bool(
                    job
                    and job.get("status") in {"cancelled", "paused"}
                    and d.get("indexed_pages", 0) == d.get("page_count", -1)
                )
                statuses.append(
                    "failed/unsupported"
                    if s in {"failed", "unsupported", "identity_unverified", "identity_mismatch"}
                    else "extraction incomplete"
                    if d.get("financial_warnings") or incomplete
                    else "indexed"
                    if s == "ready"
                    else "processing"
                )
            candidate = any(
                period_end(c.get("fiscal_period", ""), month) == end.isoformat()
                and c.get("period_type") == kind
                for discovery in discoveries
                for c in discovery["data"].get("candidates", [])
            )
            rank = [
                "indexed",
                "extraction incomplete",
                "processing",
                "failed/unsupported",
            ]
            status = next(
                (s for s in rank if s in statuses),
                "candidate found" if candidate else "missing",
            )
            rows.append(
                {
                    "period_type": kind,
                    "period_end": end.isoformat(),
                    "status": status,
                    "documents": [d["id"] for d in matching],
                }
            )
    unassigned = [
        d
        for d in documents
        if not (
            d["data"].get("period_end")
            or period_end(d["data"].get("fiscal_period", ""), month)
        )
    ]
    return {
        "rows": rows,
        "unassigned": [
            {"id": d["id"], "title": d["data"].get("title", "Report")}
            for d in unassigned
        ],
        "year_end_month": month,
        "note": "Missing means absent from this workspace, not that a report does not exist. Indexed does not mean reviewed.",
    }


def step_summary(state, records, phase):
    flow = state.get("workflow", {})
    claims = {c["id"]: c for c in flow.get("claims", [])}
    assessments = {
        a["claim_id"]: a for a in flow.get("assessments", []) if a["claim_id"] in claims
    }
    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "step": phase,
        "sources": len({s["id"] for s in flow.get("sources", [])}),
        "claims": len(claims),
        "supported": sum(
            assessments.get(cid, {}).get("status") not in {"disputed", "insufficient"}
            for cid in claims
        ),
        "corroborated": sum(
            a["status"] == "corroborated" for a in assessments.values()
        ),
        "disputed": sum(a["status"] == "disputed" for a in assessments.values()),
        "gaps": list(
            dict.fromkeys(
                flow.get("warnings", [])
                + flow.get("report", {}).get("limitations", [])
                + flow.get("follow_up_queries", [])
            )
        ),
        "candidates": len({c["url"] for c in state.get("candidates", [])}),
        "observations": len(set(state.get("observation_ids", []))),
    }
    single = sum(
        assessments.get(cid, {}).get("status", "single-source") == "single-source"
        for cid in claims
    )
    if single:
        summary["gaps"].append(
            f"Independent corroboration not established for {single} claims."
        )
    for record in records:
        if record["kind"] == "document":
            d = record["data"]
            summary.update(
                pages_indexed=d.get("indexed_pages", 0),
                pages_total=d.get("page_count"),
                gaps=d.get("notes", []),
            )
    if "pages_retrieved" in state:
        summary["gaps"] = list(dict.fromkeys(summary["gaps"] + state.get("answer_gaps", [])))
        summary.update(
            pages_retrieved=state["pages_retrieved"],
            supported_passages=state.get("supported_passages", 0),
        )
    return summary
