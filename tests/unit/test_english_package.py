from pathlib import Path

from eudr.models import Verdict


def test_english_package_matches_portuguese_twin(layers_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("EUDR_AGENTS", "0")
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "geo_provider", "mock")
    from eudr.tools.legal import overlay
    overlay.default_layers_dir = lambda: layers_dir
    from tests.fixtures.build_fixtures_en import build
    from eudr.db import CaseStore
    from eudr.workflow import engine
    engine._store = CaseStore(f"sqlite:///{tmp_path}/t.sqlite")
    try:
        folder = build()
        c = engine.create_case(folder, use_agent=False)
        assert c.operator == "Cerrado Grains Export Ltd" and len(c.suppliers) == 6 and len(c.plots) == 10 and len(c.lots) == 4
        assert {l.tonnes for l in c.lots} == {4200, 9000, 1500, 800}
        assert {d.kind for d in c.documents} >= {"coc_manifest", "trace_certificate", "contract", "car_receipt"}
        engine.run(c.id)
        c = engine.store().get(c.id)
        v = {p.name: a.final_verdict for p in c.plots if (a := c.assessment_for(p.id))}
        assert v["Santa Rita Farm - Block A"] == Verdict.CRITICAL and v["Recanto Smallholding"] == Verdict.EXCEPTION and v["Boa Vista Farm - Field 1"] == Verdict.PASS
        assert c.trace and len(c.trace.edges) == 9
        assert any("Silo Nova Mutum" in x.detail and "200 t" in x.detail for x in c.trace.checks if x.flag)
        assert any(x.flag and "LOT-2027-002" in x.detail for x in c.volume_checks)
        fields = {ci.field for d in c.documents for ci in d.citations}
        assert {"car_number", "cnpj", "tonnes", "deforestation_declaration"} <= fields
    finally:
        engine._store = None
