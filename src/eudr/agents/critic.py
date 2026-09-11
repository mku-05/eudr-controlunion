"""Critic: adversarial pass before sign-off. Every claim must trace to a tool output or human action."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case

PROMPT_VERSION = "critic-1"
SYSTEM = """You are the adversarial reviewer before an EUDR due-diligence statement is signed. Find what would embarrass the signer in
front of a competent authority: plots in the DDS that are not PASS; CRITICALs or EXCEPTIONs without a named human reviewer; analyst opinions
that contradict metrics; open gaps hidden by the summary; lots whose tonnage exceeds what linked plots can yield; blocking legality
findings with no resolution; production dates outside the shipment logic; missing evidence files; dataset versions not recorded;
narrative claims not backed by numbers. Be specific: subject id + what is wrong. ok=true only if nothing blocking remains."""


class Issue(BaseModel):
    severity: str = Field(description="blocking | major | minor")
    subject_ref: str
    detail: str


class CriticReport(BaseModel):
    ok: bool
    issues: list[Issue] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    summary: str


def run_critic(case: Case, dds_payload: dict, ledger: Ledger | None = None) -> CriticReport:
    view = case.model_dump(mode="json")
    for a in view["assessments"]:
        a["evidence"] = [{"type": e["type"], "uri": e["uri"].rsplit("/", 1)[-1], "has_hash": bool(e["sha256"])} for e in a["evidence"]]
    for p in view["plots"]:
        p.pop("geometry", None)
    view["dds_excluded_plots"] = dds_payload.get("compliance", {}).get("excluded_plots")
    view["dds_plot_count"] = sum(len(x["geometries"]["features"]) for x in dds_payload.get("producers", []))
    view["ledger_entries"] = len(ledger.entries()) if ledger else None
    return run_agent("critic", SYSTEM, f"CASE (geometry stripped):\n{json.dumps(view, ensure_ascii=False, default=str)[:60000]}\nProduce the CriticReport.",
                     CriticReport, model=settings.model_reasoning, prompt_version=PROMPT_VERSION, ledger=ledger)
