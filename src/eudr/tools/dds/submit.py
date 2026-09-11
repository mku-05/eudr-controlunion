"""TRACES submission stub: writes the payload to the outbox and returns a reference. Replace with the IS API client."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from eudr.config import settings
from eudr.ledger import sha256_json


def submit(case_id: str, payload: dict) -> dict:
    out = settings.data_dir / "cases" / case_id / "outbox"
    out.mkdir(parents=True, exist_ok=True)
    h = sha256_json(payload)[:10].upper()
    ref = f"STUB-DDS-{payload.get('country_of_production', 'XX')}-{h}"
    p = out / f"dds_{ref}.json"
    p.write_text(json.dumps({"submitted_at": datetime.now(timezone.utc).isoformat(), "reference": ref, "payload": payload}, indent=1))
    return {"reference": ref, "verification_number": f"V-{h[::-1]}", "path": str(p), "stub": True}
