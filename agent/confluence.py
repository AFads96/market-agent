"""Konfluensi: sinyal hanya dikirim jika BANYAK sumber independen searah.

Sumber (✅ mendukung, ❌ berlawanan, ➖ netral / tidak ada data):
  Crypto perpetual (7): Berita, RSI, MACD, MA/Chart, Open Interest, Funding, Smart money
  Saham & crypto spot (6): Berita, RSI, MACD, MA/Chart, Volume, Smart money
  + Sentimen X (opsional, bonus)

⭐ Indikator UTAMA (leading, sering bergerak SEBELUM harga): Smart money, Open Interest/Volume, Berita, RSI.
MACD & MA = lagging (konfirmasi setelah harga bergerak).

Bukti uang (wajib minimal SATU ✅): Smart money ATAU Open Interest (perpetual) / Volume (saham & spot).

HIGH : semua sumber kecuali satu ✅ (perpetual 6/7, saham & spot 5/6), berita material, ada bukti uang,
       tanpa ❌ di indikator utama, funding tidak berlawanan.
LOW  : >= 3 dari 4 indikator utama ✅ (maks. 1 berlawanan), ada bukti uang, funding tidak berlawanan.
       MACD/MA boleh belum searah, justru tanda sinyal masih dini.
"""
from __future__ import annotations

import logging

from . import rules_analyst, smart_money, technicals

log = logging.getLogger(__name__)


def _news(sig: dict, cand: dict) -> tuple[bool | None, str, bool]:
    d = sig["direction"]
    ns = rules_analyst.news_sentiment(cand.get("news", []))
    sign = 1 if d == "bullish" else -1
    aligned = ns["score"] * sign
    material = any(k[0] == d for k in ns["categories"])
    by_claude = sig.get("engine") == "claude" and sig.get("conviction") == "high"
    top = ns["top"]["title"][:90] if ns["top"] else None
    if aligned <= -2:
        return False, f"berlawanan: \"{top}\"" if top else "berita berlawanan", False
    if aligned >= 2 or by_claude:
        tag = "material" if (material or by_claude) else "umum"
        return True, f"{tag}: \"{top}\"" if top else f"{tag} (penilaian Claude)", material or by_claude
    return None, "tidak ada berita kuat" if not top else f"netral: \"{top}\"", False


def _oi(t: dict, d: str, dcfg: dict) -> tuple[bool | None, str]:
    oi, up = t.get("oi_change_24h_pct"), (t.get("change_pct") or 0) > 0
    if oi is None:
        return None, "tidak ada data"
    r = dcfg["oi_rise_pct"]
    txt = f"OI {oi:+.1f}% / harga {t.get('change_pct', 0):+.1f}%"
    flat = abs(t.get("change_pct") or 0) <= 2
    fr = t.get("funding")
    if d == "bullish":
        if oi >= r and flat and fr is not None and fr <= 0:
            return True, f"{txt} → OI naik saat harga datar & funding ≤0: short menumpuk, potensi squeeze naik (dini)"
        if oi >= r and up:
            return True, f"{txt} → uang baru masuk ke posisi long"
        if oi >= r and not up:
            return False, f"{txt} → posisi short baru bertambah"
        if oi <= -r and up:
            return False, f"{txt} → naik karena short ditutup, bukan uang baru"
    else:
        if oi >= r and flat and fr is not None and fr >= dcfg["funding_hot"]:
            return True, f"{txt} → OI naik saat harga datar & funding tinggi: long menumpuk, rawan turun (dini)"
        if oi >= r and not up:
            return True, f"{txt} → uang baru masuk ke posisi short"
        if oi >= r and up:
            return False, f"{txt} → posisi long baru bertambah"
        if oi <= -r and not up:
            return None, f"{txt} → long ditutup (tekanan bisa mereda)"
    return None, f"{txt} → belum signifikan"


def _funding(t: dict, d: str, dcfg: dict) -> tuple[bool | None, str]:
    fr = t.get("funding")
    if fr is None:
        return None, "tidak ada data"
    hot = dcfg["funding_hot"]
    txt = f"{fr * 100:+.3f}%/8j"
    if d == "bullish":
        if fr >= hot:
            return False, f"{txt} → long terlalu ramai, rawan long squeeze"
        if fr <= -hot:
            return True, f"{txt} → short ramai, bahan bakar short squeeze"
        return True, f"{txt} → sehat, posisi belum berlebihan"
    if fr <= -hot:
        return False, f"{txt} → short terlalu ramai, rawan short squeeze"
    if fr >= hot:
        return True, f"{txt} → long ramai, rawan dilikuidasi"
    return True, f"{txt} → sehat, posisi belum berlebihan"


def _volume(t: dict, d: str) -> tuple[bool | None, str]:
    """Bukti uang baru untuk saham & crypto spot (padanan Open Interest di futures)."""
    vr, chg = t.get("volume_ratio"), t.get("change_pct") or 0
    if vr is None:
        return None, "tidak ada data"
    txt = f"volume {vr}x rata-rata, harga {chg:+.1f}%"
    up = chg > 0
    if d == "bullish":
        if t.get("breakout_up") and vr >= 1.5:
            return True, f"{txt} → breakout dengan volume (uang baru masuk)"
        if vr >= 2 and up:
            return True, f"{txt} → lonjakan volume beli"
        if vr >= 2 and not up:
            return False, f"{txt} → volume besar saat harga turun (distribusi)"
    else:
        if t.get("breakdown") and vr >= 1.5:
            return True, f"{txt} → breakdown dengan volume (uang keluar)"
        if vr >= 2 and not up:
            return True, f"{txt} → lonjakan volume jual"
        if vr >= 2 and up:
            return False, f"{txt} → volume besar saat harga naik (akumulasi)"
    return None, f"{txt} → belum ada lonjakan"


def _x(cand: dict, d: str) -> tuple[bool | None, str] | None:
    xs = rules_analyst.x_sentiment(cand.get("x"))
    if not xs:
        return None
    label, bal = xs
    bal = bal if d == "bullish" else -bal
    ratio = cand["x"].get("mention_ratio")
    label += f", mention {ratio}x normal" if ratio else ""
    return (True if bal >= 2 else False if bal <= -2 else None), label


def evaluate(sig: dict, cand: dict, cfg: dict) -> dict:
    d, t, a = sig["direction"], cand["tech"], cand["asset"]
    dcfg = cfg["derivatives"]
    tc = technicals.confirmation(t, d)
    news_ok, news_txt, material = _news(sig, cand)
    checks = [("Berita", news_ok, news_txt, True),
              ("RSI", tc["rsi"][0], tc["rsi"][1], True),
              ("MACD", tc["macd"][0], tc["macd"][1], True),
              ("MA/Chart", tc["ma"][0], tc["ma"][1], True)]
    if a.is_crypto and a.has_perp and dcfg["enabled"]:
        checks.append(("Open Interest", *_oi(t, d, dcfg), True))
        checks.append(("Funding", *_funding(t, d, dcfg), True))
    else:
        checks.append(("Volume", *_volume(t, d), True))
    sm_ok, sm_txt = smart_money.evaluate(cand.get("smart") or {}, d)
    checks.append(("Smart money", sm_ok, sm_txt, True))
    x = _x(cand, d)
    if x:
        checks.append(("Sentimen X", x[0], x[1], False))

    ccfg = cfg["confluence"]
    kind = "stock" if not a.is_crypto else ("crypto_perp" if a.has_perp else "crypto_spot")
    key_names = set(ccfg["key_sources"][kind])
    checks = [(n, ok, txt, n in key_names) for n, ok, txt, _ in checks]   # flag ke-4 = indikator utama
    ok = sum(c[1] is True for c in checks)
    bad = sum(c[1] is False for c in checks)
    key = [c for c in checks if c[3]]
    key_ok = sum(c[1] is True for c in key)
    key_bad = sum(c[1] is False for c in key)
    vetoed = [c[0] for c in checks if c[0] in ccfg["veto_sources"] and c[1] is False]
    # Wajib ada minimal SATU bukti uang masuk/keluar (mis. Smart money ATAU Open Interest/Volume).
    must = any(c[0] in ccfg["money_flow_any"][kind] and c[1] is True for c in checks)

    if (ok >= ccfg["high_min_sources"][kind] and material and key_bad == 0 and not vetoed
            and bad <= ccfg["high_max_contradictions"] and must):
        conviction = "high"
    elif (key_ok >= ccfg["low_min_key_sources"][kind] and key_bad <= ccfg["low_max_key_contradictions"][kind]
          and not vetoed and must):
        conviction = "low"
    else:
        conviction = "skip"
    return {"checks": checks, "ok": ok, "bad": bad, "total": len(checks), "conviction": conviction,
            "key_ok": key_ok, "key_total": len(key)}


def apply(signals: list[dict], by_sym: dict, cfg: dict) -> None:
    for s in signals:
        c = by_sym.get(s.get("symbol"))
        if not c or s.get("direction") not in ("bullish", "bearish") or s.get("conviction") not in ("high", "low"):
            continue
        before = s["conviction"]
        res = evaluate(s, c, cfg)
        s["confluence"] = res
        s["conviction"] = res["conviction"]
        mark = {True: "✅", False: "❌", None: "➖"}
        detail = " ".join(f"{mark[ok]}{'⭐' if key else ''}{name}" for name, ok, _t, key in res["checks"])
        log.info("%-12s %-7s awal %-4s -> AKHIR %-4s | %d/%d sumber, utama %d/%d, berlawanan %d | %s",
                 s["symbol"], s["direction"], before.upper(), res["conviction"].upper(), res["ok"], res["total"],
                 res["key_ok"], res["key_total"], res["bad"], detail)
