"""One-shot runner — manually trigger the weekly wrap-up."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings as cfg_module
from execution.alpaca_client import AlpacaClient
from execution.regime_detector import RegimeDetector
from execution.notifier import Notifier
from execution.weekly_journal import weekly_wrapup

cfg = cfg_module.load()
alpaca = AlpacaClient(settings=cfg)

regime = "NEUTRAL"
try:
    regime = RegimeDetector(settings=cfg, alpaca_client=alpaca).detect()
except Exception as e:
    print(f"[RUN] regime detect failed: {e}")

notifier = Notifier(settings=cfg)

print(f"[RUN] Regime: {regime}")
path = weekly_wrapup(
    ref_date=date.today(),
    alpaca_client=alpaca,
    regime=regime,
    notifier=notifier,
    settings=cfg,
)
print(f"[RUN] Done — {path}")
