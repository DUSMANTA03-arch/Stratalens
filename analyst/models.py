from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartInput(StrictModel):
    filename: str = Field(min_length=1, max_length=160)
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data: str = Field(min_length=20, max_length=1_350_000)


class ResearchRequest(StrictModel):
    question: str = Field(min_length=10, max_length=2000)
    mode: Literal["live", "sample"] = "live"
    charts: list[ChartInput] = Field(default_factory=list, max_length=3)


class Plan(StrictModel):
    scope: str
    assumptions: list[str]
    questions: list[str] = Field(max_length=4)
    queries: list[str] = Field(min_length=1, max_length=4)


class Source(StrictModel):
    id: str
    url: str
    title: str
    publisher: str
    retrieved_at: str
    published_at: str = "Unknown"
    text: str
    tables: list[list[list[str]]] = Field(default_factory=list)
    kind: Literal["html", "pdf", "image", "sample"] = "html"
    source_tier: Literal[
        "government",
        "regulator",
        "company",
        "consulting",
        "industry",
        "academic",
        "news",
        "other",
    ] = "other"
    source_quality: Literal["primary", "expert", "secondary", "unclassified"] = (
        "unclassified"
    )
    image_data: str | None = None
    image_media_type: str | None = None
    origin_page: int | None = None


class Claim(StrictModel):
    metric_definition: str = "unknown"
    reporting_basis: Literal["consolidated", "standalone", "industry", "unknown"] = (
        "unknown"
    )
    value_kind: Literal["historical", "target", "forecast", "unknown"] = "unknown"
    id: str
    statement: str
    source_id: str
    quote: str
    page: int | None = None
    entity: str
    metric: str
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str
    period: str
    geography: str
    segment: str
    evidence_kind: Literal["quotation", "chart"] = "quotation"
    precision: Literal["printed", "approximate", "unknown"] = "printed"


class ChartObservation(StrictModel):
    statement: str
    visual_evidence: str
    entity: str
    metric: str
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str
    period: str
    geography: str
    segment: str
    precision: Literal["printed", "approximate", "unknown"]


class ChartExtraction(StrictModel):
    title: str
    chart_type: str
    observations: list[ChartObservation] = Field(max_length=15)
    limitations: list[str]


class Extraction(StrictModel):
    claims: list[Claim] = Field(max_length=30)


class Assessment(StrictModel):
    claim_id: str
    status: Literal["single-source", "corroborated", "disputed", "insufficient"]
    related_claim_ids: list[str]
    reason: str


class CalculationRequest(StrictModel):
    operation: Literal["growth", "cagr", "share", "difference"]
    input_claim_ids: list[str] = Field(min_length=2, max_length=2)
    years: float | None = Field(default=None, allow_inf_nan=False)
    label: str


class Validation(StrictModel):
    assessments: list[Assessment]
    follow_up_queries: list[str] = Field(default_factory=list, max_length=2)
    calculations: list[CalculationRequest] = Field(default_factory=list, max_length=4)


class Finding(StrictModel):
    text: str
    claim_ids: list[str]


class ReportSection(StrictModel):
    heading: str
    findings: list[Finding]


class Report(StrictModel):
    title: str
    sections: list[ReportSection]
    limitations: list[str]
