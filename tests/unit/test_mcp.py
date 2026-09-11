import asyncio


def test_mcp_tools_registered_and_callable(fixture_case_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("EUDR_AGENTS", "0")
    from eudr import config
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "geo_provider", "mock")
    from eudr.db import CaseStore
    from eudr.workflow import engine
    engine._store = CaseStore(f"sqlite:///{tmp_path}/t.sqlite")
    try:
        from eudr.mcp.server import mcp
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert {"create_case", "run_case", "review_queue", "approve", "override", "acknowledge", "exceptions", "roi_report"} <= names
        def call(name, args):
            r = asyncio.run(mcp.call_tool(name, args))
            sc = getattr(r, "structuredContent", None) or getattr(r, "structured_content", None)
            if sc is not None:
                return sc.get("result", sc)
            import json
            return json.loads(r.content[0].text)
        cid = call("create_case", {"folder": str(fixture_case_dir), "use_agent": False})["id"]
        assert cid.startswith("case_")
        assert call("run_case", {"case_id": cid, "with_imagery": False})["status"] == "awaiting_acknowledgement"
        assert len(call("review_queue", {"case_id": cid})) == 4
    finally:
        engine._store = None
