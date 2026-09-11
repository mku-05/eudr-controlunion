"""Overlay plots with legal layers (GeoJSON files in a layers dir) and check embargo lists."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import shape
from shapely.strtree import STRtree

from eudr.config import settings
from eudr.models import Case, LegalityFinding
from eudr.tools.geo.validate import geodesic_area_ha

LAYER_SEVERITY = {
    "indigenous_land": "blocking", "conservation_unit": "blocking", "embargo_area": "blocking", "quilombola": "blocking",
    "amazon_biome": "warning", "cerrado_biome": "info", "otbn_red": "blocking", "otbn_yellow": "warning",
}


def default_layers_dir() -> Path:
    return settings.data_dir / "layers"


def load_layers(layers_dir: Path | None = None) -> dict[str, list[tuple[object, dict]]]:
    d = layers_dir or default_layers_dir()
    out: dict[str, list] = {}
    if not d.exists():
        return out
    for f in sorted(d.glob("*.geojson")):
        fc = json.loads(f.read_text())
        feats = [(shape(x["geometry"]), x.get("properties") or {}) for x in fc.get("features", []) if x.get("geometry")]
        out[f.stem] = feats
    return out


def load_embargo_list(layers_dir: Path | None = None) -> dict[str, dict]:
    p = (layers_dir or default_layers_dir()) / "embargo_list.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    idx = {}
    for r in rows:
        for k in ("car_number", "tax_id"):
            if r.get(k):
                idx[r[k].strip()] = r
    return idx


def run_overlays(case: Case, layers_dir: Path | None = None) -> list[LegalityFinding]:
    layers = load_layers(layers_dir)
    embargo = load_embargo_list(layers_dir)
    findings: list[LegalityFinding] = []
    for s in case.suppliers:
        for key in (s.car_number, s.tax_id):
            if key and key.strip() in embargo:
                row = embargo[key.strip()]
                findings.append(LegalityFinding(layer="embargo_list", severity="blocking", subject_ref=s.id,
                                                detail=f"Supplier {s.name} appears on embargo list ({row.get('source', 'list')}: {row.get('reason', '')})."))
    for name, feats in layers.items():
        if not feats:
            continue
        tree = STRtree([g for g, _ in feats])
        sev = LAYER_SEVERITY.get(name, "info")
        for p in case.plots:
            if not p.geometry:
                continue
            g = shape(p.geometry)
            for i in tree.query(g, predicate="intersects"):
                lg, props = feats[i]
                inter = g.intersection(lg)
                ha = geodesic_area_ha(json.loads(json.dumps(inter.__geo_interface__))) if not inter.is_empty else 0.0
                if ha < 0.1 and g.geom_type != "Point":
                    continue
                label = props.get("name") or props.get("nome") or name
                findings.append(LegalityFinding(layer=name, severity=sev, subject_ref=p.id, overlap_ha=round(ha, 2),
                                                detail=f"Plot {p.name or p.id} overlaps {name} '{label}' by {ha:.1f} ha."))
    return findings
