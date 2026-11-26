# Market Agent: Alert Saham IDX & Crypto ke Telegram

Bot ini berjalan otomatis (bawaan: setiap 3 jam):

1. **Memindai semua aset**: seluruh saham IDX (+ saham AS, opsional) dan **semua crypto yang bisa
   ditradingkan** di exchange (spot + perpetual, volume 24 jam ≥ $1 juta).
2. **Menyaring secara kuantitatif** (gratis, tanpa AI): volume spike, pergerakan besar, breakout/breakdown,
   RSI, MACD cross, golden/death cross, dan aset yang sedang disebut di berita.
3. **Mengumpulkan data pendukung** untuk kandidat teratas (20 saham + 20 crypto):
   berita (RSS + Google News), dan untuk crypto: **Open Interest**, **funding rate**,
   **sentimen X** (lonjakan mention + isi postingan), serta **Fear & Greed Index**.
4. **Analisis**: Claude (Haiku, murah) menggabungkan berita dan teknikal, lalu memberi label **HIGH**, **LOW**, atau *skip*.
   **Jika Claude tidak tersedia** (tanpa API key, kredit habis, atau error), bot **otomatis** memakai analisis
   berbasis aturan yang gratis, jadi sinyal tetap terkirim.
5. **Mengirim ke Telegram** hanya yang layak, tanpa spam (ada cooldown per aset).

Contoh pesan:

```
🟢🟢 HIGH BUY
BBCA (Saham IDX) · Rp9.450 (+3.20%)

💡 Laba Q3 di atas ekspektasi, breakout dengan volume tinggi
📰 Alasan: ...
🚀 Potensi: ...
📊 Teknikal: ...
🧭 Konfirmasi (3/3): ✅ RSI 64 (momentum naik) · ✅ MACD histogram positif · ✅ Harga > MA20 > MA50
🎯 Level: Support 9.200 / Resisten 9.800 / invalid < 9.050
⚠️ Risiko: ...
🔗 Sumber berita
```

### Label sinyal
| Label | Artinya |
|---|---|
| 🟢🟢 **HIGH BUY** | Berita berpotensi mendorong kenaikan tajam **dan** RSI, MACD, MA ketiganya mengonfirmasi naik |
| 🔴🔴 **HIGH SELL** | Berita berpotensi mendorong penurunan tajam **dan** RSI, MACD, MA ketiganya mengonfirmasi turun |
| 🟢 **LOW BUY** | Ada katalis positif, tapi indikator belum semuanya searah atau berita masih rumor |
| 🔴 **LOW SELL** | Ada katalis negatif, tapi indikator belum semuanya searah atau berita masih rumor |

Aturan konfirmasi indikator (dicek oleh kode, bukan tebakan AI):
- **RSI**: Buy jika 50–75 (momentum naik, belum overbought) atau baru keluar dari oversold (<30).
  Sell jika 25–50 atau baru turun dari overbought (>70).
- **MACD**: Buy jika histogram positif atau terjadi bullish cross. Sell jika sebaliknya.
- **Moving Average**: Buy jika Harga > MA20 > MA50 atau golden cross. Sell jika Harga < MA20 < MA50 atau death cross.

Jika Claude menilai beritanya kuat tetapi indikatornya tidak 3/3 searah, sinyal **otomatis diturunkan**
menjadi LOW. Syarat ini bisa dilonggarkan lewat `min_confirmations_for_high` di `config.yaml`
(misalnya `2` = cukup 2 dari 3 indikator).

> ⚠️ Ini alat bantu riset, bukan nasihat keuangan. Sinyal sentimen dan teknikal bisa salah.

---

## Setup (±15 menit, gratis kecuali biaya API Claude)

### 1. Buat bot Telegram
1. Di Telegram, chat **@BotFather** → kirim `/newbot` → ikuti instruksi → simpan **token**-nya.
2. Kirim pesan apa saja ke bot baru Anda (misalnya "halo").
3. Cari chat ID Anda:
   ```bash
   pip install requests
   TELEGRAM_BOT_TOKEN=token_anda python get_chat_id.py
   ```

### 2. Ambil API key Claude *(opsional)*
Buat di https://console.anthropic.com → API Keys. Akun baru mendapat kredit gratis untuk mencoba.
Bot memakai **Claude Haiku 5.5** (±$0,01 per putaran). Jika Anda tidak ingin memakai Claude sama sekali,
lewati langkah ini: bot otomatis berjalan dengan analisis berbasis aturan yang gratis.

### 3. Jalankan otomatis di GitHub Actions (disarankan)
1. Buat repository **private** baru di GitHub, lalu upload semua isi folder ini.
2. Buka **Settings → Secrets and variables → Actions → New repository secret**, lalu tambahkan:
   - `ANTHROPIC_API_KEY` *(opsional; tanpa ini bot memakai mode aturan gratis)*
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `X_BEARER_TOKEN` *(opsional, untuk sentimen X)*
3. Buka tab **Actions** → pilih *market-agent* → **Run workflow** untuk tes pertama.
4. Setelah itu bot berjalan sendiri setiap 3 jam (atur di `.github/workflows/scan.yml`).

### Alternatif: jalankan di komputer atau VPS sendiri
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...  TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python run.py --no-llm     # tes screener saja (gratis)
python run.py --dry-run    # analisis lengkap, pesan dicetak di layar
python run.py              # kirim ke Telegram
# opsional: export X_BEARER_TOKEN=...   untuk sentimen X
```
Untuk penjadwalan, tambahkan ke crontab: `7 * * * * cd /path/market-agent && python run.py`

---

## Mode gratis & cadangan otomatis

| Kondisi | Yang terjadi | Label di pesan |
|---|---|---|
| `ANTHROPIC_API_KEY` ada dan kredit cukup | Claude menganalisis | 🤖 Analisis: Claude AI |
| Kredit habis / API error di tengah putaran | Sisa putaran otomatis pakai aturan | 📐 Analisis: aturan otomatis |
| `ANTHROPIC_API_KEY` tidak di-set | Selalu pakai aturan (gratis total) | 📐 Analisis: aturan otomatis |
| `provider: rules` di `config.yaml` | Selalu pakai aturan, walau ada API key | 📐 Analisis: aturan otomatis |

**Cara kerja analisis berbasis aturan:**
- **Sentimen berita** dihitung dari kata kunci bahasa Indonesia dan Inggris. Kata kunci *material* (bobot 3)
  misalnya "laba naik", "akuisisi", "kontrak baru", "listing", "ETF", atau "gugatan", "PKPU", "delisting", "hack",
  "unlock". Kata kunci umum (bobot 1) misalnya "menguat", "anjlok", "rally", "crash".
- **Sentimen X** dihitung dari kata bullish/bearish di postingan (jika X diaktifkan).
- **HIGH** hanya jika ada berita material searah **dan** indikator lolos 3/3 (saham) atau 4/4 (crypto perpetual).
- **LOW** jika ada berita searah dengan sebagian konfirmasi, atau teknikal kuat tanpa berita yang bertentangan.
- Sisanya dilewati (tidak dikirim).

Keterbatasannya: aturan tidak memahami konteks seperti AI. Misalnya, aturan tidak bisa menilai apakah berita
sudah "priced in" atau masih rumor. Selalu cek sumber beritanya.

## Crypto: semua koin, Open Interest, funding rate, dan sentimen X

### Semua koin yang bisa ditradingkan
Bot mengambil daftar pasar langsung dari exchange (lewat library `ccxt`): semua pair USDT/USDC,
baik perpetual futures maupun spot. Token leverage (BTC3L, dll.), stablecoin, dan koin dengan volume
24 jam di bawah $1 juta dibuang.

**Exchange mana yang dipakai?** Bot mencoba berurutan: `binance → bybit → okx → kucoinfutures → gate → hyperliquid`,
dan memakai yang pertama bisa diakses. **Binance dan Bybit memblokir server di Amerika Serikat**,
termasuk GitHub Actions. Di GitHub, bot biasanya otomatis jatuh ke exchange lain yang daftar koinnya
berbeda. Jika Anda ingin daftar koin **Binance**, jalankan bot di komputer sendiri di Indonesia atau di
VPS Singapura (lihat "Alternatif" di atas). Urutan exchange bisa diubah di `config.yaml`.

Contoh pesan crypto:
```
🟢🟢 HIGH BUY
PEPE/USDT (Crypto) · $2.288e-5 (+18.00%)

💡 ...
📰 Alasan: ...
🚀 Potensi: ...
📊 Teknikal: ...
⛓️ Derivatif: OI naik tajam dengan funding wajar, long baru masuk
🐦 Sentimen X: Positif, ramai dibahas setelah listing (mention 3.4x normal)
🧭 Konfirmasi (4/4):
   ✅ RSI 67.6 (momentum naik)
   ✅ MACD bullish cross
   ✅ Harga > MA20 > MA50
   ✅ OI +15.0% · Funding +0.040% → posisi long baru masuk
🎯 Level: ...
⚠️ Risiko: ...
🌡️ Fear & Greed: 71 (Greed)
```

### Open Interest & funding rate (konfirmasi ke-4 untuk crypto)
| Kondisi | Arti | Untuk BUY | Untuk SELL |
|---|---|---|---|
| Harga naik + OI naik ≥ 3% | Posisi long baru masuk | ✅ | |
| Harga naik + OI turun | Short ditutup, bukan uang baru | ❌ | |
| Funding ≤ −0,05% + harga naik | Short terlalu ramai, potensi short squeeze | ✅ | |
| Funding ≥ +0,05% | Long terlalu ramai, rawan long squeeze | ❌ | |
| Harga turun + OI naik ≥ 3% | Posisi short baru masuk | | ✅ |
| Funding ≥ +0,10% + harga turun | Long terlalu ramai, rawan long squeeze | | ✅ |

Untuk crypto yang punya kontrak perpetual, **HIGH BUY / HIGH SELL wajib 4/4**: RSI, MACD, MA, **dan**
derivatif. Koin yang hanya ada di spot memakai 3/3. Funding dinormalisasi ke per 8 jam untuk semua exchange.

### Sentimen X (opsional, berbayar)
X API memakai sistem bayar per pemakaian. Bot memakainya secara hemat, hanya untuk kandidat crypto teratas:
- **Lonjakan mention** (`$PEPE` dibicarakan berapa kali dibanding biasanya) untuk 15 kandidat.
  Satu request per koin.
- **Isi postingan** (10 postingan dengan engagement tertinggi) untuk 5 kandidat teratas, lalu Claude menilai
  sentimennya positif atau negatif dan mewaspadai shilling/pump terkoordinasi.

Cara mengaktifkan: daftar di https://console.x.com, beli kredit, buat App, salin **Bearer Token**,
lalu tambahkan sebagai secret `X_BEARER_TOKEN`. Tanpa token, bot tetap jalan tanpa sentimen X.

**Perkiraan biaya X** (cek harga terbaru di console.x.com): sekitar $0,005 per request counts dan
$0,005 per postingan dibaca. Dengan pengaturan bawaan, ±$0,33 per putaran.
Setiap 3 jam = 8 putaran per hari ≈ **$80/bulan**. Untuk menghemat, set `read_candidates: 0`
(hanya lonjakan mention, ≈ $18/bulan), atau kurangi `count_candidates`.

## Daftar SEMUA saham IDX (otomatis)
Bot mengambil daftar emiten dari situs IDX. Situs IDX memblokir server GitHub, jadi bot otomatis memakai
**screener Yahoo Finance** (semua saham di bursa Jakarta, sekitar 900+ emiten). Isi `tickers_idx.txt` selalu ikut
digabungkan; tambahkan kode di sana jika ada saham yang belum terpantau.

Saham hanya dipindai **Senin–Jumat pukul 08:00–17:00 WIB** (`stock_hours_wib`) agar hemat kuota GitHub.
Crypto dipindai 24 jam.

Saham dengan rata-rata transaksi di bawah Rp 5 miliar per hari otomatis diabaikan
(`min_avg_value_idr` di `config.yaml`) agar Anda tidak menerima sinyal dari saham gorengan yang tidak likuid.

## Pengaturan penting (`config.yaml`)
| Setting | Fungsi |
|---|---|
| `provider` | `claude` (pakai Claude, cadangan aturan) atau `rules` (selalu tanpa AI) |
| `model` | `claude-haiku-5-5` (murah) atau `claude-sonnet-5-5` (lebih tajam) |
| `send_low_conviction` | `false` = hanya kirim HIGH BUY / HIGH SELL |
| `min_confirmations_for_high` | jumlah indikator (dari RSI, MACD, MA) yang wajib searah untuk label HIGH |
| `max_candidates_stock` / `_crypto` | jumlah aset yang dianalisis Claude per putaran (memengaruhi biaya) |
| `universe.crypto.exchanges` | urutan exchange untuk daftar koin, OI, dan funding |
| `universe.crypto.min_volume_usd` | volume 24 jam minimum koin |
| `derivatives.*` | ambang funding dan OI |
| `x_sentiment.*` | berapa kandidat yang dicek di X (memengaruhi biaya X API) |
| `require_derivatives_for_high_crypto` | `false` = crypto cukup 3/3 indikator teknikal untuk HIGH |
| `cooldown_hours` | jeda sebelum aset yang sama boleh di-alert lagi |
| `volume_spike_ratio`, `big_move_pct_*` | sensitivitas screener |
| `general_feeds` | tambahkan RSS berita favorit Anda |
| `universe.us.enabled` | nyalakan untuk saham AS |
| `model` | model Claude yang dipakai |

## Biaya
Pemindaian ribuan aset tidak memakai AI sama sekali. Claude hanya membaca ±40 kandidat per putaran.
Untuk menekan biaya, turunkan `max_candidates_stock` / `max_candidates_crypto` atau jarangkan jadwal.

## Catatan
- Data harga dari Yahoo Finance tertunda ±10–15 menit dan kadang membatasi request dari server.
  Jika banyak data gagal di GitHub Actions, jalankan di komputer/VPS sendiri.
- Bot mengingat alert yang sudah dikirim di `state/alerts.json`. Aset yang sama baru dikirim lagi setelah
  cooldown, kecuali conviction naik dari LOW ke HIGH atau arahnya berbalik.
- Ingin mengubah perilaku bot? Buka folder ini dengan Claude Code dan minta perubahannya langsung,
  misalnya "tambahkan indikator Stochastic" atau "kirim ringkasan harian jam 8 pagi".
