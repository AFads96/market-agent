"""Analis cadangan tanpa AI (gratis): sentimen berita dari kata kunci + konfirmasi teknikal/derivatif.
Dipakai otomatis jika Claude tidak tersedia (API key kosong, kredit habis, atau error)."""
from __future__ import annotations

import re

from . import technicals

# (kata kunci, bobot, kategori). Bobot 3 = berita material, 1 = kata umum.
POSITIVE = [
    # kinerja
    (["laba naik", "laba bersih naik", "laba melonjak", "laba tumbuh", "kinerja positif", "pendapatan naik",
      "pendapatan tumbuh", "record profit", "earnings beat", "beats estimates", "profit jumps", "profit rises",
      "revenue growth", "laba rekor"], 3, "earnings"),
    # aksi korporasi
    (["akuisisi", "merger", "buyback", "pembelian kembali saham", "dividen", "stock split", "acquisition",
      "acquires", "dividend", "share repurchase"], 3, "corporate"),
    # kontrak / ekspansi
    (["kontrak baru", "proyek baru", "ekspansi", "kerja sama", "kemitraan", "partnership", "new contract",
      "expansion", "peluncuran", "launches"], 3, "contract"),
    # rekomendasi analis
    (["upgraded to buy", "upgrade to buy", "rating upgrade", "target harga naik", "rekomendasi beli", "buy rating",
      "outperform", "price target raised", "menaikkan target harga"], 3, "upgrade"),
    # crypto
    (["listing", "listed on", "will list", "etf approved", "etf approval", "inflows", "adoption", "mainnet",
      "integration", "token burn", "buyback program", "protocol upgrade", "network upgrade", "mainnet upgrade",
      "hard fork", "staking launch"], 3, "crypto_catalyst"),
    # umum
    (["naik", "menguat", "melonjak", "meroket", "rally", "surge", "soars", "jumps", "bullish", "all-time high",
      "rekor tertinggi", "breakout"], 1, "general"),
]
NEGATIVE = [
    (["laba turun", "laba anjlok", "rugi bersih", "kerugian", "pendapatan turun", "misses estimates",
      "loss widens", "profit falls", "revenue drop", "earnings miss"], 3, "earnings"),
    (["gugatan", "suspensi", "disuspensi", "pkpu", "pailit", "bangkrut", "delisting", "sanksi", "investigasi",
      "penipuan", "korupsi", "lawsuit", "sec charges", "probe", "fraud", "bankruptcy", "delist", "default"], 3, "legal"),
    (["hack", "hacked", "exploit", "rug pull", "token unlock", "unlock", "outflows", "depeg", "drained", "scam"], 3, "crypto_risk"),
    (["downgraded to sell", "rating downgrade", "target harga turun", "rekomendasi jual", "sell rating",
      "underperform", "price target cut", "menurunkan target harga", "downgrade"], 3, "downgrade"),
    (["turun", "melemah", "anjlok", "ambles", "jatuh", "tumbang", "plunge", "drops", "slump", "bearish", "crash",
      "breakdown"], 1, "general"),
]
X_POS = ["bullish", "moon", "breakout", "pump", "long", "buy", "send it", "ath", "accumulate"]
X_NEG = ["bearish", "dump", "rug", "scam", "short", "sell", "exit", "dead", "rekt"]

POTENTIAL = {
    ("bullish", "earnings"): "Kinerja di atas ekspektasi sering memicu re-rating dan akumulasi lanjutan dalam beberapa hari.",
    ("bullish", "corporate"): "Aksi korporasi (akuisisi/buyback/dividen) biasanya menopang harga dan menarik minat investor.",
    ("bullish", "contract"): "Kontrak/ekspansi baru menambah prospek pendapatan; pasar bisa mulai memperhitungkannya.",
    ("bullish", "upgrade"): "Kenaikan rekomendasi analis sering diikuti aliran dana institusi.",
    ("bullish", "crypto_catalyst"): "Katalis on-chain/listing/ETF/upgrade jaringan bisa memicu lonjakan volume dan harga, namun sering diikuti aksi ambil untung setelah berita tersebar.",
    ("bullish", "general"): "Sentimen positif mendukung kelanjutan kenaikan selama volume tetap tinggi.",
    ("bearish", "earnings"): "Kinerja melemah berisiko memicu aksi jual lanjutan dan penurunan target harga.",
    ("bearish", "legal"): "Masalah hukum/regulasi bisa menekan harga dalam waktu lama dan memicu suspensi.",
    ("bearish", "crypto_risk"): "Hack/unlock/outflow menambah tekanan jual; pemulihan biasanya butuh waktu.",
    ("bearish", "downgrade"): "Penurunan rekomendasi analis sering diikuti keluarnya dana institusi.",
    ("bearish", "general"): "Sentimen negatif bisa melanjutkan tekanan jual selama tidak ada katalis baru.",
}


_PAT: dict[str, re.Pattern] = {}


def _has(text: str, kw: str) -> bool:
    """Cocokkan kata kunci utuh. Frasa boleh diselingi hingga 2 kata
    (mis. "laba naik" cocok dengan "laba bersih BBCA naik")."""
    p = _PAT.get(kw)
    if p is None:
        words = [re.escape(w) for w in kw.split()]
        body = r"\W+(?:\w+\W+){0,2}?".join(words)
        # bentuk jamak/turunan bahasa Inggris ikut cocok: integration -> integrations, listing -> listings
        p = _PAT[kw] = re.compile(rf"(?<![a-z0-9]){body}(?:s|es)?(?![a-z0-9])")
    return p.search(text) is not None


def news_sentiment(items: list[dict]) -> dict:
    score, best, cats = 0.0, None, {}
    for it in items:
        text = f"{it.get('title', '')} {it.get('summary', '')}".lower()
        age = it.get("age_hours")
        w = 1.0 if age is None or age <= 12 else 0.6
        item_score = 0.0
        for groups, sign in ((POSITIVE, 1), (NEGATIVE, -1)):
            for kws, weight, cat in groups:
                if any(_has(text, k) for k in kws):
                    item_score += sign * weight * w
                    if weight >= 3:
                        key = ("bullish" if sign > 0 else "bearish", cat)
                        cats[key] = cats.get(key, 0) + 1
        score += item_score
        if item_score and (best is None or abs(item_score) > abs(best[0])):
            best = (item_score, it)
    return {"score": round(score, 1), "top": best[1] if best else None, "categories": cats}


def x_sentiment(x: dict | None) -> tuple[str, int] | None:
    if not x or not x.get("posts"):
        return None
    pos = neg = 0
    for p in x["posts"]:
        t = p["text"].lower()
        pos += sum(_has(t, k) for k in X_POS)
        neg += sum(_has(t, k) for k in X_NEG)
    bal = pos - neg
    label = "positif" if bal >= 2 else "negatif" if bal <= -2 else "campuran" if pos and neg else "netral"
    return f"{label} ({pos} kata bullish vs {neg} bearish di {len(x['posts'])} postingan)", bal


def _fmt(v):
    if v is None:
        return "-"
    if v >= 100:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:.4g}" if v >= 0.01 else f"{v:.3e}".replace("e-0", "e-")


def analyze_one(c: dict, dcfg: dict) -> dict | None:
    a, t = c["asset"], c["tech"]
    ns = news_sentiment(c["news"])
    xs = x_sentiment(c.get("x"))

    conf = {}
    for d in ("bullish", "bearish"):
        cf = technicals.confirmation(t, d)
        n = cf["count"]
        if a.is_crypto:
            dv = technicals.derivatives_check({"funding": t.get("funding"), "oi_change_24h_pct": t.get("oi_change_24h_pct")},
                                              t.get("change_pct"), d, dcfg)
            if dv:
                n += int(dv[0])
        conf[d] = n

    news_score = ns["score"] + (0.5 * xs[1] if xs else 0)
    if abs(news_score) >= 2:
        direction = "bullish" if news_score > 0 else "bearish"
    elif conf["bullish"] != conf["bearish"]:
        direction = "bullish" if conf["bullish"] > conf["bearish"] else "bearish"
    else:
        return None
    sign = 1 if direction == "bullish" else -1
    aligned_news = news_score * sign
    material = any(k[0] == direction for k in ns["categories"])

    if material and aligned_news >= 3 and conf[direction] >= 3:
        conviction = "high"          # tetap diverifikasi lagi oleh apply_confirmation (3/3 atau 4/4)
    elif (aligned_news >= 2 and conf[direction] >= 1) or (conf[direction] >= 3 and aligned_news >= 0):
        conviction = "low"
    else:
        return None                  # tidak cukup bermanfaat -> skip

    top = ns["top"]
    cat = max((k for k in ns["categories"] if k[0] == direction), key=lambda k: ns["categories"][k], default=(direction, "general"))
    word = "positif" if direction == "bullish" else "negatif"
    reason = (f"Berita {word}: \"{top['title'][:140]}\"" + (f" ({top['source']})" if top.get("source") else "")
              if top and aligned_news > 0 else "Belum ada berita kuat; sinyal dari teknikal")
    if c.get("triggers"):
        reason += ". Pemicu: " + ", ".join(c["triggers"][:3])

    macd = "MACD positif" if (t.get("macd_hist") or 0) > 0 else "MACD negatif"
    technical = f"Tren {t.get('trend')}, RSI {t.get('rsi14')}, {macd}" + (
        f", volume {t['volume_ratio']}x rata-rata" if t.get("volume_ratio") else "")
    kl = technicals.key_levels(t, direction)
    lv = lambda pairs, none="-": ", lalu ".join(f"{_fmt(v)} ({n})" for v, n in pairs) or none
    if direction == "bullish":
        levels = (f"Resisten terdekat {lv(kl.get('above', []), 'tidak ada (breakout ke area harga baru)')} · "
                  f"Support {lv(kl.get('below', []))} · "
                  f"Invalid jika tutup < {_fmt(kl.get('invalid'))}")
    else:
        levels = (f"Support terdekat {lv(kl.get('below', []), 'tidak ada (breakdown ke area harga baru)')} · "
                  f"Resisten {lv(kl.get('above', []))} · "
                  f"Invalid jika tutup > {_fmt(kl.get('invalid'))}")

    risks = []
    if direction == "bullish" and (t.get("rsi14") or 0) >= 72:
        risks.append("RSI overbought, rawan koreksi")
    if direction == "bearish" and (t.get("rsi14") or 100) <= 28:
        risks.append("RSI oversold, rawan pantulan")
    if abs(t.get("change_5d_pct") or 0) >= 15:
        risks.append(f"harga sudah bergerak {t['change_5d_pct']:+.0f}% dalam 5 hari (bisa sudah priced in)")
    fr = t.get("funding")
    if fr is not None and direction == "bullish" and fr >= dcfg["funding_hot"]:
        risks.append("funding tinggi, long terlalu ramai")
    chg, p = t.get("change_pct") or 0, t.get("price") or 0
    big = 10 if a.is_crypto else 5
    if direction == "bullish" and chg >= big:
        risks.append(f"sudah naik {chg:+.1f}% hari ini, rawan pullback; hindari mengejar, tunggu harga kembali ke support")
    if direction == "bearish" and chg <= -big:
        risks.append(f"sudah turun {chg:+.1f}% hari ini, rawan pantulan; hindari mengejar")
    if direction == "bullish" and t.get("sma50") and p < t["sma50"]:
        risks.append(f"masih downtrend (harga di bawah MA50 {_fmt(t['sma50'])}); sinyal melawan tren besar")
    if direction == "bearish" and t.get("sma50") and p > t["sma50"]:
        risks.append(f"masih uptrend (harga di atas MA50 {_fmt(t['sma50'])}); sinyal melawan tren besar")
    near = technicals.key_levels(t, direction).get("above" if direction == "bullish" else "below", [])
    if near and p and abs(near[0][0] / p - 1) <= 0.03:
        risks.append(f"{'resisten' if direction == 'bullish' else 'support'} {near[0][1]} {_fmt(near[0][0])} "
                     f"sangat dekat ({(near[0][0] / p - 1) * 100:+.1f}%)")
    if not risks:
        risks.append("Sinyal berbasis aturan; konfirmasi manual berita dan grafik sebelum bertindak")

    deriv = ""
    if a.is_crypto and a.has_perp:
        dv = technicals.derivatives_check({"funding": fr, "oi_change_24h_pct": t.get("oi_change_24h_pct")},
                                          t.get("change_pct"), direction, dcfg)
        deriv = dv[1] if dv else ""

    headline = (top["title"][:90] if top and aligned_news > 0 else
                f"Setup teknikal {'naik' if direction == 'bullish' else 'turun'}: " + ", ".join(c.get("triggers", [])[:2]))
    return {
        "symbol": a.symbol, "conviction": conviction, "direction": direction,
        "headline": headline, "reason": reason,
        "news_potential": POTENTIAL.get(cat, POTENTIAL[(direction, "general")]),
        "technical": technical, "key_levels": levels, "risk": (lambda r: r[:1].upper() + r[1:])("; ".join(risks)),
        "derivatives": deriv, "social_sentiment": xs[0] if xs else "",
        "source_link": (top or {}).get("link", "") if aligned_news > 0 else "",
        "engine": "rules",
    }


def analyze(candidates: list[dict], dcfg: dict) -> list[dict]:
    out = []
    for c in candidates:
        s = analyze_one(c, dcfg)
        if s:
            out.append(s)
    return out
