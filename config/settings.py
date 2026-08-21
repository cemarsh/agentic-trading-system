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
    status_check_interval_hours: int
    timezone: str
    slack_webhook_url: str = ""


@dataclass
class HardwareConfig:
    cpu_threshold_pct: float
    temp_threshold_c: float
    poll_interval_seconds: int


@dataclass
class IntelligenceConfig:
    min_confidence_score: float


@dataclass
class FeedsConfig:
    """Poll intervals for external intelligence feeds (see strategy_params.yaml)."""
    whale_poll_minutes: int = 30
    policy_poll_minutes: int = 15
    fetch_error_log_cooldown_minutes: int = 60


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
    max_portfolio_pct_per_trade: float
    max_wheel_allocation_pct: float
    min_iv_rank: float = 0.0          # only sell CSPs when IV rank >= this (0–1); 0 disables the gate
    iv_gate_fail_open: bool = False   # False = no IV history means NO trade (hard gate)
    min_credit_per_share: float = 0.15  # absolute floor on CSP entry credit from the NBBO bid
    earnings_gate: bool = True        # skip CSPs whose expiry window contains an earnings date
    max_contracts_per_trade: int = 1  # hard ceiling on contracts per CSP; 1 = legacy behavior
    prioritize_by_iv_rank: bool = False  # evaluate richest-premium candidates first
    skip_log_cooldown_minutes: int = 240  # de-dupe repeated skip decisions in the log/journal
    use_signal_candidates: bool = False   # let policy signals promote wheel candidates
    # --- Book-health gate (2026-08-21) ---
    max_book_loss_pct: float = 0.0        # stop opening CSPs when total unrealized loss exceeds this % of equity; 0 disables
    skip_losing_underlying: bool = False  # don't open a new CSP on a name already carrying a loss
    # --- Entry expected-value gate (2026-08-21) ---
    min_credit_vs_expected_move: float = 0.0  # credit/share as a fraction of the 1-sigma move over DTE; 0 disables
    # --- Covered calls on deeply-underwater holdings (2026-08-21) ---
    write_covered_calls: bool = False         # let run_cycle write CCs on stage-2 holdings
    underwater_cc_loss_pct: float = 25.0      # a holding this far below cost uses a spot-based strike
    underwater_cc_markup_pct: float = 12.0    # that strike = spot x (1 + this), not cost basis
    min_otm_vol_mult: float = 0.0             # strike must sit >= this many 1-sigma moves OTM; 0 disables
    realized_vol_lookback_days: int = 30      # daily bars used to compute realized vol


@dataclass
class ProtectionConfig:
    trailing_stop_pct: float
    gap_tighten_pct: float
    ladder_drop_pct: float
    ladder_buy_shares: int
    max_ladder_rungs: int = 3  # hard cap on ladder buys per ticker (prevents runaway averaging-down)
    no_auto_manage: list = None  # tickers the protective logic ignores (no trailing stop / no ladder)
    # Catastrophic backstop applied to EVERY equity long, no_auto_manage included.
    # no_auto_manage exists to stop the ladder averaging down, not to remove all
    # downside protection — FJET fell 31% with nothing watching it. 0 disables.
    max_equity_loss_pct: float = 0.0
    catastrophic_exempt: list = None  # tickers held under an explicit manual exit plan


@dataclass
class UniverseConfig:
    """Mechanical universe screening — see execution/universe_screen.py."""
    enabled: bool = False
    max_correlation: float = 0.60          # reject a candidate more correlated than this to the BOOK
    correlation_lookback_days: int = 60
    max_spread_pct: float = 25.0           # NBBO width as % of mid on the strike we'd sell
    max_new_per_run: int = 4               # don't rebuild the universe in one pass
    max_promoted: int = 12                 # ceiling on screened names held in the dynamic universe
    seed_pool: List[str] = field(default_factory=list)


@dataclass
class RegimeConfig:
    bear_spy_threshold: float
    extreme_spy_threshold: float


@dataclass
class HedgeConfig:
    enabled: bool
    tickers: List[str]
    allocation_pct: float
    extreme_multiplier: float


@dataclass
class PositionManagementConfig:
    close_profit_pct: float = 50.0
    roll_dte_threshold: int = 21
    force_close_dte: int = 7
    roll_weeks_out: int = 4
    stop_loss_pct: float = 250.0      # BTC a short PUT once its loss reaches this % of premium (0/None disables)
    roll_otm_buffer: float = 0.05     # roll down-and-out: new put strike <= spot * (1 - this)
    min_roll_credit: float = 0.15     # $/share floor on roll net credit; below it, close instead
    min_hold_hours: float = 24.0      # never ROLL a leg opened less than this long ago
    # A resting close order muted its own position: the working-order guard skipped
    # the symbol every cycle while the loss kept running. Re-price instead. 0 disables.
    stale_order_seconds: int = 0      # cancel + re-price a working close order older than this
    max_reprice_attempts: int = 3     # give up (and alert) after this many re-prices in a day
    reprice_aggression: float = 0.02  # each re-price crosses the spread by this much more


@dataclass
class RiskConfig:
    max_position_pct: float = 5.0
    quarantine_max_position_pct: float = 1.0
    quarantined_tickers: List[str] = field(default_factory=list)
    sector_cap_pct: float = 20.0
    deadman_cancel_orders: bool = True
    sector_map: dict = field(default_factory=dict)


@dataclass
class LiveGatesConfig:
    min_days_since_critical_alert: int = 60
    min_profit_factor: float = 1.3
    max_drawdown_pct: float = 8.0
    history_window_days: int = 90
    initial_capital_fraction: float = 0.25


@dataclass
class AnthropicConfig:
    api_key: str


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
    regime: RegimeConfig
    hedge: HedgeConfig
    anthropic: AnthropicConfig
    position_management: PositionManagementConfig = None
    risk: RiskConfig = None
    universe: UniverseConfig = None
    live_gates: LiveGatesConfig = None
    feeds: FeedsConfig = None


def load() -> Settings:
    raw = _load_yaml()

    alpaca_key = os.environ.get("ALPACA_KEY")
    alpaca_secret = os.environ.get("ALPACA_SECRET")
    alpaca_base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not alpaca_key or not alpaca_secret:
        raise EnvironmentError("ALPACA_KEY and ALPACA_SECRET must be set in environment")

    database_url = os.environ.get("DATABASE_URL")  # optional — logging disabled if unset
    resend_key = os.environ.get("RESEND_API_KEY")  # optional — email disabled if unset
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")  # optional — advisor disabled if unset

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
            status_check_interval_hours=raw["notifications"].get("status_check_interval_hours", 2),
            timezone=raw["notifications"]["timezone"],
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
        ),
        hardware=HardwareConfig(**raw["hardware"]),
        intelligence=IntelligenceConfig(**raw["intelligence"]),
        feeds=FeedsConfig(**(raw.get("feeds") or {})),
        whale_watch=WhaleWatchConfig(**raw["whale_watch"]),
        wheel=WheelConfig(**raw["wheel"]),
        protection=ProtectionConfig(**raw["protection"]),
        guardrails=GuardrailsConfig(**g),
        regime=RegimeConfig(**raw["regime"]),
        hedge=HedgeConfig(**raw["hedge"]),
        anthropic=AnthropicConfig(api_key=anthropic_key),
        position_management=PositionManagementConfig(**{
            k: v for k, v in raw.get("position_management", {}).items()
            if k in PositionManagementConfig.__dataclass_fields__
        }),
        risk=RiskConfig(**{
            k: v for k, v in (raw.get("risk") or {}).items()
            if k in RiskConfig.__dataclass_fields__
        }),
        universe=UniverseConfig(**{
            k: v for k, v in (raw.get("universe") or {}).items()
            if k in UniverseConfig.__dataclass_fields__
        }),
        live_gates=LiveGatesConfig(**{
            k: v for k, v in (raw.get("live_gates") or {}).items()
            if k in LiveGatesConfig.__dataclass_fields__
        }),
    )
