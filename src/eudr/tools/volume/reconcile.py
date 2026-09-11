"""Declared tonnes vs. what the plots can plausibly produce."""
from __future__ import annotations

from eudr.models import Case, VolumeCheck
from eudr.rules import RULE_PACK


def reconcile(case: Case) -> list[VolumeCheck]:
    out = []
    default_yield = RULE_PACK.default_yield_t_ha.get(case.origin_country, 3.0)
    for lot in case.lots:
        plausible = 0.0
        for pid in lot.plot_ids:
            p = next((x for x in case.plots if x.id == pid), None)
            if not p:
                continue
            area = p.computed_area_ha or p.declared_area_ha or 0.0
            plausible += area * (p.declared_yield_t_ha or default_yield)
        if plausible <= 0:
            out.append(VolumeCheck(lot_id=lot.id, declared_t=lot.tonnes, plausible_t=0.0, ratio=999.0, flag=True,
                                   detail=f"Lot {lot.reference}: no plots with area linked — {lot.tonnes} t cannot be traced."))
            continue
        ratio = lot.tonnes / plausible
        flag = ratio > RULE_PACK.volume_ratio_flag
        out.append(VolumeCheck(lot_id=lot.id, declared_t=lot.tonnes, plausible_t=round(plausible, 1), ratio=round(ratio, 3), flag=flag,
                               detail=(f"Lot {lot.reference}: declared {lot.tonnes} t vs plausible {plausible:.0f} t at {default_yield} t/ha "
                                       f"(ratio {ratio:.2f}){' — exceeds ' + str(RULE_PACK.volume_ratio_flag) if flag else ''}.")))
    return out
