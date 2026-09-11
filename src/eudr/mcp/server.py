"""Standalone MCP server so external agents and IDEs (Claude Code, Claude Desktop, CU tooling) can drive cases."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from eudr.models import Verdict
from eudr.workflow import engine

mcp = MCPServer("eudr", instructions=(
    "EUDR soya due-diligence engine (advisory). Flags: PASS / EXCEPTION / CRITICAL. Outputs are evidence preparation; "
    "conformity decisions stay with accredited human reviewers. approve/override/acknowledge require a named reviewer."))


@mcp.tool()
def list_cases(status: str | None = None) -> list[dict]:
    """List cases, newest first; optional status filter."""
    return engine.store().list(status)


@mcp.tool()
def create_case(folder: str, operator: str | None = None, use_agent: bool | None = None) -> dict:
    """Ingest a submittal package folder (polygons, tables, PDFs, brief) into a new case."""
    return engine.summary(engine.create_case(folder, operator, use_agent).id)


@mcp.tool()
def run_case(case_id: str, with_imagery: bool = True) -> dict:
    """Advance the case through validate → screen → adjudicate → draft until a human is needed."""
    return engine.run(case_id, with_imagery=with_imagery)


@mcp.tool()
def get_case(case_id: str) -> dict:
    """Case summary: plots with flags, gaps, legality, volume, trace, exceptions, risk, dossier."""
    return engine.summary(case_id)


@mcp.tool()
def explain_plot(case_id: str, plot_id: str) -> dict:
    """Metrics, evidence files, analyst opinion and reviewer state for one plot."""
    return engine.explain_plot(case_id, plot_id)


@mcp.tool()
def review_queue(case_id: str) -> list[dict]:
    """Assessments waiting for a human reviewer."""
    return engine.review_queue(case_id)


@mcp.tool()
def approve(case_id: str, assessment_id: str, reviewer: str, note: str = "") -> dict:
    """Human action: reviewer accepts the engine flag on an assessment."""
    return engine.approve(case_id, assessment_id, reviewer, note).model_dump(mode="json")


@mcp.tool()
def override(case_id: str, assessment_id: str, verdict: str, reason: str, reviewer: str) -> dict:
    """Human action: reviewer overrides a flag (PASS|EXCEPTION|CRITICAL) with a written justification."""
    return engine.override(case_id, assessment_id, Verdict(verdict), reason, reviewer).model_dump(mode="json")


@mcp.tool()
def redraft(case_id: str) -> dict:
    """Rebuild legality, risk, exceptions and dossier after reviews."""
    return engine.redraft(case_id)


@mcp.tool()
def acknowledge(case_id: str, reviewer: str, acknowledge_critic: bool = False) -> dict:
    """Human action: reviewer acknowledges the advisory dossier (no certificate, no submission in pilot mode)."""
    return engine.summary(engine.acknowledge(case_id, reviewer, acknowledge_critic).id)


@mcp.tool()
def exceptions(case_id: str) -> list[dict]:
    """The Exception Ledger with citations and evidence paths."""
    return engine.exceptions(case_id)


@mcp.tool()
def ledger(case_id: str, n: int = 30) -> list[dict]:
    """Last n hash-chained ledger entries."""
    return engine.ledger_tail(case_id, n)


@mcp.tool()
def monitor(case_id: str) -> dict:
    """Apply pending deforestation alerts and re-screen affected plots."""
    return engine.monitor(case_id)


@mcp.tool()
def push_alert(plot_id: str, source: str, area_ha: float, date: str | None = None) -> dict:
    """Queue a deforestation alert for a plot (RADD/GLAD/DETER feed stand-in)."""
    from eudr.tools.alerts.monitor import push_alert as _push
    _push(plot_id, source, area_ha, date)
    return {"ok": True}


@mcp.tool()
def roi_report() -> dict:
    """Aggregate office-level ROI figures across all cases (no per-reviewer metrics)."""
    return engine.roi_report()


def main(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8472) -> None:
    if transport == "http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()
