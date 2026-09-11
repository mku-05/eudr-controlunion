"""PDF pages → words with boxes (text layer or OCR) → citations with highlighted page images."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw

from eudr.ledger import sha256_bytes
from eudr.models import Citation

RENDER_DPI = 110
OCR_DPI = 200
FIELD_PATTERNS = {
    "car_number": r"\b[A-Z]{2}-\d{7}-[0-9A-F]{32}\b",
    "cnpj": r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b",
    "cpf": r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
    "tonnes": r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s*(?:t|ton|toneladas|tonnes|tons)\b",
    "date": r"\b(?:\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\b",
    "deforestation_declaration": r"(?i)\b(?:desmatamento|deforestation|desmonte|deforestación)\b[^.\n]{0,120}",
    "hs_code": r"\b(?:HS|NCM)\s*\d{4}(?:\.\d{2})?\b",
    "coordinates": r"-?\d{1,2}\.\d{4,},\s*-?\d{1,3}\.\d{4,}",
    "harvest_season": r"(?i)(?:safra|season)\s*\d{4}/\d{2,4}|\d{4}/\d{4}\s+season",
}


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    line: int = 0


@dataclass
class Page:
    file: str
    number: int
    width: float
    height: float
    words: list[Word]
    ocr: bool
    image: Path | None = None
    text: str = field(default="")
    spans: list[tuple[int, int]] = field(default_factory=list)

    def build_text(self) -> None:
        out, spans, prev = [], [], None
        for w in self.words:
            if out:
                out.append("\n" if w.line != prev else " ")
            start = sum(len(x) for x in out)
            out.append(w.text); spans.append((start, start + len(w.text))); prev = w.line
        self.text, self.spans = "".join(out), spans

    def bbox_for_span(self, start: int, end: int) -> list[float] | None:
        boxes = [self.words[i] for i, (a, b) in enumerate(self.spans) if a < end and b > start]
        if not boxes:
            return None
        return [min(w.x0 for w in boxes), min(w.y0 for w in boxes), max(w.x1 for w in boxes), max(w.y1 for w in boxes)]


_ocr = None


def _ocr_engine():
    global _ocr
    if _ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
        except Exception:
            _ocr = False
    return _ocr


def _ocr_page(page: fitz.Page) -> list[Word]:
    eng = _ocr_engine()
    if not eng:
        return []
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    import numpy as np
    result, _ = eng(np.array(img))
    scale = 72.0 / OCR_DPI
    words = []
    for box, text, score in (result or []):
        if score < 0.4 or not text.strip():
            continue
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        words.append(Word(text.strip(), min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale, line=len(words)))  # one box per OCR line
    return words


def extract_pages(path: str | Path, render_dir: Path | None = None) -> list[Page]:
    path = Path(path)
    doc = fitz.open(path)
    pages: list[Page] = []
    for i, pg in enumerate(doc):
        raw = pg.get_text("words")
        words = [Word(w[4], w[0], w[1], w[2], w[3], line=w[5] * 10_000 + w[6]) for w in raw]
        ocr = False
        if len(words) < 5:
            words, ocr = _ocr_page(pg), True
        p = Page(file=path.name, number=i + 1, width=pg.rect.width, height=pg.rect.height, words=words, ocr=ocr)
        p.build_text()
        if render_dir is not None:
            render_dir.mkdir(parents=True, exist_ok=True)
            out = render_dir / f"{path.stem}_p{i + 1}.png"
            if not out.exists():
                pg.get_pixmap(dpi=RENDER_DPI).save(str(out))
            p.image = out
        pages.append(p)
    return pages


def marked_text(pages: list[Page], max_chars: int = 40_000) -> str:
    return "\n".join(f"[[{p.file} p{p.number}{' OCR' if p.ocr else ''}]]\n{p.text}" for p in pages)[:max_chars]


def cite(pages: list[Page], field_name: str, pattern: str, out_dir: Path | None = None, first_only: bool = False) -> list[Citation]:
    out: list[Citation] = []
    for p in pages:
        pat = pattern.replace(r"\b", "") if p.ocr else pattern  # OCR lines often lose spaces; drop word boundaries
        for m in re.finditer(pat, p.text):
            bbox = p.bbox_for_span(m.start(), m.end())
            if not bbox:
                continue
            c = Citation(field=field_name, value=m.group(0).strip(), file=p.file, page=p.number, bbox=[round(v, 1) for v in bbox],
                         snippet=p.text[max(0, m.start() - 60): m.end() + 60].replace("\n", " "))
            if out_dir is not None and p.image:
                c.image_uri, c.sha256 = render_citation(p, bbox, out_dir, f"{field_name}_{len(out)}")
            out.append(c)
            if first_only:
                return out
    return out


def cite_snippet(pages: list[Page], field_name: str, snippet: str, out_dir: Path | None = None) -> Citation | None:
    """Locate an agent-quoted snippet (fuzzy on whitespace) and cite it."""
    needle = re.escape(re.sub(r"\s+", " ", snippet.strip()))[:400].replace(r"\ ", r"\s+")
    found = cite(pages, field_name, needle, out_dir, first_only=True)
    if found:
        return found[0]
    toks = [t for t in re.findall(r"\w{4,}", snippet)][:6]
    if len(toks) >= 2:
        loose = r"\s+(?:\S+\s+){0,6}?".join(re.escape(t) for t in toks)
        found = cite(pages, field_name, loose, out_dir, first_only=True)
        return found[0] if found else None
    return None


def render_citation(p: Page, bbox: list[float], out_dir: Path, stem: str) -> tuple[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(p.image).convert("RGB")
    s = img.width / p.width
    x0, y0, x1, y1 = [v * s for v in bbox]
    dr = ImageDraw.Draw(img, "RGBA")
    dr.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=(194, 59, 45, 255), width=3, fill=(255, 220, 0, 60))
    buf = io.BytesIO(); img.save(buf, format="PNG"); data = buf.getvalue()
    path = out_dir / f"{Path(p.file).stem}_p{p.number}_{stem}.png"
    path.write_bytes(data)
    return str(path), sha256_bytes(data)


def auto_citations(pages: list[Page], out_dir: Path | None = None) -> list[Citation]:
    out = []
    for name, pat in FIELD_PATTERNS.items():
        out.extend(cite(pages, name, pat, out_dir)[:6])
    return out
