"""CLI: eudr case|review|acknowledge|monitor|alert|regwatch|chat|serve."""
from __future__ import annotations

import asyncio
import json

import typer
from rich import print as rprint
from rich.table import Table

from eudr.models import Verdict

app = typer.Typer(no_args_is_help=True, help="Agentic EUDR compliance for soya")
case_app = typer.Typer(no_args_is_help=True); review_app = typer.Typer(no_args_is_help=True); alert_app = typer.Typer(no_args_is_help=True)
app.add_typer(case_app, name="case"); app.add_typer(review_app, name="review"); app.add_typer(alert_app, name="alert")


def _engine():
    from eudr.workflow import engine
    return engine


@case_app.command("create")
def case_create(folder: str, operator: str = typer.Option(None), no_agent: bool = typer.Option(False, "--no-agent")):
    c = _engine().create_case(folder, operator, use_agent=False if no_agent else None)
    rprint(f"[bold]{c.id}[/bold] {c.operator} — {len(c.suppliers)} suppliers, {len(c.plots)} plots, {len(c.lots)} lots, {len(c.open_gaps())} gaps")


@case_app.command("run")
def case_run(case_id: str, no_imagery: bool = typer.Option(False, "--no-imagery")):
    rprint(json.dumps(_engine().run(case_id, with_imagery=not no_imagery), indent=1, default=str))


@case_app.command("show")
def case_show(case_id: str):
    s = _engine().summary(case_id)
    rprint(f"[bold]{s['id']}[/bold] {s['operator']} · {s['status']} · {s['origin']} → {s['destination']} · {s['shipment']}")
    t = Table("plot", "supplier", "ha", "verdict", "reviewer")
    col = {"PASS": "green", "EXCEPTION": "yellow", "CRITICAL": "red", None: "grey50"}
    for p in s["plots"]:
        t.add_row(p["name"] or p["id"], p["supplier"], str(p["area_ha"] or "-"), f"[{col.get(p['verdict'])}]{p['verdict'] or 'no geometry'}[/]", p["reviewer"] or "-")
    rprint(t)
    for g in s["open_gaps"]:
        rprint(f"  [yellow]gap[/] {g['kind']}: {g['description']}")
    for f in s["legality"]:
        rprint(f"  [{'red' if f['severity'] == 'blocking' else 'yellow' if f['severity'] == 'warning' else 'grey50'}]{f['severity']}[/] {f['detail']}")
    for v in s["volume"]:
        rprint(f"  {'[red]volume[/]' if v['flag'] else 'volume'} {v['detail']}")
    if s["risk"]:
        rprint(f"  risk: {s['risk']['criteria']['level']} ({s['risk']['score']})")
    if s.get("trace"):
        for f in s["trace"]["flags"]:
            rprint(f"  [yellow]trace[/] {f}")
    for d in s.get("documents", []):
        rprint(f"  doc {d['file']} ({d['kind']}, {d['pages']}p, ocr {d['ocr_pages']}, {d['citations']} citations)")
    if s.get("exceptions"):
        rprint(f"  exceptions: {s['exceptions']['total']} {s['exceptions']['by_severity']}")
    if s["dossier"]:
        rprint(f"  dossier: {s['dossier']['evidence_pack_path']}  critic ok={s['dossier']['critic_report']['ok'] if s['dossier']['critic_report'] else '-'}")
    if s["dds_reference"]:
        rprint(f"  DDS: {s['dds_reference']}")


@case_app.command("list")
def case_list():
    for r in _engine().store().list():
        rprint(f"{r['id']}  {r['status']:18s} {r['operator']}  {r['updated_at'][:19]}")


@case_app.command("explain")
def case_explain(case_id: str, plot_id: str):
    rprint(json.dumps(_engine().explain_plot(case_id, plot_id), indent=1, default=str))


@case_app.command("ledger")
def case_ledger(case_id: str, n: int = 20):
    for e in _engine().ledger_tail(case_id, n):
        rprint(f"{e['ts'][:19]} {e['kind']:12s} {e['actor']:18s} {json.dumps(e['payload'], default=str)[:140]}")


@case_app.command("redraft")
def case_redraft(case_id: str):
    rprint(_engine().redraft(case_id))


@review_app.command("list")
def review_list(case_id: str):
    for q in _engine().review_queue(case_id):
        rprint(f"[bold]{q['assessment_id']}[/bold] {q['plot']} {q['verdict']} conf={q['confidence']}")
        if q["analyst"]:
            rprint(f"   analyst → {q['analyst']['recommended_verdict']} ({q['analyst']['confidence']:.2f}): {q['analyst']['rationale'][:300]}")
        rprint(f"   evidence: {q['evidence']}")


@review_app.command("approve")
def review_approve(case_id: str, assessment_id: str, by: str = typer.Option(...), note: str = ""):
    a = _engine().approve(case_id, assessment_id, by, note)
    rprint(f"approved {a.id} as {a.final_verdict} by {by}")


@review_app.command("override")
def review_override(case_id: str, assessment_id: str, verdict: Verdict = typer.Option(...), reason: str = typer.Option(...), by: str = typer.Option(...)):
    a = _engine().override(case_id, assessment_id, verdict, reason, by)
    rprint(f"override {a.id}: {a.verdict} → {a.final_verdict} by {by}")


@app.command("acknowledge")
def acknowledge(case_id: str, by: str = typer.Option(...), acknowledge_critic: bool = False):
    c = _engine().acknowledge(case_id, by, acknowledge_critic)
    rprint(f"acknowledged by {by}; status {c.status}" + (f"; DDS reference {c.dds_reference}" if c.dds_reference else " (pilot mode: no DDS submission)"))


@app.command("exceptions")
def exceptions(case_id: str):
    for e in _engine().exceptions(case_id):
        col = {"critical": "red", "major": "yellow", "minor": "cyan", "info": "grey50"}[e["severity"]]
        rprint(f"[{col}]{e['severity']:8s}[/] {e['category']:13s} {e['subject_label'][:30]:30s} {e['detail'][:120]}" + (f"  [{len(e['citations'])} cite]" if e["citations"] else ""))


@app.command("report")
def report(kind: str = typer.Argument("roi")):
    r = _engine().roi_report()
    rprint({k: v for k, v in r.items() if k in ("cases", "plots_screened", "flags", "pages_parsed", "ocr_pages", "citations", "exceptions", "estimated_manual_hours", "files")})


@app.command("monitor")
def monitor(case_id: str):
    rprint(_engine().monitor(case_id))


@alert_app.command("push")
def alert_push(plot_id: str, source: str = "RADD", area_ha: float = 1.0, date: str = typer.Option(None)):
    from eudr.tools.alerts.monitor import push_alert
    push_alert(plot_id, source, area_ha, date)
    rprint("alert queued")


@app.command("regwatch")
def regwatch(no_agent: bool = False):
    from eudr.tools.regwatch.watch import check
    ch = check()
    rprint(f"{len(ch)} changed/new sources")
    if ch and not no_agent:
        from eudr.agents.regwatch import assess_changes
        rprint(assess_changes(ch).model_dump())


@app.command("chat")
def chat(case_id: str):
    from eudr.agents.orchestrator import chat as _chat
    asyncio.run(_chat(case_id, lambda: typer.prompt("you"), lambda t: rprint(f"[cyan]agent[/cyan] {t}")))


@app.command("mcp")
def mcp_server(http: bool = False, host: str = "127.0.0.1", port: int = 8472):
    """Expose the engine as an MCP server (stdio by default; --http for streamable-HTTP)."""
    from eudr.mcp.server import main
    main("http" if http else "stdio", host, port)


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8471):
    import uvicorn
    uvicorn.run("eudr.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
