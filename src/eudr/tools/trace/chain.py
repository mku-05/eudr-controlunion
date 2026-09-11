"""Chain-of-custody parsing (deterministic) and tier-to-tier mass balance."""
from __future__ import annotations

import re

from eudr.models import Case, TraceChain, TraceCheck, TraceEdge, TraceNode
from eudr.tools.docs.citations import Page, cite_snippet

EDGE_RE = re.compile(r"^(?P<src>[^\n:>]+?)\s*(?:->|→)\s*(?P<dst>[^\n:>]+?):\s*(?P<t>\d{1,3}(?:[.,]\d{3})*(?:,\d+)?)\s*t\b(?P<rest>[^\n]*)", re.I | re.M)
TIER_HINTS = [("silo", "silo"), ("armaz", "silo"), ("warehouse", "silo"), ("farm", "farm"), ("smallholding", "farm"), ("grains export", "exporter"), ("coop", "cooperative"), ("esmagad", "crusher"), ("crush", "crusher"),
              ("export", "exporter"), ("trading", "trader"), ("porto", "port"), ("fazenda", "farm"), ("sítio", "farm"), ("sitio", "farm"), ("agropec", "farm")]
TOLERANCE = 0.02


def _tonnes(s: str) -> float:
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        return float(s.replace(",", ""))
    return float(s.replace(".", "").replace(",", "."))


def _tier(name: str) -> str:
    n = name.lower()
    for k, t in TIER_HINTS:
        if k in n:
            return t
    return "unknown"


def _clean(name: str) -> str:
    return re.sub(r"\s*\((?:CNPJ|tax id)[^)]*\)", "", name, flags=re.I).strip(" -–")


def parse_chain(texts: dict[str, str], pages: dict[str, list[Page]] | None = None, cite_dir=None) -> TraceChain:
    chain = TraceChain()
    nodes: dict[str, TraceNode] = {}
    for fname, text in texts.items():
        found = False
        for m in EDGE_RE.finditer(text):
            src, dst = _clean(m["src"]), _clean(m["dst"])
            if len(src) > 60 or len(dst) > 60 or not src or not dst:
                continue
            found = True
            for nm in (src, dst):
                if nm not in nodes:
                    nodes[nm] = TraceNode(id=f"node_{len(nodes) + 1}", name=nm, tier=_tier(nm), tax_id=_cnpj(m.group(0)) if nm == src else None)
            rest = m["rest"]
            lot = (re.search(r"(LOTE-[\w-]+|LOT-[\w-]+)", rest) or [None])[0]
            doc = (re.search(r"(CT-e\s*\d+|romaneios?\s*[\d\-]+|weigh tickets?\s*[\d\-]+)", rest, re.I) or [None])[0]
            edge = TraceEdge(source=nodes[src].id, target=nodes[dst].id, tonnes=_tonnes(m["t"]), lot_reference=lot, doc_ref=doc,
                             period=(re.search(r"\d{4}-\d{2}-\d{2}(?:\s*a\s*\d{4}-\d{2}-\d{2})?", rest) or [None])[0])
            if pages and fname in pages:
                edge.citation = cite_snippet(pages[fname], "trace_edge", m.group(0)[:120], cite_dir)
            chain.edges.append(edge)
        if found:
            chain.source_docs.append(fname)
    chain.nodes = list(nodes.values())
    for n in chain.nodes:
        if n.tier == "unknown":
            has_in = any(e.target == n.id for e in chain.edges); has_out = any(e.source == n.id for e in chain.edges)
            n.tier = "farm" if not has_in else "exporter" if not has_out else "unknown"
    return chain


def _cnpj(s: str) -> str | None:
    m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", s)
    return m[0] if m else None


def link_suppliers(chain: TraceChain, case: Case) -> None:
    for n in chain.nodes:
        for s in case.suppliers:
            if (n.tax_id and s.tax_id == n.tax_id) or _norm(s.name) == _norm(n.name) or _norm(n.name) in _norm(s.name) or _norm(s.name) in _norm(n.name):
                n.supplier_id = s.id
                break


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\b(ltda|s/a|sa|me|eireli)\b|[^a-z0-9]", "", s)


def reconcile(chain: TraceChain, case: Case) -> list[TraceCheck]:
    checks = []
    for n in chain.nodes:
        inflow = sum(e.tonnes for e in chain.edges if e.target == n.id)
        outflow = sum(e.tonnes for e in chain.edges if e.source == n.id)
        if inflow and outflow:
            delta = outflow - inflow
            flag = delta > TOLERANCE * inflow
            checks.append(TraceCheck(node_id=n.id, inflow_t=inflow, outflow_t=outflow, delta_t=round(delta, 1), flag=flag,
                                     detail=f"{n.name} ({n.tier}): received {inflow:.0f} t, shipped {outflow:.0f} t" + (f" — {delta:.0f} t unexplained" if flag else "")))
    for lot in case.lots:
        e = next((e for e in chain.edges if e.lot_reference == lot.reference), None)
        if e and abs(e.tonnes - lot.tonnes) > TOLERANCE * lot.tonnes:
            checks.append(TraceCheck(node_id=e.target, inflow_t=e.tonnes, outflow_t=lot.tonnes, delta_t=round(lot.tonnes - e.tonnes, 1), flag=True,
                                     detail=f"Lot {lot.reference}: manifest shows {e.tonnes:.0f} t, lot table declares {lot.tonnes:.0f} t."))
        elif e is None and chain.edges:
            checks.append(TraceCheck(node_id="", inflow_t=0, outflow_t=lot.tonnes, delta_t=lot.tonnes, flag=True,
                                     detail=f"Lot {lot.reference}: not found in any chain-of-custody manifest."))
    for s in case.suppliers:
        if any(p.supplier_id == s.id for p in case.plots) and not any(n.supplier_id == s.id for n in chain.nodes) and chain.edges:
            checks.append(TraceCheck(node_id="", inflow_t=0, outflow_t=0, delta_t=0, flag=True,
                                     detail=f"Supplier {s.name} has plots but does not appear in the chain of custody."))
    return checks
