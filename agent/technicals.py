"""Indikator teknikal dihitung dengan pandas (tanpa library TA tambahan)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(loss.notna())


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _f(x, nd=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _p(x):
    """Harga dengan 6 angka penting (aman untuk koin bernilai sangat kecil seperti PEPE)."""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return float(f"{float(x):.6g}")


def snapshot(df: pd.DataFrame, breakout_lookback: int = 20) -> dict | None:
    """Ringkasan teknikal dari data OHLCV harian (minimal ~60 bar)."""
    df = df.dropna(subset=["Close"])
    if len(df) < 60:
        return None
    c, v = df["Close"], df["Volume"].fillna(0)
    r = rsi(c)
    m_line, m_sig, m_hist = macd(c)
    sma20, sma50 = c.rolling(20).mean(), c.rolling(50).mean()
    sma200 = c.rolling(200).mean() if len(c) >= 200 else pd.Series(np.nan, index=c.index)
    std20 = c.rolling(20).std()
    a = atr(df)
    vol_avg20 = v.shift(1).rolling(20).mean()
    prior_high = df["High"].shift(1).rolling(breakout_lookback).max()
    prior_low = df["Low"].shift(1).rolling(breakout_lookback).min()
    window = df.tail(252)

    last, prev = c.iloc[-1], c.iloc[-2]
    macd_cross_up = m_hist.iloc[-2] <= 0 < m_hist.iloc[-1]
    macd_cross_down = m_hist.iloc[-2] >= 0 > m_hist.iloc[-1]
    golden = sma50.iloc[-2] <= sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1] if not np.isnan(sma200.iloc[-1]) else False
    death = sma50.iloc[-2] >= sma200.iloc[-2] and sma50.iloc[-1] < sma200.iloc[-1] if not np.isnan(sma200.iloc[-1]) else False

    if last > sma50.iloc[-1] and sma20.iloc[-1] > sma50.iloc[-1]:
        trend = "uptrend"
    elif last < sma50.iloc[-1] and sma20.iloc[-1] < sma50.iloc[-1]:
        trend = "downtrend"
    else:
        trend = "sideways"

    return {
        "price": _p(last),
        "change_pct": _f((last / prev - 1) * 100),
        "change_5d_pct": _f((last / c.iloc[-6] - 1) * 100) if len(c) > 6 else None,
        "rsi14": _f(r.iloc[-1], 1),
        "rsi14_prev": _f(r.iloc[-2], 1),
        "macd_hist": _f(m_hist.iloc[-1], 4),
        "macd_cross": "bullish" if macd_cross_up else "bearish" if macd_cross_down else None,
        "sma20": _p(sma20.iloc[-1]),
        "sma50": _p(sma50.iloc[-1]),
        "sma200": _p(sma200.iloc[-1]),
        "ma_cross": "golden_cross" if golden else "death_cross" if death else None,
        "trend": trend,
        "bb_upper": _p(sma20.iloc[-1] + 2 * std20.iloc[-1]),
        "bb_lower": _p(sma20.iloc[-1] - 2 * std20.iloc[-1]),
        "atr_pct": _f(a.iloc[-1] / last * 100),
        "volume_ratio": _f(v.iloc[-1] / vol_avg20.iloc[-1]) if vol_avg20.iloc[-1] else None,
        "avg_value_20d": _f((c * v).rolling(20).mean().iloc[-1], 0),
        "breakout_up": bool(last > prior_high.iloc[-1]),
        "breakdown": bool(last < prior_low.iloc[-1]),
        "support": _p(prior_low.iloc[-1]),
        "resistance": _p(prior_high.iloc[-1]),
        "high_52w": _p(window["High"].max()),
        "low_52w": _p(window["Low"].min()),
    }


def confirmation(s: dict, direction: str) -> dict:
    """Cek apakah RSI, MACD, dan Moving Average mengonfirmasi arah (bullish/bearish).
    Mengembalikan {"rsi": (ok, teks), "macd": (ok, teks), "ma": (ok, teks), "count": n}."""
    r, rp, h = s.get("rsi14"), s.get("rsi14_prev"), s.get("macd_hist")
    p, m20, m50 = s.get("price"), s.get("sma20"), s.get("sma50")
    bull = direction == "bullish"
    out = {}

    if r is None:
        out["rsi"] = (False, "RSI n/a")
    elif bull:
        ok = (50 <= r <= 75) or (rp is not None and rp < 30 <= r)
        out["rsi"] = (ok, f"RSI {r}" + (" (momentum naik)" if ok else " (belum kuat)" if r < 50 else " (overbought)"))
    else:
        ok = (25 <= r <= 50) or (rp is not None and rp > 70 >= r)
        out["rsi"] = (ok, f"RSI {r}" + (" (momentum turun)" if ok else " (masih kuat)" if r > 50 else " (oversold)"))

    if h is None:
        out["macd"] = (False, "MACD n/a")
    else:
        ok = (h > 0 or s.get("macd_cross") == "bullish") if bull else (h < 0 or s.get("macd_cross") == "bearish")
        label = s.get("macd_cross") and f"{s['macd_cross']} cross" or ("histogram positif" if h > 0 else "histogram negatif")
        out["macd"] = (ok, f"MACD {label}")

    if None in (p, m20, m50):
        out["ma"] = (False, "MA n/a")
    elif bull:
        ok = (p > m20 > m50) or s.get("ma_cross") == "golden_cross"
        out["ma"] = (ok, "Harga > MA20 > MA50" if p > m20 > m50 else "golden cross" if ok else "MA belum searah naik")
    else:
        ok = (p < m20 < m50) or s.get("ma_cross") == "death_cross"
        out["ma"] = (ok, "Harga < MA20 < MA50" if p < m20 < m50 else "death cross" if ok else "MA belum searah turun")

    out["count"] = sum(v[0] for k, v in out.items())
    return out


def derivatives_check(d: dict, change_pct: float, direction: str, cfg: dict) -> tuple[bool, str] | None:
    """Konfirmasi dari Open Interest + funding rate (khusus crypto perpetual).
    d = {"funding": 0.0001, "oi_change_24h_pct": 8.5}. Funding dalam desimal per 8 jam."""
    fr, oi = d.get("funding"), d.get("oi_change_24h_pct")
    if fr is None and oi is None:
        return None
    hot, extreme, rise = cfg["funding_hot"], cfg["funding_extreme"], cfg["oi_rise_pct"]
    up = (change_pct or 0) > 0
    fr_txt = f"Funding {fr * 100:+.3f}%" if fr is not None else "Funding n/a"
    oi_txt = f"OI {oi:+.1f}%" if oi is not None else "OI n/a"
    base = f"{oi_txt} · {fr_txt}"

    if direction == "bullish":
        if fr is not None and fr <= -hot and up:
            return True, f"{base} → short squeeze (short terlalu ramai)"
        if oi is not None and oi >= rise and up:
            if fr is not None and fr >= hot:
                return False, f"{base} → long terlalu ramai, rawan long squeeze"
            return True, f"{base} → posisi long baru masuk"
        if oi is not None and oi < 0 and up:
            return False, f"{base} → naik karena short ditutup, bukan uang baru"
        return False, f"{base} → belum mendukung kenaikan"
    else:
        if fr is not None and fr >= extreme and not up:
            return True, f"{base} → long terlalu ramai, rawan long squeeze"
        if oi is not None and oi >= rise and not up:
            if fr is not None and fr <= -hot:
                return False, f"{base} → short terlalu ramai, rawan short squeeze"
            return True, f"{base} → posisi short baru masuk"
        if oi is not None and oi < 0 and not up:
            return False, f"{base} → turun karena long ditutup (bisa mendekati dasar)"
        return False, f"{base} → belum mendukung penurunan"


def trigger_score(s: dict, is_crypto: bool, cfg: dict) -> tuple[float, list[str]]:
    """Seberapa 'menarik' aset ini dari sisi teknikal. 0 = tidak ada pemicu."""
    score, why = 0.0, []
    vr = s.get("volume_ratio") or 0
    chg = s.get("change_pct") or 0
    big = cfg["big_move_pct_crypto"] if is_crypto else cfg["big_move_pct_stock"]

    if vr >= cfg["volume_spike_ratio"]:
        score += min(vr, 8) * 0.6
        why.append(f"volume spike {vr}x")
    if abs(chg) >= big:
        score += abs(chg) / big * 1.5
        why.append(f"pergerakan besar {chg:+.1f}%")
    if s.get("breakout_up") and vr >= 1.5:
        score += 2.5
        why.append(f"breakout di atas high {cfg['breakout_lookback']} hari")
    if s.get("breakdown") and vr >= 1.5:
        score += 2.0
        why.append(f"breakdown di bawah low {cfg['breakout_lookback']} hari")
    r, rp = s.get("rsi14"), s.get("rsi14_prev")
    if r is not None and rp is not None:
        if rp < cfg["rsi_oversold"] <= r:
            score += 1.5
            why.append("RSI keluar dari oversold")
        elif r >= cfg["rsi_overbought"] and vr >= 1.5:
            score += 0.8
            why.append(f"RSI overbought {r}")
    if s.get("macd_cross"):
        score += 1.0
        why.append(f"MACD {s['macd_cross']} cross")
    if s.get("ma_cross"):
        score += 2.0
        why.append(s["ma_cross"].replace("_", " "))
    fr = s.get("funding")
    if fr is not None and abs(fr) >= cfg.get("funding_extreme", 1):
        score += 1.5
        why.append(f"funding ekstrem {fr * 100:+.3f}%")
    return round(score, 2), why
