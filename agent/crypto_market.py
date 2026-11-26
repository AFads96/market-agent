"""Data crypto langsung dari exchange (via ccxt): semua pair yang bisa ditradingkan,
harga OHLCV, funding rate, dan Open Interest."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import pandas as pd

from .universe import STABLES, Asset

log = logging.getLogger(__name__)
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR|[235][LS])$")


class CryptoExchange:
    """Membungkus satu exchange ccxt. Coba beberapa exchange berurutan sampai ada yang bisa diakses."""

    def __init__(self, cfg: dict):
        import ccxt

        self.cfg = cfg
        self.ex = None
        self.perp = {}      # base -> simbol perpetual (mis. BTC -> BTC/USDT:USDT)
        self.spot = {}      # base -> simbol spot (mis. BTC -> BTC/USDT)
        quotes = set(cfg.get("quotes", ["USDT", "USDC"]))
        for name in cfg["exchanges"]:
            try:
                ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 20000})
                markets = ex.load_markets()
            except Exception as e:
                log.warning("Exchange %s tidak bisa diakses (%s), coba berikutnya", name, str(e)[:120])
                continue
            for m in markets.values():
                if not m.get("active", True) or m.get("quote") not in quotes:
                    continue
                base = (m.get("base") or "").upper()
                if not base or base.lower() in STABLES or LEVERAGED.search(base):
                    continue
                if m.get("swap") and m.get("linear"):
                    self.perp.setdefault(base, m["symbol"])
                elif m.get("spot") and cfg.get("include_spot_only", True):
                    self.spot.setdefault(base, m["symbol"])
            if self.perp or self.spot:
                self.ex, self.name = ex, name
                log.info("Exchange crypto: %s (%d perpetual, %d spot)", name, len(self.perp), len(self.spot))
                break
        if not self.ex:
            raise RuntimeError("Tidak ada exchange crypto yang bisa diakses")

    # ---------- universe ----------
    def assets(self, names: dict[str, str] | None = None) -> list[Asset]:
        """Semua aset yang bisa ditradingkan, disaring berdasarkan volume 24 jam."""
        names = names or {}
        sym_by_base = {b: self.perp.get(b) or self.spot.get(b) for b in set(self.perp) | set(self.spot)}
        vols = {}
        try:
            tickers = {}
            # Ambil ticker spot dan perpetual (beberapa exchange memisahkannya per tipe).
            for kind in ("spot", "swap"):
                try:
                    tickers.update(self.ex.fetch_tickers(params={"type": kind}))
                except Exception:
                    pass
            if not tickers:
                tickers = self.ex.fetch_tickers()

            def usd_volume(t: dict) -> float:
                # quoteVolume di sebagian exchange (mis. OKX perpetual) berisi jumlah kontrak,
                # jadi ambil nilai terbesar dari quoteVolume dan baseVolume x harga.
                last = t.get("last") or t.get("close") or 0
                cands = [t.get("quoteVolume") or 0, (t.get("baseVolume") or 0) * last]
                return max(cands)

            for base in sym_by_base:
                vols[base] = max(usd_volume(tickers.get(s) or {})
                                 for s in (self.perp.get(base, ""), self.spot.get(base, "")))
        except Exception as e:
            log.warning("fetch_tickers gagal (%s); filter volume dilewati", e)
        min_vol = self.cfg["min_volume_usd"]
        out = []
        for base, s in sorted(sym_by_base.items()):
            if vols and vols.get(base, 0) < min_vol:
                continue
            nm = names.get(base, "")
            quote = s.split("/")[1].split(":")[0]
            a = Asset(f"{base}/{quote}", s, "crypto", nm, [nm] if nm else [])
            a.base, a.has_perp, a.vol_24h = base, base in self.perp, float(vols.get(base, 0) or 0)
            out.append(a)
        log.info("Crypto likuid (vol 24j >= $%s): %d aset", f"{min_vol:,.0f}", len(out))
        return out

    # ---------- harga ----------
    def ohlcv(self, assets: list[Asset], days: int = 220) -> dict[str, pd.DataFrame]:
        data = {}
        for i, a in enumerate(assets):
            sym = self.spot.get(a.base) or a.yf_symbol   # spot dulu (riwayat lebih panjang), lalu perp
            try:
                rows = self.ex.fetch_ohlcv(sym, "1d", limit=days)
            except Exception:
                try:
                    rows = self.ex.fetch_ohlcv(a.yf_symbol, "1d", limit=days)
                except Exception as e:
                    log.debug("OHLCV %s gagal: %s", a.symbol, e)
                    continue
            if rows:
                df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
                df.index = pd.to_datetime(df["ts"], unit="ms")
                data[a.yf_symbol] = df.drop(columns="ts")
            if i and i % 100 == 0:
                log.info("OHLCV crypto: %d/%d", i, len(assets))
        log.info("Data harga crypto: %d/%d aset", len(data), len(assets))
        return data

    # ---------- derivatif ----------
    def funding_rates(self) -> dict[str, float]:
        """Funding rate terkini untuk SEMUA perpetual (satu request). Kunci = base (BTC)."""
        if not self.perp:
            return {}
        try:
            fr = self.ex.fetch_funding_rates(list(self.perp.values()))
        except Exception:
            try:
                fr = self.ex.fetch_funding_rates()
            except Exception as e:
                log.warning("Funding rate gagal: %s", e)
                return {}
        rev = {v: k for k, v in self.perp.items()}
        out = {}
        for s, d in fr.items():
            if s in rev and d.get("fundingRate") is not None:
                rate = float(d["fundingRate"])
                # normalisasi ke per-8 jam bila exchange memakai interval lain (mis. 1 jam di Hyperliquid)
                interval = (d.get("interval") or "8h").rstrip("h")
                try:
                    rate = rate * 8 / float(interval)
                except ValueError:
                    pass
                out[rev[s]] = rate
        log.info("Funding rate: %d perpetual", len(out))
        return out

    def open_interest(self, base: str, snapshots: "OISnapshots") -> dict | None:
        """OI sekarang + perubahan 24 jam. Pakai riwayat exchange; kalau tidak ada, pakai snapshot run sebelumnya."""
        s = self.perp.get(base)
        if not s:
            return None
        if self.ex.has.get("fetchOpenInterestHistory"):
            try:
                hist = self.ex.fetch_open_interest_history(s, "1h", limit=25)
                vals = [h.get("openInterestValue") or h.get("openInterestAmount") for h in hist]
                vals = [float(v) for v in vals if v]
                if len(vals) >= 2:
                    return {"oi_now": vals[-1], "oi_change_24h_pct": round((vals[-1] / vals[0] - 1) * 100, 2),
                            "oi_basis": f"{len(vals) - 1}j"}
            except Exception as e:
                log.debug("OI history %s gagal: %s", base, e)
        try:
            d = self.ex.fetch_open_interest(s)
            now = float(d.get("openInterestValue") or d.get("openInterestAmount") or 0)
        except Exception as e:
            log.debug("OI %s gagal: %s", base, e)
            return None
        if not now:
            return None
        prev = snapshots.get(f"{self.name}:{base}")
        snapshots.put(f"{self.name}:{base}", now)
        if prev:
            hours = max((time.time() - prev[0]) / 3600, 0.1)
            return {"oi_now": now, "oi_change_24h_pct": round((now / prev[1] - 1) * 100, 2),
                    "oi_basis": f"{hours:.0f}j"}
        return {"oi_now": now, "oi_change_24h_pct": None, "oi_basis": None}


class OISnapshots:
    """Simpan OI dari run sebelumnya (untuk exchange tanpa riwayat OI). Ambil snapshot ~24 jam lalu."""

    def __init__(self, path="state/oi_snapshots.json"):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, key):
        snaps = self.data.get(key, [])
        if not snaps:
            return None
        target = time.time() - 24 * 3600
        return min(snaps, key=lambda s: abs(s[0] - target))

    def put(self, key, value):
        snaps = [s for s in self.data.get(key, []) if s[0] > time.time() - 30 * 3600]
        snaps.append([time.time(), value])
        self.data[key] = snaps

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


def coin_names(limit_pages: int = 2) -> dict[str, str]:
    """Nama koin dari CoinGecko (untuk mencocokkan berita). Opsional; gagal tidak masalah."""
    import requests

    names = {}
    for page in range(1, limit_pages + 1):
        try:
            r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                             params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page},
                             timeout=20)
            r.raise_for_status()
            for c in r.json():
                names.setdefault(c["symbol"].upper(), c["name"])
        except Exception as e:
            log.debug("CoinGecko names gagal: %s", e)
            break
    return names


def fear_greed() -> dict | None:
    """Crypto Fear & Greed Index (alternative.me), gratis."""
    import requests

    try:
        d = requests.get("https://api.alternative.me/fng/?limit=2", timeout=15).json()["data"]
        return {"value": int(d[0]["value"]), "label": d[0]["value_classification"],
                "yesterday": int(d[1]["value"]) if len(d) > 1 else None}
    except Exception as e:
        log.debug("Fear & Greed gagal: %s", e)
        return None
