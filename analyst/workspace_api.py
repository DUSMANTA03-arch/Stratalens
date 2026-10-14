import asyncio
import csv
import io
import os
import httpx
from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field, HttpUrl, model_validator

from analyst.auth import require_owner
from analyst.reliability import TEMPLATES, coverage
from analyst.financials import comparison
from analyst.models import StrictModel, ChartInput
from analyst.charts import prepare_chart
from analyst.retrieval import download, public_address
from analyst.workspace_jobs import advance
from analyst.workspace_store import Store
from analyst.company_documents import candidate_matches, validate_company_document

router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_owner)])


async def get_store(owner=Depends(require_owner)):
    async with Store(owner) as store:
        yield store


class CompanyInput(StrictModel):
    year_end_month: int = Field(default=3, ge=1, le=12)
    name: str = Field(min_length=2, max_length=200)
    symbol: str = Field(min_length=1, max_length=30)
    isin: str = Field(
        default="", max_length=12, pattern=r"^(?:[A-Z]{2}[A-Z0-9]{9}[0-9])?$"
    )
    website: HttpUrl | None = None
    sector: Literal["non_financial", "bank", "insurance"] = "non_financial"


class DocumentInput(StrictModel):
    company_id: UUID
    title: str = Field(min_length=2, max_length=240)
    document_type: Literal["annual_report", "financial_results"]
    fiscal_period: str = Field(default="", max_length=40)
    published_at: date | None = None
    size: int = Field(default=40_000_000, gt=0, le=40_000_000)
    url: HttpUrl | None = None


class ResearchInput(StrictModel):
    template_id: str | None = None
    question: str = Field(min_length=10, max_length=2000)
    mode: Literal["market", "company"] = "market"
    company_ids: list[UUID] = Field(default_factory=list, max_length=3)
    document_ids: list[UUID] = Field(default_factory=list, max_length=12)
    charts: list[ChartInput] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def selections(self):
        if self.template_id and (
            self.template_id not in TEMPLATES
            or TEMPLATES[self.template_id]["mode"] != self.mode
        ):
            raise ValueError("Choose a template for this research mode.")
        if len(self.question.strip()) < 10:
            raise ValueError("Enter a meaningful question.")
        if self.mode == "company" and (not self.company_ids or not self.document_ids):
            raise ValueError("Company analysis needs a company and selected documents.")
        if self.mode == "market" and self.document_ids:
            raise ValueError("Use company mode for selected-document analysis.")
        if self.mode != "market" and self.charts:
            raise ValueError("Chart attachments are supported in market research.")
        return self


class ChatInput(StrictModel):
    question: str = Field(min_length=3, max_length=2000)
    document_ids: list[UUID] = Field(min_length=1, max_length=12)
    conversation_id: UUID | None = None


class Correction(StrictModel):
    value: float = Field(allow_inf_nan=False)
    reason: str = Field(min_length=10, max_length=1000)
    expected_updated_at: str


def document_public(row):
    return {**row, "data": {k: v for k, v in row["data"].items() if k != "path"}}


def job_public(row):
    state = row.get("state", {})
    return {k: v for k, v in row.items() if k not in {"lease_token", "state"}} | {
        "state": {
            k: v
            for k, v in state.items()
            if k
            in {
                "step_summaries",
                "template_id",
                "phase",
                "next_page",
                "question",
                "document_id",
                "document_ids",
                "company_id",
                "company_ids",
                "mode",
                "conversation_id",
            }
        },
        "result": row.get("result"),
    }


@router.get("/companies/search")
async def search_companies(q: str = Query(min_length=2, max_length=100)):
    try:
        raw, _, _ = await download(
            "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
            max_bytes=4_000_000,
        )
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        matches = []
        for original in rows:
            row = {k.strip(): v.strip() for k, v in original.items() if k}
            if (
                q.casefold()
                in (
                    row.get("NAME OF COMPANY", "") + " " + row.get("SYMBOL", "")
                ).casefold()
            ):
                matches.append(
                    {
                        "name": row.get("NAME OF COMPANY", ""),
                        "symbol": row.get("SYMBOL", ""),
                        "isin": row.get("ISIN NUMBER", ""),
                        "source": "NSE equity listing",
                    }
                )
        return {
            "candidates": matches[:30],
            "note": "Select the exact listing. For BSE-only companies or unavailable listings, add identifiers manually from an official filing.",
        }
    except (ValueError, UnicodeError, OSError, httpx.HTTPError) as exc:
        raise HTTPException(
            502,
            "NSE listing unavailable. Add company identifiers manually from an official filing.",
        ) from exc


@router.get("/companies")
async def companies(store=Depends(get_store)):
    return await store.records("company")


@router.post("/companies")
async def add_company(body: CompanyInput, store=Depends(get_store)):
    if body.website:
        try:
            await public_address(str(body.website))
        except (ValueError, OSError) as exc:
            raise HTTPException(
                422, "Use a reachable public HTTP(S) company website."
            ) from exc
    for company in await store.records("company"):
        if (
            company["data"]["symbol"].casefold() == body.symbol.casefold()
            or body.isin
            and company["data"].get("isin") == body.isin
        ):
            return company
    return await store.put("company", body.model_dump(mode="json"))


@router.post("/companies/{company_id}/discover")
async def discover_reports(company_id: UUID, store=Depends(get_store)):
    await store.record("company", company_id)
    return job_public(await store.new_job("discover", {"company_id": str(company_id)}))


@router.get("/documents")
async def documents(store=Depends(get_store)):
    return [document_public(d) for d in await store.records("document")]


@router.post("/documents")
async def create_document(body: DocumentInput, store=Depends(get_store)):
    company = await store.record("company", body.company_id)
    if body.url:
        try:
            await public_address(str(body.url))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    did = str(uuid4())
    data = body.model_dump(mode="json")
    data.update(
        path=f"{store.owner}/{did}/report.pdf",
        status="uploading" if not body.url else "queued",
        origin="user-upload" if not body.url else "user-confirmed URL",
        indexed_pages=0,
    )
    host = (urlsplit(str(body.url)).hostname or "") if body.url else ""
    official = urlsplit(company["data"].get("website") or "").hostname or ""
    if host and (
        any(
            host == h or host.endswith("." + h)
            for h in ("nseindia.com", "bseindia.com")
        )
        or official
        and (host == official or host.endswith("." + official))
    ):
        data["origin"] = (
            "official exchange"
            if host.endswith(("nseindia.com", "bseindia.com"))
            else "owner-confirmed company website"
        )
    ok = await store.rpc("allocate_workspace_document", document=did, data=data)
    if not ok:
        raise HTTPException(
            409,
            "Library storage limit reached (800 MB reserved). Delete unused documents first.",
        )
    row = {"id": did, "kind": "document", "data": data}
    if body.url:
        job = await store.new_job(
            "ingest",
            {"document_id": did, "phase": "inspect"},
            str(uuid5(NAMESPACE_URL, "ingest:" + did)),
        )
        return {"document": document_public(row), "job": job_public(job)}
    return {
        "document": document_public(row),
        "upload_url": await store.signed_upload(data["path"]),
    }


@router.post("/documents/{document_id}/complete")
async def complete_upload(document_id: UUID, store=Depends(get_store)):
    doc = await store.record("document", document_id)
    jobs = await store.jobs()
    existing = next(
        (
            j
            for j in jobs
            if j["kind"] == "ingest"
            and j["state"].get("document_id") == str(document_id)
        ),
        None,
    )
    if existing:
        return job_public(existing)
    if doc["data"]["status"] != "uploading":
        raise HTTPException(409, "This document has already been submitted.")
    return job_public(
        await store.new_job(
            "ingest",
            {"document_id": str(document_id), "phase": "inspect"},
            str(uuid5(NAMESPACE_URL, "ingest:" + str(document_id))),
        )
    )


@router.get("/documents/{document_id}/view")
async def view_document(
    document_id: UUID,
    page: int = Query(default=1, ge=1, le=600),
    store=Depends(get_store),
):
    doc = await store.record("document", document_id)
    if doc["data"]["status"] in {"uploading", "queued", "duplicate", "deleting"}:
        raise HTTPException(409, "Document must be validated before viewing.")
    pages = await store.pages(document_id, page, page)
    return {
        "url": await store.signed_url(doc["data"]["path"]),
        "page": pages[0] if pages else None,
        "document": document_public(doc),
    }


@router.delete("/documents/{document_id}")
async def delete_document(document_id: UUID, store=Depends(get_store)):
    doc = await store.record("document", document_id)
    # A retained tombstone lets the owner retry if object deletion fails.
    if not await store.rpc("delete_workspace_document", document=str(document_id)):
        raise HTTPException(
            409,
            "Pause processing and wait for the current step before deleting documents.",
        )
    await store.remove_blob(doc["data"]["path"])
    await store.request(
        "DELETE",
        "/rest/v1/workspace_records",
        params={
            "owner_id": "eq." + store.owner,
            "id": "eq." + str(document_id),
            "kind": "eq.document",
        },
    )
    return {"ok": True}


async def verify_documents(store, ids):
    for did in ids:
        doc = await store.record("document", did)
        if doc["data"]["status"] not in {"ready", "extracting"}:
            raise HTTPException(
                409, "Wait for all selected documents to finish indexing."
            )
        try:
            await validate_company_document(store, doc)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post("/research")
async def research(body: ResearchInput, store=Depends(get_store)):
    await verify_documents(store, body.document_ids)
    for cid in body.company_ids:
        await store.record("company", cid)
    for did in body.document_ids:
        if (await store.record("document", did))["data"]["company_id"] not in [
            str(c) for c in body.company_ids
        ]:
            raise HTTPException(
                422, "Selected reports must belong to the selected companies."
            )
    import base64

    job_id = str(uuid4())
    state = body.model_dump(mode="json", exclude={"charts"})
    state["chart_paths"] = []
    for chart in body.charts:
        try:
            prepared = await asyncio.to_thread(prepare_chart, chart)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        raw = base64.b64decode(prepared.pop("data"))
        path = f"{store.owner}/research/{job_id}/{prepared['id']}.jpg"
        asset_id = str(uuid5(NAMESPACE_URL, path))
        if not await store.rpc(
            "allocate_workspace_asset",
            asset=asset_id,
            data={"path": path, "size": len(raw), "job_id": job_id},
        ):
            raise HTTPException(
                409, "Storage limit reached. Delete unused reports first."
            )
        await store.upload(path, raw, "image/jpeg")
        state["chart_paths"].append(prepared | {"path": path})
    return job_public(await store.new_job("research", state, job_id))


@router.post("/chat")
async def chat(body: ChatInput, store=Depends(get_store)):
    await verify_documents(store, body.document_ids)
    if body.conversation_id:
        convo = await store.record("conversation", body.conversation_id)
        if set(convo["data"]["document_ids"]) != set(map(str, body.document_ids)):
            raise HTTPException(
                422, "Start a new conversation when changing selected documents."
            )
        if len(convo["data"]["turns"]) >= 50:
            raise HTTPException(422, "Start a new conversation after 50 questions.")
    return job_public(await store.new_job("chat", body.model_dump(mode="json")))


@router.get("/jobs")
async def jobs(store=Depends(get_store)):
    return [job_public(j) for j in await store.jobs()]


@router.get("/jobs/{job_id}")
async def job(job_id: UUID, store=Depends(get_store)):
    rows = await store.jobs(job_id)
    if not rows:
        raise HTTPException(404, "Job not found.")
    return job_public(rows[0])


@router.post("/jobs/{job_id}/advance")
async def advance_job(job_id: UUID, store=Depends(get_store)):
    return job_public(await advance(store, job_id))


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, store=Depends(get_store)):
    await store.rpc("cancel_workspace_job", job=str(job_id))
    return {"ok": True}


@router.get("/briefs")
async def briefs(store=Depends(get_store)):
    return await store.records("brief")


@router.get("/briefs/{brief_id}/export.pdf")
async def export_pdf(brief_id: UUID, store=Depends(get_store)):
    from analyst.exports import brief_pdf

    brief = await store.record("brief", brief_id)
    content = await asyncio.to_thread(brief_pdf, brief["data"])
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="stratalens-brief.pdf"'},
    )


@router.get("/briefs/{brief_id}/images/{source_id}")
async def brief_image(brief_id: UUID, source_id: str, store=Depends(get_store)):
    brief = await store.record("brief", brief_id)
    source = next(
        (
            s
            for s in brief["data"].get("sources", [])
            if s["id"] == source_id and s.get("image_path")
        ),
        None,
    )
    if not source:
        raise HTTPException(404, "Image evidence not found.")
    return {"url": await store.signed_url(source["image_path"])}


@router.get("/conversations")
async def conversations(store=Depends(get_store)):
    return await store.records("conversation")


@router.get("/discoveries")
async def discoveries(store=Depends(get_store)):
    rows = await store.records("discovery")
    companies = {c["id"]: c for c in await store.records("company")}
    for row in rows:
        company = companies.get(row["data"]["company_id"])
        row["data"]["candidates"] = [item for item in row["data"].get("candidates", []) if company and candidate_matches(item, company)]
    return rows


@router.get("/observations")
async def observations(company_id: UUID, store=Depends(get_store)):
    await store.record("company", company_id)
    return await store.records(
        "observation", **{"data->>company_id": "eq." + str(company_id)}
    )


@router.patch("/observations/{observation_id}")
async def correct(observation_id: UUID, body: Correction, store=Depends(get_store)):
    result = await store.rpc(
        "correct_workspace_observation",
        observation=str(observation_id),
        value=body.value,
        reason=body.reason,
        expected=body.expected_updated_at,
    )
    if not result:
        raise HTTPException(409, "Observation changed. Refresh before correcting it.")
    return result


@router.get("/comparison")
async def compare(
    company_ids: list[UUID] = Query(min_length=1, max_length=3),
    basis: Literal["consolidated", "standalone"] = "consolidated",
    reviewed_only: bool = False,
    store=Depends(get_store),
):
    companies = [
        await store.record("company", cid) for cid in dict.fromkeys(company_ids)
    ]
    observations = []
    for company in companies:
        observations.extend(
            await store.records(
                "observation", **{"data->>company_id": "eq." + company["id"]}
            )
        )
    return comparison(observations, companies, basis, reviewed_only) | {
        "companies": companies
    }


@router.get("/settings")
async def settings(store=Depends(get_store)):
    try:
        reliability_ready = bool(await store.rpc("workspace_reliability_ready"))
    except HTTPException:
        reliability_ready = False
    docs = await store.records("document")
    assets = await store.records("asset")
    return {
        "reliability_ready": reliability_ready,
        "storage_bytes": sum(d["data"].get("size", 0) for d in docs + assets),
        "storage_limit": 800_000_000,
        "usage": await store.usage(),
        "gemini_ready": bool(os.getenv("GEMINI_API_KEY")),
        "search_ready": bool(os.getenv("TAVILY_API_KEY")),
        "limits": {
            "daily_model_calls": 100,
            "daily_search_calls": 20,
            "document_mb": 40,
            "document_pages": 600,
        },
        "note": "Application counters record attempted calls, not provider quota balances. Configure free provider projects; this app never enables billing or switches providers.",
    }


class ReviewInput(StrictModel):
    status: Literal["reviewed", "unreviewed", "excluded"]
    reason: str = Field(default="", max_length=1000)
    expected_updated_at: str


class PeriodInput(StrictModel):
    period_end: date
    period_type: Literal["annual", "quarterly"]
    expected_updated_at: str


class YearEndInput(StrictModel):
    month: int = Field(ge=1, le=12)
    expected_updated_at: str


class NoteInput(StrictModel):
    target_kind: Literal["brief", "observation"]
    target_id: UUID
    evidence_id: str | None = None
    text: str = Field(min_length=1, max_length=4000)


class NoteEdit(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    expected_updated_at: str


class CompanyConfirmation(StrictModel):
    expected_updated_at: str
    reason: str = Field(min_length=20, max_length=1000)


@router.post("/documents/{document_id}/confirm-company")
async def confirm_company(document_id: UUID, body: CompanyConfirmation, store=Depends(get_store)):
    doc = await store.record("document", document_id)
    if doc["data"]["status"] != "identity_unverified":
        raise HTTPException(422, "Only an unidentified report can be confirmed. A different issuer is blocked.")
    if len(body.reason.strip()) < 20:
        raise HTTPException(422, "Explain how you verified the issuer (at least 20 characters).")
    await patch_record(store, "document", document_id, body.expected_updated_at, {
        "company_identity": {"status": "owner_confirmed", "company_id": doc["data"]["company_id"], "reason": body.reason},
        "status": "queued",
    })
    return job_public(await store.new_job("ingest", {"document_id": str(document_id), "phase": "inspect"}, str(uuid5(NAMESPACE_URL, "company-confirm:" + str(document_id)))))


@router.get("/templates")
async def templates():
    return TEMPLATES


@router.post("/observations/{observation_id}/review")
async def review(observation_id: UUID, body: ReviewInput, store=Depends(get_store)):
    if body.status == "excluded" and len(body.reason.strip()) < 10:
        raise HTTPException(
            422, "Explain why this figure should be excluded (at least 10 characters)."
        )
    result = await store.rpc(
        "review_workspace_observation",
        observation=str(observation_id),
        status=body.status,
        reason=body.reason,
        expected=body.expected_updated_at,
    )
    if not result:
        raise HTTPException(
            409, "Observation changed or processing is active. Refresh and try again."
        )
    return result


async def patch_record(store, kind, rid, expected, patch, delete=False):
    result = await store.rpc(
        "patch_workspace_record",
        kind=kind,
        record=str(rid),
        expected=expected,
        patch=patch,
        delete=delete,
    )
    if not result:
        raise HTTPException(
            409, "Record changed or processing is active. Refresh and try again."
        )
    return result


@router.get("/companies/{company_id}/coverage")
async def get_coverage(company_id: UUID, store=Depends(get_store)):
    company = await store.record("company", company_id)
    docs = await store.records(
        "document", **{"data->>company_id": "eq." + str(company_id)}
    )
    discoveries = await store.records(
        "discovery", **{"data->>company_id": "eq." + str(company_id)}
    )
    for row in discoveries:
        row["data"]["candidates"] = [item for item in row["data"].get("candidates", []) if candidate_matches(item, company)]
    return coverage(company, docs, discoveries, jobs=await store.jobs())


@router.patch("/companies/{company_id}/year-end")
async def year_end(company_id: UUID, body: YearEndInput, store=Depends(get_store)):
    return await patch_record(
        store,
        "company",
        company_id,
        body.expected_updated_at,
        {"year_end_month": body.month},
    )


@router.patch("/documents/{document_id}/period")
async def assign_period(document_id: UUID, body: PeriodInput, store=Depends(get_store)):
    from analyst.reliability import month_end

    if body.period_end != month_end(body.period_end.year, body.period_end.month):
        raise HTTPException(422, "Use the reporting period's month-end date.")
    doc = await store.record("document", document_id)
    company = await store.record("company", doc["data"]["company_id"])
    offset = (body.period_end.month - company["data"].get("year_end_month", 3)) % 12
    if (body.period_type == "annual" and offset) or (
        body.period_type == "quarterly" and offset % 3
    ):
        raise HTTPException(
            422, "Period does not match the company's financial year-end."
        )
    return await patch_record(
        store,
        "document",
        document_id,
        body.expected_updated_at,
        {
            "period_end": body.period_end.isoformat(),
            "period_type": body.period_type,
            "fiscal_period": body.period_end.isoformat(),
        },
    )


@router.get("/notes")
async def notes(target_id: UUID, store=Depends(get_store)):
    return await store.records("note", **{"data->>target_id": "eq." + str(target_id)})


@router.post("/notes")
async def add_note(body: NoteInput, store=Depends(get_store)):
    await store.rpc("workspace_reliability_ready")
    target = await store.record(body.target_kind, body.target_id)
    if body.evidence_id and (
        body.target_kind != "brief"
        or body.evidence_id not in {c["id"] for c in target["data"].get("claims", [])}
    ):
        raise HTTPException(422, "Evidence record not found in this brief.")
    return await store.put("note", body.model_dump(mode="json"))


@router.patch("/notes/{note_id}")
async def edit_note(note_id: UUID, body: NoteEdit, store=Depends(get_store)):
    return await patch_record(
        store, "note", note_id, body.expected_updated_at, {"text": body.text}
    )


@router.delete("/notes/{note_id}")
async def remove_note(
    note_id: UUID, expected_updated_at: str, store=Depends(get_store)
):
    return await patch_record(store, "note", note_id, expected_updated_at, {}, True)
