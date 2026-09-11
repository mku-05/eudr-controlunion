import json

from eudr.db import CaseStore
from eudr.ledger import Ledger
from eudr.models import Case, CaseStatus


def test_ledger_chain_and_tamper_detection(tmp_path, monkeypatch):
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    led = Ledger("case_x")
    led.append("tool_call", "geo.screen", {"plot": "p1"})
    led.append("human_action", "auditor@cu", {"sign": True})
    assert led.verify() and len(led.entries()) == 2
    lines = led.path.read_text().splitlines()
    e = json.loads(lines[0]); e["payload"]["plot"] = "p2"
    led.path.write_text(json.dumps(e) + "\n" + lines[1] + "\n")
    assert led.verify() is False


def test_store_roundtrip(tmp_path):
    st = CaseStore(f"sqlite:///{tmp_path}/t.sqlite")
    c = Case(operator="Op", status=CaseStatus.SCREENING)
    st.save(c)
    back = st.get(c.id)
    assert back.operator == "Op" and back.status == CaseStatus.SCREENING
    assert st.list()[0]["id"] == c.id and st.list(status="intake") == []
