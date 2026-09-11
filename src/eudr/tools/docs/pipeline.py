"""Documents in a submittal package → pages, OCR where needed, auto citations, marked text for agents."""
from __future__ import annotations

from pathlib import Path

from eudr.config import settings
from eudr.models import Case, Document
from eudr.tools.docs.citations import Page, auto_citations, extract_pages, marked_text
from eudr.tools.docs.extract import extract_text

DOC_EXT = (".pdf", ".txt", ".md")


def docs_dir(case_id: str) -> Path:
    d = settings.data_dir / "cases" / case_id / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process_documents(case: Case, folder: Path) -> dict[str, str]:
    """Attach Documents to the case; return {filename: marked text} for agents."""
    texts: dict[str, str] = {}
    cache: dict[str, list[Page]] = {}
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in DOC_EXT or f.name.lower().startswith("brief"):
            continue
        if f.suffix.lower() == ".pdf":
            pages = extract_pages(f, docs_dir(case.id) / "pages")
            cache[f.name] = pages
            text = marked_text(pages)
            cites = auto_citations(pages, docs_dir(case.id) / "citations")
            doc = Document(kind=_kind(f.name, text), path=str(f), pages=len(pages), ocr_pages=sum(p.ocr for p in pages), citations=cites)
        else:
            text = extract_text(f)
            doc = Document(kind=_kind(f.name, text), path=str(f), pages=1)
        doc.supplier_id = next((s.id for s in case.suppliers if s.tax_id and s.tax_id in text), None)
        doc.extracted = {"chars": len(text), "fields": sorted({c.field for c in doc.citations})}
        case.documents.append(doc)
        texts[f.name] = text
    _PAGES.update(cache)
    return texts


_PAGES: dict[str, list[Page]] = {}


def pages_for(doc: Document) -> list[Page]:
    name = Path(doc.path).name
    if name not in _PAGES and doc.path.lower().endswith(".pdf"):
        _PAGES[name] = extract_pages(doc.path)
    return _PAGES.get(name, [])


def _kind(name: str, text: str) -> str:
    n, t = name.lower(), text.lower()
    if "manifest" in n or "cadeia de cust" in t or "chain of custody" in t:
        return "coc_manifest"
    if "rastreab" in n or "traceab" in n or "rastreabilidade" in t or "traceability certificate" in t:
        return "trace_certificate"
    if "contrat" in n or "contrato" in t or "agreement" in n or "purchase agreement" in t:
        return "contract"
    if "car" in n.split("_") or "recibo" in n or "car_receipt" in n or "cadastro ambiental" in t:
        return "car_receipt"
    if "matric" in n or "escritura" in t:
        return "land_title"
    return "other"
