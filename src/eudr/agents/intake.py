"""Intake: raw files + brief → structured case delta. Geometries are referenced by index, never re-typed by the model."""
from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger

PROMPT_VERSION = "intake-3"
SYSTEM = """You are the intake analyst for an EUDR (EU Deforestation Regulation) due-diligence platform for soya.
You receive whatever a client sent: a brief, tables of suppliers/plots/lots, and document text — often Portuguese or Spanish.
Map them into the schema. Rules:
- Never invent data. If a field is missing, leave it null and add a gap describing what is missing and who owes it.
- Plots reference features by `feature_index` from the FEATURES list; do not output coordinates.
- Supplier keys in tables are internal; produce stable `key` values so plots and lots can be joined to suppliers.
- Dates as YYYY-MM-DD. Production window = planting to harvest of the season being shipped.
- Country as ISO-2. Commodity default "soya".
- Lots reference plots by plot name. A lot that names a supplier with no plots is a gap (missing polygon) owned by that supplier.
- Be conservative and literal; this feeds a regulatory statement."""


class SupplierIn(BaseModel):
    key: str
    name: str
    country: str = "BR"
    car_number: str | None = None
    tax_id: str | None = None
    contact: str | None = None
    municipality: str | None = None
    state: str | None = None


class PlotIn(BaseModel):
    name: str
    supplier_key: str
    feature_index: int | None = Field(default=None, description="index into FEATURES, or null if no geometry")
    declared_area_ha: float | None = None
    production_start: date | None = None
    production_end: date | None = None
    declared_yield_t_ha: float | None = None


class LotIn(BaseModel):
    reference: str
    tonnes: float
    plot_names: list[str] = Field(default_factory=list)
    supplier_keys_without_plots: list[str] = Field(default_factory=list)
    silo: str | None = None
    destination: str | None = None


class GapIn(BaseModel):
    kind: str = Field(description="missing_polygon | missing_production_window | missing_supplier_id | missing_document | other")
    subject: str
    description: str
    owner: str = "supplier"


class CaseDelta(BaseModel):
    operator: str
    commodity: str = "soya"
    origin_country: str = "BR"
    destination: str | None = None
    shipment_window: str | None = None
    suppliers: list[SupplierIn]
    plots: list[PlotIn]
    lots: list[LotIn]
    gaps: list[GapIn] = Field(default_factory=list)
    notes: str | None = None


def build_prompt(brief: str, features: list[dict], tables: dict[str, list[dict]], doc_texts: dict[str, str]) -> str:
    feat_view = [{"feature_index": i, "geometry_type": (f.get("geometry") or {}).get("type"),
                  **{k: v for k, v in f.items() if k != "geometry"}} for i, f in enumerate(features)]
    parts = [f"BRIEF:\n{brief or '(none)'}", f"FEATURES (geometry stripped):\n{json.dumps(feat_view, ensure_ascii=False, default=str)[:30000]}"]
    for name, rows in tables.items():
        parts.append(f"TABLE {name}:\n{json.dumps(rows[:300], ensure_ascii=False, default=str)[:20000]}")
    for name, txt in doc_texts.items():
        parts.append(f"DOCUMENT {name}:\n{txt[:6000]}")
    parts.append("Produce the CaseDelta.")
    return "\n\n".join(parts)


def run_intake(brief: str, features: list[dict], tables: dict[str, list[dict]], doc_texts: dict[str, str], ledger: Ledger | None = None) -> CaseDelta:
    return run_agent("intake", SYSTEM, build_prompt(brief, features, tables, doc_texts), CaseDelta,
                     model=settings.model_fast, prompt_version=PROMPT_VERSION, ledger=ledger)
