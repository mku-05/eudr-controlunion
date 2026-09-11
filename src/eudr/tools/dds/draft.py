"""Due diligence statement payload in the EU Information System shape (approximation of the 2026 IS spec)."""
from __future__ import annotations

from eudr.models import Case, Verdict
from eudr.rules import RULE_PACK


def draft_dds(case: Case, ledger_hash: str) -> dict:
    producers = []
    for s in case.suppliers:
        feats = []
        for p in case.plots:
            if p.supplier_id != s.id or not p.geometry:
                continue
            a = case.assessment_for(p.id)
            if not a or a.final_verdict != Verdict.PASS:
                continue
            feats.append({"type": "Feature", "geometry": p.geometry,
                          "properties": {"ProducerName": s.name, "ProducerCountry": s.country, "ProductionPlace": p.name or p.id,
                                         "Area": p.computed_area_ha, "ProductionStart": str(p.production_start), "ProductionEnd": str(p.production_end)}})
        if feats:
            producers.append({"name": s.name, "country": s.country, "identifier": s.car_number or s.tax_id,
                              "geometries": {"type": "FeatureCollection", "features": feats}})
    tonnes = sum(l.tonnes for l in case.lots)
    excluded = [p.id for p in case.plots if (a := case.assessment_for(p.id)) and a.final_verdict != Verdict.PASS]
    return {
        "statement_type": "DDS", "activity": "import", "operator": {"name": case.operator},
        "commodity": {"name": case.commodity, "hs_headings": list(RULE_PACK.annex_i_soya_cn)},
        "quantity": {"net_mass_kg": round(tonnes * 1000), "units": "kg"},
        "country_of_production": case.origin_country, "producers": producers,
        "compliance": {"deforestation_free": not excluded, "excluded_plots": excluded, "rule_pack": RULE_PACK.version,
                       "cutoff_date": RULE_PACK.cutoff_date, "risk_level": case.risk.criteria.get("level") if case.risk else None},
        "verification": {"ledger_hash": ledger_hash, "case_id": case.id},
    }
