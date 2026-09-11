"""Exception Ledger: one list of everything a reviewer must look at, with citations and evidence."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from eudr.config import settings
from eudr.models import Case, ExceptionItem, Verdict

SEV = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def build_exceptions(case: Case) -> list[ExceptionItem]:
    out: list[ExceptionItem] = []
    label = {p.id: p.name or p.id for p in case.plots} | {s.id: s.name for s in case.suppliers} | {l.id: l.reference for l in case.lots}
    for g in case.open_gaps():
        if g.kind == "volume_mismatch":
            continue  # reported from volume_checks with the lot label
        sev = "major" if g.kind in ("missing_polygon", "point_for_plot_over_4ha", "invalid_geometry") else "minor"
        out.append(ExceptionItem(category="geolocation" if "geometry" in g.kind or "polygon" in g.kind or "4ha" in g.kind else "documentation",
                                 severity=sev, subject_ref=g.subject_ref, subject_label=label.get(g.subject_ref, g.subject_ref), detail=g.description, owner=g.owner))
    for p in case.plots:
        a = case.assessment_for(p.id)
        if not a or a.final_verdict == Verdict.PASS:
            continue
        m = a.metrics
        detail = (f"{a.final_verdict}: forest at cut-off {m.forest_2020_ha} ha, loss after cut-off {m.loss_after_cutoff_ha} ha, converted {m.converted_ha} ha"
                  + (f", first loss {m.first_loss_year}" if m and m.first_loss_year else "")) if m else str(a.final_verdict)
        if a.analyst_opinion:
            detail += f". Analyst: {a.analyst_opinion.recommended_verdict} ({a.analyst_opinion.confidence:.2f}) — {a.analyst_opinion.rationale[:240]}"
        out.append(ExceptionItem(category="deforestation", severity="critical" if a.final_verdict == Verdict.CRITICAL else "major", subject_ref=p.id,
                                 subject_label=label[p.id], detail=detail, owner="analyst" if not a.reviewer else "operator",
                                 status="acknowledged" if a.reviewer else "open", evidence_uris=[e.uri for e in a.evidence if e.type != "dataset"]))
    for p in case.plots:
        a = case.assessment_for(p.id)
        if a and a.metrics and a.metrics.native_vegetation_loss_ha >= 0.5:
            out.append(ExceptionItem(category="deforestation", severity="info", subject_ref=p.id, subject_label=label[p.id], owner="operator",
                                     detail=f"Native (non-forest) vegetation converted after cut-off: {a.metrics.native_vegetation_loss_ha} ha. Not EUDR forest; relevant to buyer policies / Cerrado commitments."))
    for f in case.legality:
        out.append(ExceptionItem(category="legality", severity={"blocking": "critical", "warning": "major", "info": "info"}[f.severity], subject_ref=f.subject_ref,
                                 subject_label=label.get(f.subject_ref, f.subject_ref), detail=f.detail, owner="operator", citations=f.citations))
    for v in case.volume_checks:
        if v.flag:
            out.append(ExceptionItem(category="volume", severity="major", subject_ref=v.lot_id, subject_label=label.get(v.lot_id, v.lot_id), detail=v.detail))
    if case.trace:
        for c in case.trace.checks:
            if c.flag:
                cites = [e.citation for e in case.trace.edges if e.citation and (e.source == c.node_id or e.target == c.node_id)]
                out.append(ExceptionItem(category="traceability", severity="major", subject_ref=c.node_id or "chain", subject_label=next((n.name for n in case.trace.nodes if n.id == c.node_id), "chain"),
                                         detail=c.detail, citations=cites[:4]))
    for d in case.documents:
        if d.ocr_pages and not d.citations:
            out.append(ExceptionItem(category="documentation", severity="minor", subject_ref=d.id, subject_label=Path(d.path).name, owner="analyst",
                                     detail=f"{d.ocr_pages} scanned page(s) yielded no recognisable fields; manual read needed."))
    if case.dossier and case.dossier.critic_report:
        for i in case.dossier.critic_report.get("issues", []):
            out.append(ExceptionItem(category="review", severity={"blocking": "critical", "major": "major", "minor": "minor"}.get(i.get("severity"), "minor"),
                                     subject_ref=i.get("subject_ref", "case"), subject_label=label.get(i.get("subject_ref"), i.get("subject_ref", "case")), detail=i.get("detail", ""), owner="analyst"))
    out.sort(key=lambda x: (SEV.get(x.severity, 9), x.category))
    return out


def export(case: Case) -> dict[str, str]:
    d = settings.data_dir / "cases" / case.id
    d.mkdir(parents=True, exist_ok=True)
    js = d / "exception_ledger.json"; cs = d / "exception_ledger.csv"
    js.write_text(json.dumps([e.model_dump(mode="json") for e in case.exceptions], indent=1, ensure_ascii=False))
    with open(cs, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "severity", "category", "subject", "detail", "owner", "status", "citations", "evidence"])
        for e in case.exceptions:
            w.writerow([e.id, e.severity, e.category, e.subject_label, e.detail, e.owner, e.status,
                        "; ".join(f"{c.file} p{c.page} {c.bbox}" for c in e.citations), "; ".join(Path(u).name for u in e.evidence_uris)])
    return {"json": str(js), "csv": str(cs)}
