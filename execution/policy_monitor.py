"""
Policy Intelligence Monitor — proactive signal detection.

Monitors upstream policy signals BEFORE they become congressional trades:
  Level 1: White House / Federal Register EOs (immediate sector catalyst)
  Level 2: DoD / USASpending contract awards (specific stock catalyst)
  Level 3: Agency press releases (sector confirmation)
  Level 4: Congressional trade (lagging — already in whale_watch.py)

Run on each loop tick alongside whale_watch. Fires alerts on new signals.
"""

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from bs4 import BeautifulSoup

SIGNAL_CACHE = Path("logs/policy_signal_cache.json")

# ── Sector map: keywords → tickers to act on ──────────────────────────────
SECTOR_MAP = {
    "defense": {
        "keywords": ["defense", "military", "pentagon", "armed forces", "weapon",
                     "drone", "missile", "munition", "warfighter", "national security",
                     "golden dome", "maven", "darpa", "department of war"],
        "tickers": ["SHLD", "RTX", "LMT", "NOC", "AVAV", "LDOS", "GD", "LHX", "PLTR"],
        "etf": "SHLD",
    },
    "energy_fossil": {
        "keywords": ["oil", "gas", "lng", "coal", "drill", "offshore leasing",
                     "energy dominance", "pipeline", "permian", "outer continental shelf"],
        "tickers": ["XOM", "CVX", "COP", "OXY", "SLB"],
        "etf": "XLE",
    },
    "nuclear": {
        "keywords": ["nuclear", "reactor", "uranium", "nrc", "advanced reactor",
                     "small modular reactor", "smr", "fission", "400 gigawatt"],
        "tickers": ["CEG", "VST", "CCJ", "SMR", "OKLO", "NNE"],
        "etf": "NLR",
    },
    "critical_minerals": {
        "keywords": ["critical mineral", "rare earth", "lithium", "cobalt", "gallium",
                     "germanium", "tungsten", "semiconductor mineral", "strategic stockpile",
                     "mp materials", "usa rare earth"],
        "tickers": ["MP", "ALB", "LTHM", "CRIS", "UUUU"],
        "etf": "REMX",
    },
    "semiconductors": {
        "keywords": ["semiconductor", "chips act", "chip", "fab", "wafer", "intel",
                     "domestic manufacturing", "advanced computing", "tsmc"],
        "tickers": ["INTC", "AVGO", "AMAT", "KLAC", "LRCX"],
        "etf": "SOXX",
    },
    "domestic_manufacturing": {
        "keywords": ["reshoring", "made in america", "tariff", "domestic production",
                     "steel", "aluminum", "infrastructure", "industrial"],
        "tickers": ["CAT", "GE", "NUE", "X", "WHR", "DE"],
        "etf": "XLI",
    },
    "border_security": {
        "keywords": ["border", "immigration", "detention", "deportation", "ice",
                     "dhs", "customs", "enforcement", "detention center"],
        "tickers": ["GEO", "CXW"],
        "etf": None,
    },
    "crypto": {
        "keywords": ["bitcoin", "cryptocurrency", "digital asset", "strategic reserve",
                     "blockchain", "crypto", "defi", "stablecoin"],
        "tickers": ["MSTR", "COIN", "MARA", "RIOT", "CLSK"],
        "etf": "BITO",
    },
    "space_aerospace": {
        "keywords": ["space", "satellite", "launch", "nasa", "orbit", "supersonic",
                     "hypersonic", "spaceforce", "spacex"],
        "tickers": ["BA", "SPCE", "KTOS", "RKLB", "IRDM"],
        "etf": "UFO",
    },
    "ai_infrastructure": {
        "keywords": ["artificial intelligence", "ai", "data center", "gpu", "inference",
                     "model", "foundation model", "government ai", "aip"],
        "tickers": ["PLTR", "MSFT", "ORCL", "SMCI", "VRT"],
        "etf": "BOTZ",
    },
}

# ── Policy signal sources ──────────────────────────────────────────────────
# selector=None means use the json_api fetcher instead of BeautifulSoup
SOURCES = [
    {
        "name": "White House Fact Sheets",
        "url": "https://www.whitehouse.gov/fact-sheets/",
        "selector": ".wp-block-post-title a",
        "level": 1,
    },
    {
        "name": "Federal Register EOs",
        "url": (
            "https://www.federalregister.gov/api/v1/documents.json"
            "?conditions[presidential_document_type]=executive_order"
            "&per_page=20&order=newest&fields[]=title"
        ),
        "selector": None,  # JSON API — parsed separately
        "level": 1,
    },
    {
        "name": "DoD Contract Announcements",
        "url": "https://www.defense.gov/News/Contracts/",
        "selector": "p.title",
        "level": 2,
    },
    {
        "name": "White House Presidential Actions",
        "url": "https://www.whitehouse.gov/presidential-actions/",
        "selector": ".wp-block-post-title a",
        "level": 1,
    },
]


@dataclass
class PolicySignal:
    source: str
    headline: str
    sectors: List[str]
    tickers: List[str]
    level: int
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signal_id: str = ""

    def __post_init__(self):
        raw = f"{self.source}:{self.headline}"
        self.signal_id = hashlib.md5(raw.encode()).hexdigest()[:12]


class PolicyMonitor:
    def __init__(self, settings=None, notifier=None, db=None):
        self._settings = settings
        self._notifier = notifier
        self._db = db
        self._seen: set = self._load_cache()

    def _load_cache(self) -> set:
        if SIGNAL_CACHE.exists():
            try:
                return set(json.loads(SIGNAL_CACHE.read_text()))
            except Exception:
                pass
        return set()

    def _save_cache(self):
        SIGNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        # Keep last 500 signal IDs
        trimmed = list(self._seen)[-500:]
        SIGNAL_CACHE.write_text(json.dumps(trimmed))

    def _classify(self, text: str) -> tuple[List[str], List[str]]:
        """Map text to matched sectors and their tickers."""
        text_lower = text.lower()
        matched_sectors, matched_tickers = [], []
        for sector, cfg in SECTOR_MAP.items():
            if any(kw in text_lower for kw in cfg["keywords"]):
                matched_sectors.append(sector)
                matched_tickers.extend(cfg["tickers"])
        return matched_sectors, list(set(matched_tickers))

    def _fetch_headlines(self, source: dict) -> List[str]:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; PolicyMonitor/1.0)"}
            resp = requests.get(source["url"], headers=headers, timeout=12)
            resp.raise_for_status()

            # JSON API path (e.g. Federal Register)
            if source.get("selector") is None:
                data = resp.json()
                results = data.get("results", [])
                return [r["title"] for r in results[:20] if r.get("title")]

            # HTML scrape path
            soup = BeautifulSoup(resp.text, "html.parser")
            elements = soup.select(source["selector"])
            return [el.get_text(strip=True) for el in elements[:20] if el.get_text(strip=True)]
        except Exception as e:
            print(f"[POLICY] Fetch failed {source['name']}: {e}")
            return []

    def scan(self) -> List[PolicySignal]:
        """Scan all sources, return new signals not seen before."""
        new_signals: List[PolicySignal] = []

        for source in SOURCES:
            headlines = self._fetch_headlines(source)
            for headline in headlines:
                sectors, tickers = self._classify(headline)
                if not sectors:
                    continue

                sig = PolicySignal(
                    source=source["name"],
                    headline=headline,
                    sectors=sectors,
                    tickers=tickers,
                    level=source["level"],
                )

                if sig.signal_id in self._seen:
                    continue

                self._seen.add(sig.signal_id)
                new_signals.append(sig)
                print(f"[POLICY L{sig.level}] {sig.source}: {sig.headline[:80]}")
                print(f"  Sectors: {', '.join(sig.sectors)}")
                print(f"  Tickers: {', '.join(sig.tickers)}")

                if self._db:
                    try:
                        self._db.log_decision(
                            ticker=",".join(sig.tickers[:3]),
                            action="SIGNAL",
                            tier="policy_monitor",
                            confidence=0.85 if sig.level == 1 else 0.65,
                            reasoning=f"[L{sig.level}] {sig.source}: {sig.headline[:200]}",
                            status="signal",
                        )
                    except Exception:
                        pass

        if new_signals:
            self._save_cache()
            self._fire_alert(new_signals)

        return new_signals

    def _fire_alert(self, signals: List[PolicySignal]):
        if not self._notifier:
            return
        lines = [f"POLICY INTELLIGENCE — {len(signals)} new signal(s)\n"]
        for s in signals:
            lines.append(f"[L{s.level}] {s.source}")
            lines.append(f"  {s.headline[:100]}")
            lines.append(f"  Sectors: {', '.join(s.sectors)}")
            lines.append(f"  Watch:   {', '.join(s.tickers)}")
            lines.append("")
        try:
            self._notifier.send(
                subject=f"[Trading] {len(signals)} Policy Signal(s) Detected",
                body="\n".join(lines),
            )
        except Exception as e:
            print(f"[POLICY] Alert send failed: {e}")
