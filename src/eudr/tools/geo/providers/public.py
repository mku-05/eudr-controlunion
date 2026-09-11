"""Free public data: Hansen GFC (baseline + loss), ESA WorldCover (land cover), Sentinel-2 L2A COGs via Earth Search."""
from __future__ import annotations

import io
import math
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import rasterio
from PIL import Image, ImageDraw
from pyproj import Transformer
from rasterio.env import Env
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

from eudr.config import settings
from eudr.tools.geo.grid import Grid
from eudr.tools.geo.providers.base import Chip, NdviPoint, PlotRasters

HANSEN = "https://storage.googleapis.com/earthenginepartners-hansen/{ver}/Hansen_{ver}_{layer}_{tile}.tif"
WORLDCOVER = {
    2020: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_{tile}_Map.tif",
    2021: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif",
}
STAC = "https://earth-search.aws.element84.com/v1/search"
GDAL_OPTS = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                 GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")
SCL_VALID = (4, 5, 6)


def hansen_tile(lat: float, lon: float) -> str:
    top = math.ceil(lat / 10) * 10
    left = math.floor(lon / 10) * 10
    return f"{abs(top):02d}{'N' if top >= 0 else 'S'}_{abs(left):03d}{'E' if left >= 0 else 'W'}"


def worldcover_tile(lat: float, lon: float) -> str:
    ll_lat = math.floor(lat / 3) * 3
    ll_lon = math.floor(lon / 3) * 3
    return f"{'N' if ll_lat >= 0 else 'S'}{abs(ll_lat):02d}{'E' if ll_lon >= 0 else 'W'}{abs(ll_lon):03d}"


def _tiles_for_bounds(bounds, fn, step) -> set[str]:
    minx, miny, maxx, maxy = bounds
    tiles = set()
    lat = miny
    while lat <= maxy + 1e-9:
        lon = minx
        while lon <= maxx + 1e-9:
            tiles.add(fn(lat, lon)); lon += step
        tiles.add(fn(lat, maxx)); lat += step
    tiles.add(fn(maxy, maxx)); tiles.add(fn(maxy, minx))
    return tiles


class PublicProvider:
    name = "public"

    def __init__(self, cache_dir: Path | None = None, client: httpx.Client | None = None):
        self.cache = cache_dir or settings.raster_cache_dir
        self.http = client or httpx.Client(timeout=60)
        self.versions = {"hansen": settings.hansen_version, "worldcover_post": f"v200-{settings.worldcover_year}",
                         "worldcover_2020": "v100-2020", "sentinel2": "L2A COG (Earth Search v1)"}

    # ---------- rasters ----------
    def _read(self, urls: list[str], bounds, key: str):
        cpath = self.cache / f"{key}.npz"
        if cpath.exists():
            z = np.load(cpath, allow_pickle=True)
            return z["arr"], rasterio.Affine(*z["transform"]), str(z["crs"])
        with Env(**GDAL_OPTS):
            dss = [rasterio.open(f"/vsicurl/{u}") for u in urls]
            try:
                if len(dss) == 1:
                    ds = dss[0]
                    win = from_bounds(*bounds, transform=ds.transform)
                    win = win.round_offsets().round_lengths()
                    arr = ds.read(1, window=win)
                    tr = ds.window_transform(win)
                else:
                    arr, tr = merge(dss, bounds=bounds)
                    arr = arr[0]
                crs = dss[0].crs.to_string()
            finally:
                for d in dss:
                    d.close()
        np.savez_compressed(cpath, arr=arr, transform=np.array(tr)[:6], crs=crs)
        return arr, tr, crs

    def _hansen(self, layer: str, bounds):
        tiles = _tiles_for_bounds(bounds, hansen_tile, 10)
        urls = [HANSEN.format(ver=settings.hansen_version, layer=layer, tile=t) for t in sorted(tiles)]
        key = f"hansen_{settings.hansen_version}_{layer}_{_bkey(bounds)}"
        return self._read(urls, bounds, key)

    def _worldcover(self, year: int, bounds, grid: Grid) -> np.ndarray:
        tiles = _tiles_for_bounds(bounds, worldcover_tile, 3)
        urls = [WORLDCOVER[year].format(tile=t) for t in sorted(tiles)]
        arr, tr, crs = self._read(urls, bounds, f"worldcover_{year}_{_bkey(bounds)}")
        out = np.zeros((grid.height, grid.width), dtype=np.uint8)
        reproject(arr, out, src_transform=tr, src_crs=crs, dst_transform=grid.transform, dst_crs=grid.crs,
                  resampling=Resampling.mode)
        return out

    def rasters(self, geometry: dict) -> PlotRasters:
        geom = shape(geometry)
        pad = 0.002
        b = (geom.bounds[0] - pad, geom.bounds[1] - pad, geom.bounds[2] + pad, geom.bounds[3] + pad)
        tc, tr, crs = self._hansen("treecover2000", b)
        ly, _, _ = self._hansen("lossyear", b)
        h = min(tc.shape[0], ly.shape[0]); w = min(tc.shape[1], ly.shape[1])
        tc, ly = tc[:h, :w], ly[:h, :w]
        grid = Grid(tr, h, w, crs)
        mask = grid.rasterize(geometry)
        loss_year = np.where(ly > 0, 2000 + ly.astype(np.int16), 0).astype(np.int16)
        forest_2020 = (tc >= settings.tree_cover_threshold) & ((ly == 0) | (loss_year > 2020))
        lc20 = self._worldcover(2020, b, grid)
        lcpost = self._worldcover(settings.worldcover_year, b, grid)
        forest_2020 &= (lc20 == 10) | (lc20 == 95) | (ly > 20)  # WorldCover 2020 agrees it was tree cover, unless lost since
        return PlotRasters(grid=grid, plot_mask=mask, forest_2020=forest_2020, loss_year=loss_year,
                           landcover_post=lcpost, landcover_2020=lc20, loss_sources={},
                           dataset_versions=dict(self.versions))

    # ---------- Sentinel-2 ----------
    def _search(self, bounds, start: date, end: date, max_cloud: float, limit: int = 8) -> list[dict]:
        body = {"collections": ["sentinel-2-l2a"], "bbox": list(bounds),
                "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
                "query": {"eo:cloud_cover": {"lt": max_cloud}}, "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
                "limit": limit}
        r = self.http.post(STAC, json=body); r.raise_for_status()
        feats = r.json().get("features", [])
        minx, miny, maxx, maxy = bounds
        return [f for f in feats if _covers(f.get("bbox"), bounds)] or feats

    def chip(self, geometry: dict, target: date, window_days: int = 120) -> Chip | None:
        geom = shape(geometry)
        start, end = target - timedelta(days=window_days), target + timedelta(days=window_days)
        if target <= date(2020, 12, 31):
            end = min(end, date(2020, 12, 31))
        feats = self._search(geom.bounds, start, end, 25)
        if not feats:
            return None
        f = min(feats, key=lambda x: (x["properties"].get("eo:cloud_cover", 100), abs((_dt(x) - target).days)))
        epsg = f["properties"].get("proj:epsg") or int(str(f["properties"].get("proj:code", "EPSG:32721")).split(":")[-1])
        tf = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        g_utm = shp_transform(tf.transform, geom)
        minx, miny, maxx, maxy = g_utm.bounds
        padx, pady = max(300, (maxx - minx) * 0.25), max(300, (maxy - miny) * 0.25)
        wb = (minx - padx, miny - pady, maxx + padx, maxy + pady)
        with Env(**GDAL_OPTS), rasterio.open(f"/vsicurl/{f['assets']['visual']['href']}") as ds:
            win = from_bounds(*wb, transform=ds.transform).round_offsets().round_lengths()
            scale = max(1, int(max(win.width, win.height) / 900))
            arr = ds.read(window=win, out_shape=(3, int(win.height // scale), int(win.width // scale)))
            wtr = ds.window_transform(win) * rasterio.Affine.scale(scale)
        img = Image.fromarray(np.moveaxis(arr, 0, -1))
        dr = ImageDraw.Draw(img)
        inv = ~wtr
        polys = [g_utm] if g_utm.geom_type == "Polygon" else list(g_utm.geoms)
        for p in polys:
            pts = [tuple(inv * xy) for xy in p.exterior.coords]
            dr.line(pts, fill=(255, 230, 0), width=3)
        dr.text((8, img.height - 16), f"{f['id']} {_dt(f):%Y-%m-%d} cc={f['properties'].get('eo:cloud_cover', 0):.0f}%", fill=(255, 255, 255))
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return Chip(png=buf.getvalue(), scene_id=f["id"], captured_at=_dt(f), cloud_pct=float(f["properties"].get("eo:cloud_cover", 0)),
                    sensor="Sentinel-2 L2A", bounds=geom.bounds)

    def ndvi_series(self, geometry: dict, start: date, end: date, max_points: int = 16) -> list[NdviPoint]:
        geom = shape(geometry)
        months = max(1, (end.year - start.year) * 12 + end.month - start.month)
        step = max(1, math.ceil(months / max_points))
        pts: list[NdviPoint] = []
        d = date(start.year, start.month, 1)
        while d <= end:
            m_end = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            feats = self._search(geom.bounds, d, min(m_end, end), 40, limit=4)
            if feats:
                f = feats[0]
                try:
                    v, cc = self._ndvi_for_scene(f, geom)
                    if v is not None:
                        pts.append(NdviPoint(date=_dt(f), ndvi=round(v, 3), cloud_pct=cc, scene=f["id"]))
                except Exception:
                    pass
            d = (d + timedelta(days=32 * step)).replace(day=1)
        return pts

    def _ndvi_for_scene(self, f: dict, geom):
        epsg = f["properties"].get("proj:epsg") or int(str(f["properties"].get("proj:code", "EPSG:32721")).split(":")[-1])
        tf = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        g = shp_transform(tf.transform, geom)
        with Env(**GDAL_OPTS):
            with rasterio.open(f"/vsicurl/{f['assets']['red']['href']}") as ds:
                win = from_bounds(*g.bounds, transform=ds.transform).round_offsets().round_lengths()
                red = ds.read(1, window=win).astype("float32"); tr = ds.window_transform(win)
            with rasterio.open(f"/vsicurl/{f['assets']['nir']['href']}") as ds:
                nir = ds.read(1, window=win).astype("float32")
            with rasterio.open(f"/vsicurl/{f['assets']['scl']['href']}") as ds:
                swin = from_bounds(*g.bounds, transform=ds.transform).round_offsets().round_lengths()
                scl = ds.read(1, window=swin, out_shape=red.shape, resampling=Resampling.nearest)
        mask = rasterize([(g, 1)], out_shape=red.shape, transform=tr, fill=0, dtype="uint8").astype(bool)
        valid = mask & np.isin(scl, SCL_VALID) & (red + nir > 0)
        if mask.sum() == 0 or valid.sum() < 0.3 * mask.sum():
            return None, 100.0
        ndvi = (nir[valid] - red[valid]) / (nir[valid] + red[valid])
        return float(ndvi.mean()), float(100 * (1 - valid.sum() / mask.sum()))


def _bkey(b) -> str:
    return "_".join(f"{v:.4f}" for v in b).replace("-", "m").replace(".", "p")


def _dt(f: dict) -> date:
    return date.fromisoformat(f["properties"]["datetime"][:10])


def _covers(bbox, bounds) -> bool:
    return bool(bbox) and bbox[0] <= bounds[0] and bbox[1] <= bounds[1] and bbox[2] >= bounds[2] and bbox[3] >= bounds[3]
