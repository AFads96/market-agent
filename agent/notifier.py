"""Format pesan dan kirim ke Telegram."""
from __future__ import annotations

import html
import logging
import os

import requests

log = logging.getLogger(__name__)


def _fmt_price(p, market: str) -> str:
    if p is None:
        return "-"
    if market == "idx":
        return f"Rp{p:,.0f}".replace(",", ".")
    if p >= 1:
        return f"${p:,.2f}"
    return f"${p:.4g}" if p >= 0.01 else f"${p:.3e}".replace("e-0", "e-")


def format_message(sig: dict, cand: dict, context: dict | None = None) -> str:
    a, t = cand["asset"], cand["tech"]
    e = lambda s: html.escape(str(s or "-"))
    high = sig["conviction"] == "high"
    bull = sig.get("direction") == "bullish"
    action = f"{'HIGH' if high else 'LOW'} {'BUY' if bull else 'SELL'}"
    icon = ("🟢🟢" if high else "🟢") if bull else ("🔴🔴" if high else "🔴")
    mkt = {"idx": "Saham IDX", "us": "Saham AS", "crypto": "Crypto"}[a.market]
    vr = f" | Vol {t['volume_ratio']}x" if t.get("volume_ratio") else ""
    cf = sig.get("confluence") or {}
    icon_of = {True: "✅", False: "❌", None: "➖"}
    checks = "\n".join(f"   {icon_of[ok]} {'⭐' if key else ''}<b>{e(name)}:</b> {e(txt)}" for name, ok, txt, key in cf.get("checks", []))
    lines = [
        f"{icon} <b>{action}</b>",
        f"<b>{e(a.symbol)}</b> ({mkt}) · {_fmt_price(t.get('price'), a.market)} ({(t.get('change_pct') or 0):+.2f}%)",
        "",
        f"💡 <b>{e(sig.get('headline'))}</b>",
        f"📰 <b>Alasan:</b> {e(sig.get('reason'))}",
        f"🚀 <b>Potensi:</b> {e(sig.get('news_potential'))}",
        f"📊 <b>Teknikal:</b> {e(sig.get('technical'))}",
    ]
    if checks:
        lines.append(f"🧭 <b>Konfluensi: {cf['ok']}/{cf['total']} sumber · ⭐ utama {cf.get('key_ok', 0)}/{cf.get('key_total', 0)}"
                     f"{' · ' + str(cf['bad']) + ' berlawanan' if cf.get('bad') else ''}</b>\n{checks}")
    lines += [
        f"<i>{t.get('trend')}{vr}</i>",
        f"🎯 <b>Level:</b> {e(sig.get('key_levels'))}",
        f"⚠️ <b>Risiko:</b> {e(sig.get('risk'))}",
    ]
    fg = (context or {}).get("crypto_fear_greed")
    if a.is_crypto and fg:
        lines.append(f"🌡️ Fear &amp; Greed: {fg['value']} ({e(fg['label'])})")
    link = sig.get("source_link")
    if link and str(link).startswith("http"):
        lines.append(f'🔗 <a href="{html.escape(link, quote=True)}">Sumber berita</a>')
    engine = "🤖 Analisis: Claude AI" if sig.get("engine") == "claude" else "📐 Analisis: aturan otomatis (tanpa AI)"
    lines += ["", f"<i>{engine}</i>", "<i>Bukan nasihat keuangan. Lakukan riset sendiri.</i>"]
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum di-set")
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        log.error("Telegram error %s: %s", r.status_code, r.text[:200])
    return r.ok
