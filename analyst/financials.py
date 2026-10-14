"""Financial evidence, typed extraction and deterministic compatible comparisons."""

import re
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from analyst.reliability import review_status
from analyst.evidence import normalized
from analyst.models import StrictModel

Metric = Literal[
    "revenue",
    "net_profit",
    "assets",
    "equity",
    "borrowings",
    "cash",
    "operating_cash_flow",
    "capex",
    "eps",
]
SCALES = {
    "units": 1,
    "thousand": 1000,
    "lakh": 100000,
    "million": 1000000,
    "crore": 10000000,
    "billion": 1000000000,
}


class Observation(StrictModel):
    metric: Metric
    label: str = Field(description="Original financial statement row label, copied from the source. Do not put a reporting definition such as group_total here.")
    value: float = Field(allow_inf_nan=False)
    currency: str
    scale: Literal["units", "thousand", "lakh", "million", "crore", "billion"]
    period_start: str | None
    period_end: str
    period_type: Literal["annual", "quarterly", "ytd", "instant"]
    basis: Literal["consolidated", "standalone", "unknown"]
    definition: str = Field(description="Normalized comparison definition: group_total for consolidated totals, company_total for standalone totals, basic_eps for basic EPS. This is separate from the original row label.")
    page: int = Field(ge=1, le=600)
    quote: str = Field(min_length=10)
    restated: bool

    @model_validator(mode="after")
    def dates(self):
        end = date.fromisoformat(self.period_end)
        if self.period_start:
            start = date.fromisoformat(self.period_start)
            if start > end:
                raise ValueError("Reporting dates are reversed.")
            days = (end - start).days + 1
            if self.period_type == "quarterly" and not 80 <= days <= 100:
                raise ValueError("Not a standalone quarter.")
            if self.period_type == "annual" and not 350 <= days <= 380:
                raise ValueError("Not a comparable annual period.")
        elif self.period_type != "instant":
            raise ValueError("Flow metrics require explicit period start.")
        if (
            self.metric in {"assets", "equity", "borrowings", "cash"}
            and self.period_type != "instant"
        ):
            raise ValueError("Balance sheet metrics need instant dates.")
        if (
            self.metric
            in {"revenue", "net_profit", "operating_cash_flow", "capex", "eps"}
            and self.period_type == "instant"
        ):
            raise ValueError("Flow metric requires a duration.")
        return self


class FinancialExtraction(StrictModel):
    observations: list[Observation] = Field(max_length=80)


def numbers(text):
    out = set()
    for raw in re.findall(r"\(?[-−]?\d[\d,]*(?:\.\d+)?\)?", text):
        negative = raw.startswith("(") and raw.endswith(")")
        try:
            value = Decimal(raw.strip("()").replace(",", "").replace("−", "-"))
            out.add(-value if negative else value)
        except Exception:
            continue
    return out


def verify_observations(extraction, pages, document):
    indexed = {p["page"]: p for p in pages}
    accepted, warnings = [], []
    for obs in extraction.observations:
        data = obs.model_dump()
        data["original_currency"] = obs.currency
        data["currency"] = {
            "rs": "INR",
            "rs.": "INR",
            "₹": "INR",
            "inr": "INR",
            "indian rupees": "INR",
        }.get(obs.currency.strip().lower(), obs.currency.upper())
        page = indexed.get(obs.page)
        if (
            not page
            or normalized(obs.quote) not in normalized(page["text"])
            or Decimal(str(obs.value)) not in numbers(obs.quote)
        ):
            warnings.append(
                f"Unmatched financial evidence on page {obs.page} was omitted."
            )
            continue
        # A value's presence confirms provenance, not semantic mapping; keep review visible.
        data.update(
            document_id=document["id"],
            company_id=document["data"]["company_id"],
            published_at=document["data"].get("published_at"),
            provenance="reported",
            review_status="unreviewed",
            corrections=[],
            original_value=obs.value,
        )
        identity = f"{document['id']}:{obs.page}:{obs.metric}:{obs.period_start}:{obs.period_end}:{obs.basis}:{obs.definition}"
        accepted.append(
            {
                "id": str(uuid5(NAMESPACE_URL, identity)),
                "kind": "observation",
                "data": data,
            }
        )
    return accepted, warnings


def amount(obs):
    value = Decimal(str(obs["value"]))
    return value if obs["metric"] == "eps" else value * SCALES[obs["scale"]]


def signature(obs, include_metric=True):
    fields = [
        "period_start",
        "period_end",
        "period_type",
        "basis",
        "currency",
        "definition",
    ]
    if include_metric:
        fields.insert(0, "metric")
    return tuple(obs.get(k) for k in fields)


def select_versions(rows):
    """Conflicts remain excluded unless an explicitly restated newer filing resolves them."""
    grouped = {}
    for row in rows:
        d = row["data"]
        grouped.setdefault((d["company_id"], *signature(d)), []).append(row)
    selected, warnings = [], []
    for group in grouped.values():
        group.sort(
            key=lambda r: (
                r["data"].get("published_at") or "",
                r.get("created_at", ""),
            ),
            reverse=True,
        )
        first = group[0]
        if len({amount(x["data"]) for x in group}) > 1:
            if not (
                first["data"].get("restated")
                and first["data"].get("published_at")
                and all(
                    (x["data"].get("published_at") or "")
                    < first["data"]["published_at"]
                    for x in group[1:]
                )
            ):
                warnings.append(
                    f"Conflicting versions excluded: {first['data']['metric']} ending {first['data']['period_end']}."
                )
                continue
        selected.append(first)
    return selected, warnings


def comparison(rows, companies, basis="consolidated", reviewed_only=False):
    excluded = {
        c["id"] for c in companies if c["data"].get("sector") in {"bank", "insurance"}
    }
    candidates = [
        r
        for r in rows
        if review_status(r["data"]) != "excluded"
        and r["data"]["basis"] == basis
        and r["data"]["company_id"] not in excluded
        and r["data"]["currency"] == "INR"
        and r["data"]["definition"] in {"group_total", "company_total", "basic_eps"}
    ]
    selected, warnings = select_versions(candidates)
    if reviewed_only:
        selected = [r for r in selected if review_status(r["data"]) == "reviewed"]
    if excluded:
        warnings.append(
            "Bank and insurance companies are excluded from generic financial comparisons."
        )
    if len(candidates) < len(rows):
        warnings.append(
            "Other statement bases, currencies, sectors or unresolved definitions are excluded. Missing figures are not zero."
        )
    groups = {}
    for row in selected:
        d = row["data"]
        key = signature(d)
        groups.setdefault(key, []).append(row)
    output = []
    for key, values in groups.items():
        d = values[0]["data"]
        if len({x["data"]["company_id"] for x in values}) != len(values):
            continue
        output.append(
            {
                "metric": d["metric"],
                "period_start": d["period_start"],
                "period_end": d["period_end"],
                "period_type": d["period_type"],
                "basis": basis,
                "unit": "INR/share" if d["metric"] == "eps" else "INR crore",
                "values": {
                    x["data"]["company_id"]: {
                        "value": float(
                            amount(x["data"])
                            / (1 if d["metric"] == "eps" else 10000000)
                        ),
                        "observation_id": x["id"],
                        "document_id": x["data"]["document_id"],
                        "page": x["data"]["page"],
                        "restated": x["data"]["restated"],
                        "review_status": review_status(x["data"]),
                    }
                    for x in values
                },
            }
        )
    # Limit periods per class, retaining missing values as absent rather than filling with zero.
    keep = {
        kind: sorted(
            {r["period_end"] for r in output if r["period_type"] == kind}, reverse=True
        )[: 8 if kind == "quarterly" else 3]
        for kind in ("annual", "quarterly", "instant", "ytd")
    }
    output = [r for r in output if r["period_end"] in keep[r["period_type"]]]
    derived = []
    for a in selected:
        x = a["data"]
        for b in selected:
            y = b["data"]
            if (
                x["company_id"] != y["company_id"]
                or x["basis"] != y["basis"]
                or x["currency"] != y["currency"]
            ):
                continue
            if (
                x["metric"] == "net_profit"
                and y["metric"] == "revenue"
                and signature(x, False) == signature(y, False)
                and amount(y) > 0
            ):
                derived.append(
                    {
                        "label": "Net profit margin",
                        "company_id": x["company_id"],
                        "period_end": x["period_end"],
                        "value": round(float(amount(x) / amount(y) * 100), 4),
                        "unit": "%",
                        "inputs": [a["id"], b["id"]],
                        "formula": "net profit / revenue × 100",
                    }
                )
            if (
                x["metric"] != y["metric"]
                or x["definition"] != y["definition"]
                or x["period_type"] != y["period_type"]
                or x["period_type"] not in {"annual", "quarterly"}
            ):
                continue
            dx, dy = (
                date.fromisoformat(x["period_end"]),
                date.fromisoformat(y["period_end"]),
            )
            if (
                dy.year - dx.year != 1
                or (dx.month, dx.day) != (dy.month, dy.day)
                or amount(x) <= 0
            ):
                continue
            sx, sy = (
                date.fromisoformat(x["period_start"]),
                date.fromisoformat(y["period_start"]),
            )
            if sy.year - sx.year != 1 or (sx.month, sx.day) != (sy.month, sy.day):
                continue
            derived.append(
                {
                    "label": x["metric"] + " YoY growth",
                    "company_id": x["company_id"],
                    "period_end": y["period_end"],
                    "value": round(float((amount(y) / amount(x) - 1) * 100), 4),
                    "unit": "%",
                    "inputs": [a["id"], b["id"]],
                    "formula": "(later / earlier − 1) × 100",
                }
            )
    evidence = {r["id"]: r["data"] for r in selected}
    for calculation in derived:
        calculation["citations"] = [
            {
                "document_id": evidence[i]["document_id"],
                "page": evidence[i]["page"],
                "quote": evidence[i]["quote"],
            }
            for i in calculation["inputs"]
        ]
    return {
        "rows": sorted(
            output, key=lambda r: (r["period_end"], r["metric"]), reverse=True
        ),
        "derived": derived,
        "warnings": warnings,
    }
