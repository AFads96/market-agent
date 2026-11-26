"""Gambar chart sinyal: candlestick + MA20/50/200, volume, RSI, MACD, support/resisten."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .technicals import macd, rsi  # noqa: E402

BG, PANEL, GRID, TEXT = "#0f1419", "#131a22", "#233040", "#c9d1d9"
UP, DOWN = "#26a69a", "#ef5350"
MA_COLORS = {20: "#f5c542", 50: "#42a5f5", 200: "#ab47bc"}


def _fmt_price(v: float) -> str:
    if v >= 1000:
        return f"{v:.0f}"            # tanpa pemisah ribuan agar sama dengan angka di sumbu harga
    if v >= 1:
        return f"{v:,.2f}"
    return f"{v:.4g}"


def render(df: pd.DataFrame, title: str, subtitle: str, levels: dict | None = None, bars: int = 120) -> bytes:
    """Kembalikan PNG (bytes). df = OHLCV harian (minimal ~60 bar)."""
    full = df.dropna(subset=["Close"]).copy()
    c = full["Close"]
    full["MA20"], full["MA50"] = c.rolling(20).mean(), c.rolling(50).mean()
    full["MA200"] = c.rolling(200).mean() if len(full) >= 200 else np.nan
    full["RSI"] = rsi(c)
    full["MACD"], full["SIG"], full["HIST"] = macd(c)
    d = full.tail(bars)
    x = np.arange(len(d))

    fig = plt.figure(figsize=(11, 8.2), dpi=110, facecolor=BG)
    gs = fig.add_gridspec(4, 1, height_ratios=[4.2, 1.0, 1.3, 1.3], hspace=0.06)
    axp, axv, axr, axm = (fig.add_subplot(gs[i]) for i in range(4))
    for ax in (axp, axv, axr, axm):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=TEXT, labelsize=8)
        ax.grid(color=GRID, linewidth=0.6, alpha=0.7)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.yaxis.tick_right()
        ax.set_xlim(-1, len(d) + 20)

    # --- candlestick ---
    o, h, l, cl = d["Open"].values, d["High"].values, d["Low"].values, d["Close"].values
    col = np.where(cl >= o, UP, DOWN)
    axp.vlines(x, l, h, color=col, linewidth=0.8)
    axp.bar(x, np.maximum(np.abs(cl - o), (h - l) * 0.01 + 1e-12), bottom=np.minimum(o, cl), color=col, width=0.65)
    for n, colr in MA_COLORS.items():
        s = d[f"MA{n}"]
        if s.notna().any():
            axp.plot(x, s.values, color=colr, linewidth=1.3, label=f"MA{n} {_fmt_price(s.iloc[-1])}")
    last = cl[-1]
    lines = [("Harga", last, col[-1], "-", 0.6)]
    if levels:
        plan = levels.get("plan")
        if plan:   # rencana trading lebih penting daripada support/resisten mentah
            lines.append(("SL", plan["sl"], "#ff5252", "-", 1.3))
            for i, tp in enumerate(plan["tps"], 1):
                lines.append((f"TP{i}", tp["price"], "#00e676", "-", 1.1))
            lines.append(("Entry ideal", plan["entry_zone"][0], "#90caf9", ":", 1.0))
        else:
            lines += [("Resisten", levels.get("resistance"), "#ef9a9a", "--", 0.9),
                      ("Support", levels.get("support"), "#80cbc4", "--", 0.9)]
    lines = [ln for ln in lines if ln[1]]
    for name, val, colr, ls, lw in lines:
        axp.axhline(val, color=colr, linestyle=ls, linewidth=lw, alpha=0.85)
    # Label di sisi kanan, disusun dari bawah ke atas agar tidak saling menimpa.
    y0, y1 = axp.get_ylim()
    gap = (y1 - y0) * 0.045
    placed = []
    for name, val, colr, ls, lw in sorted(lines, key=lambda ln: ln[1]):
        ty = max(val, placed[-1] + gap) if placed else val
        placed.append(ty)
        if name == "Harga":
            axp.text(len(d) + 19.5, ty, f" {_fmt_price(val)} ", color="white", fontsize=9, va="center", ha="right",
                     fontweight="bold", bbox=dict(boxstyle="round,pad=0.25", fc=colr, ec="none"))
        else:
            axp.text(len(d) + 19.5, ty, f"{name} {_fmt_price(val)}", color=colr, fontsize=8, va="center", ha="right",
                     fontweight="bold" if name.startswith(("SL", "TP")) else "normal",
                     bbox=dict(boxstyle="round,pad=0.15", fc=PANEL, ec="none", alpha=0.85))
    if placed and placed[-1] > y1:
        axp.set_ylim(y0, placed[-1] + gap)
    axp.legend(loc="upper left", fontsize=8, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
    axp.set_title(title, color="white", fontsize=14, loc="left", fontweight="bold", pad=22)
    axp.text(0, 1.015, subtitle, transform=axp.transAxes, color=TEXT, fontsize=9)

    # --- volume ---
    v = d["Volume"].fillna(0).values
    axv.bar(x, v, color=col, width=0.65, alpha=0.7)
    axv.plot(x, pd.Series(v).rolling(20).mean().values, color="#f5c542", linewidth=1)
    axv.set_ylabel("Volume", color=TEXT, fontsize=8)
    axv.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda y, _: f"{y / 1e9:.1f}B" if y >= 1e9 else f"{y / 1e6:.1f}M" if y >= 1e6 else f"{y / 1e3:.0f}K"))

    # --- RSI ---
    r = d["RSI"].values
    axr.plot(x, r, color="#ce93d8", linewidth=1.2)
    for lvl, colr in ((70, DOWN), (50, GRID), (30, UP)):
        axr.axhline(lvl, color=colr, linestyle="--", linewidth=0.8)
    axr.fill_between(x, 70, 100, color=DOWN, alpha=0.06)
    axr.fill_between(x, 0, 30, color=UP, alpha=0.06)
    axr.set_ylim(0, 100)
    axr.set_ylabel(f"RSI {r[-1]:.1f}", color=TEXT, fontsize=8)

    # --- MACD ---
    hist = d["HIST"].values
    axm.bar(x, hist, color=np.where(hist >= 0, UP, DOWN), width=0.65, alpha=0.7)
    axm.plot(x, d["MACD"].values, color="#42a5f5", linewidth=1.1)
    axm.plot(x, d["SIG"].values, color="#ff9800", linewidth=1.1)
    axm.axhline(0, color=GRID, linewidth=0.8)
    axm.set_ylabel("MACD", color=TEXT, fontsize=8)

    # sumbu-x: tanggal
    idx = d.index
    step = max(len(d) // 8, 1)
    ticks = list(range(0, len(d), step))
    for ax in (axp, axv, axr):
        ax.set_xticks(ticks)
        ax.set_xticklabels([])
    axm.set_xticks(ticks)
    axm.set_xticklabels([pd.Timestamp(idx[i]).strftime("%d %b") for i in ticks], color=TEXT, fontsize=8)

    fig.text(0.99, 0.005, "Market Agent · harian (1D) · bukan nasihat keuangan", color="#6e7681",
             fontsize=7, ha="right")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
