"""Drafter: Art. 10 narrative, mitigation, and the client-facing summary."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case

PROMPT_VERSION = "drafter-1"
SYSTEM = """You draft the risk-assessment narrative (EUDR Art. 10) and a client summary for a soya due-diligence case.
Write from the numbers given — plot verdicts, legality findings, volume checks, gaps, country risk. No new facts.
Narrative: 150–300 words, third person, regulator-readable, names the criteria considered. Mitigation: concrete actions tied to
specific plots/suppliers/gaps. Client summary: 5–8 short lines an exporter can act on today."""


class Drafts(BaseModel):
    risk_narrative: str
    mitigation: list[str] = Field(default_factory=list)
    client_summary: str


def run_drafter(case: Case, ledger: Ledger | None = None) -> Drafts:
    view = {
        "operator": case.operator, "country": case.origin_country, "destination": case.destination, "shipment": case.shipment_window,
        "risk": case.risk.model_dump() if case.risk else None,
        "plots": [{"id": p.id, "name": p.name, "supplier": case.supplier(p.supplier_id).name, "area_ha": p.computed_area_ha,
                   "verdict": (a.final_verdict if (a := case.assessment_for(p.id)) else None),
                   "metrics": (a.metrics.model_dump() if a and a.metrics else None),
                   "analyst": (a.analyst_opinion.rationale if a and a.analyst_opinion else None)} for p in case.plots],
        "legality": [f.model_dump() for f in case.legality], "volume": [v.model_dump() for v in case.volume_checks],
        "gaps": [g.model_dump() for g in case.open_gaps()],
    }
    return run_agent("drafter", SYSTEM, f"CASE:\n{json.dumps(view, ensure_ascii=False, default=str)[:40000]}\nProduce Drafts.",
                     Drafts, model=settings.model_fast, prompt_version=PROMPT_VERSION, ledger=ledger)
