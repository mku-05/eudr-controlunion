"""Alert intake: a JSONL inbox of {plot_id, source, date, area_ha}. Real feeds (RADD/GLAD/DETER) plug in here."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from shapely.geometry import shape, Point

from eudr.config import settings
from eudr.models import Case


def inbox_path():
    p = settings.data_dir / "alerts" / "inbox.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def pending_alerts(case: Case) -> list[dict]:
    p = inbox_path()
    if not p.exists():
        return []
    hits = []
    plot_ids = {x.id for x in case.plots}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        a = json.loads(line)
        if a.get("plot_id") in plot_ids:
            hits.append(a)
        elif "lat" in a and "lon" in a:
            pt = Point(a["lon"], a["lat"])
            for x in case.plots:
                if x.geometry and shape(x.geometry).contains(pt):
                    hits.append({**a, "plot_id": x.id})
    return hits


def push_alert(plot_id: str, source: str, area_ha: float, when: str | None = None, **extra) -> None:
    with open(inbox_path(), "a") as f:
        f.write(json.dumps({"plot_id": plot_id, "source": source, "area_ha": area_ha,
                            "date": when or datetime.now(timezone.utc).date().isoformat(), **extra}) + "\n")
