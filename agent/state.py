"""Mengingat alert yang sudah dikirim agar tidak spam."""
from __future__ import annotations

import json
import time
from pathlib import Path

RANK = {"low": 1, "high": 2}


class AlertState:
    def __init__(self, path: str = "state/alerts.json"):
        self.path = Path(path)
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def should_send(self, symbol: str, direction: str, conviction: str, cooldown_hours: float) -> bool:
        prev = self.data.get(symbol)
        if not prev:
            return True
        age_h = (time.time() - prev["ts"]) / 3600
        if age_h >= cooldown_hours:
            return True
        if prev["direction"] != direction:
            return True                     # arah berbalik = informasi baru
        return RANK[conviction] > RANK.get(prev["conviction"], 0)   # naik dari low ke high

    def why_blocked(self, symbol: str) -> str:
        prev = self.data.get(symbol)
        if not prev:
            return ""
        age_h = (time.time() - prev["ts"]) / 3600
        return f"sudah dikirim {prev['conviction'].upper()} {prev['direction']} {age_h:.1f} jam lalu"

    def record(self, symbol: str, direction: str, conviction: str):
        self.data[symbol] = {"direction": direction, "conviction": conviction, "ts": time.time()}

    def save(self):
        cutoff = time.time() - 7 * 86400
        self.data = {k: v for k, v in self.data.items() if v["ts"] > cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True))
