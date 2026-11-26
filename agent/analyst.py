"""Claude sebagai analis: menggabungkan teknikal + berita, memberi conviction."""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

SYSTEM = """Anda adalah analis pasar saham Indonesia dan crypto yang skeptis dan disiplin.
Tugas: untuk tiap aset, gabungkan data teknikal dan berita terbaru, lalu putuskan apakah ada
informasi yang BENAR-BENAR bermanfaat bagi trader/investor.

Aturan:
- Nilai conviction hanya "high", "low", atau "skip".
  * high: berita material (laba, aksi korporasi, kontrak besar, regulasi, listing, hack, ETF, dll.)
    yang berpotensi menggerakkan harga secara tajam DAN RSI, MACD, serta Moving Average
    mengonfirmasi arah yang sama. Keduanya harus selaras.
  * low: ada katalis atau setup menarik tapi belum terkonfirmasi, sinyal bertentangan, atau berita masih rumor.
  * skip: tidak ada yang layak dikirim (berita basi/umum, pergerakan tanpa sebab jelas, likuiditas buruk).
  Lebih baik skip daripada mengirim alert yang tidak berguna.
- direction: "bullish" atau "bearish".
- Jangan mengarang fakta yang tidak ada di data. Jika berita tidak relevan dengan aset, abaikan.
- Perhatikan apakah berita sudah "priced in" (harga sudah naik jauh sebelum berita).
- Khusus crypto, gunakan juga:
  * Derivatif: funding (desimal per 8 jam, 0.0001 = 0,01%) dan oi_change_24h_pct.
    Harga naik + OI naik = uang baru masuk (kuat). Harga naik + OI turun = short covering (lemah).
    Funding sangat positif = long terlalu ramai (rawan turun tajam); sangat negatif = short ramai (rawan squeeze naik).
  * Sentimen X: mention_ratio (>2 = ramai dibicarakan) dan contoh postingan. Waspadai shilling/pump
    terkoordinasi: sentimen sangat positif dari akun kecil tanpa berita nyata bukan alasan HIGH.
  * market_context.crypto_fear_greed: kondisi pasar crypto secara umum.
- Tulis dalam Bahasa Indonesia, singkat dan padat.

Balas HANYA dengan JSON array, satu objek per aset:
[{"symbol": "...", "conviction": "high|low|skip", "direction": "bullish|bearish",
  "headline": "ringkasan 1 kalimat (maks 15 kata)",
  "reason": "alasan utama 1-2 kalimat, sebut beritanya",
  "news_potential": "potensi dampak berita: apa yang bisa terjadi selanjutnya, 1-2 kalimat",
  "technical": "ringkasan teknikal 1 kalimat",
  "derivatives": "khusus crypto perpetual: arti OI & funding 1 kalimat, kosong jika tidak ada data",
  "social_sentiment": "khusus crypto: positif|negatif|netral|campuran + alasan singkat dari X, kosong jika tidak ada data",
  "key_levels": "support / resistance / invalidasi",
  "risk": "risiko utama 1 kalimat",
  "source_link": "link berita paling relevan atau kosong"}]"""


def _payload(c: dict) -> dict:
    return {
        "symbol": c["asset"].symbol,
        "market": c["asset"].market,
        "name": c["asset"].name,
        "technical_triggers": c["triggers"],
        "technicals": c["tech"],
        "news": [{k: n.get(k) for k in ("title", "summary", "source", "age_hours", "link")} for n in c["news"]],
        **({"x_social": c["x"]} if c.get("x") else {}),
    }


def parse_json_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [d for d in data if isinstance(d, dict) and d.get("symbol")]
    except json.JSONDecodeError as e:
        log.warning("JSON dari model tidak valid: %s", e)
        return []


def _claude_batch(client, model: str, batch: list[dict], context: dict | None) -> list[dict]:
    user = ("market_context: " + json.dumps(context or {}, ensure_ascii=False) +
            "\n\nAnalisis aset berikut:\n" + json.dumps([_payload(c) for c in batch], ensure_ascii=False, default=str))
    msg = client.messages.create(model=model, max_tokens=4000, system=SYSTEM,
                                 messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    out = parse_json_array(text)
    if not out and text.strip():
        raise ValueError("jawaban Claude tidak bisa dibaca sebagai JSON")
    for o in out:
        o["engine"] = "claude"
    return out


def analyze(candidates: list[dict], acfg: dict, dcfg: dict, context: dict | None = None) -> list[dict]:
    """Pakai Claude bila tersedia; jika tidak (tanpa API key, kredit habis, error), otomatis pakai aturan."""
    import os

    from . import rules_analyst

    use_claude = acfg.get("provider", "claude") == "claude" and bool(os.environ.get("ANTHROPIC_API_KEY"))
    fallback = acfg.get("fallback_to_rules", True)
    if not use_claude:
        log.info("Analisis: mode ATURAN (tanpa AI)")
        return rules_analyst.analyze(candidates, dcfg)

    import anthropic

    client = anthropic.Anthropic()
    results, bs = [], acfg.get("batch_size", 8)
    for i in range(0, len(candidates), bs):
        batch = candidates[i : i + bs]
        if use_claude:
            try:
                results += _claude_batch(client, acfg["model"], batch, context)
                continue
            except Exception as e:
                log.warning("Claude gagal (%s). %s", str(e)[:200],
                            "Beralih ke mode ATURAN untuk sisa putaran ini." if fallback else "Batch dilewati.")
                use_claude = False
        if fallback:
            results += rules_analyst.analyze(batch, dcfg)
    log.info("Analisis selesai: %d sinyal (claude %d, aturan %d)", len(results),
             sum(r.get("engine") == "claude" for r in results), sum(r.get("engine") == "rules" for r in results))
    return results
