"""Deterministic screening: plot rasters → ScreenMetrics → verdict. No model in the loop."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from eudr.models import ScreenMetrics, Verdict
from eudr.rules import RULE_PACK, RulePack, decide_verdict
from eudr.tools.geo.grid import area_ha
from eudr.tools.geo.providers.base import AGRI_CLASSES, NATIVE_NONFOREST, WC_CROP, PlotRasters

CUTOFF_YEAR = 2020


def _drop_small_patches(mask: np.ndarray, pixel_area: np.ndarray, min_ha: float) -> np.ndarray:
    labels, n = ndimage.label(mask)
    if n == 0:
        return mask
    areas = ndimage.sum(pixel_area, labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, dtype=bool); keep[1:] = areas >= min_ha
    return keep[labels]


def compute_metrics(r: PlotRasters, rp: RulePack = RULE_PACK) -> tuple[ScreenMetrics, dict[str, np.ndarray]]:
    pa = r.grid.pixel_area_ha()
    forest = _drop_small_patches(r.forest_2020 & r.plot_mask, pa, rp.forest_min_patch_ha)
    loss_after = forest & (r.loss_year > CUTOFF_YEAR)
    converted = loss_after & np.isin(r.landcover_post, AGRI_CLASSES)

    # concordance: primary (Hansen/mock loss_year) vs any alert sources present
    concordant = True
    if r.loss_sources:
        primary_ha = area_ha(loss_after, r.grid)
        for name, src in r.loss_sources.items():
            src_ha = area_ha(src & forest, r.grid)
            if abs(src_ha - primary_ha) > max(0.5, 0.5 * max(primary_ha, src_ha)):
                concordant = False

    native = r.plot_mask & ~forest & np.isin(r.landcover_2020, NATIVE_NONFOREST)
    native_loss = native & (r.landcover_post == WC_CROP)
    years = r.loss_year[loss_after]
    m = ScreenMetrics(
        plot_area_ha=round(area_ha(r.plot_mask, r.grid), 2),
        forest_2020_ha=round(area_ha(forest, r.grid), 2),
        loss_after_cutoff_ha=round(area_ha(loss_after, r.grid), 2),
        converted_ha=round(area_ha(converted, r.grid), 2),
        first_loss_year=int(years.min()) if years.size else None,
        native_vegetation_2020_ha=round(area_ha(native, r.grid), 2),
        native_vegetation_loss_ha=round(area_ha(native_loss, r.grid), 2),
        sources_concordant=concordant,
    )
    layers = {"forest_2020": forest, "loss_after": loss_after, "converted": converted, "native_loss": native_loss}
    return m, layers


def screen(r: PlotRasters, rp: RulePack = RULE_PACK) -> tuple[Verdict, float, str, ScreenMetrics, dict[str, np.ndarray]]:
    m, layers = compute_metrics(r, rp)
    v, conf, reason = decide_verdict(m, rp)
    return v, conf, reason, m, layers
