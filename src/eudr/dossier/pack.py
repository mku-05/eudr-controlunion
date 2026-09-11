"""Evidence pack PDF + dossier.json for one case."""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import Case, Verdict
from eudr.rules import RULE_PACK

VCOL = {Verdict.PASS: colors.HexColor("#2E7D4F"), Verdict.EXCEPTION: colors.HexColor("#C7841A"), Verdict.CRITICAL: colors.HexColor("#B23A3A")}


def build_pack(case: Case, led: Ledger) -> Path:
    out = settings.data_dir / "cases" / case.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "dossier.json").write_text(case.model_dump_json(indent=1))
    pdf = out / "evidence_pack.pdf"
    ss = getSampleStyleSheet()
    h1, h2, body = ss["Heading1"], ss["Heading2"], ss["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    story = [Paragraph("EUDR Due Diligence — Evidence Pack (advisory)", h1),
             Paragraph("Automated evidence preparation and advisory analysis. Conformity decisions, certificate issuance and audit sign-off remain exclusively with Control Union's accredited reviewers.", small),
             Paragraph(f"Operator: {case.operator} · Commodity: {case.commodity} · Origin: {case.origin_country} · Destination: {case.destination or '-'}", body),
             Paragraph(f"Case {case.id} · Rule pack {RULE_PACK.version} · Cut-off {RULE_PACK.cutoff_date}", body),
             Paragraph(f"Ledger entries: {len(led.entries())} · Ledger head: {led.entries()[-1]['hash'][:16] if led.entries() else '-'}…", small), Spacer(1, 6 * mm)]
    if case.dossier:
        story += [Paragraph("Summary", h2), Paragraph(case.dossier.summary, body)]
    rows = [["Plot", "Supplier", "Area ha", "Forest 2020", "Loss", "Converted", "Flag", "Reviewer"]]
    for p in case.plots:
        a = case.assessment_for(p.id)
        m = a.metrics if a else None
        rows.append([p.name or p.id, case.supplier(p.supplier_id).name, f"{p.computed_area_ha or '-'}",
                     f"{m.forest_2020_ha}" if m else "-", f"{m.loss_after_cutoff_ha}" if m else "-", f"{m.converted_ha}" if m else "-",
                     a.final_verdict if a else "no geometry", (a.reviewer or "-") if a else "-"])
    t = Table(rows, repeatRows=1, colWidths=[42 * mm, 34 * mm, 16 * mm, 20 * mm, 14 * mm, 18 * mm, 18 * mm, 24 * mm])
    style = [("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEFE7"))]
    for i, r in enumerate(rows[1:], start=1):
        if r[6] in VCOL:
            style.append(("TEXTCOLOR", (6, i), (6, i), VCOL[r[6]]))
    t.setStyle(TableStyle(style))
    story += [Spacer(1, 4 * mm), Paragraph("Plot flags", h2), t, Spacer(1, 4 * mm)]
    if case.risk:
        story += [Paragraph("Risk assessment (Art. 10)", h2), Paragraph(f"Country risk: {case.risk.country_risk} · score {case.risk.score} · level {case.risk.criteria.get('level')}", body)]
        if case.risk.narrative:
            story.append(Paragraph(case.risk.narrative, body))
        for mtg in case.risk.mitigation:
            story.append(Paragraph(f"• {mtg}", body))
    if case.legality:
        story += [Paragraph("Legality findings", h2)] + [Paragraph(f"[{f.severity}] {f.layer}: {f.detail}", small) for f in case.legality]
    if case.volume_checks:
        story += [Paragraph("Volume reconciliation", h2)] + [Paragraph(("⚠ " if v.flag else "") + v.detail, small) for v in case.volume_checks]
    if case.exceptions:
        story += [PageBreak(), Paragraph("Exception ledger", h2)]
        rows = [["Sev", "Category", "Subject", "Detail", "Owner", "Status"]] + [[e.severity, e.category, e.subject_label[:28], Paragraph(e.detail[:400], small), e.owner, e.status] for e in case.exceptions]
        et = Table(rows, repeatRows=1, colWidths=[14 * mm, 22 * mm, 34 * mm, 84 * mm, 16 * mm, 16 * mm])
        et.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAEFE7"))]))
        story.append(et)
        cited = [(e, c) for e in case.exceptions for c in e.citations if c.image_uri and Path(c.image_uri).exists()]
        if cited:
            story += [Spacer(1, 4 * mm), Paragraph("Visual citations", h2)]
            for e, c in cited[:12]:
                story += [Paragraph(f"{e.category} · {e.subject_label}: {c.file} p{c.page} — “{c.snippet[:160]}”", small),
                          Image(c.image_uri, width=170 * mm, height=60 * mm, kind="proportional"), Spacer(1, 2 * mm)]
    if case.trace and case.trace.edges:
        story += [Paragraph("Chain of custody", h2)]
        names = {n.id: n.name for n in case.trace.nodes}
        for ed in case.trace.edges:
            story.append(Paragraph(f"{names.get(ed.source)} → {names.get(ed.target)}: {ed.tonnes:.0f} t {ed.lot_reference or ''} {ed.doc_ref or ''}" + (f" [{ed.citation.file} p{ed.citation.page}]" if ed.citation else ""), small))
        for ck in case.trace.checks:
            story.append(Paragraph(("⚠ " if ck.flag else "") + ck.detail, small))
    if case.documents:
        story += [Paragraph("Documents", h2)] + [Paragraph(f"{Path(d.path).name} · {d.kind} · {d.pages} pages ({d.ocr_pages} OCR) · {len(d.citations)} auto-citations: " + ", ".join(sorted({c.field for c in d.citations})), small) for d in case.documents]
        doc_cites = [c for d in case.documents for c in d.citations if c.image_uri and Path(c.image_uri).exists() and c.field in ("car_number", "cnpj", "deforestation_declaration", "tonnes")]
        for c in doc_cites[:8]:
            story += [Paragraph(f"{c.field}: {c.value} — {c.file} p{c.page}", small), Image(c.image_uri, width=170 * mm, height=45 * mm, kind="proportional")]
    if case.open_gaps():
        story += [Paragraph("Open gaps", h2)] + [Paragraph(f"[{g.kind}] {g.description} (owner: {g.owner})", small) for g in case.open_gaps()]
    if case.dossier and case.dossier.critic_report:
        cr = case.dossier.critic_report
        story += [Paragraph("Critic report", h2), Paragraph(f"ok={cr.get('ok')} — {cr.get('summary', '')}", body)]
        for i in cr.get("issues", []):
            story.append(Paragraph(f"[{i['severity']}] {i['subject_ref']}: {i['detail']}", small))
    for p in case.plots:
        a = case.assessment_for(p.id)
        if not a:
            continue
        story += [PageBreak(), Paragraph(f"Plot {p.name or p.id} — {a.final_verdict}", h2),
                  Paragraph(f"Supplier {case.supplier(p.supplier_id).name} · {p.computed_area_ha} ha · production {p.production_start}..{p.production_end} · assessment {a.id}", small)]
        if a.metrics:
            story.append(Paragraph(json.dumps(a.metrics.model_dump()), small))
        imgs = [e for e in a.evidence if e.type in ("chip_before", "chip_after", "loss_overlay", "ndvi_chart") and Path(e.uri).exists()]
        cells = []
        for e in imgs:
            cap = f"{e.type} · {e.source} · {e.captured_at or ''} · {e.meta.get('scene', '')} · sha256 {e.sha256[:12]}…"
            cells.append([Image(e.uri, width=80 * mm, height=80 * mm if e.type != "ndvi_chart" else 27 * mm, kind="proportional"), Paragraph(cap, small)])
        for i in range(0, len(cells), 2):
            row = cells[i:i + 2]
            story.append(Table([[c[0] for c in row], [c[1] for c in row]], colWidths=[85 * mm] * len(row)))
        if a.analyst_opinion:
            op = a.analyst_opinion
            story.append(Paragraph(f"Analyst ({op.model}, {op.prompt_version}): recommends {op.recommended_verdict} at {op.confidence:.2f}. {op.rationale}", body))
        if a.reviewer:
            story.append(Paragraph(f"Reviewed by {a.reviewer} at {a.reviewed_at}. {('Override → ' + a.override_verdict + ': ' + (a.override_reason or '')) if a.override_verdict else (a.override_reason or '')}", body))
        story.append(Paragraph("Datasets: " + ", ".join(f"{e.source} {e.source_version}" for e in a.evidence if e.type == "dataset"), small))
    if case.acknowledgement:
        story += [PageBreak(), Paragraph("Reviewer acknowledgement", h2), Paragraph(f"{case.acknowledgement.reviewer} · {case.acknowledgement.acknowledged_at} · dossier hash {case.acknowledgement.dossier_hash}", body), Paragraph(case.acknowledgement.statement, body)]
    SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    return pdf
