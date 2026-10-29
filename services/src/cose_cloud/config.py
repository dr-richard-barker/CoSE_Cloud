"""Settings from the environment (deploy/compose/.env.example lists them). Nothing secret has a default."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: Optional[float]) -> Optional[float]:
    v = os.environ.get(name)
    return default if v in (None, "") else float(v)


@dataclass(frozen=True)
class Settings:
    database_url: str
    # broker (ingest + simulator only; the API gets no broker credentials at all)
    mqtt_host: str
    mqtt_port: int
    mqtt_ca: Optional[Path]
    mqtt_cert: Optional[Path]
    mqtt_key: Optional[Path]
    # CoSE_Agent
    chat_model: str
    chat_effort: str
    chat_max_tokens: int
    chat_max_rounds: int
    chat_server_fallback: bool
    local_llm_url: str
    local_llm_model: Optional[str]
    llm_global_monthly_cap_usd: Optional[float]
    llm_kill_switch: bool
    # sessions
    session_days: int
    cookie_secure: bool


def settings() -> Settings:
    env = os.environ.get
    path = lambda k: Path(env(k)) if env(k) else None  # noqa: E731
    return Settings(
        database_url=env("COSE_DATABASE_URL", "postgresql://cose:cose@127.0.0.1:5432/cose"),
        mqtt_host=env("COSE_MQTT_HOST", "localhost"),
        mqtt_port=int(env("COSE_MQTT_PORT", "8883")),
        mqtt_ca=path("COSE_MQTT_CA"), mqtt_cert=path("COSE_MQTT_CERT"), mqtt_key=path("COSE_MQTT_KEY"),
        chat_model=env("COSE_CHAT_MODEL", "claude-opus-5-5"),
        chat_effort=env("COSE_CHAT_EFFORT", "medium"),
        chat_max_tokens=int(env("COSE_CHAT_MAX_TOKENS", "16000")),
        chat_max_rounds=int(env("COSE_CHAT_MAX_ROUNDS", "8")),
        chat_server_fallback=_bool("COSE_CHAT_SERVER_FALLBACK", True),
        local_llm_url=env("COSE_LOCAL_LLM_URL", "http://127.0.0.1:11434/v1"),
        local_llm_model=env("COSE_LOCAL_LLM_MODEL") or None,
        llm_global_monthly_cap_usd=_float("COSE_LLM_GLOBAL_MONTHLY_CAP_USD", 50.0),
        llm_kill_switch=_bool("COSE_LLM_KILL_SWITCH", False),
        session_days=int(env("COSE_SESSION_DAYS", "14")),
        cookie_secure=_bool("COSE_COOKIE_SECURE", False),
    )
