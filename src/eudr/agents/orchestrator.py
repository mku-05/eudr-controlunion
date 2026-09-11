"""Orchestrator: conversational front over the workflow. Tools call the same engine functions the CLI does."""
from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock, create_sdk_mcp_server, tool

from eudr.agents.runtime import _env
from eudr.config import settings

SYSTEM = """You are the case manager for an EUDR soya due-diligence platform. You talk to an exporter or a Control Union auditor.
Use the tools to inspect and advance the case; never guess numbers — read them from the tools. Explain verdicts in plain language,
list what is still owed and by whom, and say clearly which actions need a named human (CRITICALs, overrides, signing).
Outputs are advisory evidence preparation; you cannot acknowledge, override or decide conformity yourself; offer the exact CLI/API action instead."""


def _txt(x: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(x, ensure_ascii=False, default=str)[:60000]}]}


def build_tools(case_id: str):
    from eudr.workflow import engine

    @tool("get_case", "Full case summary: status, suppliers, plots with verdicts, gaps, lots, risk, legality", {})
    async def get_case(args):
        return _txt(engine.summary(case_id))

    @tool("run", "Advance the case through the workflow until it needs a human", {})
    async def run(args):
        return _txt(engine.run(case_id))

    @tool("explain_plot", "Metrics, evidence, analyst opinion and reviewer state for one plot", {"plot_id": str})
    async def explain_plot(args):
        return _txt(engine.explain_plot(case_id, args["plot_id"]))

    @tool("review_queue", "Assessments waiting for a human", {})
    async def review_queue(args):
        return _txt(engine.review_queue(case_id))

    @tool("ledger_tail", "Last N ledger entries", {"n": int})
    async def ledger_tail(args):
        return _txt(engine.ledger_tail(case_id, int(args.get("n", 20))))

    return create_sdk_mcp_server("eudr", tools=[get_case, run, explain_plot, review_queue, ledger_tail])


async def chat(case_id: str, ask, say) -> None:
    opts = ClaudeAgentOptions(model=settings.model_reasoning, env=_env(), system_prompt=SYSTEM,
                              mcp_servers={"eudr": build_tools(case_id)}, allowed_tools=["mcp__eudr__*"],
                              permission_mode="bypassPermissions", max_turns=30)
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(f"Case {case_id} is loaded. Start by summarising it in 5 lines.")
        async for m in client.receive_response():
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock):
                        say(b.text)
        while True:
            q = ask()
            if not q or q.strip().lower() in ("exit", "quit"):
                return
            await client.query(q)
            async for m in client.receive_response():
                if isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock):
                            say(b.text)
