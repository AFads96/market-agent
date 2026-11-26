"""Market Agent: pindai -> saring -> berita + X + derivatif -> analisis Claude -> Telegram.

  python run.py              # jalan normal, kirim ke Telegram
  python run.py --dry-run    # analisis lengkap, pesan dicetak (tidak dikirim)
  python run.py --no-llm     # hanya screener (teknikal, berita, derivatif), tanpa Claude
"""
from __future__ import annotations

import argparse
import logging
import sys

import yaml

from agent import analyst, confluence, news, notifier, smart_money, technicals, universe, x_sentiment
from agent.state import AlertState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
for noisy in ("yfinance", "peewee", "ccxt"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)
log = logging.getLogger("market-agent")


def liquid_enough(a: universe.Asset, tech: dict, cfg: dict) -> bool:
    val = tech.get("avg_value_20d") or 0
    u = cfg["universe"]
    if a.market == "idx":
        return val >= u["idx"]["min_avg_value_idr"]
    if a.market == "us":
        return val >= u["us"]["min_avg_value_usd"]
    return True  # crypto sudah disaring berdasarkan volume 24 jam


def load_crypto(cfg: dict):
    """Kembalikan (assets, prices, exchange|None, funding)."""
    ccfg = cfg["universe"]["crypto"]
    if not ccfg["enabled"]:
        return [], {}, None, {}
    if ccfg.get("source", "exchange") == "exchange":
        try:
            from agent.crypto_market import CryptoExchange, coin_names

            ex = CryptoExchange(ccfg)
            assets = ex.assets(coin_names())
            prices = ex.ohlcv(assets)
            funding = ex.funding_rates() if cfg["derivatives"]["enabled"] else {}
            return assets, prices, ex, funding
        except Exception as e:
            log.error("Data exchange crypto gagal (%s); memakai CoinGecko + Yahoo", e)
    assets = universe.coingecko_crypto(ccfg)
    return assets, universe.download_prices(assets), None, {}


def stock_market_open(cfg: dict) -> bool:
    """Saham hanya dipindai Senin-Jumat pada jam yang diatur (WIB). Crypto selalu dipindai."""
    from datetime import datetime, timedelta, timezone

    win = cfg["universe"].get("stock_hours_wib")
    if not win:
        return True
    now = datetime.now(timezone(timedelta(hours=7)))
    return now.weekday() < 5 and win[0] <= now.hour < win[1]


def find_candidates(cfg: dict) -> tuple[list[dict], dict]:
    scr, dcfg = cfg["screener"], cfg["derivatives"]
    if stock_market_open(cfg):
        stocks = universe.stock_universe(cfg)
    else:
        log.info("Di luar jam bursa saham (WIB); hanya memindai crypto")
        stocks = []
    prices = universe.download_prices(stocks) if stocks else {}
    crypto, cprices, ex, funding = load_crypto(cfg)
    prices.update(cprices)
    assets = stocks + crypto

    snaps: dict[str, dict] = {}
    for a in assets:
        df = prices.get(a.yf_symbol)
        if df is None:
            continue
        try:
            t = technicals.snapshot(df, scr["breakout_lookback"])
        except Exception as e:
            log.debug("snapshot %s gagal: %s", a.yf_symbol, e)
            continue
        if t and liquid_enough(a, t, cfg):
            if a.is_crypto and a.base in funding:
                t["funding"] = funding[a.base]
            snaps[a.yf_symbol] = t

    ncfg = cfg["news"]
    general = [it for url in ncfg["general_feeds"] for it in news.fetch_feed(url, ncfg["max_age_hours"])]
    mentioned = news.match_assets(general, [a for a in assets if a.yf_symbol in snaps])
    log.info("Berita umum: %d item, %d aset disebut", len(general), len(mentioned))

    scr_crypto = {**scr, "funding_extreme": dcfg["funding_extreme"]}
    pools = {"stock": [], "crypto": []}
    for a in assets:
        t = snaps.get(a.yf_symbol)
        if not t:
            continue
        score, why = technicals.trigger_score(t, a.is_crypto, scr_crypto if a.is_crypto else scr)
        hits = mentioned.get(a.yf_symbol, [])
        if hits:
            score += min(len(hits), 3) * 1.5
            why.append(f"disebut di {len(hits)} berita")
        if score > 0:
            pools["crypto" if a.is_crypto else "stock"].append(
                {"asset": a, "tech": t, "score": score, "triggers": why, "news": hits})

    cands = []
    for kind, key in (("stock", "max_candidates_stock"), ("crypto", "max_candidates_crypto")):
        pool = sorted(pools[kind], key=lambda c: c["score"], reverse=True)[: scr[key]]
        cands += pool
    log.info("Kandidat: %d saham, %d crypto", sum(not c["asset"].is_crypto for c in cands),
             sum(c["asset"].is_crypto for c in cands))

    # Open Interest untuk kandidat crypto perpetual
    if ex and dcfg["enabled"]:
        from agent.crypto_market import OISnapshots

        oisnap = OISnapshots()
        for c in cands:
            if c["asset"].is_crypto and c["asset"].has_perp:
                oi = ex.open_interest(c["asset"].base, oisnap)
                if oi:
                    c["tech"].update(oi)
        oisnap.save()

    # Smart money / whale: arus volume dari grafik (semua), plus whale trades & top trader (crypto)
    smcfg = cfg["smart_money"]
    for c in cands:
        a = c["asset"]
        sm = smart_money.volume_flow(prices[a.yf_symbol]) if a.yf_symbol in prices else {}
        if a.is_crypto and ex and smcfg["enabled"]:
            sm.update(smart_money.exchange_flow(ex, a, smcfg))
        c["smart"] = sm
    log.info("Data smart money: %d kandidat (whale trades: %d)", sum(bool(c["smart"]) for c in cands),
             sum("whale_count" in c["smart"] for c in cands))

    # Sentimen X untuk kandidat crypto
    x_sentiment.enrich([c for c in cands if c["asset"].is_crypto], cfg["x_sentiment"])

    for c in cands:
        extra = news.asset_news(c["asset"], ncfg["per_asset_headlines"], ncfg["max_age_hours"])
        seen, merged = set(), []
        for n in c["news"] + extra:
            key = n["title"].lower()[:80]
            if key not in seen:
                seen.add(key)
                merged.append(n)
        c["news"] = merged[: ncfg["per_asset_headlines"] + 3]

    context = {}
    if crypto:
        from agent.crypto_market import fear_greed

        context["crypto_fear_greed"] = fear_greed()
        if ex:
            context["crypto_exchange"] = ex.name
    return cands, context


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))

    cands, context = find_candidates(cfg)
    if args.no_llm:
        print("Konteks:", context)
        for c in cands:
            t = c["tech"]
            extra = ""
            if c["asset"].is_crypto:
                fr = t.get("funding")
                extra = (f" | funding {fr * 100:+.3f}%" if fr is not None else "") + \
                        (f" | OI {t['oi_change_24h_pct']:+.1f}%" if t.get("oi_change_24h_pct") is not None else "") + \
                        (f" | X {c['x'].get('mention_ratio')}x" if c.get("x") else "")
            print(f"{c['asset'].symbol:12} skor {c['score']:5.1f}  {', '.join(c['triggers'])}  | berita: {len(c['news'])}{extra}")
        return
    if not cands:
        log.info("Tidak ada kandidat. Selesai.")
        return

    acfg, alcfg = cfg["analyst"], cfg["alerts"]
    signals = analyst.analyze(cands, acfg, cfg["derivatives"], context)
    by_sym = {c["asset"].symbol: c for c in cands}
    confluence.apply(signals, by_sym, cfg)

    allowed = {"high", "low"} if acfg["send_low_conviction"] else {"high"}
    picks = [s for s in signals if s.get("conviction") in allowed and s.get("symbol") in by_sym
             and s.get("direction") in ("bullish", "bearish")]
    picks.sort(key=lambda s: (s["conviction"] != "high", -by_sym[s["symbol"]]["score"]))
    log.info("Sinyal: %d (high %d, low %d)", len(picks),
             sum(s["conviction"] == "high" for s in picks), sum(s["conviction"] == "low" for s in picks))

    state, sent = AlertState(), 0
    for s in picks:
        if sent >= alcfg["max_alerts_per_run"]:
            break
        if not state.should_send(s["symbol"], s["direction"], s["conviction"], alcfg["cooldown_hours"]):
            continue
        msg = notifier.format_message(s, by_sym[s["symbol"]], context)
        if args.dry_run:
            print(msg, "\n" + "-" * 40)
            ok = True
        else:
            ok = notifier.send_telegram(msg)
        if ok:
            sent += 1
            if not args.dry_run:
                state.record(s["symbol"], s["direction"], s["conviction"])
    if not args.dry_run:
        state.save()
    log.info("Alert terkirim: %d", sent)


if __name__ == "__main__":
    sys.exit(main())
