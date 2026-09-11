"""Art. 10 risk criteria → 0..1 score. Narrative is written later by the Drafter agent."""
from __future__ import annotations

from eudr.config import settings
from eudr.models import Case, RiskAssessment, Verdict

WEIGHTS = {"country": 0.2, "forest_presence": 0.15, "deforestation_signal": 0.25, "legality": 0.2,
           "supply_chain_complexity": 0.1, "volume": 0.05, "documentation": 0.05}


def score(case: Case) -> RiskAssessment:
    cr = settings.country_risk.get(case.origin_country, "standard")
    c: dict[str, float | str | int] = {"country_risk": cr}
    c["country"] = {"low": 0.1, "standard": 0.5, "high": 1.0}[cr]
    plots = [p for p in case.plots if p.geometry]
    asm = [case.assessment_for(p.id) for p in plots]
    asm = [a for a in asm if a]
    with_forest = sum(1 for a in asm if a.metrics and a.metrics.forest_2020_ha >= 0.5)
    c["plots_with_forest_at_cutoff"] = with_forest
    c["forest_presence"] = (with_forest / len(asm)) if asm else 0.5
    reds = sum(1 for a in asm if a.final_verdict == Verdict.CRITICAL); ambers = sum(1 for a in asm if a.final_verdict == Verdict.EXCEPTION)
    c["red_plots"], c["amber_plots"] = reds, ambers
    c["deforestation_signal"] = min(1.0, (reds * 1.0 + ambers * 0.4) / max(1, len(asm)) * 2)
    blocking = sum(1 for f in case.legality if f.severity == "blocking"); warn = sum(1 for f in case.legality if f.severity == "warning")
    c["legality_blocking"], c["legality_warning"] = blocking, warn
    c["legality"] = min(1.0, blocking * 0.5 + warn * 0.15)
    n_sup, n_lots = len(case.suppliers), len(case.lots)
    mixed = sum(1 for l in case.lots if len(l.plot_ids) > 3)
    c["supply_chain_complexity"] = min(1.0, 0.1 * n_sup / 5 + 0.2 * mixed / max(1, n_lots) + (0.3 if n_lots > 5 else 0))
    c["volume"] = 1.0 if any(v.flag for v in case.volume_checks) else 0.0
    open_gaps = len(case.open_gaps()); c["open_gaps"] = open_gaps
    c["documentation"] = min(1.0, open_gaps / max(1, len(plots)))
    total = sum(WEIGHTS[k] * float(c[k]) for k in WEIGHTS)
    level = "negligible" if total < 0.15 and cr == "low" else "low" if total < 0.3 else "medium" if total < 0.6 else "high"
    c["level"] = level
    return RiskAssessment(country=case.origin_country, country_risk=cr, score=round(total, 3), criteria=c)
