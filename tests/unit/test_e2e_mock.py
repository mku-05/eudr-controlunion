"""Whole workflow on the fixture folder with the mock provider and agents off."""
import os

import pytest
from fastapi.testclient import TestClient

from eudr.models import CaseStatus, Verdict


@pytest.fixture(autouse=True)
def _no_agents(monkeypatch, tmp_path):
    monkeypatch.setenv("EUDR_AGENTS", "0")
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "geo_provider", "mock")
    from eudr.workflow import engine
    from eudr.db import CaseStore
    engine._store = CaseStore(f"sqlite:///{tmp_path}/t.sqlite")
    yield
    engine._store = None


def test_full_run_to_signoff(fixture_case_dir, layers_dir):
    from eudr.tools.legal import overlay
    overlay.default_layers_dir = lambda: layers_dir
    from eudr.workflow import engine
    c = engine.create_case(fixture_case_dir, use_agent=False)
    assert c.operator.startswith("Grãos do Cerrado") and len(c.suppliers) == 6 and len(c.plots) == 10 and len(c.lots) == 4
    assert any(g.kind == "missing_polygon" for g in c.gaps)  # Cooperativa Sem Dados

    r = engine.run(c.id)
    assert r["status"] == CaseStatus.AWAITING_ACK
    c = engine.store().get(c.id)
    verdicts = {p.name: a.final_verdict for p in c.plots if (a := c.assessment_for(p.id))}
    assert verdicts["Fazenda Boa Vista - Talhão 1"] == Verdict.PASS
    assert verdicts["Fazenda Santa Rita - Gleba A"] == Verdict.CRITICAL
    assert verdicts["Sítio Recanto"] == Verdict.EXCEPTION
    assert verdicts["Fazenda Chapadão"] == Verdict.PASS
    assert "Sítio Recanto - Área 2" not in verdicts  # point, no screening
    q = engine.review_queue(c.id)
    assert {x["verdict"] for x in q} == {"EXCEPTION", "CRITICAL"} and len(q) == 4
    assert any(f.layer == "indigenous_land" for f in c.legality) and any(f.layer == "embargo_list" for f in c.legality)
    assert any(v.flag for v in c.volume_checks)
    assert c.risk and c.risk.criteria["level"] in ("medium", "high")
    assert c.dossier and c.dossier.critic_report["ok"] is False
    assert os.path.exists(c.dossier.evidence_pack_path) and os.path.getsize(c.dossier.evidence_pack_path) > 50_000
    excluded = set(c.dossier.dds_payload["compliance"]["excluded_plots"])
    assert len(excluded) == 4

    with pytest.raises(ValueError):
        engine.acknowledge(c.id, "auditor@cu")
    for x in q:
        if x["verdict"] == "CRITICAL":
            engine.approve(c.id, x["assessment_id"], "auditor@cu", "confirmed on imagery")
        else:
            engine.override(c.id, x["assessment_id"], Verdict.PASS, "burn scar regrowing, no agricultural use; harvest cycle on NDVI", "auditor@cu")
    engine.redraft(c.id)
    c = engine.acknowledge(c.id, "auditor@cu")
    assert c.status == CaseStatus.MONITORING and c.dds_reference is None
    assert len(c.dossier.dds_payload["compliance"]["excluded_plots"]) == 2
    from eudr.ledger import Ledger
    led = Ledger(c.id)
    assert led.verify() and any(e["kind"] == "human_action" and e["payload"]["action"] == "acknowledge" for e in led.entries())

    from eudr.tools.alerts.monitor import push_alert
    push_alert(next(p.id for p in c.plots if p.name == "Fazenda Boa Vista - Talhão 2"), "RADD", 2.0)
    m = engine.monitor(c.id)
    assert m["alerts"] == 1 and m["rescreened"]


def test_api_surface(fixture_case_dir):
    from eudr.api.app import app
    client = TestClient(app)
    r = client.post("/cases", json={"folder": str(fixture_case_dir), "use_agent": False}); assert r.status_code == 200
    cid = r.json()["id"]
    assert client.post(f"/cases/{cid}/run").json()["status"] == "awaiting_acknowledgement"
    q = client.get(f"/cases/{cid}/review").json(); assert len(q) == 4
    assert client.post(f"/cases/{cid}/acknowledge", json={"reviewer": "x"}).status_code == 409
    a = q[0]["assessment_id"]
    assert client.post(f"/cases/{cid}/assessments/{a}/override", json={"reviewer": "x", "verdict": "PASS", "reason": "short"}).status_code == 400
    assert client.get(f"/cases/{cid}/dossier").headers["content-type"] == "application/pdf"
    assert client.get(f"/cases/{cid}/ledger?n=5").json()
    plot = q[0]["plot_id"]
    assert client.get(f"/cases/{cid}/evidence/{plot}/loss_overlay.png").status_code == 200
