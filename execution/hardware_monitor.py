"""
Hardware monitor — CPU load and temperature.
Triggers alerts and pauses non-essential tasks when thresholds are exceeded.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psutil
from config import settings as cfg_module

ALERT_COOLDOWN_SEC = 3600  # at most one CPU/temp alert per hour (per type) — no per-cycle spam


class HardwareMonitor:
    def __init__(self, settings=None, notifier=None):
        self.cfg = settings or cfg_module.load()
        self._notifier = notifier
        self._cpu_samples: list = []
        self._temp_samples: list = []
        self._last_alert: dict = {}  # alert_key -> monotonic time of last send (cooldown)

    def _alert(self, key: str, msg: str) -> None:
        """Fire a critical alert at most once per ALERT_COOLDOWN_SEC per key, so a
        sustained breach doesn't email + Slack every loop cycle."""
        if not self._notifier:
            return
        now = time.monotonic()
        if now - self._last_alert.get(key, 0.0) < ALERT_COOLDOWN_SEC:
            return
        self._notifier.critical_alert(msg)
        self._last_alert[key] = now

    def sample(self) -> dict:
        cpu_pct = psutil.cpu_percent(interval=1)
        temp_c = self._read_temp()
        self._cpu_samples.append(cpu_pct)
        self._temp_samples.append(temp_c)
        return {"cpu_pct": cpu_pct, "temp_c": temp_c}

    def _read_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            for key in ("coretemp", "k10temp", "acpitz", "cpu_thermal"):
                if key in temps and temps[key]:
                    return temps[key][0].current
        except (AttributeError, NotImplementedError):
            pass
        return 0.0

    def averages(self) -> dict:
        cpu_avg = sum(self._cpu_samples) / len(self._cpu_samples) if self._cpu_samples else 0.0
        temp_avg = sum(self._temp_samples) / len(self._temp_samples) if self._temp_samples else 0.0
        return {"cpu_avg": cpu_avg, "temp_avg": temp_avg}

    def check_thresholds(self, metrics: dict) -> bool:
        """Returns True if thresholds are breached (caller should pause non-essential work)."""
        hw = self.cfg.hardware
        breached = False

        if metrics["cpu_pct"] > hw.cpu_threshold_pct:
            msg = f"CPU load {metrics['cpu_pct']:.1f}% exceeds threshold {hw.cpu_threshold_pct}%"
            print(f"[WARN] {msg}")
            self._alert("cpu", msg)
            breached = True

        if metrics["temp_c"] > hw.temp_threshold_c:
            msg = f"CPU temp {metrics['temp_c']:.1f}°C exceeds threshold {hw.temp_threshold_c}°C"
            print(f"[WARN] {msg}")
            self._alert("temp", msg)
            breached = True

        return breached
