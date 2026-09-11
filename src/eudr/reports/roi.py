"""Aggregate ROI report across cases. Office-level only: no per-reviewer timing or throughput, by design."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case, Verdict

ASSUMED_MANUAL_MINUTES = {"polygon_validated": 12, "plot_screened": 45, "page_read": 6, "citation_located": 4, "exception_triaged": 8}


def build(cases: list[Case]) -> dict:
    agg = {"cases": len(cases), "suppliers": 0, "plots": 0, "polygons_validated": 0, "plots_screened": 0, "flags": {v.value: 0 for v in Verdict},
           "pages_parsed": 0, "ocr_pages": 0, "citations": 0, "exceptions": 0, "exceptions_by_category": {}, "exceptions_by_severity": {},
           "agent_steps": 0, "tool_calls": 0, "human_actions": 0, "auto_accepted_exceptions": 0, "wall_minutes_total": 0.0}
    for c in cases:
        agg["suppliers"] += len(c.suppliers); agg["plots"] += len(c.plots)
        agg["polygons_validated"] += sum(1 for p in c.plots if p.geometry and p.computed_area_ha)
        for p in c.plots:
            a = c.assessment_for(p.id)
            if a:
                agg["plots_screened"] += 1; agg["flags"][a.final_verdict.value] += 1
                if a.reviewer and a.reviewer.startswith("system:"):
                    agg["auto_accepted_exceptions"] += 1
        agg["pages_parsed"] += sum(d.pages for d in c.documents); agg["ocr_pages"] += sum(d.ocr_pages for d in c.documents)
        agg["citations"] += sum(len(d.citations) for d in c.documents) + sum(len(e.citations) for e in c.exceptions)
        agg["exceptions"] += len(c.exceptions)
        for e in c.exceptions:
            agg["exceptions_by_category"][e.category] = agg["exceptions_by_category"].get(e.category, 0) + 1
            agg["exceptions_by_severity"][e.severity] = agg["exceptions_by_severity"].get(e.severity, 0) + 1
        entries = Ledger(c.id).entries()
        for e in entries:
            agg[{"agent_step": "agent_steps", "tool_call": "tool_calls", "human_action": "human_actions"}.get(e["kind"], "tool_calls")] += 1
        if len(entries) >= 2:
            t0, t1 = datetime.fromisoformat(entries[0]["ts"]), datetime.fromisoformat(entries[-1]["ts"])
            agg["wall_minutes_total"] += (t1 - t0).total_seconds() / 60
    est = {"polygon_validated": agg["polygons_validated"], "plot_screened": agg["plots_screened"], "page_read": agg["pages_parsed"],
           "citation_located": agg["citations"], "exception_triaged": agg["exceptions"]}
    agg["estimated_manual_hours"] = round(sum(ASSUMED_MANUAL_MINUTES[k] * v for k, v in est.items()) / 60, 1)
    agg["assumptions_minutes"] = ASSUMED_MANUAL_MINUTES
    agg["wall_minutes_total"] = round(agg["wall_minutes_total"], 1)
    agg["generated_at"] = datetime.now(timezone.utc).isoformat()
    agg["note"] = "Aggregate office-level figures only. No per-reviewer speed, time-per-task or performance metrics are computed or stored."
    return agg


def write(agg: dict, out_dir: Path | None = None) -> dict[str, str]:
    d = out_dir or (settings.data_dir / "reports")
    d.mkdir(parents=True, exist_ok=True)
    js = d / "roi_report.json"; md = d / "roi_report.md"
    js.write_text(json.dumps(agg, indent=1))
    lines = ["# EUDR pilot — ROI report (aggregate)", "", f"Generated {agg['generated_at']}", "",
             f"- Packages processed: **{agg['cases']}** ({agg['suppliers']} suppliers, {agg['plots']} plots)",
             f"- Polygons validated: **{agg['polygons_validated']}**; plots screened on satellite data: **{agg['plots_screened']}**",
             f"- Flags: " + ", ".join(f"{k} {v}" for k, v in agg["flags"].items()),
             f"- Pages parsed: **{agg['pages_parsed']}** (OCR: {agg['ocr_pages']}); visual citations: **{agg['citations']}**",
             f"- Exceptions raised: **{agg['exceptions']}** — by category " + json.dumps(agg["exceptions_by_category"]) + "; by severity " + json.dumps(agg["exceptions_by_severity"]),
             f"- Automated steps: {agg['tool_calls']} tool calls, {agg['agent_steps']} agent steps; human actions: {agg['human_actions']}",
             f"- Engine wall time: {agg['wall_minutes_total']} min total", "",
             f"## Estimated manual effort displaced: **{agg['estimated_manual_hours']} h**", "",
             "Assumed minutes per item (to be replaced by Control Union's own benchmarks in Phase 1): " + json.dumps(agg["assumptions_minutes"]), "",
             f"_{agg['note']}_"]
    md.write_text("\n".join(lines))
    return {"json": str(js), "md": str(md)}
