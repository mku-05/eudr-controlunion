"""Evidence objects for one plot: dated chips, loss overlay, NDVI series, dataset versions. Everything hashed."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from eudr.config import settings
from eudr.ledger import sha256_bytes
from eudr.models import Evidence, Plot
from eudr.tools.geo.providers.base import GeoProvider, PlotRasters

BEFORE_TARGET = date(2020, 8, 15)


def evidence_dir(case_id: str, plot_id: str) -> Path:
    d = settings.data_dir / "cases" / case_id / "evidence" / plot_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(d: Path, name: str, data: bytes) -> tuple[str, str]:
    p = d / name
    p.write_bytes(data)
    return str(p), sha256_bytes(data)


def loss_overlay_png(r: PlotRasters, layers: dict[str, np.ndarray], scale: int = 6) -> bytes:
    h, w = r.plot_mask.shape
    img = np.zeros((h, w, 3), dtype=np.uint8) + 235
    img[r.plot_mask] = (215, 205, 170)
    img[layers["forest_2020"]] = (59, 122, 78)
    img[layers["native_loss"]] = (200, 170, 90)
    img[layers["loss_after"]] = (230, 150, 60)
    img[layers["converted"]] = (194, 59, 45)
    im = Image.fromarray(img).resize((w * scale, h * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 250, 62], fill=(255, 255, 255))
    for i, (c, t) in enumerate([((59, 122, 78), "forest at 2020-12-31"), ((230, 150, 60), "loss after cut-off"),
                                ((194, 59, 45), "converted to agriculture"), ((200, 170, 90), "native veg → crop")]):
        dr.rectangle([4, 4 + i * 14, 14, 14 + i * 14], fill=c); dr.text((18, 2 + i * 14), t, fill=(0, 0, 0))
    import io
    buf = io.BytesIO(); im.save(buf, format="PNG"); return buf.getvalue()


def ndvi_chart_png(points, cutoff: date = date(2020, 12, 31)) -> bytes:
    import io
    W, H, pad = 720, 240, 36
    im = Image.new("RGB", (W, H), (255, 255, 255)); dr = ImageDraw.Draw(im)
    dr.line([(pad, H - pad), (W - 8, H - pad)], fill=(120, 120, 120)); dr.line([(pad, 8), (pad, H - pad)], fill=(120, 120, 120))
    for v in (0.2, 0.4, 0.6, 0.8):
        y = H - pad - v * (H - pad - 8); dr.line([(pad, y), (W - 8, y)], fill=(230, 230, 230)); dr.text((4, y - 6), f"{v:.1f}", fill=(90, 90, 90))
    if points:
        t0, t1 = points[0].date.toordinal(), max(points[-1].date.toordinal(), points[0].date.toordinal() + 1)
        xs = [pad + (p.date.toordinal() - t0) / (t1 - t0) * (W - pad - 8) for p in points]
        ys = [H - pad - max(0, min(1, p.ndvi)) * (H - pad - 8) for p in points]
        if t0 <= cutoff.toordinal() <= t1:
            xc = pad + (cutoff.toordinal() - t0) / (t1 - t0) * (W - pad - 8)
            dr.line([(xc, 8), (xc, H - pad)], fill=(194, 59, 45), width=2); dr.text((xc + 3, 10), "cut-off", fill=(194, 59, 45))
        dr.line(list(zip(xs, ys)), fill=(31, 95, 122), width=2)
        for x, y in zip(xs, ys):
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(31, 95, 122))
        dr.text((pad, H - pad + 4), points[0].date.isoformat(), fill=(90, 90, 90))
        dr.text((W - 90, H - pad + 4), points[-1].date.isoformat(), fill=(90, 90, 90))
    dr.text((pad + 4, 8), "mean NDVI inside plot", fill=(60, 60, 60))
    buf = io.BytesIO(); im.save(buf, format="PNG"); return buf.getvalue()


def build_evidence(case_id: str, plot: Plot, r: PlotRasters, layers: dict[str, np.ndarray], provider: GeoProvider,
                   with_imagery: bool = True) -> list[Evidence]:
    d = evidence_dir(case_id, plot.id)
    ev: list[Evidence] = []
    path, h = _save(d, "loss_overlay.png", loss_overlay_png(r, layers))
    ev.append(Evidence(type="loss_overlay", uri=path, sha256=h, source=provider.name, source_version=json.dumps(r.dataset_versions)))
    for name, ver in r.dataset_versions.items():
        ev.append(Evidence(type="dataset", uri=name, sha256=sha256_bytes(f"{name}:{ver}".encode()), source=name, source_version=ver))
    if not with_imagery:
        return ev
    after_target = plot.production_end or date.today()
    for label, target in (("chip_before", BEFORE_TARGET), ("chip_after", after_target)):
        chip = provider.chip(plot.geometry, target)
        if chip:
            path, h = _save(d, f"{label}.png", chip.png)
            ev.append(Evidence(type=label, uri=path, sha256=h, captured_at=chip.captured_at.isoformat(), source=chip.sensor,
                               meta={"scene": chip.scene_id, "cloud_pct": chip.cloud_pct, "target": target.isoformat()}))
    series = provider.ndvi_series(plot.geometry, date(2020, 6, 1), after_target)
    js = json.dumps([{"date": p.date.isoformat(), "ndvi": p.ndvi, "cloud_pct": p.cloud_pct, "scene": p.scene} for p in series], indent=1).encode()
    path, h = _save(d, "ndvi_series.json", js)
    ev.append(Evidence(type="ndvi_series", uri=path, sha256=h, source=provider.name, meta={"points": len(series)}))
    path, h = _save(d, "ndvi_series.png", ndvi_chart_png(series))
    ev.append(Evidence(type="ndvi_chart", uri=path, sha256=h, source=provider.name))
    return ev
