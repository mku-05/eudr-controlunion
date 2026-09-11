from pathlib import Path

from eudr.tools.docs.citations import auto_citations, cite_snippet, extract_pages, marked_text
from eudr.tools.trace.chain import link_suppliers, parse_chain, reconcile


def test_text_layer_citations(fixture_case_dir, tmp_path):
    pages = extract_pages(fixture_case_dir / "certificado_rastreabilidade_boavista.pdf", tmp_path / "pages")
    assert len(pages) == 1 and not pages[0].ocr and pages[0].image and pages[0].image.exists()
    cites = auto_citations(pages, tmp_path / "cites")
    fields = {c.field for c in cites}
    assert {"car_number", "cnpj", "tonnes", "deforestation_declaration", "coordinates", "harvest_season"} <= fields
    car = next(c for c in cites if c.field == "car_number")
    assert car.value == "MT-5105259-ABCD1234EF5678901234567890ABCDEF" and car.page == 1
    assert car.bbox[2] > car.bbox[0] and car.bbox[3] > car.bbox[1] and Path(car.image_uri).exists() and car.sha256
    q = cite_snippet(pages, "decl", "não houve desmatamento ou conversão de vegetação nativa após 31/12/2020", tmp_path / "cites")
    assert q and q.page == 1 and "desmatamento" in q.value
    assert "[[certificado_rastreabilidade_boavista.pdf p1]]" in marked_text(pages)


def test_ocr_scanned_page(fixture_case_dir, tmp_path):
    pages = extract_pages(fixture_case_dir / "car_recibo_tresirmaos_scan.pdf", tmp_path / "pages")
    assert pages[0].ocr and len(pages[0].words) >= 8
    cites = auto_citations(pages, tmp_path / "cites")
    values = {c.field: c.value for c in cites}
    assert "cnpj" in values and values["cnpj"] == "55.666.777/0001-88"
    assert any(c.field == "car_number" and "5106224" in c.value for c in cites)


def test_chain_parse_and_reconcile(fixture_case_dir, tmp_path):
    from eudr.workflow.intake_map import load_folder, map_deterministic
    brief, feats, tables, docs = load_folder(fixture_case_dir)
    case = map_deterministic(None, brief, feats, tables)
    pages = {"manifesto_cadeia_custodia.pdf": extract_pages(fixture_case_dir / "manifesto_cadeia_custodia.pdf", tmp_path / "pages")}
    chain = parse_chain({"manifesto_cadeia_custodia.pdf": marked_text(pages["manifesto_cadeia_custodia.pdf"])}, pages, tmp_path / "cites")
    assert len(chain.edges) == 9 and all(e.citation for e in chain.edges)
    tiers = {n.name: n.tier for n in chain.nodes}
    assert tiers["Silo LRV-2"] == "silo" and tiers["Fazenda Boa Vista Ltda"] == "farm" and tiers["Grãos do Cerrado"] == "exporter"
    link_suppliers(chain, case)
    assert sum(1 for n in chain.nodes if n.supplier_id) >= 5
    checks = reconcile(chain, case)
    flagged = [c.detail for c in checks if c.flag]
    assert any("Silo Nova Mutum" in d and "200 t unexplained" in d for d in flagged)
    assert not any("Silo LRV-2" in d for d in flagged)  # 4300 in, 4200 out is fine
    lot_flags = [d for d in flagged if d.startswith("Lot")]
    assert lot_flags == []


def test_exception_ledger_and_roi_in_e2e(fixture_case_dir, layers_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("EUDR_AGENTS", "0")
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "geo_provider", "mock")
    from eudr.tools.legal import overlay
    overlay.default_layers_dir = lambda: layers_dir
    from eudr.db import CaseStore
    from eudr.workflow import engine
    engine._store = CaseStore(f"sqlite:///{tmp_path}/t.sqlite")
    try:
        c = engine.create_case(fixture_case_dir, use_agent=False)
        assert {d.kind for d in c.documents} >= {"coc_manifest", "trace_certificate", "contract", "car_receipt"}
        assert sum(d.ocr_pages for d in c.documents) >= 1 and sum(len(d.citations) for d in c.documents) > 10
        engine.run(c.id)
        c = engine.store().get(c.id)
        assert c.trace and len(c.trace.edges) == 9 and any(x.flag for x in c.trace.checks)
        cats = {e.category for e in c.exceptions}
        assert {"geolocation", "deforestation", "legality", "volume", "traceability", "review"} <= cats
        tr = next(e for e in c.exceptions if e.category == "traceability")
        assert tr.citations and Path(tr.citations[0].image_uri).exists()
        assert (tmp_path / "cases" / c.id / "exception_ledger.csv").exists()
        r = engine.roi_report()
        assert r["cases"] == 1 and r["ocr_pages"] >= 1 and r["citations"] > 10 and r["exceptions"] == len(c.exceptions)
        assert "per-reviewer" in r["note"] and Path(r["files"]["md"]).exists()
    finally:
        engine._store = None
