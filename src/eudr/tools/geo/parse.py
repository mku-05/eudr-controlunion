"""Turn whatever the client sends into feature records. Mapping to Plots is the Intake agent's job."""
from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any

from shapely import wkt
from shapely.geometry import mapping


def parse_file(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".geojson", ".json"):
        return _geojson(json.loads(p.read_text()))
    if ext in (".shp", ".kml", ".kmz", ".gpkg"):
        return _ogr(p)
    if ext == ".zip":
        with zipfile.ZipFile(p) as z:
            shp = [n for n in z.namelist() if n.lower().endswith(".shp")]
            if shp:
                return _ogr(Path(f"/vsizip/{p}/{shp[0]}"))
        return []
    if ext == ".csv":
        with open(p, newline="", encoding="utf-8-sig") as f:
            return _rows(list(csv.DictReader(f)))
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        hdr = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]
        return _rows([dict(zip(hdr, r)) for r in rows[1:] if any(v is not None for v in r)])
    raise ValueError(f"unsupported file type: {ext}")


def _geojson(obj: dict) -> list[dict[str, Any]]:
    feats = obj["features"] if obj.get("type") == "FeatureCollection" else [obj]
    out = []
    for f in feats:
        geom = f.get("geometry") if f.get("type") == "Feature" else f
        props = dict(f.get("properties") or {})
        props["geometry"] = geom
        out.append(props)
    return out


def _ogr(p: Path) -> list[dict[str, Any]]:
    import pyogrio
    gdf = pyogrio.read_dataframe(str(p))
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    out = []
    for _, row in gdf.iterrows():
        props = {k: (None if (v != v) else v) for k, v in row.items() if k != "geometry"}  # NaN → None
        props["geometry"] = mapping(row.geometry) if row.geometry is not None else None
        out.append(props)
    return out


def _rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        r = {str(k).strip(): v for k, v in r.items() if k is not None}
        low = {k.lower(): k for k in r}
        geom = None
        for key in ("geometry", "geojson", "polygon", "wkt"):
            if key in low and r[low[key]]:
                val = r[low[key]]
                try:
                    geom = mapping(wkt.loads(val)) if isinstance(val, str) and val.strip().upper().startswith(("POLYGON", "MULTIPOLYGON", "POINT")) else (json.loads(val) if isinstance(val, str) else val)
                except Exception:
                    geom = None
                break
        if geom is None:
            lat = next((r[low[k]] for k in ("lat", "latitude", "y") if k in low), None)
            lon = next((r[low[k]] for k in ("lon", "lng", "longitude", "x") if k in low), None)
            if lat not in (None, "") and lon not in (None, ""):
                try:
                    geom = {"type": "Point", "coordinates": [float(lon), float(lat)]}
                except ValueError:
                    geom = None
        r["geometry"] = geom
        out.append(r)
    return out
