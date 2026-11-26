"""Mengumpulkan berita: feed umum (untuk menemukan aset yang diberitakan)
dan Google News per aset (untuk konteks analisis)."""
from __future__ import annotations

import calendar
import logging
import re
import time
from urllib.parse import quote_plus

import feedparser

from .universe import Asset

log = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")
# Simbol crypto yang juga kata umum: jangan dicocokkan tanpa tanda $.
AMBIGUOUS = {"ONE", "GAS", "SAND", "NEAR", "FLOW", "MASK", "BLUR", "GALA", "HOT", "CAKE",
             "BOND", "KEY", "SUN", "ROSE", "TRUMP", "PEOPLE", "ACE", "TON", "SUI", "OP", "ID"}


def _age_hours(entry) -> float | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return (time.time() - calendar.timegm(t)) / 3600


def _clean(s: str, n: int = 280) -> str:
    s = TAG_RE.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def fetch_feed(url: str, max_age_hours: float) -> list[dict]:
    try:
        f = feedparser.parse(url, agent="Mozilla/5.0 (market-agent)")
    except Exception as e:
        log.warning("Feed gagal %s: %s", url, e)
        return []
    items = []
    for e in f.entries:
        age = _age_hours(e)
        if age is not None and age > max_age_hours:
            continue
        items.append({
            "title": _clean(e.get("title", ""), 200),
            "summary": _clean(e.get("summary", "")),
            "link": e.get("link", ""),
            "source": _clean((e.get("source") or {}).get("title", "") or f.feed.get("title", ""), 60),
            "age_hours": round(age, 1) if age is not None else None,
        })
    return items


def match_assets(items: list[dict], assets: list[Asset]) -> dict[str, list[dict]]:
    """Cocokkan judul berita umum ke aset (kode saham 4 huruf / nama crypto)."""
    by_code = {a.symbol: a for a in assets if a.market == "idx"}
    crypto = [a for a in assets if a.is_crypto]
    hits: dict[str, list[dict]] = {}
    for it in items:
        text = f"{it['title']} {it['summary']}"
        for code in set(re.findall(r"\b[A-Z]{4}\b", text)):
            if code in by_code:
                hits.setdefault(by_code[code].yf_symbol, []).append(it)
        low = text.lower()
        for a in crypto:
            names = [n.lower() for n in a.aliases if len(n) >= 4]
            b = a.base or a.symbol
            sym_hit = (f"${b}" in text) or (
                b not in AMBIGUOUS and len(b) >= 3 and re.search(rf"\b{re.escape(b)}\b", text)
            )
            if sym_hit or any(re.search(rf"\b{re.escape(n)}\b", low) for n in names):
                hits.setdefault(a.yf_symbol, []).append(it)
    return hits


def asset_news(a: Asset, max_items: int, max_age_hours: float) -> list[dict]:
    if a.market == "idx":
        q, hl, gl, ceid = f"saham {a.symbol}", "id", "ID", "ID:id"
    elif a.is_crypto:
        q, hl, gl, ceid = f"{a.name or a.base or a.symbol} crypto", "en-US", "US", "US:en"
    else:
        q, hl, gl, ceid = f"{a.symbol} stock", "en-US", "US", "US:en"
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl={hl}&gl={gl}&ceid={ceid}"
    return fetch_feed(url, max_age_hours)[:max_items]
