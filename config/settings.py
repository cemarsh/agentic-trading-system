"""
Centralized configuration loader.
Reads strategy_params.yaml and environment variables.
Never logs or exposes credentials.
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

CONFIG_PATH = Path(__file__).parent / "strategy_params.yaml"


def _load_yaml() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@dataclass
class AlpacaConfig:
    key: str
    secret: str
    base_url: str
    paper_mode: bool


@dataclass
class DatabaseConfig:
    url: str
    table: str
    state_file: str


@dataclass
class NotificationConfig:
    resend_key: str
    alert_email: str
    daily_report_time: str
    timezone: str


@dataclass
class HardwareConfig:
    cpu_threshold_pct: float
    temp_threshold_c: float
    poll_interval_seconds: int


@dataclass
class IntelligenceConfig:
    min_confidence_score: float


@dataclass
class WhaleWatchConfig:
    source_url: str
    politician_names: List[str]
    whale_trade_min_value: float
    max_portfolio_pct_per_trade: float
    roc_lookback_minutes: int


@dataclass
class WheelConfig:
    tickers: List[str]
    target_delta: float
    expiration_weeks: int
    cc_strike_markup_pct: float
    min_premium_pct: float


@dataclass
class ProtectionConfig:
    trailing_stop_pct: float
    gap_tighten_pct: float
    ladder_drop_pct: float
    ladder_buy_shares: int


@dataclass
class GuardrailsConfig:
    manual_confirm_threshold: float
    verification_trades: int
    api_retry_limit: int
    paper_mode: bool


@dataclass
class Settings:
    alpaca: AlpacaConfig
    database: DatabaseConfig
    notifications: NotificationConfig
    hardware: HardwareConfig
    intelligence: IntelligenceConfig
    whale_watch: WhaleWatchConfig
    wheel: WheelConfig
    protection: ProtectionConfig
    guardrails: GuardrailsConfig


def load() -> Settings:
    raw = _load_yaml()

    alpaca_key = os.environ.get("ALPACA_KEY")
    alpaca_secret = os.environ.get("ALPACA_SECRET")
    alpaca_base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not alpaca_key or not alpaca_secret:
        raise EnvironmentError("ALPACA_KEY and ALPACA_SECRET must be set in environment")

    database_url = os.environ.get("DATABASE_URL")  # optional — logging disabled if unset
    resend_key = os.environ.get("RESEND_API_KEY")  # optional — email disabled if unset

    g = raw["guardrails"]
    paper_mode = g.get("paper_mode", True)

    return Settings(
        alpaca=AlpacaConfig(
            key=alpaca_key,
            secret=alpaca_secret,
            base_url=alpaca_base_url,
            paper_mode=paper_mode,
        ),
        database=DatabaseConfig(
            url=database_url or "",
            table=raw["database"]["table"],
            state_file=raw["database"]["state_file"],
        ),
        notifications=NotificationConfig(
            resend_key=resend_key or "",
            alert_email=os.environ.get("ALERT_EMAIL", raw["notifications"]["alert_email"]),
            daily_report_time=raw["notifications"]["daily_report_time"],
            timezone=raw["notifications"]["timezone"],
        ),
        hardware=HardwareConfig(**raw["hardware"]),
        intelligence=IntelligenceConfig(**raw["intelligence"]),
        whale_watch=WhaleWatchConfig(**raw["whale_watch"]),
        wheel=WheelConfig(**raw["wheel"]),
        protection=ProtectionConfig(**raw["protection"]),
        guardrails=GuardrailsConfig(**g),
    )
