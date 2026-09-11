"""Legality Analyst: documents + overlay findings → checklist per supplier."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case

PROMPT_VERSION = "legality-1"
SYSTEM = """You assess legality of production under EUDR Art. 2(40) for a soya supplier in the stated country: land-use rights and
tenure, environmental law (Brazil: CAR registration, legal reserve/APP, IBAMA embargoes, licensing), labour and human rights
(slave-labour list, FPIC where indigenous/quilombola lands are involved), tax/anti-corruption/trade only where documents speak to them.
Use only the document text and overlay findings given. Mark each requirement met / missing / concern with the evidence you relied on.
Missing documents are gaps, not violations. For every item backed by a document, give the file name and a verbatim quote (character-for-character, ≤160 chars) from the [[file pN]] text. A blocking overlay (indigenous land, conservation unit, embargo) is a concern until refuted."""


class ChecklistItem(BaseModel):
    requirement: str
    status: str = Field(description="met | missing | concern")
    evidence: str
    subject_ref: str
    file: str | None = Field(default=None, description="document file name the evidence comes from, if any")
    quote: str | None = Field(default=None, description="verbatim text (≤160 chars) from that document supporting the evidence; used for a PDF bounding-box citation")


class LegalityChecklist(BaseModel):
    supplier_id: str
    items: list[ChecklistItem]
    blocking: bool
    summary: str


def run_legality(case: Case, supplier_id: str, doc_texts: dict[str, str], ledger: Ledger | None = None) -> LegalityChecklist:
    s = case.supplier(supplier_id)
    plots = [p.id for p in case.plots if p.supplier_id == supplier_id]
    findings = [f.model_dump() for f in case.legality if f.subject_ref in plots or f.subject_ref == supplier_id]
    prompt = "\n\n".join([
        f"SUPPLIER: {s.model_dump_json()}", f"COUNTRY: {s.country}", f"OVERLAY FINDINGS: {json.dumps(findings, ensure_ascii=False)}",
        *[f"DOCUMENT {k}:\n{v[:8000]}" for k, v in doc_texts.items()], "Produce the LegalityChecklist."])
    return run_agent("legality", SYSTEM, prompt, LegalityChecklist, model=settings.model_fast, prompt_version=PROMPT_VERSION, ledger=ledger)
