"""Real Claude calls through the personal profile. EUDR_AGENT=1 to enable."""
import pytest

pytestmark = pytest.mark.agent


def test_intake_maps_fixture(fixture_case_dir):
    from eudr.agents.intake import run_intake
    from eudr.workflow.intake_map import load_folder
    brief, features, tables, docs = load_folder(fixture_case_dir)
    d = run_intake(brief, features, tables, docs)
    assert "Cerrado" in d.operator and d.origin_country == "BR"
    assert len(d.suppliers) == 6 and len(d.plots) == 10 and len(d.lots) == 4
    assert all(p.feature_index is not None for p in d.plots)
    assert any("Sem Dados" in g.description or g.kind == "missing_polygon" for g in d.gaps) or any(l.supplier_keys_without_plots for l in d.lots)
    assert {l.tonnes for l in d.lots} == {4200, 9000, 1500, 800}


def test_geo_analyst_reads_evidence(tmp_path, monkeypatch):
    from shapely.geometry import box, mapping
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    from eudr.agents.geo_analyst import run_geo_analyst
    from eudr.models import Assessment, Plot, Verdict
    from eudr.rules import RULE_PACK
    from eudr.tools.geo.evidence import build_evidence
    from eudr.tools.geo.providers.mock import MockProvider, _geom_key
    from eudr.tools.geo.screen import screen
    geom = mapping(box(-55.5, -12.9, -55.48, -12.885))
    p = Plot(id="plot_amber", supplier_id="s", name="Sítio Recanto", geometry=geom, computed_area_ha=360)
    prov = MockProvider({_geom_key(geom): "amber_fire_no_conversion"})
    r = prov.rasters(geom); v, conf, reason, m, layers = screen(r)
    a = Assessment(subject_ref=p.id, rule_pack_version=RULE_PACK.version, verdict=v, confidence=conf, metrics=m,
                   evidence=build_evidence("case_t", p, r, layers, prov))
    op = run_geo_analyst(p, a, reason)
    assert op.recommended_verdict in (Verdict.PASS, Verdict.EXCEPTION)
    assert op.cited_evidence and 0 <= op.confidence <= 1 and len(op.rationale) > 40
