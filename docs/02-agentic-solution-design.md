# Agentic EUDR Compliance — Solution Design

_Companion to `01-requirement-interpretation.md`. Date: 11 Sep 2026._

## Design principle

**The agent does the job; the tools hold the truth; a human signs the outcome.**

- LLM agents: intake, extraction, gap-finding, chasing suppliers, reasoning over ambiguous cases, drafting, explaining.
- Deterministic tools: geometry, raster screening, legal overlays, volume maths, hashing, submission. Reproducible, versioned.
- Human: signs every RED and the final DDS. Everything else is autonomous.

The agent never invents a polygon, never flips a RED to GREEN alone, never submits without a named signer, and never claims compliance where a gap exists — it returns the gap.

## The unit of work: a Case

```
ComplianceCase
  operator, commodity, destination market, shipment window
  suppliers[]      (name, CAR / tax id, contact, role)
  plots[]          (geometry, source, version, production window, declared area/yield)
  lots[]           (tonnes, plots→lot mapping, silo/crusher)
  documents[]      (CAR receipts, land title, invoices, labour certs, prior DDS)
  assessments[]    (ComplianceAssessment — see below)
  gaps[]           (what is missing, who owes it, how it will be obtained)
  dossier          (evidence pack, risk assessment, legality checklist, DDS payload)
  status           intake → collecting → screening → adjudicating → drafting → awaiting_signoff → submitted → monitoring
```

```
ComplianceAssessment
  subject_ref, subject_type          plot | supplier | lot
  rule_pack_version                  "EUDR 2023/1115 r2025-12 / guidance v3"
  verdict GREEN|AMBER|RED, confidence
  metrics {forest_2020_ha, loss_ha, converted_ha, first_loss_date}
  evidence[] {type, uri, sha256, captured_at, source, source_version}
  analyst_opinion {model, prompt_version, rationale, cited_evidence[]}
  reviewer, reviewed_at, override_reason
  hash
```

## End-to-end flow

```
user: "40 suppliers, CAR numbers + contracts attached, 12,000 t soya, Mato Grosso → Rotterdam, ship Feb 2027"
 │
 ▼
[1] INTAKE            Orchestrator + Intake agent (vision on PDFs/xlsx/shp)
                      → entities, case created, gap list ("3 suppliers: no polygon; 2: no production dates")
 │
 ▼
[2] COLLECT           tools fetch what they can (CAR polygon by number, municipality geocode)
                      agent chases the rest: PT-BR email/WhatsApp with magic-link upload, parses replies,
                      re-asks only for what is still missing
 │
 ▼
[3] VALIDATE          geo.validate: topology, area vs declared, duplicates, cross-supplier overlap,
                      inside municipality, >4 ha ⇒ polygon; CAR reconciliation; legal-reserve split suggestion
 │
 ▼
[4] SCREEN            geo.screen (deterministic, batch, Earth Engine / openEO):
                      forest@2020-12-31 ∩ plot → loss 2021..prod_date → post-loss land use
                      → GREEN / AMBER / RED + ha + dataset versions + before/after chips + NDVI/S1 series
 │
 ├── GREEN ───────────────────────────────────────────────┐   (random 5 % QA sample → Geo Analyst)
 ├── AMBER → [5] ADJUDICATE  Geo Analyst (multimodal):    │
 │           chips + series + alerts + PRODES + context   │
 │           → structured opinion, confidence, rationale  │
 │           conf ≥ τ and not RED → auto-accept           │
 │           else → human review queue                    │
 └── RED   → human review queue (always)                  │
 ▼                                                        │
[6] LEGALITY + RISK   legal.overlay (embargo, TI, UC, moratorium, OTBN) + Legality agent on docs
                      risk.score Art. 10 criteria → Drafter writes mitigation narrative
                      volume.reconcile: tonnes vs area × yield → flag over-declaration
 ▼
[7] DOSSIER           evidence pack (PDF + JSON), DDS payload (EU IS GeoJSON), action list
                      Critic agent: every claim traces to a tool output; dates consistent; no gap hidden
 ▼
[8] SIGN-OFF          auditor sees: summary, REDs with evidence, AMBER opinions, gaps, critic report
                      one click: sign → dds.submit (TRACES) → reference number stored
 ▼
[9] MONITOR           plots subscribed to RADD / GLAD / DETER; new alert → re-screen → notify
                      Regulatory-watch agent: new guidance/FAQ → proposed rule-pack diff → human approves → version bump
```

## Agents and their tools

| Agent | Model | Job | Tools (MCP) | Output schema |
|---|---|---|---|---|
| **Orchestrator** | Opus 5 | Owns case state machine, chooses next step, talks to user, delegates | all, via sub-agents | next_action, user_message |
| **Intake / Normalizer** | Sonnet 5 (vision) | files → suppliers, plots, lots, docs; gap list | docs.extract, geo.parse, geo.fetch_car, geocode | CaseDelta |
| **Collector** | Sonnet 5 | supplier outreach in PT-BR/ES, parse replies, track what's owed | comms.send, comms.inbox, docs.extract | GapUpdate |
| **Geo Analyst** | Opus 5 (vision) | adjudicate AMBER, QA-sample GREEN/RED | geo.evidence, geo.timeseries, alerts.query, prodes.query | AnalystOpinion |
| **Legality Analyst** | Sonnet 5 (vision) | docs → checklist, overlays → findings | legal.overlay, docs.extract, registry.lookup | LegalityChecklist |
| **Drafter** | Sonnet 5 | Art. 10 narrative, DDS fields, client summary | risk.score, dds.draft | Drafts |
| **Critic** | Opus 5 | adversarial pass before sign-off | read-only case access | CriticReport |
| **Reg-watch** | Sonnet 5 | monitor EU guidance/FAQ/IS spec changes | web.fetch, rules.diff | RulePackProposal |

Rules that keep it honest:
- Every agent output is a typed schema; free text lives only in `rationale`.
- An agent may cite only tool outputs in the case; the Critic rejects uncited claims.
- Geo Analyst can recommend, never write, a verdict. The deterministic engine writes GREEN/AMBER/RED; humans write overrides.
- Model id, prompt version, rule-pack version and dataset versions are pinned per case. Re-running the deterministic path reproduces the same numbers.

## Deterministic core (the part that carries liability)

`geo.screen(plot, production_window) →`
1. Baseline: JRC GFC 2020 (primary) ∩ plot; tie-break with Hansen 2020 tree cover and a 2020 Sentinel-2 composite when they disagree at edges → `forest_2020_ha`.
2. Loss: Hansen lossyear ≥ 2021, GLAD-L/S2, RADD, PRODES/DETER, own NDVI/NBR + Sentinel-1 backscatter change on the plot → `loss_ha`, `first_loss_date`.
3. Conversion: post-loss land cover (cropland/pasture classifier + persistence ≥ 2 seasons) → `converted_ha`.
4. Verdict rule (versioned): `forest_2020_ha < 0.5` → GREEN; loss with no conversion or low confidence → AMBER; converted ≥ 0.5 ha with concordant sources → RED.
5. Emits chips (before ≤ 2020-12-31, after ≈ production date, cloud < 20 %, sensor/date/tile in metadata), time series, overlay, sha256 of everything.

Also emits a **native-vegetation flag** (Cerrado) separately from the EUDR verdict.

## Evidence and audit

- Append-only ledger: every tool call {tool, input hash, output hash, versions, timestamp}; every agent step {model, prompt version, input/output hash}; every human action.
- Dossier hash covers ledger + evidence objects. Regulator can replay.
- Retention 5 years; object lock on evidence storage.
- Tenant isolation at DB + storage level; EU or Brazil region.

## Evals — no prompt ships without them

- Golden set: ≥ 500 plots with ground truth — PRODES-confirmed clearings, stable farms, Cerrado savanna edges, harvest/fire false positives, eucalyptus rotations, legal-reserve partial clearings.
- Metrics: RED precision/recall vs ground truth; AMBER rate (want < 15 %); Geo Analyst agreement with human panel; Critic catch rate on seeded errors; intake extraction accuracy on messy real files.
- Regression run on every rule-pack, prompt or model change.

## Stack

- Agents: Claude Agent SDK (or Managed Agents) — Opus 5 for orchestrator/analyst/critic, Sonnet 5 for extraction and drafting.
- Durable execution: Temporal — cases run for days, wait on suppliers, retry raster jobs, resume after human signals.
- Tools: MCP servers — `geo` (Python/FastAPI, PostGIS, Earth Engine or Copernicus openEO), `legal`, `docs`, `comms`, `dds` (TRACES API), `alerts`.
- Data: Postgres (cases, ledger), PostGIS (geometries), object storage with object lock (evidence), vector store only for guidance/FAQ retrieval.
- UI: auditor console (queue, evidence viewer, sign-off), client portal (status, gaps), supplier magic-link uploader (PT-BR/ES, mobile).

## What the user experiences

Input: one message and a folder. Output within hours (deterministic screening is minutes; the long pole is suppliers): "37 plots GREEN, 2 AMBER resolved (harvest signal, analyst opinion attached), 1 RED — 41 ha legal reserve cleared Jul 2023, evidence attached; 3 polygons still owed by suppliers X, Y, Z (chased today); volume reconciles within 8 %; Art. 10 assessment drafted; DDS ready to sign." One click to sign; reference number back; plots under watch.

## Cost shape (rough)

- Screening: cents per plot (Earth Engine batch).
- LLM: intake ≈ $1–3 per case; Geo Analyst ≈ $0.5–2 per AMBER plot (vision); Critic ≈ $1 per case. GREEN plots cost no LLM.
- Commercial imagery only on disputed REDs, by exception.

## MVP in ~8 weeks

1. Orchestrator + Intake + `geo` MCP (validate, screen, evidence) + case DB + ledger.
2. Geo Analyst on AMBER + human review queue + sign-off.
3. Dossier + DDS-ready export.
Then: Collector outreach, Legality, Risk, Critic, TRACES submit, monitoring, Reg-watch.

---

## Addendum (11 Sep 2026) — alignment with the Control Union SOW (Line A pilot)

The SOW frames the platform as an **automated pre-processing compliance gateway**: evidence preparation and advisory
analysis only. The build reflects that:

| SOW clause | Implementation |
|---|---|
| Evidence preparation only; no autonomous conformity decisions | Flags are **PASS / EXCEPTION / CRITICAL** (advisory). CRITICAL always needs a named reviewer. The human step is *acknowledge the dossier*, not sign a certificate. |
| No automated digital sign-off of official certificates | `EUDR_PILOT_MODE=1` (default): no DDS submission; DDS-ready payload produced as a draft only. |
| Spatial polygon parsing | GeoJSON / Shapefile / KML / CSV / XLSX ingest, topology repair, 4 ha polygon rule, overlaps, country sanity, geodesic area. |
| Document extraction on dirty scans, multi-language PDFs | PyMuPDF text layer; RapidOCR (local ONNX) for image-only pages; PT/ES/EN prompts. Nothing leaves the box for OCR. |
| Visual PDF bounding-box citations | Every auto-extracted field (CAR, CNPJ, tonnes, dates, declarations, HS codes, coordinates), every chain-of-custody edge and every agent-cited quote is located on the page, boxed, rendered to PNG and hashed. |
| Multi-tier supplier trace certificates, chain-of-custody manifests | Chain parsed into nodes/edges with citations; tier-to-tier mass balance; lot ↔ manifest reconciliation; suppliers with plots but absent from the chain flagged. |
| Exception Ledger & Visual Citation Dossier | `exception_ledger.{json,csv}` + evidence pack PDF with citation images; API `/cases/{id}/exceptions`. |
| Executive ROI report | `eudr report roi` — aggregate office-level only. |
| Worker privacy / union-safe | Reviewer identity is kept on decisions for ISO 17020/17065 traceability; **no per-reviewer speed, time-per-task or throughput is computed anywhere**. |
| Zero public model training / isolated tenant | Agent calls default to the Claude Code personal profile (owner's decision for the pilot); `EUDR_AGENT_PROFILE=work` routes to Bedrock eu-west-1 under commercial terms. Hosting decision deferred; provider-neutral Dockerfile + compose included. |
| No live integrations into CU production systems | None. Folder / upload ingestion only. |
| Regulatory reference PDFs for calibration | Rule pack is versioned (`rules/pack.py`); the reg-watch agent proposes diffs a human approves. CU's licensed EUDR PDFs can be dropped into the reg-watch sources. |
