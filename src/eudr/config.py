"""Runtime settings. Everything overridable via EUDR_* env vars or .env."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EUDR_", env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = Field(default=ROOT / "data", description="cases, evidence, ledger, outbox")
    db_url: str = Field(default="", description="SQLAlchemy URL; empty → sqlite under data_dir")
    geo_provider: str = Field(default="public", description="public | mock")
    raster_cache_dir: Path = Field(default=ROOT / "data" / "raster-cache")
    hansen_version: str = "GFC-2024-v1.12"
    worldcover_year: int = 2021
    tree_cover_threshold: int = Field(default=30, description="Hansen treecover2000 % ⇒ forest (EUDR canopy >10%, 30 is the conservative tropical default)")
    min_forest_patch_ha: float = 0.5
    min_loss_ha: float = 0.5
    cutoff_date: str = "2020-12-31"

    # Agents — run through the Claude Code personal profile (Max subscription, OAuth)
    agent_profile: str = Field(default="personal", description="personal (ccp, Max) | work (ccw, Bedrock eu-west-1)")
    claude_config_dir: Path | None = None
    pilot_mode: bool = Field(default=True, description="advisory outputs; no DDS submission")
    model_reasoning: str = "claude-opus-5"
    model_fast: str = "claude-sonnet-5"
    agent_max_turns: int = 24
    agent_workers: int = Field(default=3, description="concurrent agent calls")
    screen_workers: int = Field(default=4, description="concurrent plot screenings (network-bound)")
    analyst_auto_accept_confidence: float = 0.85

    # Country risk (Implementing Regulation of 20 May 2025)
    country_risk: dict[str, str] = Field(default_factory=lambda: {
        "BR": "standard", "AR": "standard", "PY": "standard", "UY": "low", "US": "low", "IN": "standard",
        "BY": "high", "KP": "high", "MM": "high", "RU": "high",
    })

    @property
    def sqlalchemy_url(self) -> str:
        return self.db_url or f"sqlite:///{self.data_dir / 'eudr.sqlite'}"

    def agent_env(self) -> dict[str, str]:
        """Env for the claude CLI subprocess: personal profile, no Bedrock/Vertex/API-key leakage."""
        work = self.agent_profile == "work"
        drop = ("ANTHROPIC_",) if work else ("ANTHROPIC_", "AWS_", "CLAUDE_CODE_USE_")
        env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        env["CLAUDE_CONFIG_DIR"] = str(self.claude_config_dir or (Path.home() / (".claude-work" if work else ".claude-personal")))
        return env


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.raster_cache_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
