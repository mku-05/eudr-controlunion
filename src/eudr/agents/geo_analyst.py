"""Geo Analyst: adjudicates EXCEPTION plots and QA-samples others by looking at the evidence. Recommends; never writes verdicts."""
from __future__ import annotations

import json

from eudr.agents.runtime import run_agent
from eudr.config import settings
from eudr.ledger import Ledger
from eudr.models import AnalystOpinion, Assessment, Plot

PROMPT_VERSION = "geo-analyst-2"
SYSTEM = """You are a remote-sensing analyst verifying EUDR deforestation-free status of a soya plot.
EUDR: forest = >0.5 ha, trees >5 m, canopy >10 %, not predominantly agricultural/urban. Deforestation = conversion of forest to
agricultural use after 31 Dec 2020, whether human-induced or not. Loss without conversion (fire, storm) is NOT deforestation for soya.
Cerrado savanna often fails the forest definition; say so when relevant, but flag native-vegetation conversion separately.
Flags: PASS = no deforestation signal, EXCEPTION = needs analyst/human review, CRITICAL = forest converted to agriculture after cut-off.
You will Read the evidence files listed (PNG chips, loss overlay, NDVI series). Look at them before concluding.
Common false positives: harvest cycles (NDVI dips every season), cloud/shadow, burn scars that regrow, eucalyptus rotations.
Cite only what you saw in the files or the metrics. If evidence is insufficient, say so and recommend EXCEPTION with low confidence.
Never recommend CRITICAL unless you saw loss inside the yellow plot outline in the after-image or overlay AND agricultural use after it."""


def run_geo_analyst(plot: Plot, asm: Assessment, reason: str, ledger: Ledger | None = None) -> AnalystOpinion:
    files = [e.uri for e in asm.evidence if e.type in ("chip_before", "chip_after", "loss_overlay", "ndvi_chart", "ndvi_series")]
    prompt = "\n".join([
        f"PLOT: {plot.name or plot.id} ({plot.computed_area_ha} ha), production {plot.production_start}..{plot.production_end}",
        f"ENGINE VERDICT: {asm.verdict} conf={asm.confidence} — {reason}",
        f"METRICS: {json.dumps(asm.metrics.model_dump() if asm.metrics else {})}",
        f"DATASETS: {[e.source + ':' + str(e.source_version) for e in asm.evidence if e.type == 'dataset']}",
        "EVIDENCE FILES (Read each):", *files,
        "Return an AnalystOpinion: recommended_verdict, confidence 0..1, rationale, cited_evidence (file names), flags.",
    ])
    op = run_agent("geo_analyst", SYSTEM, prompt, AnalystOpinion, model=settings.model_reasoning, prompt_version=PROMPT_VERSION,
                   tools=["Read"], cwd=str(settings.data_dir), ledger=ledger, max_turns=16)
    op.model, op.prompt_version = settings.model_reasoning, PROMPT_VERSION
    return op
