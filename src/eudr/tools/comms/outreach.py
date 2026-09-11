"""Supplier outreach stub: messages land in the case outbox; replies are files dropped in the inbox."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from eudr.config import settings


def _dirs(case_id: str) -> tuple[Path, Path]:
    base = settings.data_dir / "cases" / case_id
    out, inb = base / "outbox", base / "inbox"
    out.mkdir(parents=True, exist_ok=True); inb.mkdir(parents=True, exist_ok=True)
    return out, inb


def send(case_id: str, to: str, subject: str, body: str, gap_ids: list[str]) -> str:
    out, _ = _dirs(case_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    p = out / f"msg_{ts}_{gap_ids[0] if gap_ids else 'general'}.md"
    p.write_text(f"To: {to}\nSubject: {subject}\nGaps: {', '.join(gap_ids)}\nSent: {ts}\n\n{body}\n")
    return str(p)


def replies(case_id: str) -> list[Path]:
    _, inb = _dirs(case_id)
    return sorted(x for x in inb.iterdir() if x.is_file())
