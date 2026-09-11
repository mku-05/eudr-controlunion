"""Deterministic synthetic provider. Scenario is taken from Plot.scenario (test fixtures) or a default."""
from __future__ import annotations

import io
import math
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import shape

from eudr.tools.geo.grid import Grid
from eudr.tools.geo.providers.base import (WC_CROP, WC_SHRUB, WC_TREE, Chip, NdviPoint, PlotRasters)

RES = 0.00025  # ~27 m, Hansen-like

SCENARIOS = {
    "green_established": "long-standing soya field, no forest at cut-off",
    "green_forest_intact": "forest on the north 40 % of the plot, untouched",
    "green_small_loss": "forest present, 0.3 ha lost in 2022 — below the 0.5 ha flag",
    "red_reserve_cleared": "north 40 % forest; a block cleared in 2023 and cropped — all sources agree",
    "red_partial_edge": "3 % of the plot, at the forest edge, cleared 2022 and cropped",
    "amber_fire_no_conversion": "forest lost 2022, regrown shrub — no agricultural conversion",
    "amber_discordant": "one alert source shows loss, Hansen does not; NDVI shows a harvest cycle",
    "cerrado_savanna": "no EUDR forest; native shrub/grass converted to cropland after 2020",
}


def _blocks(grid: Grid, mask: np.ndarray):
    h, w = mask.shape
    ys, xs = np.where(mask)
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    return h, w, top, bottom, left, right


class MockProvider:
    name = "mock"

    def __init__(self, scenario_lookup=None):
        self._lookup = scenario_lookup or {}

    def scenario_for(self, geometry: dict) -> str:
        return self._lookup.get(_geom_key(geometry), "green_established")

    def rasters(self, geometry: dict) -> PlotRasters:
        sc = self.scenario_for(geometry)
        geom = shape(geometry)
        grid = Grid.for_bounds(geom.bounds, RES)
        mask = grid.rasterize(geometry)
        h, w, top, bottom, left, right = _blocks(grid, mask)
        forest = np.zeros_like(mask)
        loss = np.zeros(mask.shape, dtype=np.int16)
        lc20 = np.full(mask.shape, WC_CROP, dtype=np.uint8)
        lcpost = np.full(mask.shape, WC_CROP, dtype=np.uint8)
        sources: dict[str, np.ndarray] = {}
        north = np.zeros_like(mask); north[top: top + int((bottom - top) * 0.4), :] = True
        forest_block = north & mask

        if sc == "green_established":
            pass
        elif sc == "green_forest_intact":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
        elif sc == "green_small_loss":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
            px = _n_pixels_for_ha(grid, 0.3); cleared = _first_n(forest, px)
            loss[cleared] = 2022; lcpost[cleared] = WC_CROP
        elif sc == "red_reserve_cleared":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
            cleared = np.zeros_like(mask)
            r0 = top + int((bottom - top) * 0.2); r1 = top + int((bottom - top) * 0.4)
            c0 = left + int((right - left) * 0.55)
            cleared[r0:r1, c0:right + 1] = True; cleared &= forest
            loss[cleared] = 2023; lcpost[cleared] = WC_CROP
            sources = {"glad": cleared.copy(), "radd": cleared.copy()}
        elif sc == "red_partial_edge":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
            px = max(int(mask.sum() * 0.03), _n_pixels_for_ha(grid, 0.6)); cleared = _last_n(forest, px)
            loss[cleared] = 2022; lcpost[cleared] = WC_CROP
            sources = {"glad": cleared.copy(), "radd": cleared.copy()}
        elif sc == "amber_fire_no_conversion":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
            burned = _first_n(forest, int(forest.sum() * 0.5))
            loss[burned] = 2022; lcpost[burned] = WC_SHRUB
            sources = {"glad": burned.copy(), "radd": burned.copy()}
        elif sc == "amber_discordant":
            forest = forest_block; lc20[forest] = WC_TREE; lcpost[forest] = WC_TREE
            alert = _first_n(forest, int(forest.sum() * 0.3))
            loss[alert] = 2024; lcpost[alert] = WC_CROP
            sources = {"glad": alert.copy(), "radd": np.zeros_like(mask)}
        elif sc == "cerrado_savanna":
            lc20[mask] = WC_SHRUB; lcpost[mask] = WC_CROP
        else:
            raise ValueError(f"unknown scenario {sc}")

        return PlotRasters(grid=grid, plot_mask=mask, forest_2020=forest & mask, loss_year=loss,
                           landcover_post=lcpost, landcover_2020=lc20, loss_sources=sources,
                           dataset_versions={"mock": sc})

    def ndvi_series(self, geometry: dict, start: date, end: date) -> list[NdviPoint]:
        sc = self.scenario_for(geometry)
        pts, d, i = [], start, 0
        while d <= end:
            season = 0.35 + 0.35 * math.sin((d.timetuple().tm_yday / 365.0) * 2 * math.pi + 1.2)  # soya cycle
            ndvi = season if sc != "amber_fire_no_conversion" else (0.75 if d < date(2022, 8, 1) else 0.3 + 0.02 * i)
            pts.append(NdviPoint(date=d, ndvi=round(ndvi, 3), cloud_pct=5.0, scene=f"MOCK_{d:%Y%m%d}"))
            d += timedelta(days=30); i += 1
        return pts

    def chip(self, geometry: dict, target: date, window_days: int = 120) -> Chip | None:
        sc = self.scenario_for(geometry)
        img = Image.new("RGB", (512, 512), (120, 96, 60))
        dr = ImageDraw.Draw(img)
        after = target > date(2020, 12, 31)
        if sc in ("green_forest_intact", "green_small_loss", "red_reserve_cleared", "red_partial_edge",
                  "amber_fire_no_conversion", "amber_discordant"):
            dr.rectangle([0, 0, 512, 205], fill=(24, 78, 36))
        if after and sc in ("red_reserve_cleared",):
            dr.rectangle([280, 100, 512, 205], fill=(150, 110, 70))
        if after and sc == "red_partial_edge":
            dr.rectangle([440, 170, 512, 205], fill=(150, 110, 70))
        if after and sc == "amber_fire_no_conversion":
            dr.rectangle([0, 0, 256, 205], fill=(90, 110, 60))
        if sc == "cerrado_savanna" and not after:
            img.paste((140, 150, 80), [0, 0, 512, 512])
        for y in range(220, 512, 24):
            dr.line([(0, y), (512, y)], fill=(100, 80, 50), width=1)
        dr.rectangle([8, 8, 504, 504], outline=(255, 230, 0), width=3)
        dr.text((16, 480), f"MOCK {sc} {target:%Y-%m-%d}", fill=(255, 255, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return Chip(png=buf.getvalue(), scene_id=f"MOCK_{target:%Y%m%d}", captured_at=target, cloud_pct=3.0,
                    sensor="mock-s2", bounds=shape(geometry).bounds)


def _geom_key(geometry: dict) -> str:
    return shape(geometry).wkb_hex


def _n_pixels_for_ha(grid: Grid, ha: float) -> int:
    return max(1, int(round(ha / float(grid.pixel_area_ha().mean()))))


def _first_n(mask: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros_like(mask); idx = np.flatnonzero(mask)[:n]; out.flat[idx] = True; return out


def _last_n(mask: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros_like(mask); idx = np.flatnonzero(mask)[-n:]; out.flat[idx] = True; return out
