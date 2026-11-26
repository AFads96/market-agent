"""Menyusun daftar aset dan mengunduh data harga."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (market-agent)"}
STABLES = {"usdt", "usdc", "dai", "fdusd", "tusd", "usde", "usds", "pyusd", "busd", "usdd",
           "frax", "gusd", "usdp", "lusd", "eurc", "eurt", "xaut", "paxg", "susde", "usd1", "rlusd"}


@dataclass
class Asset:
    symbol: str            # kode tampilan, mis. BBCA atau BTC
    yf_symbol: str         # kode Yahoo Finance, mis. BBCA.JK atau BTC-USD
    market: str            # idx | us | crypto
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    base: str = ""          # crypto: simbol dasar, mis. BTC
    has_perp: bool = False  # crypto: punya kontrak perpetual (ada OI & funding)

    @property
    def is_crypto(self) -> bool:
        return self.market == "crypto"


def _read_list(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.split("#", 1)[0].strip().upper()
        if line:
            out.append(line)
    return out


def _fetch_idx_list() -> list[str]:
    url = "https://www.idx.co.id/primary/StockData/GetSecuritiesStock?start=0&length=9999"
    try:
        r = requests.get(url, headers={**UA, "Accept": "application/json"}, timeout=20)
        r.raise_for_status()
        rows = r.json().get("data", [])
        codes = sorted({row["Code"].strip().upper() for row in rows if row.get("Code")})
        if len(codes) > 300:
            log.info("Daftar IDX diambil dari situs IDX: %d emiten", len(codes))
            return codes
    except Exception as e:  # situs IDX sering memblokir bot
        log.warning("Gagal mengambil daftar IDX (%s), memakai file lokal", e)
    return []


def idx_assets(cfg: dict) -> list[Asset]:
    codes = _fetch_idx_list() if cfg.get("try_fetch_from_idx") else []
    if not codes:
        codes = _read_list(cfg["tickers_file"])
    return [Asset(c, f"{c}.JK", "idx") for c in codes]


def us_assets(cfg: dict) -> list[Asset]:
    return [Asset(c, c.replace(".", "-"), "us") for c in _read_list(cfg["tickers_file"])]


def crypto_assets(cfg: dict) -> list[Asset]:
    out, page, per_page = [], 1, 250
    while len(out) < cfg["top_n"] and page <= 4:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": per_page, "page": page},
            headers=UA, timeout=30,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for c in rows:
            sym = c["symbol"].upper()
            if cfg.get("exclude_stablecoins") and c["symbol"].lower() in STABLES:
                continue
            if (c.get("total_volume") or 0) < cfg["min_volume_usd"]:
                continue
            out.append(Asset(sym, f"{sym}-USD", "crypto", c["name"], [c["name"], c["id"]]))
        page += 1
    return out[: cfg["top_n"]]


def stock_universe(cfg: dict) -> list[Asset]:
    u = cfg["universe"]
    assets: list[Asset] = []
    if u["idx"]["enabled"]:
        assets += idx_assets(u["idx"])
    if u["us"]["enabled"]:
        assets += us_assets(u["us"])
    log.info("Universe saham: %d", len(assets))
    return assets


def coingecko_crypto(cfg: dict) -> list[Asset]:
    """Cadangan bila tidak ada exchange yang bisa diakses."""
    try:
        out = crypto_assets(cfg)
    except Exception as e:
        log.error("Gagal mengambil daftar crypto dari CoinGecko: %s", e)
        return []
    for a in out:
        a.base = a.symbol
        a.symbol = f"{a.base}/USD"
    return out


def download_prices(assets: list[Asset], period: str = "1y", chunk: int = 150) -> dict[str, pd.DataFrame]:
    """Unduh OHLCV harian dari Yahoo Finance, dalam beberapa batch."""
    import yfinance as yf

    data: dict[str, pd.DataFrame] = {}
    syms = [a.yf_symbol for a in assets]
    for i in range(0, len(syms), chunk):
        part = syms[i : i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", group_by="ticker",
                              auto_adjust=False, threads=True, progress=False)
        except Exception as e:
            log.warning("Batch %d gagal: %s", i // chunk, e)
            continue
        for s in part:
            try:
                df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.dropna(how="all")
                if len(df):
                    data[s] = df
            except KeyError:
                pass
    log.info("Data harga didapat untuk %d/%d aset", len(data), len(syms))
    return data
