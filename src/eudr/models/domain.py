"""Domain model. A Case is the unit of work; everything hangs off it."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Verdict(StrEnum):
    PASS = "PASS"
    EXCEPTION = "EXCEPTION"
    CRITICAL = "CRITICAL"


class CaseStatus(StrEnum):
    INTAKE = "intake"
    COLLECTING = "collecting"
    SCREENING = "screening"
    ADJUDICATING = "adjudicating"
    DRAFTING = "drafting"
    AWAITING_ACK = "awaiting_acknowledgement"
    ACKNOWLEDGED = "acknowledged"
    MONITORING = "monitoring"
    BLOCKED = "blocked"


class GapKind(StrEnum):
    MISSING_POLYGON = "missing_polygon"
    MISSING_PRODUCTION_WINDOW = "missing_production_window"
    INVALID_GEOMETRY = "invalid_geometry"
    POINT_TOO_LARGE = "point_for_plot_over_4ha"
    MISSING_SUPPLIER_ID = "missing_supplier_id"
    MISSING_DOCUMENT = "missing_document"
    VOLUME_MISMATCH = "volume_mismatch"
    OVERLAP = "plot_overlap"
    OTHER = "other"


class Supplier(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sup"))
    name: str
    country: str = "BR"
    car_number: str | None = None
    tax_id: str | None = None
    contact: str | None = None
    municipality: str | None = None
    state: str | None = None
    notes: str | None = None


class Plot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plot"))
    supplier_id: str
    name: str | None = None
    geometry: dict[str, Any] | None = Field(default=None, description="GeoJSON geometry, WGS84")
    geometry_source: str | None = Field(default=None, description="upload:file | car:number | point | agent")
    declared_area_ha: float | None = None
    computed_area_ha: float | None = None
    production_start: date | None = None
    production_end: date | None = None
    commodity: str = "soya"
    declared_yield_t_ha: float | None = None
    scenario: str | None = Field(default=None, description="test-only hint for the mock provider")


class Lot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lot"))
    reference: str
    tonnes: float
    plot_ids: list[str] = Field(default_factory=list)
    silo: str | None = None
    destination: str | None = None


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    supplier_id: str | None = None
    kind: str = Field(description="car_receipt | land_title | contract | invoice | labour_cert | prior_dds | other")
    path: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    pages: int = 0
    ocr_pages: int = 0
    citations: list[Citation] = Field(default_factory=list)


class Gap(BaseModel):
    id: str = Field(default_factory=lambda: new_id("gap"))
    kind: GapKind
    subject_ref: str
    description: str
    owner: str = Field(default="supplier", description="who must resolve it: supplier | operator | analyst")
    resolved: bool = False
    resolution: str | None = None


class Evidence(BaseModel):
    type: str = Field(description="chip_before | chip_after | ndvi_series | loss_overlay | dataset | document | overlay")
    uri: str
    sha256: str
    captured_at: str | None = None
    source: str
    source_version: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ScreenMetrics(BaseModel):
    plot_area_ha: float
    forest_2020_ha: float
    loss_after_cutoff_ha: float
    converted_ha: float
    first_loss_year: int | None = None
    native_vegetation_2020_ha: float = 0.0
    native_vegetation_loss_ha: float = 0.0
    sources_concordant: bool = True
    cloud_free_scenes: int = 0


class AnalystOpinion(BaseModel):
    model: str
    prompt_version: str
    recommended_verdict: Verdict
    confidence: float
    rationale: str
    cited_evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class Assessment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asm"))
    subject_ref: str
    subject_type: str = "plot"
    rule_pack_version: str
    verdict: Verdict
    confidence: float
    metrics: ScreenMetrics | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    analyst_opinion: AnalystOpinion | None = None
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    override_verdict: Verdict | None = None
    override_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    hash: str | None = None

    @property
    def final_verdict(self) -> Verdict:
        return self.override_verdict or self.verdict


class LegalityFinding(BaseModel):
    layer: str
    severity: str = Field(description="info | warning | blocking")
    subject_ref: str
    detail: str
    overlap_ha: float | None = None
    citations: list[Citation] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    country: str
    country_risk: str
    score: float
    criteria: dict[str, Any]
    narrative: str | None = None
    mitigation: list[str] = Field(default_factory=list)


class VolumeCheck(BaseModel):
    lot_id: str
    declared_t: float
    plausible_t: float
    ratio: float
    flag: bool
    detail: str


class TraceNode(BaseModel):
    id: str
    name: str
    tier: str = Field(description="farm | silo | cooperative | crusher | trader | exporter | port | unknown")
    tax_id: str | None = None
    supplier_id: str | None = None


class TraceEdge(BaseModel):
    source: str
    target: str
    tonnes: float
    lot_reference: str | None = None
    doc_ref: str | None = None
    period: str | None = None
    citation: Citation | None = None


class TraceCheck(BaseModel):
    node_id: str
    inflow_t: float
    outflow_t: float
    delta_t: float
    flag: bool
    detail: str


class TraceChain(BaseModel):
    nodes: list[TraceNode] = Field(default_factory=list)
    edges: list[TraceEdge] = Field(default_factory=list)
    checks: list[TraceCheck] = Field(default_factory=list)
    source_docs: list[str] = Field(default_factory=list)


class ExceptionItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exc"))
    category: str = Field(description="geolocation | deforestation | legality | volume | traceability | documentation | review")
    severity: str = Field(description="critical | major | minor | info")
    subject_ref: str
    subject_label: str = ""
    detail: str
    owner: str = "operator"
    status: str = "open"
    citations: list[Citation] = Field(default_factory=list)
    evidence_uris: list[str] = Field(default_factory=list)


class Dossier(BaseModel):
    generated_at: datetime = Field(default_factory=utcnow)
    summary: str = ""
    dds_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_pack_path: str | None = None
    critic_report: dict[str, Any] | None = None
    hash: str | None = None


class Citation(BaseModel):
    field: str
    value: str
    file: str
    page: int
    bbox: list[float] = Field(description="x0,y0,x1,y1 in PDF points")
    snippet: str = ""
    image_uri: str | None = None
    sha256: str | None = None


class Acknowledgement(BaseModel):
    reviewer: str
    acknowledged_at: datetime = Field(default_factory=utcnow)
    dossier_hash: str
    statement: str


class Case(BaseModel):
    id: str = Field(default_factory=lambda: new_id("case"))
    operator: str
    commodity: str = "soya"
    origin_country: str = "BR"
    destination: str | None = None
    shipment_window: str | None = None
    status: CaseStatus = CaseStatus.INTAKE
    suppliers: list[Supplier] = Field(default_factory=list)
    plots: list[Plot] = Field(default_factory=list)
    lots: list[Lot] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    legality: list[LegalityFinding] = Field(default_factory=list)
    risk: RiskAssessment | None = None
    volume_checks: list[VolumeCheck] = Field(default_factory=list)
    trace: TraceChain | None = None
    exceptions: list[ExceptionItem] = Field(default_factory=list)
    dossier: Dossier | None = None
    acknowledgement: Acknowledgement | None = None
    dds_reference: str | None = None
    intake_notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def plot(self, plot_id: str) -> Plot:
        return next(p for p in self.plots if p.id == plot_id)

    def supplier(self, supplier_id: str) -> Supplier:
        return next(s for s in self.suppliers if s.id == supplier_id)

    def assessment_for(self, subject_ref: str) -> Assessment | None:
        return next((a for a in reversed(self.assessments) if a.subject_ref == subject_ref), None)

    def open_gaps(self) -> list[Gap]:
        return [g for g in self.gaps if not g.resolved]
