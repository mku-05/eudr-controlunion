"""The case state machine. Each step persists the case and writes the ledger; agents are optional per settings."""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from eudr.config import settings
from eudr.db import CaseStore
from eudr.ledger import Ledger, sha256_json
from eudr.models import (AnalystOpinion, Assessment, Case, CaseStatus, Dossier, Gap, GapKind, Acknowledgement, Verdict)
from eudr.rules import RULE_PACK
from eudr.tools.alerts.monitor import pending_alerts
from eudr.tools.comms import outreach
from eudr.tools.dds.draft import draft_dds
from eudr.tools.dds.submit import submit as dds_submit
from eudr.tools.docs.extract import extract_text
from eudr.tools.docs.pipeline import pages_for, process_documents
from eudr.tools.trace.chain import link_suppliers, parse_chain, reconcile as trace_reconcile
from eudr.workflow.exceptions import build_exceptions, export as export_exceptions
from eudr.tools.geo.evidence import build_evidence
from eudr.tools.geo.parse import parse_file
from eudr.tools.geo.providers import get_provider
from eudr.tools.geo.screen import screen
from eudr.tools.geo.validate import validate_case_plots
from eudr.tools.legal.overlay import run_overlays
from eudr.tools.risk.score import score as risk_score
from eudr.tools.volume.reconcile import reconcile
from eudr.workflow.intake_map import apply_delta, load_folder, map_deterministic

_store: CaseStore | None = None


def store() -> CaseStore:
    global _store
    if _store is None:
        _store = CaseStore()
    return _store


def try_agent(led: Ledger, name: str, fn, fallback=None):
    """Run an agent step; on failure record it in the ledger and use the fallback instead of aborting the case."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — any agent failure degrades to the deterministic path
        led.append("agent_error", name, {"error": str(e)[:500]})
        return fallback() if callable(fallback) else fallback


def agents_on() -> bool:
    import os
    return os.environ.get("EUDR_AGENTS", "1") not in ("0", "false", "no")


def _provider(case: Case):
    if settings.geo_provider == "mock":
        from eudr.tools.geo.providers.mock import MockProvider, _geom_key
        return MockProvider({_geom_key(p.geometry): p.scenario for p in case.plots if p.geometry and p.scenario})
    return get_provider()


def _set_status(case: Case, led: Ledger, status: CaseStatus, why: str = "") -> None:
    led.append("state_change", "engine", {"from": case.status, "to": status, "why": why})
    case.status = status
    store().save(case)


# ---------- intake ----------
def create_case(folder: str | Path, operator: str | None = None, use_agent: bool | None = None) -> Case:
    folder = Path(folder)
    brief, features, tables, docs = load_folder(folder)
    case = map_deterministic(operator, brief, features, tables)
    led = Ledger(case.id)
    led.append("tool_call", "intake.load_folder", {"folder": str(folder), "features": len(features), "tables": list(tables), "docs": list(docs)})
    texts = process_documents(case, folder)
    led.append("tool_call", "docs.process", {"documents": [(Path(d.path).name, d.kind, d.pages, d.ocr_pages, len(d.citations)) for d in case.documents]})
    if (agents_on() if use_agent is None else use_agent):
        from eudr.agents.intake import run_intake
        delta = try_agent(led, "intake", lambda: run_intake(brief, features, tables, texts, ledger=led))
        if delta is not None:
            case = apply_delta(case, delta, features)
        if operator:
            case.operator = operator
    for d in case.documents:
        d.supplier_id = next((s.id for s in case.suppliers if s.tax_id and s.tax_id in texts.get(Path(d.path).name, "")), None)
    store().save(case)
    _set_status(case, led, CaseStatus.COLLECTING, "intake complete")
    return case


# ---------- collect ----------
def collect(case: Case, led: Ledger) -> Case:
    existing = {(g.kind, g.subject_ref) for g in case.gaps}
    for g in validate_case_plots(case):
        if (g.kind, g.subject_ref) not in existing:
            case.gaps.append(g)
    led.append("tool_call", "geo.validate", {"open_gaps": len(case.open_gaps())})
    _ingest_replies(case, led)
    open_sup = [g for g in case.open_gaps() if g.owner == "supplier"]
    already = {e["payload"].get("gap_ids_key") for e in led.entries() if e["actor"] == "comms.send"}
    if open_sup and agents_on():
        from eudr.agents.collector import draft_outreach
        key = sha256_json(sorted(g.id for g in open_sup))
        if key not in already:
            drafted = try_agent(led, "collector", lambda: draft_outreach(case, open_sup, ledger=led))
            for m in (drafted.messages if drafted else []):
                p = outreach.send(case.id, m.to, m.subject, m.body, m.gap_ids)
                led.append("tool_call", "comms.send", {"to": m.to, "path": p, "gap_ids": m.gap_ids, "gap_ids_key": key})
    elif open_sup:
        key = sha256_json(sorted(g.id for g in open_sup))
        if key not in already:
            by_sup: dict[str, list[Gap]] = {}
            for g in open_sup:
                sid = g.subject_ref if any(s.id == g.subject_ref for s in case.suppliers) else next((p.supplier_id for p in case.plots if p.id == g.subject_ref), None)
                if sid:
                    by_sup.setdefault(sid, []).append(g)
            for sid, gs in by_sup.items():
                s = case.supplier(sid)
                body = "Prezado(a) " + s.name + ",\n\nPara atender ao EUDR precisamos de:\n" + "\n".join(f"- {g.description}" for g in gs) + "\n\nFormatos aceitos: KML, GeoJSON, shapefile ou número do CAR. Prazo: 10 dias.\n\nEquipe de Due Diligence EUDR"
                p = outreach.send(case.id, s.contact or "(sem contato)", "EUDR — informações pendentes", body, [g.id for g in gs])
                led.append("tool_call", "comms.send", {"to": s.contact, "path": p, "gap_ids": [g.id for g in gs], "gap_ids_key": key})
    store().save(case)
    return case


def _ingest_replies(case: Case, led: Ledger) -> None:
    seen = {e["payload"].get("file") for e in led.entries() if e["actor"] == "comms.reply"}
    for f in outreach.replies(case.id):
        if str(f) in seen:
            continue
        gap = next((g for g in case.open_gaps() if g.id in f.name), None)
        resolved, note = False, ""
        if f.suffix.lower() in (".geojson", ".json", ".kml", ".zip", ".shp"):
            try:
                feats = parse_file(f)
            except Exception as e:
                feats, note = [], f"unparseable: {e}"
            if feats and gap:
                target = next((p for p in case.plots if p.id == gap.subject_ref), None)
                if target is None:
                    from eudr.models import Plot
                    sid = gap.subject_ref
                    for i, ft in enumerate(feats):
                        case.plots.append(Plot(supplier_id=sid, name=ft.get("nome") or ft.get("name") or f"{f.stem}-{i}", geometry=ft["geometry"],
                                               geometry_source=f"reply:{f.name}"))
                else:
                    target.geometry, target.geometry_source = feats[0]["geometry"], f"reply:{f.name}"
                resolved, note = True, f"geometry from {f.name}"
        elif gap and agents_on():
            from eudr.agents.collector import parse_reply
            r = try_agent(led, "collector", lambda: parse_reply(gap, extract_text(f), ledger=led))
            resolved, note = (r.resolved, r.resolution) if r else (False, "agent unavailable; manual read needed")
        if gap and resolved:
            gap.resolved, gap.resolution = True, note
        led.append("tool_call", "comms.reply", {"file": str(f), "gap": gap.id if gap else None, "resolved": resolved, "note": note})


# ---------- screen ----------
def _screen_one(case_id: str, p, prov, with_imagery: bool):
    geom = _screenable_geometry(p)
    if geom is None:
        return None
    r = prov.rasters(geom)
    v, conf, reason, m, layers = screen(r)
    if not r.loss_sources and v == Verdict.CRITICAL:
        v, conf, reason = Verdict.EXCEPTION, 0.6, reason + " Single loss source — analyst confirmation required."
    ev = build_evidence(case_id, p, r, layers, prov, with_imagery=with_imagery)
    a = Assessment(subject_ref=p.id, rule_pack_version=RULE_PACK.version, verdict=v, confidence=conf, metrics=m, evidence=ev)
    a.hash = sha256_json(a.model_dump(mode="json", exclude={"hash"}))
    return a, reason, r.dataset_versions


def screen_case(case: Case, led: Ledger, with_imagery: bool = True) -> Case:
    prov = _provider(case)
    todo = [p for p in case.plots if p.geometry and not (
        (prev := case.assessment_for(p.id)) and prev.rule_pack_version == RULE_PACK.version and not _needs_rescreen(case, p.id))]
    with ThreadPoolExecutor(max_workers=settings.screen_workers) as pool:
        results = list(pool.map(lambda p: _screen_one(case.id, p, prov, with_imagery), todo))
    for p, res in zip(todo, results):
        if res is None:
            continue
        a, reason, versions = res
        case.assessments.append(a)
        led.append("tool_call", "geo.screen", {"plot": p.id, "verdict": a.verdict, "confidence": a.confidence, "reason": reason, "metrics": a.metrics.model_dump(),
                                              "datasets": versions, "evidence": [(e.type, e.sha256) for e in a.evidence], "assessment": a.id})
    store().save(case)
    return case


def _screenable_geometry(p) -> dict | None:
    """Points stand in for plots ≤ 4 ha only: screen a circle of the declared area."""
    if p.geometry.get("type") != "Point":
        return p.geometry
    area = p.declared_area_ha or 0
    if area <= 0 or area > RULE_PACK.polygon_required_over_ha:
        return None
    import math
    from shapely.geometry import mapping, shape
    r_deg = math.sqrt(area * 10_000 / math.pi) / 111_320
    return mapping(shape(p.geometry).buffer(r_deg))


def _needs_rescreen(case: Case, plot_id: str) -> bool:
    return any(a.get("plot_id") == plot_id for a in pending_alerts(case))


# ---------- adjudicate ----------
def adjudicate(case: Case, led: Ledger, qa_fraction: float = 0.05) -> Case:
    rng = random.Random(case.id)
    todo = []
    for p in case.plots:
        a = case.assessment_for(p.id)
        if not a or a.reviewer or a.analyst_opinion:
            continue
        if a.verdict in (Verdict.EXCEPTION, Verdict.CRITICAL) or rng.random() < qa_fraction:
            reason = next((e["payload"]["reason"] for e in reversed(led.entries()) if e["actor"] == "geo.screen" and e["payload"].get("assessment") == a.id), "")
            todo.append((p, a, reason))

    def opinion(item):
        p, a, reason = item
        carry = lambda why: AnalystOpinion(model="none", prompt_version="skip", recommended_verdict=a.verdict, confidence=a.confidence,
                                           rationale=f"{why} — engine flag carried forward", flags=[why.replace(" ", "_")])
        if not agents_on():
            return carry("agents disabled")
        from eudr.agents.geo_analyst import run_geo_analyst
        return try_agent(led, "geo_analyst", lambda: run_geo_analyst(p, a, reason, ledger=led), lambda: carry("analyst unavailable"))

    with ThreadPoolExecutor(max_workers=settings.agent_workers) as pool:
        opinions = list(pool.map(opinion, todo))
    for (p, a, _), op in zip(todo, opinions):
        a.analyst_opinion = op
        auto = (a.verdict == Verdict.EXCEPTION and op.recommended_verdict == Verdict.PASS and op.confidence >= settings.analyst_auto_accept_confidence)
        if auto:
            a.override_verdict, a.override_reason, a.reviewer = Verdict.PASS, f"auto-accepted analyst opinion ({op.confidence:.2f}): {op.rationale[:200]}", "system:geo_analyst"
            a.reviewed_at = datetime.now(timezone.utc)
        led.append("agent_step" if agents_on() else "tool_call", "adjudicate", {"plot": p.id, "assessment": a.id, "recommended": op.recommended_verdict,
                                                                                  "confidence": op.confidence, "auto_accepted": auto})
    store().save(case)
    return case


def review_queue(case_id: str) -> list[dict]:
    case = store().get(case_id)
    out = []
    for p in case.plots:
        a = case.assessment_for(p.id)
        if a and a.reviewer is None and a.verdict in (Verdict.EXCEPTION, Verdict.CRITICAL):
            out.append({"assessment_id": a.id, "plot_id": p.id, "plot": p.name, "verdict": a.verdict, "confidence": a.confidence,
                        "metrics": a.metrics.model_dump() if a.metrics else None,
                        "analyst": a.analyst_opinion.model_dump() if a.analyst_opinion else None,
                        "evidence": [e.uri for e in a.evidence if e.type != "dataset"]})
    return out


def approve(case_id: str, assessment_id: str, reviewer: str, note: str = "") -> Assessment:
    case = store().get(case_id); led = Ledger(case_id)
    a = next(x for x in case.assessments if x.id == assessment_id)
    a.reviewer, a.reviewed_at = reviewer, datetime.now(timezone.utc)
    if note:
        a.override_reason = note
    led.append("human_action", reviewer, {"action": "approve", "assessment": a.id, "verdict": a.final_verdict, "note": note})
    store().save(case)
    return a


def override(case_id: str, assessment_id: str, verdict: Verdict, reason: str, reviewer: str) -> Assessment:
    if not reason or len(reason) < 10:
        raise ValueError("override needs a justification")
    case = store().get(case_id); led = Ledger(case_id)
    a = next(x for x in case.assessments if x.id == assessment_id)
    a.override_verdict, a.override_reason, a.reviewer, a.reviewed_at = verdict, reason, reviewer, datetime.now(timezone.utc)
    led.append("human_action", reviewer, {"action": "override", "assessment": a.id, "from": a.verdict, "to": verdict, "reason": reason})
    store().save(case)
    return a


# ---------- legality, volume, risk ----------
def _doc_texts(case: Case, kinds: tuple[str, ...] | None = None) -> dict[str, str]:
    from eudr.tools.docs.citations import marked_text
    out = {}
    for d in case.documents:
        if kinds and d.kind not in kinds:
            continue
        pages = pages_for(d)
        out[Path(d.path).name] = marked_text(pages) if pages else extract_text(d.path)
    return out


def trace_chain(case: Case, led: Ledger) -> Case:
    from eudr.tools.docs.citations import cite_snippet
    texts = _doc_texts(case, ("coc_manifest", "trace_certificate"))
    if not texts:
        return case
    cite_dir = settings.data_dir / "cases" / case.id / "docs" / "citations"
    pages = {Path(d.path).name: pages_for(d) for d in case.documents if d.kind in ("coc_manifest", "trace_certificate")}
    chain = parse_chain(texts, pages, cite_dir)
    if agents_on() and len(chain.edges) < 2:
        from eudr.agents.trace import run_trace
        from eudr.models import TraceEdge, TraceNode
        out = try_agent(led, "trace", lambda: run_trace(texts, ledger=led))
        nodes: dict[str, TraceNode] = {}
        for e in (out.edges if out else []):
            for nm, tier in ((e.source, e.source_tier), (e.target, e.target_tier)):
                if nm not in nodes:
                    nodes[nm] = TraceNode(id=f"node_{len(nodes) + 1}", name=nm, tier=tier)
            edge = TraceEdge(source=nodes[e.source].id, target=nodes[e.target].id, tonnes=e.tonnes, lot_reference=e.lot_reference, doc_ref=e.doc_ref, period=e.period)
            if e.file in pages:
                edge.citation = cite_snippet(pages[e.file], "trace_edge", e.quote, cite_dir)
            chain.edges.append(edge)
        if out:
            chain.nodes = list(nodes.values()); chain.source_docs = list(texts)
    link_suppliers(chain, case)
    chain.checks = trace_reconcile(chain, case)
    case.trace = chain
    led.append("tool_call", "trace.reconcile", {"nodes": len(chain.nodes), "edges": len(chain.edges), "flags": [c.detail for c in chain.checks if c.flag]})
    store().save(case)
    return case


def legality_and_risk(case: Case, led: Ledger) -> Case:
    case.legality = run_overlays(case)
    led.append("tool_call", "legal.overlay", {"findings": len(case.legality), "blocking": sum(f.severity == "blocking" for f in case.legality)})
    trace_chain(case, led)
    if agents_on() and case.documents:
        from eudr.agents.legality import run_legality
        from eudr.models import LegalityFinding
        from eudr.tools.docs.citations import cite_snippet
        cite_dir = settings.data_dir / "cases" / case.id / "docs" / "citations"
        all_texts = _doc_texts(case)
        jobs = []
        for s in case.suppliers:
            names = [Path(d.path).name for d in case.documents if d.supplier_id == s.id]
            docs = {n: all_texts[n] for n in names if n in all_texts}
            if docs:
                jobs.append((s, docs))
        with ThreadPoolExecutor(max_workers=settings.agent_workers) as pool:
            results = list(pool.map(lambda j: try_agent(led, "legality", lambda: run_legality(case, j[0].id, j[1], ledger=led)), jobs))
        for (s, _), cl in zip(jobs, results):
            for it in (cl.items if cl else []):
                if it.status in ("missing", "concern"):
                    f = LegalityFinding(layer=f"doc:{it.requirement}", severity="warning" if it.status == "concern" else "info",
                                        subject_ref=s.id, detail=f"{it.status}: {it.evidence}")
                    doc = next((d for d in case.documents if Path(d.path).name == it.file), None) if it.file else None
                    if doc and it.quote:
                        c = cite_snippet(pages_for(doc), it.requirement[:30], it.quote, cite_dir)
                        if c:
                            f.citations.append(c)
                    case.legality.append(f)
    case.volume_checks = reconcile(case)
    for v in case.volume_checks:
        if v.flag and not any(g.kind == GapKind.VOLUME_MISMATCH and g.subject_ref == v.lot_id for g in case.gaps):
            case.gaps.append(Gap(kind=GapKind.VOLUME_MISMATCH, subject_ref=v.lot_id, owner="operator", description=v.detail))
    led.append("tool_call", "volume.reconcile", {"flags": [v.lot_id for v in case.volume_checks if v.flag]})
    case.risk = risk_score(case)
    led.append("tool_call", "risk.score", {"score": case.risk.score, "level": case.risk.criteria["level"]})
    if agents_on():
        from eudr.agents.drafter import run_drafter
        d = try_agent(led, "drafter", lambda: run_drafter(case, ledger=led))
        if d:
            case.risk.narrative, case.risk.mitigation = d.risk_narrative, d.mitigation
            case.intake_notes = (case.intake_notes or "") + "\n\nCLIENT SUMMARY:\n" + d.client_summary
    store().save(case)
    return case


# ---------- dossier ----------
def draft_dossier(case: Case, led: Ledger) -> Case:
    from eudr.dossier.pack import build_pack
    payload = draft_dds(case, led.entries()[-1]["hash"] if led.entries() else "")
    critic = None
    if agents_on():
        from eudr.agents.critic import run_critic
        rep = try_agent(led, "critic", lambda: run_critic(case, payload, ledger=led))
        critic = rep.model_dump() if rep else None
    if critic is None:
        blocking = [f"{p.id}: {a.final_verdict} without reviewer" for p in case.plots if (a := case.assessment_for(p.id)) and a.final_verdict != Verdict.PASS and not a.reviewer]
        critic = {"ok": not blocking, "issues": [{"severity": "blocking", "subject_ref": b.split(":")[0], "detail": b} for b in blocking], "unsupported_claims": [],
                  "summary": "deterministic critic" + ("" if not agents_on() else " (agent critic unavailable)")}
    case.dossier = Dossier(summary=_summary_text(case), dds_payload=payload, critic_report=critic)
    case.exceptions = build_exceptions(case)
    led.append("tool_call", "exceptions.build", {"count": len(case.exceptions), **export_exceptions(case)})
    path = build_pack(case, led)
    case.dossier.evidence_pack_path = str(path)
    case.dossier.hash = sha256_json({"dds": payload, "critic": critic, "ledger_head": led.entries()[-1]["hash"], "pack": str(path)})
    led.append("tool_call", "dossier.build", {"path": str(path), "hash": case.dossier.hash, "critic_ok": critic["ok"]})
    store().save(case)
    return case


def _summary_text(case: Case) -> str:
    counts = {v: 0 for v in Verdict}
    for p in case.plots:
        a = case.assessment_for(p.id)
        if a:
            counts[a.final_verdict] += 1
    no_geom = sum(1 for p in case.plots if not p.geometry)
    parts = [f"{counts[Verdict.PASS]} PASS, {counts[Verdict.EXCEPTION]} EXCEPTION, {counts[Verdict.CRITICAL]} CRITICAL plots; {no_geom} without geometry;",
             f"{len(case.open_gaps())} open gaps; {sum(f.severity == 'blocking' for f in case.legality)} blocking legality findings;",
             f"traceability flags: {sum(c.flag for c in case.trace.checks) if case.trace else 0}; volume flags: {[v.lot_id for v in case.volume_checks if v.flag]};",
             f"risk {case.risk.criteria['level'] if case.risk else 'n/a'}."]
    return " ".join(parts)


# ---------- sign & submit ----------
def acknowledge(case_id: str, reviewer: str, acknowledge_critic: bool = False) -> Case:
    case = store().get(case_id); led = Ledger(case_id)
    if case.status != CaseStatus.AWAITING_ACK or not case.dossier:
        raise ValueError(f"case is {case.status}, not awaiting acknowledgement")
    unreviewed = [p.id for p in case.plots if (a := case.assessment_for(p.id)) and a.final_verdict != Verdict.PASS and not a.reviewer]
    if unreviewed:
        raise ValueError(f"unreviewed non-PASS plots: {unreviewed}")
    if not case.dossier.critic_report.get("ok") and not acknowledge_critic:
        raise ValueError("critic report not ok; pass acknowledge_critic=True to acknowledge anyway")
    case.acknowledgement = Acknowledgement(reviewer=reviewer, dossier_hash=case.dossier.hash,
                                           statement="I acknowledge this advisory evidence dossier. Conformity decisions remain with Control Union's accredited reviewers.")
    led.append("human_action", reviewer, {"action": "acknowledge", "dossier_hash": case.dossier.hash, "critic_ok": case.dossier.critic_report.get("ok"), "critic_acknowledged": acknowledge_critic})
    if not settings.pilot_mode:
        res = dds_submit(case.id, {**case.dossier.dds_payload, "acknowledgement": case.acknowledgement.model_dump(mode="json")})
        case.dds_reference = res["reference"]
        led.append("tool_call", "dds.submit", res)
    _set_status(case, led, CaseStatus.ACKNOWLEDGED, "dossier acknowledged" + ("" if settings.pilot_mode else "; DDS submitted"))
    _set_status(case, led, CaseStatus.MONITORING, "plots under alert watch")
    return case


# ---------- monitor ----------
def monitor(case_id: str) -> dict:
    case = store().get(case_id); led = Ledger(case_id)
    alerts = pending_alerts(case)
    if not alerts:
        return {"alerts": 0, "rescreened": []}
    led.append("tool_call", "alerts.pending", {"alerts": alerts})
    before = {p.id: (a.final_verdict if (a := case.assessment_for(p.id)) else None) for p in case.plots}
    screen_case(case, led)
    changed = [pid for pid, v in before.items() if (a := case.assessment_for(pid)) and a.final_verdict != v]
    from eudr.tools.alerts.monitor import inbox_path
    inbox_path().write_text("")
    if changed:
        _set_status(case, led, CaseStatus.ADJUDICATING, f"alerts changed verdicts on {changed}")
        outreach.send(case.id, case.operator, "EUDR alert: plot status changed", f"Plots {changed} changed verdict after new alerts; case reopened.", [])
    return {"alerts": len(alerts), "rescreened": [a["plot_id"] for a in alerts], "changed": changed}


# ---------- run loop ----------
def run(case_id: str, with_imagery: bool = True) -> dict:
    case = store().get(case_id); led = Ledger(case_id)
    steps = []
    while True:
        st = case.status
        if st in (CaseStatus.INTAKE, CaseStatus.COLLECTING):
            collect(case, led)
            steps.append("collect")
            _set_status(case, led, CaseStatus.SCREENING, f"{len(case.open_gaps())} open gaps; proceeding with plots that have geometry")
        elif st == CaseStatus.SCREENING:
            screen_case(case, led, with_imagery=with_imagery); steps.append("screen")
            _set_status(case, led, CaseStatus.ADJUDICATING)
        elif st == CaseStatus.ADJUDICATING:
            adjudicate(case, led); steps.append("adjudicate")
            _set_status(case, led, CaseStatus.DRAFTING)
        elif st == CaseStatus.DRAFTING:
            legality_and_risk(case, led); draft_dossier(case, led); steps.append("draft")
            _set_status(case, led, CaseStatus.AWAITING_ACK)
        elif st == CaseStatus.AWAITING_ACK:
            q = review_queue(case.id)
            return {"case": case.id, "status": st, "steps": steps, "needs_human": {"review": len(q), "acknowledge": not q}, "summary": case.dossier.summary if case.dossier else ""}
        elif st in (CaseStatus.ACKNOWLEDGED, CaseStatus.MONITORING):
            return {"case": case.id, "status": st, "steps": steps, "dds_reference": case.dds_reference, **monitor(case.id)}
        else:
            return {"case": case.id, "status": st, "steps": steps}


def redraft(case_id: str) -> dict:
    case = store().get(case_id); led = Ledger(case_id)
    legality_and_risk(case, led); draft_dossier(case, led)
    return {"case": case.id, "critic_ok": case.dossier.critic_report.get("ok"), "summary": case.dossier.summary}


# ---------- read models ----------
def summary(case_id: str) -> dict:
    c = store().get(case_id)
    return {"id": c.id, "operator": c.operator, "status": c.status, "origin": c.origin_country, "destination": c.destination, "shipment": c.shipment_window,
            "suppliers": [{"id": s.id, "name": s.name, "car": s.car_number, "contact": s.contact} for s in c.suppliers],
            "plots": [{"id": p.id, "name": p.name, "supplier": c.supplier(p.supplier_id).name, "area_ha": p.computed_area_ha, "has_geometry": bool(p.geometry),
                       "verdict": (a.final_verdict if (a := c.assessment_for(p.id)) else None), "reviewer": (a.reviewer if a else None)} for p in c.plots],
            "lots": [l.model_dump() for l in c.lots], "open_gaps": [g.model_dump() for g in c.open_gaps()],
            "legality": [f.model_dump() for f in c.legality], "volume": [v.model_dump() for v in c.volume_checks],
            "risk": c.risk.model_dump() if c.risk else None, "dossier": (c.dossier.model_dump(exclude={"dds_payload"}) if c.dossier else None),
            "documents": [{"file": Path(d.path).name, "kind": d.kind, "pages": d.pages, "ocr_pages": d.ocr_pages, "citations": len(d.citations)} for d in c.documents],
            "trace": ({"nodes": len(c.trace.nodes), "edges": len(c.trace.edges), "flags": [x.detail for x in c.trace.checks if x.flag]} if c.trace else None),
            "exceptions": {"total": len(c.exceptions), "by_severity": {k: sum(1 for e in c.exceptions if e.severity == k) for k in ("critical", "major", "minor", "info")}},
            "dds_reference": c.dds_reference, "acknowledgement": c.acknowledgement.model_dump() if c.acknowledgement else None}


def explain_plot(case_id: str, plot_id: str) -> dict:
    c = store().get(case_id); p = c.plot(plot_id); a = c.assessment_for(plot_id)
    return {"plot": p.model_dump(exclude={"geometry"}), "assessment": a.model_dump() if a else None,
            "gaps": [g.model_dump() for g in c.gaps if g.subject_ref == plot_id]}


def exceptions(case_id: str) -> list[dict]:
    return [e.model_dump(mode="json") for e in store().get(case_id).exceptions]


def roi_report() -> dict:
    from eudr.reports import roi
    cases = [store().get(r["id"]) for r in store().list()]
    agg = roi.build(cases)
    return {**agg, "files": roi.write(agg)}


def ledger_tail(case_id: str, n: int = 20) -> list[dict]:
    return Ledger(case_id).entries()[-n:]
