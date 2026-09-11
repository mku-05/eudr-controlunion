"""Collector: writes supplier outreach for open gaps (PT-BR/ES) and reads replies."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case, Gap

PROMPT_VERSION = "collector-1"
SYSTEM = """You write short, polite supplier requests for an EUDR due-diligence team. Language: Portuguese (Brazil) for BR suppliers,
Spanish for AR/PY, English otherwise. One message per supplier covering all their gaps. Explain what is needed, why (EUDR, EU market
access from 30 Dec 2026), the accepted formats (KML/GeoJSON/shapefile, CAR number, planting and harvest dates), and a deadline of 10 days.
No legal threats. Sign as 'Equipe de Due Diligence EUDR'."""


class Message(BaseModel):
    supplier_id: str
    to: str
    subject: str
    body: str
    gap_ids: list[str]


class Outreach(BaseModel):
    messages: list[Message] = Field(default_factory=list)


class ReplyParse(BaseModel):
    gap_id: str
    resolved: bool
    resolution: str
    extracted: dict = Field(default_factory=dict)


def draft_outreach(case: Case, gaps: list[Gap], ledger: Ledger | None = None) -> Outreach:
    by_sup: dict[str, list[Gap]] = {}
    for g in gaps:
        sid = _supplier_for(case, g.subject_ref)
        if sid:
            by_sup.setdefault(sid, []).append(g)
    payload = [{"supplier_id": sid, "name": case.supplier(sid).name, "country": case.supplier(sid).country,
                "contact": case.supplier(sid).contact or "(no contact on file)",
                "gaps": [{"id": g.id, "kind": g.kind, "description": g.description} for g in gs]} for sid, gs in by_sup.items()]
    if not payload:
        return Outreach()
    return run_agent("collector", SYSTEM, f"OPERATOR: {case.operator}\nSUPPLIERS AND GAPS:\n{json.dumps(payload, ensure_ascii=False)}\nWrite the messages.",
                     Outreach, model=settings.model_fast, prompt_version=PROMPT_VERSION, ledger=ledger)


def parse_reply(gap: Gap, reply_text: str, ledger: Ledger | None = None) -> ReplyParse:
    return run_agent("collector", "You read a supplier's reply and decide whether it resolves the gap. Extract any dates, CAR numbers or file references.",
                     f"GAP: {gap.model_dump_json()}\nREPLY:\n{reply_text[:6000]}", ReplyParse, model=settings.model_fast,
                     prompt_version=PROMPT_VERSION, ledger=ledger)


def _supplier_for(case: Case, subject_ref: str) -> str | None:
    if any(s.id == subject_ref for s in case.suppliers):
        return subject_ref
    p = next((p for p in case.plots if p.id == subject_ref), None)
    return p.supplier_id if p else None
