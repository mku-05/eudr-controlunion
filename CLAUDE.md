# CLAUDE.md — eudr-agent

Agentic EUDR compliance engine for soya, built for a Control Union engagement. Python 3.12, `uv`.

**Principle:** the agent does the job; the tools hold the truth; a human signs the outcome. Deterministic code writes verdicts
(`rules/pack.py` + `tools/geo/screen.py`); agents recommend, extract, draft, chase and criticise; humans approve/override/sign.

## Layout
```
src/eudr/
  config.py          settings (EUDR_* env); agent_env() points the claude CLI at ~/.claude-personal
  models/domain.py   Case, Plot, Assessment, Gap, Dossier … (pydantic)
  rules/pack.py      versioned rule pack + decide_verdict()
  ledger.py          hash-chained append-only ledger per case
  tools/geo/         grid, parse, validate, screen, evidence; providers/{mock,public}
  tools/{legal,volume,risk,dds,alerts,comms,regwatch}
  tools/docs/        extract, citations (PyMuPDF + RapidOCR → word boxes → highlighted renders), pipeline
  tools/trace/       chain-of-custody parse + tier mass balance
  workflow/exceptions.py  Exception Ledger; reports/roi.py aggregate ROI
  agents/            runtime.py (claude-agent-sdk via ccp) + intake, collector, geo_analyst, legality, drafter, critic, regwatch, orchestrator
  workflow/engine.py the case state machine; intake_map.py deterministic file→Case mapping
  dossier/pack.py    evidence-pack PDF
  api/app.py         FastAPI; cli.py Typer; mcp/server.py standalone MCP server (stdio / streamable-HTTP)
tests/unit           mock provider, no network, no agents
tests/live           EUDR_LIVE=1 — real Hansen/WorldCover/Sentinel-2
tests/agents         EUDR_AGENT=1 — real Claude calls
```

## Commands
```
uv sync --extra dev
.venv/bin/pytest tests/unit -q
EUDR_LIVE=1 .venv/bin/pytest tests/live -q
scripts/demo.sh mock data/demo-mock        # full run with agents on synthetic rasters
scripts/demo.sh public data/demo-public    # full run on real satellite data
.venv/bin/eudr --help
```

## Conventions
- Comments: one-line docstring at most; variable comments only when the value isn't obvious.
- Verdict logic only in `rules/pack.py`. Anything that changes a verdict bumps `RulePack.version`.
- Every tool call / agent step / human action → `Ledger.append`. Never mutate a Case outside `workflow/engine.py`.
- Agents return typed pydantic schemas via `output_format`; free text only inside `rationale` fields.
- Geo Analyst can recommend but never write a flag; CRITICAL always needs a named reviewer.
- Flags are PASS / EXCEPTION / CRITICAL (advisory); the human step is `acknowledge`, never sign/submit, in pilot mode.
- Never compute per-reviewer timing or throughput; aggregate office-level only.
