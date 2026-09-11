"""Reg-watch: turns fetched guidance changes into a rule-pack proposal a human can approve."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.rules import RULE_PACK

PROMPT_VERSION = "regwatch-1"
SYSTEM = """You monitor EU deforestation regulation guidance for a compliance engine. Given page excerpts that changed since the last
check and the current rule pack, say whether anything affects the engine's rules (cut-off date, forest definition, geolocation/polygon
thresholds, country benchmarking, DDS obligations, application dates, product scope for soya). Propose concrete parameter changes
with the source. If the change is irrelevant (layout, news), say relevant=false."""


class RulePackProposal(BaseModel):
    relevant: bool
    summary: str
    proposed_changes: list[str] = Field(default_factory=list)
    affected_rules: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


def assess_changes(changes: list[dict]) -> RulePackProposal:
    rp = {k: getattr(RULE_PACK, k) for k in RULE_PACK.__dataclass_fields__}
    return run_agent("regwatch", SYSTEM, f"CURRENT RULE PACK:\n{json.dumps(rp, default=str)}\n\nCHANGES:\n{json.dumps(changes, ensure_ascii=False)[:40000]}",
                     RulePackProposal, model=settings.model_fast, prompt_version=PROMPT_VERSION)
