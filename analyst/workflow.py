import asyncio
import time
from typing import TypedDict
from urllib.parse import urlsplit

from langgraph.graph import END, START, StateGraph

from analyst.charts import read_chart
from analyst.evidence import (
    calculate,
    clean_report,
    evidence_graph,
    sanitize_assessments,
    verify_claims,
)
from analyst.models import Extraction, Plan, Report, Validation
from analyst.providers import ProviderError
from analyst.retrieval import canonical_url, retrieve
from analyst.sample import sample_sources
from analyst.source_quality import quality_score


class ResearchState(TypedDict, total=False):
    question: str
    mode: str
    plan: dict
    sources: list[dict]
    claims: list[dict]
    assessments: list[dict]
    calculations: list[dict]
    follow_up_queries: list[str]
    rounds: int
    attempted_urls: list[str]
    extracted_source_ids: list[str]
    warnings: list[str]
    report: dict
    charts: list[dict]
    chart_ids_read: list[str]
    source_coverage: list[dict]
    partial: bool


def fallback_report(state):
    claims = state.get("claims", [])
    return {
        "title": "Partial research brief",
        "sections": [
            {
                "heading": "Source-backed observations",
                "findings": [
                    {"text": c["statement"], "claim_ids": [c["id"]]}
                    for c in claims[:12]
                ],
            }
        ]
        if claims
        else [],
        "limitations": [
            "Research did not complete. Observations are source claims, not independently established facts."
        ]
        + state.get("warnings", []),
    }


def public_result(state, providers, elapsed, partial=False):
    report = state.get("report") or fallback_report(state)
    assessments = state.get("assessments", [])
    if not assessments:
        assessments = sanitize_assessments(
            [], state.get("claims", []), state.get("sources", [])
        )
    return {
        "question": state["question"],
        "mode": state["mode"],
        "partial": partial,
        "plan": state.get("plan"),
        "sources": [
            {k: v for k, v in s.items() if k not in {"text", "chart_candidates"}}
            for s in state.get("sources", [])
        ],
        "claims": state.get("claims", []),
        "assessments": assessments,
        "source_coverage": state.get("source_coverage", []),
        "calculations": state.get("calculations", []),
        "report": report,
        "warnings": list(dict.fromkeys(state.get("warnings", []))),
        "graph": evidence_graph(
            state.get("sources", []),
            state.get("claims", []),
            assessments,
            state.get("calculations", []),
            report,
        ),
        "usage": {
            "model_calls": providers.llm_calls,
            "search_calls": providers.search_calls,
            "elapsed_seconds": round(elapsed, 1),
        },
    }


def build_workflow(providers, started=None, handlers_only=False):
    started = started or time.monotonic()

    async def planner(state):
        plan = await providers.generate(
            "planning agent",
            "Define a precise scope and four or fewer subquestions and search queries. "
            "For broad markets distinguish vehicle/product segments. State assumptions about unspecified dates. "
            "Do not assume policy names, market figures or current leaders; those must be discovered from sources. "
            "Favor government portals, regulators, company filings/annual reports, reputed consulting firms "
            "(McKinsey, Bain, BCG, Deloitte, PwC, EY, Kearney), recognized industry bodies, academic institutions, "
            "and named industry experts. Create queries that explicitly seek these source types, such as: "
            "site:gov.in, site:gov, annual report, investor presentation, methodology, consulting report, industry association. "
            "Use a news article only to locate an underlying primary report; do not use it as the strongest evidence. "
            "Keep queries diverse across market size, competition, policy, demand and technology.",
            {"question": state["question"]},
            Plan,
        )
        return {"plan": plan.model_dump(), "warnings": [], "rounds": 0}

    async def researcher(state):
        if state["mode"] == "sample":
            return {"sources": sample_sources(), "rounds": state.get("rounds", 0) + 1}
        if time.monotonic() - started >= 180:
            return {
                "rounds": state.get("rounds", 0) + 1,
                "warnings": state.get("warnings", [])
                + ["Collection deadline reached; additional searches were skipped."],
            }
        queries = (
            state.get("follow_up_queries")
            if state.get("rounds", 0)
            else state["plan"]["queries"]
        )
        results = await asyncio.gather(
            *(providers.search(q) for q in (queries or [])), return_exceptions=True
        )
        warnings = list(state.get("warnings", []))
        candidates, seen = [], set(state.get("attempted_urls", []))
        for result in results:
            if isinstance(result, BaseException):
                warnings.append(
                    str(result)
                    if isinstance(result, ProviderError)
                    else "A search request failed."
                )
                continue
            for item in result:
                try:
                    url = canonical_url(item["url"])
                except (KeyError, ValueError):
                    continue
                if url not in seen:
                    seen.add(url)
                    candidates.append(item)
        sources = list(state.get("sources", []))
        slots = max(0, 12 - sum(s["kind"] != "image" for s in sources))
        pdf_slots = max(0, 2 - sum(s["kind"] == "pdf" for s in sources))
        selected = []
        for item in candidates:
            if urlsplit(item["url"]).path.lower().endswith(".pdf"):
                if pdf_slots == 0:
                    continue
                pdf_slots -= 1
            selected.append(item)
            if len(selected) >= slots:
                break
        candidates = selected if slots else []
        semaphore = asyncio.Semaphore(3)

        async def fetch(item):
            async with semaphore:
                if time.monotonic() - started >= 175:
                    return ValueError("Collection deadline")
                try:
                    return await retrieve(item)
                except Exception:
                    return ValueError("Source unavailable")

        retrieved = await asyncio.gather(*(fetch(item) for item in candidates))
        ids = {s["id"] for s in sources}
        pdfs = sum(s["kind"] == "pdf" for s in sources)
        for item, result in zip(candidates, retrieved):
            if isinstance(result, BaseException):
                warnings.append(
                    f"Could not retrieve readable content: {item.get('url', 'unknown source')}"
                )
                continue
            if result["id"] in ids:
                continue
            if result["kind"] == "pdf":
                if pdfs >= 2:
                    warnings.append(
                        "Additional PDFs omitted because the two-PDF limit was reached."
                    )
                    continue
                pdfs += 1
            ids.add(result["id"])
            sources.append(result)
        # Preserve quality diversity while making the strongest documents first in context.
        sources.sort(key=quality_score, reverse=True)
        if not sources:
            warnings.append(
                "No full-text sources were retrieved. A factual report cannot be produced."
            )
        return {
            "sources": sources,
            "warnings": warnings,
            "attempted_urls": sorted(seen),
            "rounds": state.get("rounds", 0) + 1,
        }

    async def analyst(state):
        old_ids = set(state.get("extracted_source_ids", []))
        sources = [
            s
            for s in state.get("sources", [])
            if s["id"] not in old_ids and s["kind"] != "image"
        ]
        if not sources:
            return {"claims": state.get("claims", [])}
        # Keep extraction contexts small. A single prompt containing a dozen long
        # reports can time out or cause the model to return an empty structured
        # response, which used to make the downstream report look blank. Each
        # batch is independently validated, then merged by stable claim id.
        claims, warnings = [], []
        extraction_instructions = (
            "Set metric_definition to the precise disclosed measurement definition, reporting_basis to consolidated, standalone or industry only if established, and value_kind to historical, target or forecast only when explicit; otherwise unknown. "
            "Extract at most 12 atomic, relevant claims from this batch. Every claim must have a verbatim continuous quote "
            "from the supplied text, at least 20 characters. Preserve source_id exactly. "
            "For PDFs use the [Page N] markers. Set page null for HTML. Do not use snippets or infer absent figures. "
            "Normalize entity, metric, unit, geography and segment consistently without changing meaning. "
            "Use 'Unknown' for missing definitions; only use a four-digit period for explicit calendar years. "
            "A numeric value must appear in or be unambiguously represented by its quoted passage. "
            "Separate different periods. Treat source statements as claims, not established truth. "
            "Try to represent every source in the batch with at least one claim when it contains relevant evidence; "
            "return no claim only when the source truly has no usable evidence."
        )
        for offset in range(0, len(sources), 3):
            batch = sources[offset : offset + 3]
            try:
                extraction = await providers.generate(
                    "evidence analyst",
                    extraction_instructions,
                    {
                        "question": state["question"],
                        "scope": state["plan"],
                        "sources": [
                            {k: v for k, v in s.items() if k != "chart_candidates"}
                            for s in batch
                        ],
                    },
                    Extraction,
                )
                batch_claims, batch_warnings = verify_claims(
                    [c.model_dump() for c in extraction.claims], batch
                )
                claims.extend(batch_claims)
                warnings.extend(batch_warnings)
            except ProviderError:
                warnings.append(
                    f"Evidence extraction failed for {len(batch)} source(s); other batches were retained."
                )
        combined = {c["id"]: c for c in state.get("claims", []) + claims}
        covered = {c["source_id"] for c in claims}
        coverage = list(state.get("source_coverage", []))
        for source in sources:
            if source["id"] in covered:
                status, note = (
                    "used",
                    "At least one validated claim was extracted from this retrieved source.",
                )
            else:
                status, note = (
                    "retrieved-not-used",
                    "Retrieved successfully, but the evidence agent found no relevant claim in this pass.",
                )
                warnings.append(
                    f"Retrieved source not represented in claims: {source['title']}"
                )
            coverage.append({"source_id": source["id"], "status": status, "note": note})
        return {
            "claims": list(combined.values())[:45],
            "extracted_source_ids": list(old_ids | {s["id"] for s in sources}),
            "warnings": state.get("warnings", []) + warnings,
            "source_coverage": coverage,
        }

    async def chart_reader(state):
        read_ids = set(state.get("chart_ids_read", []))
        sources, claims = list(state.get("sources", [])), list(state.get("claims", []))
        warnings = list(state.get("warnings", []))
        candidates = state.get("charts", []) + [
            c for s in sources for c in s.get("chart_candidates", [])
        ]
        for chart in candidates[:3]:
            if chart["id"] in read_ids or state["mode"] == "sample":
                continue
            read_ids.add(chart["id"])
            if time.monotonic() - started >= 155:
                warnings.append(
                    "An attached chart was skipped to reserve time for validation and writing."
                )
                continue
            try:
                source, observations, notes = await read_chart(
                    providers, chart, state["question"]
                )
                sources.append(source)
                claims.extend(observations)
                warnings.extend(notes)
            except ProviderError as exc:
                warnings.append(str(exc))
        return {
            "sources": sources,
            "claims": claims,
            "chart_ids_read": list(read_ids),
            "warnings": warnings,
        }

    async def validator(state):
        claims = state.get("claims", [])
        if not claims:
            return {"assessments": [], "calculations": [], "follow_up_queries": []}
        try:
            validation = await providers.generate(
                "claim validation agent",
                "Assess each claim against its quote and related source evidence. Unsupported numeric mappings are insufficient. "
                "Chart evidence has a visual description rather than a matched quote; approximate chart readings are "
                "estimates, never independently verified numbers. Do not propose calculations on approximate readings. "
                "Compare only the same entity, metric, units, geography, period and segment. "
                "Corroborated requires independent original evidence: syndication and common underlying reports do not count. "
                "If independence is unclear, use single-source. Explain uncertainty. "
                "Request at most two targeted follow-up queries only for important unresolved gaps or disputes. "
                "Propose at most four useful calculations using claim IDs: growth and CAGR inputs are earlier then later "
                "calendar-year values; share inputs are part then explicit 'market total'; difference is second minus first. "
                "Do not propose calculations using disputed or insufficient claims.",
                {
                    "question": state["question"],
                    "claims": claims,
                    "sources": [
                        {
                            k: v
                            for k, v in s.items()
                            if k
                            not in {"text", "tables", "image_data", "chart_candidates"}
                        }
                        for s in state["sources"]
                    ],
                },
                Validation,
            )
        except ProviderError as exc:
            # Validation is useful but must not prevent the writer from using
            # the quoted evidence. The sanitizer supplies conservative
            # single-source statuses for every claim.
            return {
                "assessments": sanitize_assessments([], claims, state["sources"]),
                "calculations": [],
                "follow_up_queries": [],
                "partial": True,
                "warnings": state.get("warnings", [])
                + [
                    str(exc),
                    "Claim validation did not complete; claims are shown as single-source evidence.",
                ],
            }
        assessments = sanitize_assessments(
            [a.model_dump() for a in validation.assessments], claims, state["sources"]
        )
        calculations, warnings = [], list(state.get("warnings", []))
        for request in validation.calculations:
            try:
                calculations.append(
                    calculate(request.model_dump(), claims, assessments)
                )
            except ValueError as exc:
                warnings.append(f"Calculation omitted: {exc}")
        follow_up = (
            validation.follow_up_queries
            if state.get("rounds", 0) < 2
            and time.monotonic() - started < 120
            and providers.llm_calls <= 6
            else []
        )
        if validation.follow_up_queries and not follow_up:
            warnings.append(
                "Further verification is needed; the bounded follow-up budget has ended."
            )
        return {
            "assessments": assessments,
            "calculations": calculations,
            "warnings": warnings,
            "follow_up_queries": follow_up,
        }

    async def writer(state):
        claims = state.get("claims", [])
        if not claims:
            return {"report": fallback_report(state)}
        try:
            report = await providers.generate(
                "report writing agent",
                "Write a consulting-style brief prioritizing implications, competitive differences and uncertainties over length. Start with one clear cited executive takeaway. Avoid repetition, unsupported rankings and invented figures. With sections: Executive summary, Market context and demand drivers, "
                "Competitive landscape, Trends, Strategic implications, and Contradictions. "
                "Use a clear thesis and 3–5 substantive findings per supported section. Explain the significance of evidence, "
                "competitive differentiation, dependencies and uncertainties. Keep thin-evidence reports shorter; never pad or repeat findings to meet a word target. "
                "Every finding requires valid claim_ids from the supplied evidence. No new factual assertions, invented figures, "
                "or URLs. Attribute single-source facts; explicitly flag disputed estimates and never silently choose one. "
                "Label strategic interpretations as 'Analyst interpretation'. Use supplied calculations only; do not do new math. "
                "Identify chart-derived findings as visual readings. Approximate values must remain explicitly approximate. "
                "Omit unsupported sections. Put evidence gaps and methodology caveats in limitations. "
                "If mode is sample, clearly state that all data is fictional.",
                {
                    "question": state["question"],
                    "mode": state["mode"],
                    "plan": state["plan"],
                    "claims": claims,
                    "assessments": state["assessments"],
                    "calculations": state["calculations"],
                    "warnings": state.get("warnings", []),
                },
                Report,
            )
            cleaned = clean_report(report.model_dump(), claims, state["assessments"])
            return {
                "report": cleaned if cleaned.get("sections") else fallback_report(state)
            }
        except ProviderError:
            return {
                "report": fallback_report(
                    dict(
                        state,
                        warnings=state.get("warnings", [])
                        + [
                            "Report writing timed out; source-backed observations are shown instead."
                        ],
                    )
                ),
                "partial": True,
            }

    if handlers_only:
        return dict(
            planner=planner,
            researcher=researcher,
            chart_reader=chart_reader,
            analyst=analyst,
            validator=validator,
            writer=writer,
        )
    graph = StateGraph(ResearchState)
    for name, handler in (
        ("planner", planner),
        ("researcher", researcher),
        ("chart_reader", chart_reader),
        ("analyst", analyst),
        ("validator", validator),
        ("writer", writer),
    ):
        graph.add_node(name, handler)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "chart_reader")
    graph.add_edge("chart_reader", "analyst")
    graph.add_edge("analyst", "validator")
    graph.add_conditional_edges(
        "validator",
        lambda state: "researcher" if state.get("follow_up_queries") else "writer",
    )
    graph.add_edge("writer", END)
    return graph.compile()
