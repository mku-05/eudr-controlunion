"""A raster window on a WGS84 grid with per-pixel area — the common currency between providers and screening."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine, from_origin
from shapely.geometry import shape

DEG_M = 111_320.0


@dataclass
class Grid:
    transform: Affine
    height: int
    width: int
    crs: str = "EPSG:4326"

    @classmethod
    def for_bounds(cls, bounds: tuple[float, float, float, float], res_deg: float, pad_px: int = 4) -> "Grid":
        minx, miny, maxx, maxy = bounds
        minx -= pad_px * res_deg; maxx += pad_px * res_deg; miny -= pad_px * res_deg; maxy += pad_px * res_deg
        width = max(1, math.ceil((maxx - minx) / res_deg))
        height = max(1, math.ceil((maxy - miny) / res_deg))
        return cls(from_origin(minx, maxy, res_deg, res_deg), height, width)

    @property
    def res(self) -> float:
        return self.transform.a

    def pixel_area_ha(self) -> np.ndarray:
        """Per-row pixel area (ha) from latitude; broadcast to (height, width)."""
        rows = np.arange(self.height)
        lat = self.transform.f + (rows + 0.5) * self.transform.e  # e is negative
        m_lon = self.res * DEG_M * np.cos(np.radians(lat))
        m_lat = abs(self.transform.e) * DEG_M
        return np.repeat((m_lon * m_lat / 10_000.0)[:, None], self.width, axis=1)

    def rasterize(self, geometry: dict) -> np.ndarray:
        return rasterize([(shape(geometry), 1)], out_shape=(self.height, self.width), transform=self.transform,
                         fill=0, dtype="uint8", all_touched=False).astype(bool)

    def bounds(self) -> tuple[float, float, float, float]:
        minx, maxy = self.transform.c, self.transform.f
        return minx, maxy + self.transform.e * self.height, minx + self.res * self.width, maxy


def area_ha(mask: np.ndarray, grid: Grid) -> float:
    return float((mask.astype(bool) * grid.pixel_area_ha()).sum())
