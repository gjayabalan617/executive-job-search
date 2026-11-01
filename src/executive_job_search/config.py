"""Settings loaded from environment variables (EJS_ prefix) with safe defaults."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, Field, SecretStr

DEFAULT_SEEN_PATH = "/home/user/workspace/job_search/seen_jobs.json"
MODES = ("linkedin_only", "employer_direct")


def _bool(v: Optional[str], default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _opt_float(v: Optional[str]) -> Optional[float]:
    return float(v) if v not in (None, "") else None


class Settings(BaseModel):
    mode: str = "linkedin_only"
    data_dir: Path = Path("./data")
    seen_path: Path = Path(DEFAULT_SEEN_PATH)
    boards_file: Path = Path("./boards.yaml")
    intents_file: Optional[Path] = None

    freshness_days: int = 14
    min_score: float = 80.0
    min_description_chars: int = 500

    max_concurrency: int = 2
    http_timeout: float = 20.0
    http_max_retries: int = 3
    lever_page_size: int = 100
    lever_max_pages: int = 50

    # notifications (disabled until the operator explicitly enables sending)
    notify_send_enabled: bool = False
    notify_unknown_date: bool = False
    notify_max_attempts: int = 5
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[SecretStr] = None
    smtp_starttls: bool = True
    smtp_from: Optional[str] = None
    smtp_to: Optional[str] = None

    # optional LLM evaluator (disabled by default: no paid API usage without operator approval)
    llm_enabled: bool = False
    anthropic_api_key: Optional[SecretStr] = None
    anthropic_model: Optional[str] = None
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_max_calls_per_run: int = 25
    llm_max_tokens_per_run: int = 200_000
    llm_max_output_tokens: int = 900
    llm_max_input_chars: int = 14_000
    llm_max_retries: int = 2
    llm_usd_cap_per_run: Optional[float] = None
    llm_price_in_per_mtok: Optional[float] = None
    llm_price_out_per_mtok: Optional[float] = None

    # LinkedIn: only a configured, authorised provider is ever used
    linkedin_provider: Optional[str] = None
    linkedin_feed_path: Optional[Path] = None

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "executive_job_search.sqlite3"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def run_lock_path(self) -> Path:
        return self.data_dir / "run.lock"

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)

    def llm_ready(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key and self.anthropic_model)


def load_settings(env: Optional[Mapping[str, str]] = None, **overrides) -> Settings:
    e = os.environ if env is None else env
    g = lambda k, d=None: e.get(k, d)  # noqa: E731
    data: dict = {
        "mode": g("EJS_MODE", "linkedin_only"),
        "data_dir": Path(g("EJS_DATA_DIR", "./data")),
        "seen_path": Path(g("EJS_SEEN_PATH", DEFAULT_SEEN_PATH)),
        "boards_file": Path(g("EJS_BOARDS_FILE", "./boards.yaml")),
        "intents_file": Path(g("EJS_INTENTS_FILE")) if g("EJS_INTENTS_FILE") else None,
        "freshness_days": int(g("EJS_FRESHNESS_DAYS", "14")),
        "min_score": float(g("EJS_MIN_SCORE", "80")),
        "min_description_chars": int(g("EJS_MIN_DESCRIPTION_CHARS", "500")),
        "max_concurrency": int(g("EJS_MAX_CONCURRENCY", "2")),
        "http_timeout": float(g("EJS_HTTP_TIMEOUT", "20")),
        "http_max_retries": int(g("EJS_HTTP_MAX_RETRIES", "3")),
        "notify_send_enabled": _bool(g("EJS_NOTIFY_SEND_ENABLED")),
        "notify_unknown_date": _bool(g("EJS_NOTIFY_UNKNOWN_DATE")),
        "notify_max_attempts": int(g("EJS_NOTIFY_MAX_ATTEMPTS", "5")),
        "smtp_host": g("EJS_SMTP_HOST") or None,
        "smtp_port": int(g("EJS_SMTP_PORT", "587")),
        "smtp_user": g("EJS_SMTP_USER") or None,
        "smtp_password": SecretStr(g("EJS_SMTP_PASSWORD")) if g("EJS_SMTP_PASSWORD") else None,
        "smtp_starttls": _bool(g("EJS_SMTP_STARTTLS"), True),
        "smtp_from": g("EJS_SMTP_FROM") or None,
        "smtp_to": g("EJS_SMTP_TO") or None,
        "llm_enabled": _bool(g("EJS_LLM_ENABLED")),
        "anthropic_api_key": SecretStr(g("ANTHROPIC_API_KEY")) if g("ANTHROPIC_API_KEY") else None,
        "anthropic_model": g("EJS_ANTHROPIC_MODEL") or None,
        "llm_max_calls_per_run": int(g("EJS_LLM_MAX_CALLS_PER_RUN", "25")),
        "llm_max_tokens_per_run": int(g("EJS_LLM_MAX_TOKENS_PER_RUN", "200000")),
        "llm_usd_cap_per_run": _opt_float(g("EJS_LLM_USD_CAP_PER_RUN")),
        "llm_price_in_per_mtok": _opt_float(g("EJS_LLM_PRICE_IN_PER_MTOK")),
        "llm_price_out_per_mtok": _opt_float(g("EJS_LLM_PRICE_OUT_PER_MTOK")),
        "linkedin_provider": g("EJS_LINKEDIN_PROVIDER") or None,
        "linkedin_feed_path": Path(g("EJS_LINKEDIN_FEED_PATH")) if g("EJS_LINKEDIN_FEED_PATH") else None,
        "log_level": g("EJS_LOG_LEVEL", "INFO"),
    }
    data.update(overrides)
    s = Settings(**data)
    if s.mode not in MODES:
        raise ValueError(f"EJS_MODE must be one of {MODES}, got {s.mode!r}")
    return s
