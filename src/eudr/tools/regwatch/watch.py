"""Fetch known guidance pages, hash them, report what changed since last run."""
from __future__ import annotations

import hashlib
import json
import re

import httpx

from eudr.config import settings

SOURCES = {
    "commission_eudr": "https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en",
    "green_forum_country_list": "https://green-forum.ec.europa.eu/nature-and-biodiversity/deforestation-regulation-implementation/eudr-cooperation-and-partnerships/country-classification-list_en",
}


def _state_path():
    p = settings.data_dir / "regwatch" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:200_000]


def check() -> list[dict]:
    sp = _state_path()
    state = json.loads(sp.read_text()) if sp.exists() else {}
    changes = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "eudr-agent/0.1"}) as c:
        for name, url in SOURCES.items():
            try:
                t = _text(c.get(url).text)
            except Exception as e:
                changes.append({"source": name, "url": url, "error": str(e)}); continue
            h = hashlib.sha256(t.encode()).hexdigest()
            prev = state.get(name, {})
            if prev.get("hash") != h:
                changes.append({"source": name, "url": url, "changed": bool(prev), "excerpt": t[:1500], "prev_hash": prev.get("hash"), "hash": h})
            state[name] = {"hash": h, "text": t[:20_000]}
    sp.write_text(json.dumps(state))
    return changes
