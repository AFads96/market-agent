"""Pelacak smart money / whale.

Crypto (dari exchange, gratis):
  * Whale trades   : transaksi besar terbaru (>= ambang USD), total beli vs jual.
  * Top trader     : rasio posisi long/short trader terbesar (OKX / Binance) dan perubahannya 24 jam.
  * Taker flow     : volume taker buy vs sell 24 jam (OKX / Binance).
Saham & crypto (dari grafik harga+volume):
  * CMF (Chaikin Money Flow 20 hari), tren OBV, hari akumulasi vs distribusi.
  Catatan: untuk saham IDX ini adalah PROXY dari harga & volume, bukan data broker/asing.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ---------------- dari grafik (saham & crypto) ----------------
def volume_flow(df: pd.DataFrame) -> dict:
    df = df.dropna(subset=["Close"]).tail(60)
    if len(df) < 25:
        return {}
    h, l, c, v = df["High"], df["Low"], df["Close"], df["Volume"].fillna(0)
    rng = (h - l).replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / rng                      # posisi close dalam range hari itu (-1..1)
    cmf = float((mfm * v).tail(20).sum() / v.tail(20).sum()) if v.tail(20).sum() else 0.0
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    obv_slope = float((obv.iloc[-1] - obv.iloc[-11]) / (v.tail(20).mean() or 1))   # dalam satuan "hari volume"
    avg = v.shift(1).rolling(20).mean()
    big = v > 1.5 * avg
    last10 = df.tail(10).index
    acc = int((big & (mfm > 0.4)).loc[last10].sum())     # volume besar, tutup dekat high
    dist = int((big & (mfm < -0.4)).loc[last10].sum())   # volume besar, tutup dekat low
    chg10 = float((c.iloc[-1] / c.iloc[-11] - 1) * 100)
    return {"cmf": round(cmf, 3), "obv_trend": round(obv_slope, 2), "acc_days": acc, "dist_days": dist,
            "price_chg_10d": round(chg10, 2)}


# ---------------- dari exchange (crypto) ----------------
def whale_trades(ex, symbol: str, vol_24h: float, cfg: dict) -> dict:
    try:
        trades = ex.fetch_trades(symbol, limit=500)
    except Exception as e:
        log.debug("trades %s gagal: %s", symbol, e)
        return {}
    if not trades:
        return {}
    thr = max(cfg["whale_min_usd"], (vol_24h or 0) * cfg["whale_vol_fraction"])
    buy = sell = tb = ts = 0.0
    n = 0
    for t in trades:
        cost = t.get("cost") or (t.get("amount") or 0) * (t.get("price") or 0)
        if t.get("side") == "buy":
            tb += cost
        else:
            ts += cost
        if cost >= thr:
            n += 1
            if t.get("side") == "buy":
                buy += cost
            else:
                sell += cost
    stamps = [t["timestamp"] for t in trades if t.get("timestamp")]
    window = (max(stamps) - min(stamps)) / 60000 if len(stamps) > 1 else None
    return {"whale_threshold_usd": round(thr), "whale_buy_usd": round(buy), "whale_sell_usd": round(sell),
            "whale_count": n, "trades_window_min": round(window, 1) if window else None,
            "taker_buy_share_recent": round(tb / (tb + ts), 3) if tb + ts else None}


def _okx_stats(ex, symbol: str) -> dict:
    out = {}
    inst = ex.market(symbol)["id"]
    try:
        r = ex.public_get_rubik_stat_contracts_long_short_position_ratio_contract_top_trader({"instId": inst, "period": "1H"})
        rows = sorted(((int(a), float(b)) for a, b in r.get("data", [])), key=lambda x: x[0])
        if len(rows) >= 2:
            now, past = rows[-1][1], rows[max(0, len(rows) - 25)][1]
            out["top_trader_ls"] = round(now, 3)
            out["top_trader_ls_change_pct"] = round((now / past - 1) * 100, 1) if past else None
    except Exception as e:
        log.debug("OKX top trader %s gagal: %s", symbol, e)
    try:
        r = ex.public_get_rubik_stat_taker_volume_contract({"instId": inst, "period": "1H", "unit": "2"})
        rows = sorted(r.get("data", []), key=lambda x: int(x[0]))[-24:]
        sell = sum(float(x[1]) for x in rows)
        buy = sum(float(x[2]) for x in rows)
        if buy + sell:
            out["taker_buy_share_24h"] = round(buy / (buy + sell), 3)
    except Exception as e:
        log.debug("OKX taker %s gagal: %s", symbol, e)
    return out


def _binance_stats(ex, symbol: str) -> dict:
    out = {}
    sid = ex.market(symbol)["id"]
    try:
        rows = ex.fapidata_get_toplongshortpositionratio({"symbol": sid, "period": "1h", "limit": 25})
        rows = sorted(rows, key=lambda x: int(x["timestamp"]))
        if len(rows) >= 2:
            now, past = float(rows[-1]["longShortRatio"]), float(rows[0]["longShortRatio"])
            out["top_trader_ls"] = round(now, 3)
            out["top_trader_ls_change_pct"] = round((now / past - 1) * 100, 1) if past else None
    except Exception as e:
        log.debug("Binance top trader %s gagal: %s", symbol, e)
    try:
        rows = ex.fapidata_get_takerlongshortratio({"symbol": sid, "period": "1h", "limit": 24})
        buy = sum(float(x["buyVol"]) for x in rows)
        sell = sum(float(x["sellVol"]) for x in rows)
        if buy + sell:
            out["taker_buy_share_24h"] = round(buy / (buy + sell), 3)
    except Exception as e:
        log.debug("Binance taker %s gagal: %s", symbol, e)
    return out


def exchange_flow(cx, asset, cfg: dict) -> dict:
    """cx = CryptoExchange. Pakai perpetual bila ada (whale lebih aktif di futures), jika tidak spot."""
    sym = cx.perp.get(asset.base) or cx.spot.get(asset.base)
    if not sym:
        return {}
    out = whale_trades(cx.ex, sym, asset.vol_24h, cfg)
    if asset.base in cx.perp:
        if cx.name == "okx":
            out.update(_okx_stats(cx.ex, cx.perp[asset.base]))
        elif cx.name == "binance":
            out.update(_binance_stats(cx.ex, cx.perp[asset.base]))
    return out


# ---------------- penilaian ----------------
def _usd(v):
    v = v or 0
    return f"${v / 1e6:.2f}jt" if v >= 1e6 else f"${v / 1e3:.0f}rb"


def evaluate(sm: dict, direction: str) -> tuple[bool | None, str]:
    """Hasil: (True=mendukung, False=berlawanan, None=netral/tidak ada data, teks ringkas)."""
    if not sm:
        return None, "tidak ada data"
    bull = bear = 0
    parts = []

    wb, ws = sm.get("whale_buy_usd", 0), sm.get("whale_sell_usd", 0)
    if sm.get("whale_count"):
        share = wb / (wb + ws) if wb + ws else 0.5
        if share >= 0.6:
            bull += 1
        elif share <= 0.4:
            bear += 1
        win = f" dlm {sm['trades_window_min']:.0f} mnt" if sm.get("trades_window_min") else ""
        parts.append(f"whale beli {_usd(wb)} vs jual {_usd(ws)}{win}")
    ch = sm.get("top_trader_ls_change_pct")
    if ch is not None:
        if ch >= 5:
            bull += 1
        elif ch <= -5:
            bear += 1
        parts.append(f"top trader L/S {sm['top_trader_ls']} ({ch:+.0f}% 24j)")
    tk = sm.get("taker_buy_share_24h")
    if tk is not None:
        if tk >= 0.55:
            bull += 1
        elif tk <= 0.45:
            bear += 1
        parts.append(f"taker buy {tk * 100:.0f}%")
    cmf = sm.get("cmf")
    if cmf is not None:
        if cmf >= 0.05:
            bull += 1
        elif cmf <= -0.05:
            bear += 1
        parts.append(f"CMF {cmf:+.2f}")
    acc, dist, obv = sm.get("acc_days", 0), sm.get("dist_days", 0), sm.get("obv_trend", 0)
    if acc or dist or obv:
        if acc > dist and obv > 0:
            bull += 1
            parts.append(f"akumulasi {acc} hari, OBV naik")
        elif dist > acc and obv < 0:
            bear += 1
            parts.append(f"distribusi {dist} hari, OBV turun")

    # Deteksi DINI: uang masuk/keluar sementara harga belum bergerak (divergensi volume vs harga).
    p10 = sm.get("price_chg_10d")
    if p10 is not None and abs(p10) <= 3:
        if (obv or 0) > 0 and (cmf or 0) > 0:
            bull += 1
            parts.append(f"akumulasi diam-diam (OBV & CMF naik, harga 10 hari {p10:+.1f}%)")
        elif (obv or 0) < 0 and (cmf or 0) < 0:
            bear += 1
            parts.append(f"distribusi diam-diam (OBV & CMF turun, harga 10 hari {p10:+.1f}%)")

    support = (bull - bear) if direction == "bullish" else (bear - bull)
    verdict = "akumulasi" if bull > bear else "distribusi" if bear > bull else "netral"
    text = f"{verdict} ({bull} tanda beli vs {bear} tanda jual): " + ", ".join(parts)
    if support >= 2:
        return True, text
    if support <= -1:
        return False, text
    return None, text
