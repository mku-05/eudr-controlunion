"""Append-only ledger: every tool call, agent step and human action, hash-chained."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eudr.config import settings


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, default=str).encode())


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Ledger:
    def __init__(self, case_id: str):
        self.path = settings.data_dir / "cases" / case_id / "ledger.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = None
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else "0" * 64

    def append(self, kind: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,            # tool_call | agent_step | human_action | state_change
            "actor": actor,          # tool name, agent name, or user id
            "payload": payload,
            "prev": self._last_hash(),
        }
        entry["hash"] = sha256_json(entry)
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def verify(self) -> bool:
        prev = "0" * 64
        for e in self.entries():
            h = e.pop("hash")
            if e["prev"] != prev or sha256_json(e) != h:
                return False
            prev = h
        return True
