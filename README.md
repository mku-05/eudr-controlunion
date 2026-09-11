# eudr-agent

An agentic EUDR (Regulation (EU) 2023/1115) pre-processing compliance gateway for soya, built for the Control Union
"Line A" pilot. Give it a raw submittal package — polygon files, supplier tables, chain-of-custody manifests, trace
certificates, contracts, scanned CAR receipts, a brief — and it returns an **advisory evidence dossier**: per-plot
deforestation flags on satellite evidence, legality overlays, tier-to-tier volume reconciliation, an Art. 10 risk assessment,
an **Exception Ledger with visual PDF bounding-box citations**, a DDS-ready payload, and an aggregate ROI report — with an
append-only ledger behind every number.

**Advisory only.** Outputs are automated evidence preparation. Conformity decisions, certificate issuance and audit sign-off
remain exclusively with Control Union's accredited reviewers (a reviewer *acknowledges* the dossier; nothing is submitted).

Background: `docs/01-requirement-interpretation.md`, `docs/02-agentic-solution-design.md`.

## How it works

```
package ──► documents: text layer / OCR → words with boxes → auto-citations (CAR, CNPJ, tonnes, dates, declarations)
        ──► Intake agent ──► Case ──► validate polygons ──► screen (Hansen + WorldCover + Sentinel-2) ──► PASS / EXCEPTION / CRITICAL
                               │                                                                          │
                          gaps → Collector agent → supplier outreach                    EXCEPTION/CRITICAL → Geo Analyst (vision) → human queue
                                                                                                          │
   legality overlays + Legality agent (cited) · chain-of-custody parse + mass balance · volume · risk + Drafter ──► Exception Ledger + dossier + Critic
                                                                                                          │
                                                         reviewer approves / overrides ──► acknowledges dossier ──► monitoring
```

Deterministic code decides verdicts. Agents (Claude via the Claude Code personal profile) do intake, outreach, evidence
adjudication, legality reading, drafting and adversarial review. A named human signs.

## Quick start

```bash
uv sync --extra dev
.venv/bin/pytest tests/unit -q                       # no network, no agents
.venv/bin/python tests/fixtures/build_fixtures.py    # synthetic Mato Grosso case folder

# deterministic run on synthetic rasters
EUDR_AGENTS=0 EUDR_GEO_PROVIDER=mock .venv/bin/eudr case create tests/fixtures/case_mt_2027 --no-agent
EUDR_AGENTS=0 EUDR_GEO_PROVIDER=mock .venv/bin/eudr case run <case_id>
.venv/bin/eudr case show <case_id>
.venv/bin/eudr review list <case_id>
.venv/bin/eudr review approve <case_id> <assessment_id> --by auditor@cu
.venv/bin/eudr review override <case_id> <assessment_id> --verdict GREEN --reason "..." --by auditor@cu
.venv/bin/eudr case redraft <case_id>
.venv/bin/eudr acknowledge <case_id> --by auditor@cu
.venv/bin/eudr exceptions <case_id>                   # Exception Ledger (also data/cases/<id>/exception_ledger.csv)
.venv/bin/eudr report roi                            # aggregate ROI report → data/reports/

# with agents and real satellite data
scripts/demo.sh public data/demo-public

# API + web console (The Regulator AI design system)
.venv/bin/eudr serve   # console at http://127.0.0.1:8471/app · API docs at /docs

# talk to the case
.venv/bin/eudr chat <case_id>

# expose the engine as an MCP server (for Claude Code, Claude Desktop, or CU's own agents)
.venv/bin/eudr mcp                # stdio
.venv/bin/eudr mcp --http         # streamable-HTTP on http://127.0.0.1:8472/mcp
claude mcp add eudr -e EUDR_DATA_DIR=$PWD/data -- $PWD/.venv/bin/eudr mcp   # register in Claude Code
```

## How a user works with it

| Who | Door | Typical flow |
|---|---|---|
| CU lead auditor / technical reviewer | Web console (`/app`), CLI or REST (`/docs`) | create case from the package folder → run → work the review queue (approve / override with justification) → redraft → acknowledge → hand over `evidence_pack.pdf` + `exception_ledger.csv` |
| CU quality manager | REST `/reports/roi`, `eudr report roi` | aggregate office-level figures only |
| Anyone with an MCP client | `eudr mcp` | Claude Code / Claude Desktop / a CU agent calls `create_case`, `run_case`, `review_queue`, `approve`, `override`, `acknowledge`, `exceptions`, `roi_report`… |
| Conversational | `eudr chat <case_id>` | orchestrator agent explains flags, gaps and what needs a human |

## Data sources (no accounts needed)

| Purpose | Source |
|---|---|
| Forest baseline 2020 + loss year | Hansen/UMD Global Forest Change (GFC-2024 v1.12), public GCS |
| Land cover 2020 / 2021 | ESA WorldCover v100 / v200, public S3 |
| Imagery, NDVI | Sentinel-2 L2A COGs via Earth Search STAC, public S3 |
| Documents | PyMuPDF text layer; RapidOCR (ONNX, local) for scanned pages — nothing leaves the box |
| Legal layers | GeoJSON files in `$EUDR_DATA_DIR/layers/` + `embargo_list.csv` (fixtures included; drop real FUNAI/ICMBio/IBAMA layers in) |

JRC Global Forest Cover 2020, RADD/GLAD/PRODES alerts and TRACES submission are plug points (`providers/`, `tools/alerts`, `tools/dds/submit.py`).

## Human gates and governance (per SOW)

- CRITICAL is never automatic: every CRITICAL and unresolved EXCEPTION needs a named reviewer.
- Overrides need a written justification.
- Acknowledgement is refused while non-PASS plots are unreviewed or the Critic report is not ok (unless explicitly acknowledged).
- Pilot mode (`EUDR_PILOT_MODE=1`, default): no DDS submission; the payload is produced as a draft only.
- Reviewer identity is recorded on each decision for audit traceability; **no per-reviewer speed, time-per-task or throughput
  metrics are computed anywhere** — the ROI report is office-level aggregate only.
- Everything lands in `data/cases/<id>/ledger.jsonl`, hash-chained; `Ledger.verify()` detects tampering.
- Agent calls run through the Claude Code personal profile by default (`EUDR_AGENT_PROFILE=personal`); set `work` to route
  through the Bedrock eu-west-1 profile.
