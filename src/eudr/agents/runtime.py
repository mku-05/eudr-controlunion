"""One way to call a typed agent through the Claude Code personal profile."""
from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
from pydantic import BaseModel

from eudr.config import settings
from eudr.ledger import Ledger, sha256_json

T = TypeVar("T", bound=BaseModel)


class AgentError(RuntimeError):
    pass


def _env() -> dict[str, str]:
    env = settings.agent_env()
    if settings.agent_profile != "work":
        for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"):
            env[k] = ""
    return env


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else json.loads(text)


async def run_agent_async(name: str, system_prompt: str, prompt: str, schema: type[T], *, model: str | None = None,
                          prompt_version: str = "1", tools: list[str] | None = None, mcp_servers: dict | None = None,
                          cwd: str | None = None, max_turns: int | None = None, ledger: Ledger | None = None) -> T:
    model = model or settings.model_fast
    opts = ClaudeAgentOptions(
        model=model, env=_env(), cwd=cwd, max_turns=max_turns or settings.agent_max_turns,
        system_prompt=system_prompt, allowed_tools=tools or [], mcp_servers=mcp_servers or {},
        permission_mode="bypassPermissions" if tools else None,
        output_format={"type": "json_schema", "schema": schema.model_json_schema()},
    )
    texts: list[str] = []
    result: ResultMessage | None = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            texts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise AgentError(f"{name}: {getattr(result, 'subtype', 'no result')} {getattr(result, 'result', '')}")
    raw = result.structured_output
    if raw is None:
        if not texts:
            raise AgentError(f"{name}: no output")
        raw = _extract_json(texts[-1])
    out = schema.model_validate(raw)
    if ledger:
        ledger.append("agent_step", name, {"model": model, "prompt_version": prompt_version, "system_hash": sha256_json(system_prompt),
                                           "prompt_hash": sha256_json(prompt), "output_hash": sha256_json(out.model_dump(mode="json")),
                                           "turns": result.num_turns, "cost_usd": result.total_cost_usd})
    return out


def run_agent(*args, **kwargs):
    return asyncio.run(run_agent_async(*args, **kwargs))
