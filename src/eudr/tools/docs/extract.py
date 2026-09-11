"""Document text extraction; the Legality/Intake agents reason over the result."""
from __future__ import annotations

from pathlib import Path


def extract_text(path: str | Path, max_chars: int = 20_000) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)[:max_chars]
    if ext in (".txt", ".md", ".csv"):
        return p.read_text(errors="ignore")[:max_chars]
    if ext in (".xlsx",):
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                rows.append("\t".join("" if v is None else str(v) for v in r))
        return "\n".join(rows)[:max_chars]
    return f"[binary {ext}; {p.stat().st_size} bytes]"
