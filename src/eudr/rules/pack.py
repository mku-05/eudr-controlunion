"""Versioned rule pack. Anything that turns numbers into a verdict lives here, nowhere else."""
from __future__ import annotations

from dataclasses import dataclass, field

from eudr.models import ScreenMetrics, Verdict


@dataclass(frozen=True)
class RulePack:
    version: str = "EUDR-2023/1115-r2025.12-guidance3-rp1"
    cutoff_date: str = "2020-12-31"
    forest_min_patch_ha: float = 0.5          # Art. 2(4): > 0.5 ha
    forest_canopy_pct: int = 10               # Art. 2(4): canopy > 10 %
    polygon_required_over_ha: float = 4.0     # Art. 9(1)(d)
    coordinate_decimals: int = 6
    min_loss_to_flag_ha: float = 0.5
    red_requires_conversion: bool = True      # Art. 2(3): conversion to agricultural use
    concordance_for_auto_red: bool = True     # ≥2 independent loss sources before CRITICAL without a human
    volume_ratio_flag: float = 1.15           # declared > 115 % of plausible ⇒ flag
    default_yield_t_ha: dict[str, float] = field(default_factory=lambda: {"BR": 3.5, "AR": 3.0, "PY": 3.0, "US": 3.4, "IN": 1.1})
    annex_i_soya_cn: tuple[str, ...] = ("1201", "1208 10", "1507", "2304")  # beans, flour, oil, cake
    high_risk_countries: tuple[str, ...] = ("BY", "KP", "MM", "RU")


RULE_PACK = RulePack()


def decide_verdict(m: ScreenMetrics, rp: RulePack = RULE_PACK) -> tuple[Verdict, float, str]:
    """Deterministic verdict from screen metrics. Returns (verdict, confidence, reason)."""
    if m.forest_2020_ha < rp.forest_min_patch_ha:
        return Verdict.PASS, 0.97, "No EUDR-definition forest inside the plot at the cut-off date."
    if m.loss_after_cutoff_ha < rp.min_loss_to_flag_ha:
        return Verdict.PASS, 0.93, f"Forest present at cut-off ({m.forest_2020_ha:.1f} ha) with no loss ≥ {rp.min_loss_to_flag_ha} ha since."
    if m.converted_ha >= rp.min_loss_to_flag_ha and (m.sources_concordant or not rp.concordance_for_auto_red):
        return Verdict.CRITICAL, 0.9, f"{m.converted_ha:.1f} ha of cut-off forest converted to agricultural use (first loss {m.first_loss_year})."
    if m.converted_ha >= rp.min_loss_to_flag_ha:
        return Verdict.EXCEPTION, 0.6, f"{m.converted_ha:.1f} ha conversion signal but loss sources disagree — needs analyst."
    return Verdict.EXCEPTION, 0.55, f"{m.loss_after_cutoff_ha:.1f} ha forest loss after cut-off without confirmed conversion — needs analyst."
