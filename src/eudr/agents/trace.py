"""Trace agent: reads manifests/certificates the regex parser can't, returns edges with quoted snippets for citation."""
from __future__ import annotations

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger

PROMPT_VERSION = "trace-1"
SYSTEM = """You extract a soya chain of custody from manifests and traceability certificates (often Portuguese/Spanish).
Output every movement as an edge: source name, target name, tonnes, lot reference, document reference, period, and the exact
quoted line (verbatim from the text, ≤160 chars) that states it — this quote is used to draw a bounding box on the PDF, so it
must match the text character-for-character. Tiers: farm, silo, cooperative, crusher, trader, exporter, port. Do not infer
movements that are not written. Tonnes as a number (1.300 t in Portuguese = 1300)."""


class EdgeOut(BaseModel):
    source: str
    source_tier: str
    target: str
    target_tier: str
    tonnes: float
    lot_reference: str | None = None
    doc_ref: str | None = None
    period: str | None = None
    quote: str
    file: str


class TraceOut(BaseModel):
    edges: list[EdgeOut] = Field(default_factory=list)
    notes: str | None = None


def run_trace(texts: dict[str, str], ledger: Ledger | None = None) -> TraceOut:
    prompt = "\n\n".join(f"FILE {k}:\n{v[:20000]}" for k, v in texts.items()) + "\n\nExtract all edges."
    return run_agent("trace", SYSTEM, prompt, TraceOut, model=settings.model_fast, prompt_version=PROMPT_VERSION, ledger=ledger)
