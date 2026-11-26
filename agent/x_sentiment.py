"""Sentimen dari X (Twitter) lewat X API resmi (pay-per-use).

Dua lapis agar hemat:
1. Counts (murah, per request): jumlah postingan $SYMBOL per jam selama 7 hari -> deteksi lonjakan mention.
2. Recent search (dibayar per postingan yang dibaca): beberapa postingan teratas untuk dinilai sentimennya oleh Claude.
Hanya dijalankan untuk kandidat crypto teratas, bukan semua koin.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)
API = "https://api.x.com/2"


def _headers():
    return {"Authorization": f"Bearer {os.environ['X_BEARER_TOKEN']}"}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("enabled")) and bool(os.environ.get("X_BEARER_TOKEN"))


def _query(base: str) -> str:
    return f"${base} -is:retweet -is:reply"


def mention_spike(base: str) -> dict | None:
    """Mention 24 jam terakhir dibanding rata-rata harian 6 hari sebelumnya."""
    try:
        r = requests.get(f"{API}/tweets/counts/recent", headers=_headers(), timeout=20,
                         params={"query": _query(base), "granularity": "hour"})
        r.raise_for_status()
        buckets = r.json().get("data", [])
    except Exception as e:
        log.debug("X counts %s gagal: %s", base, e)
        return None
    if not buckets:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last24 = prior = 0
    prior_hours = 0
    for b in buckets:
        t = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        if t >= cutoff:
            last24 += b["tweet_count"]
        else:
            prior += b["tweet_count"]
            prior_hours += 1
    daily_avg = prior / prior_hours * 24 if prior_hours else None
    return {"mentions_24h": last24,
            "mention_ratio": round(last24 / daily_avg, 2) if daily_avg else None}


def top_posts(base: str, n: int = 10) -> list[dict]:
    """Postingan terbaru tentang $BASE, diurutkan berdasarkan engagement."""
    try:
        r = requests.get(f"{API}/tweets/search/recent", headers=_headers(), timeout=20,
                         params={"query": _query(base) + " lang:en", "max_results": max(10, min(n, 100)),
                                 "tweet.fields": "public_metrics,created_at", "sort_order": "relevancy"})
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        log.debug("X search %s gagal: %s", base, e)
        return []
    out = []
    for t in rows:
        m = t.get("public_metrics", {})
        eng = m.get("like_count", 0) + 2 * m.get("retweet_count", 0) + m.get("reply_count", 0)
        text = re.sub(r"https?://\S+", "", t.get("text", "")).strip()
        out.append({"text": text[:240], "engagement": eng})
    out.sort(key=lambda x: x["engagement"], reverse=True)
    return out[:n]


def enrich(crypto_cands: list[dict], cfg: dict) -> None:
    """Tambahkan data X ke kandidat crypto (urut skor tertinggi)."""
    if not enabled(cfg):
        return
    for i, c in enumerate(crypto_cands[: cfg["count_candidates"]]):
        base = c["asset"].base
        x = mention_spike(base) or {}
        if i < cfg["read_candidates"]:
            x["posts"] = top_posts(base, cfg["posts_per_asset"])
        if x:
            c["x"] = x
    log.info("Data X ditambahkan untuk %d kandidat crypto", sum("x" in c for c in crypto_cands))
