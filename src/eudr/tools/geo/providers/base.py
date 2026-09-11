"""Provider contract. All rasters for one plot come back on the same Grid."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import numpy as np

from eudr.tools.geo.grid import Grid

# ESA WorldCover classes
WC_TREE, WC_SHRUB, WC_GRASS, WC_CROP, WC_BUILT, WC_BARE, WC_SNOW, WC_WATER, WC_WETLAND, WC_MANGROVE, WC_MOSS = (
    10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
AGRI_CLASSES = (WC_CROP, WC_GRASS)          # grassland in soya country is overwhelmingly pasture
NATIVE_NONFOREST = (WC_SHRUB, WC_GRASS, WC_WETLAND)


@dataclass
class PlotRasters:
    grid: Grid
    plot_mask: np.ndarray                     # bool
    forest_2020: np.ndarray                   # bool — EUDR-definition forest at cut-off
    loss_year: np.ndarray                     # int16 — year of loss (0 = none)
    landcover_post: np.ndarray                # uint8 — WorldCover class after cut-off (latest available)
    landcover_2020: np.ndarray                # uint8 — WorldCover class at cut-off
    loss_sources: dict[str, np.ndarray] = field(default_factory=dict)   # name → bool post-cutoff loss
    dataset_versions: dict[str, str] = field(default_factory=dict)


@dataclass
class NdviPoint:
    date: date
    ndvi: float
    cloud_pct: float
    scene: str


@dataclass
class Chip:
    png: bytes
    scene_id: str
    captured_at: date
    cloud_pct: float
    sensor: str
    bounds: tuple[float, float, float, float]


class GeoProvider(Protocol):
    name: str

    def rasters(self, geometry: dict) -> PlotRasters: ...
    def ndvi_series(self, geometry: dict, start: date, end: date) -> list[NdviPoint]: ...
    def chip(self, geometry: dict, target: date, window_days: int = 120) -> Chip | None: ...
