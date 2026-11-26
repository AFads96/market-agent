"""Rencana trading: Entry, Stop Loss, TP1/TP2/TP3.

Cara menghitung:
  * SL   : di balik support/resisten kuat terdekat yang berjarak minimal 1,5x ATR (agar tidak kena "noise").
  * TP   : kandidat = level Fibonacci (retracement & extension dari swing 90 hari) + level struktur
           (MA20/MA50/MA200, high/low 20 hari, high/low swing). Dipilih bertingkat:
             TP1 = level pertama dengan Risk:Reward >= 1
             TP2 = level berikutnya dengan R:R >= 2
             TP3 = level berikutnya dengan R:R >= 3 (jika tidak ada: Fibonacci extension 1.618)
  * Entry: harga sekarang, plus area entry ideal saat pullback (berguna jika harga sudah lari jauh).
"""
from __future__ import annotations

import math

import pandas as pd

from .technicals import key_levels

FIB_RET = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_EXT = [1.272, 1.618, 2.0, 2.618]


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) and v > 0


def fib_levels(df: pd.DataFrame, lookback: int = 90) -> dict:
    d = df.dropna(subset=["Close"]).tail(lookback)
    hi, lo = float(d["High"].max()), float(d["Low"].min())
    rng = hi - lo
    if rng <= 0:
        return {}
    up = d["High"].idxmax() > d["Low"].idxmin()       # swing terakhir naik (low dulu, lalu high)?
    levels = {}
    for f in FIB_RET:   # retracement diukur dari high ke bawah (dan dari low ke atas)
        levels[f"Fib {f}"] = hi - f * rng if up else lo + f * rng
    for f in FIB_EXT:   # extension ke atas & ke bawah
        levels[f"Fib ext {f}"] = lo + f * rng
        levels[f"Fib ext -{f}"] = hi - f * rng
    levels["Swing high"], levels["Swing low"] = hi, lo
    return {"levels": levels, "high": hi, "low": lo, "up": up}


def build(df: pd.DataFrame, t: dict, direction: str, lookback: int = 90) -> dict | None:
    p = t.get("price")
    if not _ok(p) or df is None or len(df) < 30:
        return None
    bull = direction == "bullish"
    kl = key_levels(t, direction)
    sl = kl.get("invalid")
    atr = (t.get("atr_pct") or 5) / 100
    if not _ok(sl) or (bull and sl >= p) or (not bull and sl <= p):
        sl = p * (1 - 1.5 * atr) if bull else p * (1 + 1.5 * atr)
    risk = abs(p - sl)

    fib = fib_levels(df, lookback)
    cands = [(v, n) for n, v in fib.get("levels", {}).items()]
    cands += [(t.get(k), n) for k, n in (("sma20", "MA20"), ("sma50", "MA50"), ("sma200", "MA200"),
                                         ("resistance", "high 20 hari"), ("support", "low 20 hari"))]
    cands = [(float(v), n) for v, n in cands if _ok(v)]
    side = [c for c in cands if (c[0] > p * 1.003 if bull else c[0] < p * 0.997)]
    side.sort(key=lambda c: c[0] if bull else -c[0])
    # gabungkan level yang berdekatan (<1,5%) menjadi satu "zona"
    merged = []
    for v, n in side:
        if merged and abs(v / merged[-1][0] - 1) < 0.015:
            merged[-1] = (merged[-1][0], merged[-1][1] + " / " + n)
        else:
            merged.append((v, n))

    rr = lambda v: abs(v - p) / risk if risk else 0
    # buang target yang tidak realistis: > 5R, atau turun > 60% / naik > 200%
    merged = [(v, n) for v, n in merged
              if rr(v) <= 5 and (-60 <= (v / p - 1) * 100 <= 200)]
    tps, need = [], [1.0, 2.0, 3.0]
    for v, n in merged:
        if len(tps) == 3:
            break
        if rr(v) >= need[len(tps)]:
            tps.append((v, n))
    while len(tps) < 3:   # tidak ada level struktur yang cukup jauh -> pakai kelipatan risiko
        k = need[len(tps)] + (0.5 if tps and rr(tps[-1][0]) >= need[len(tps)] else 0)
        v = p + k * risk if bull else p - k * risk
        v = min(v, p * 3.0) if bull else max(v, p * 0.4)          # batas realistis
        if tps and (v <= tps[-1][0] if bull else v >= tps[-1][0]):
            v = tps[-1][0] * (1 + atr) if bull else tps[-1][0] * (1 - atr)
        tps.append((v, f"{rr(v):.1f}R (proyeksi)"))

    # area entry ideal: pullback ke level terdekat di sisi bawah (BUY) / atas (SELL) dalam 1,5 ATR
    near = kl.get("below" if bull else "above", [])
    zone = None
    for v, n in near:
        if abs(v / p - 1) <= 1.5 * atr:
            zone = (v, n)
            break
    if zone is None:
        zone = (p * (1 - 0.5 * atr) if bull else p * (1 + 0.5 * atr), "0,5x ATR")

    sl_pct = (sl / p - 1) * 100
    return {
        "direction": direction, "entry": p, "entry_zone": zone, "sl": sl, "sl_pct": sl_pct,
        "tps": [{"price": v, "label": n, "pct": (v / p - 1) * 100, "rr": rr(v)} for v, n in tps],
        "fib_high": fib.get("high"), "fib_low": fib.get("low"),
        "size_pct_for_1pct_risk": min(100.0, 1 / (abs(sl_pct) / 100)) if sl_pct else None,
    }


def _f(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}".replace(",", ".")
    if v >= 1:
        return f"{v:,.2f}" if v < 100 else f"{v:,.1f}"
    return f"{v:.4g}"


def format_html(plan: dict, esc) -> list[str]:
    if not plan:
        return []
    bull = plan["direction"] == "bullish"
    z = plan["entry_zone"]
    lines = ["", "📐 <b>Rencana Trading</b>",
             f"   ▶️ <b>Entry:</b> {_f(plan['entry'])} (harga sekarang)"
             f" · ideal saat {'pullback' if bull else 'pantulan'} ke {_f(z[0])} ({esc(z[1])})",
             f"   🛑 <b>SL:</b> {_f(plan['sl'])} ({plan['sl_pct']:+.1f}%)"]
    for i, tp in enumerate(plan["tps"], 1):
        lines.append(f"   🎯 <b>TP{i}:</b> {_f(tp['price'])} ({tp['pct']:+.1f}%, R:R 1:{tp['rr']:.1f}) · {esc(tp['label'])}")
    tips = ["ambil sebagian profit di TP1 lalu geser SL ke entry (break-even)"]
    if abs(plan["sl_pct"]) >= 12:
        tips.append(f"SL lebar ({plan['sl_pct']:+.0f}%), kecilkan ukuran posisi")
    if plan.get("size_pct_for_1pct_risk"):
        tips.append(f"jika risiko maks 1% modal, ukuran posisi ±{plan['size_pct_for_1pct_risk']:.0f}% modal")
    tip = "; ".join(tips)
    lines.append("   💡 " + esc(tip[:1].upper() + tip[1:]))
    return lines
