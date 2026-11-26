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
SOL/USDT (Crypto) · $182.40 (+4.30%)

💡 ...
📰 Alasan: ...
🚀 Potensi: ...
📊 Teknikal: ...
🧭 Konfluensi: 7/7 sumber mendukung
   ✅ Berita: material: "..."
   ✅ RSI: RSI 68 (momentum naik)
   ✅ MACD: MACD histogram positif
   ✅ MA/Chart: Harga > MA20 > MA50
   ✅ Open Interest: OI +15.4% / harga +4.3% → uang baru masuk ke posisi long
   ✅ Funding: +0.010%/8j → sehat, posisi belum berlebihan
   ✅ Smart money: akumulasi: whale beli $2.40jt vs jual $600rb dlm 20 mnt, top trader L/S 1.68 (+12% 24j), taker buy 80%, CMF +0.31
🎯 Level: ...
⚠️ Risiko: ...
```

### Chart otomatis
Setiap sinyal dikirim dengan **gambar chart harian** (120 candle terakhir), berisi:
- Candlestick, **MA20 / MA50 / MA200**, garis **support & resisten**, dan harga terakhir
- Panel **Volume** (dengan rata-rata 20 hari), **RSI** (garis 30/50/70), dan **MACD**

Di Telegram, chart dikirim lebih dulu sebagai foto dengan ringkasan singkat. Analisis lengkap dikirim
sebagai **balasan** di bawah foto tersebut. Jika chart gagal dibuat, analisis teks tetap terkirim.
Matikan dengan `charts: enabled: false` di `config.yaml`. Saat `--dry-run`, chart disimpan ke folder `charts/`.

### Rencana trading: Entry, SL, TP1/TP2/TP3
Setiap sinyal disertai rencana trading yang dihitung otomatis (juga digambar di chart):

| Bagian | Cara menghitung |
|---|---|
| **Entry** | Harga sekarang, plus **area entry ideal** saat pullback (BUY) / pantulan (SELL) ke level terdekat dalam 1,5x ATR |
| **SL** | Di balik support (BUY) / resisten (SELL) terdekat yang berjarak **1x–3x ATR**. Tidak terlalu dekat (kena noise), tidak terlalu jauh (risiko besar) |
| **TP1 / TP2 / TP3** | Level **Fibonacci** (retracement & extension dari swing 90 hari) dan level struktur (MA20/50/200, high/low 20 hari). TP1 = level pertama dengan **R:R ≥ 1**, TP2 **≥ 2**, TP3 **≥ 3**. Jika tidak ada level yang cukup jauh, dipakai proyeksi kelipatan risiko |
| **Ukuran posisi** | Saran ukuran posisi jika risiko maksimal 1% modal per trade |

Target yang tidak realistis (> 5R, turun > 60%, atau naik > 200%) dibuang otomatis.
Saran manajemen: ambil sebagian profit di TP1, lalu geser SL ke harga entry (break-even).

### Label sinyal & aturan konfluensi
Setiap sinyal diperiksa terhadap beberapa **sumber independen**. Tiap sumber diberi ✅ (mendukung),
❌ (berlawanan), atau ➖ (netral / tidak ada data).

| Sumber | Saham | Crypto perpetual | Crypto spot |
|---|---|---|---|
| ⭐ Berita (Claude atau kata kunci) | ✓ | ✓ | ✓ |
| ⭐ RSI | ✓ | ✓ | ✓ |
| MACD | ✓ | ✓ | ✓ |
| Moving Average / chart | ✓ | ✓ | ✓ |
| ⭐ Open Interest | | ✓ | |
| Funding rate (veto jika terlalu ramai) | | ✓ | |
| ⭐ Volume (lonjakan / breakout bervolume) | ✓ | | ✓ |
| ⭐ Smart money / whale | ✓ | ✓ | ✓ |
| Sentimen X (opsional, bonus) | | ✓ | ✓ |
| **Total sumber** | **6** | **7** | **6** |

**⭐ Indikator utama (leading)** biasanya bergerak **sebelum** harga naik/turun. MACD dan MA adalah
indikator *lagging* (baru berubah setelah harga bergerak), jadi untuk LOW keduanya boleh belum searah.

**Bukti uang masuk/keluar (wajib minimal satu ✅):** sinyal harus didukung bukti bahwa uang sungguhan
sedang masuk atau keluar, bukan hanya berita dan RSI.
- Crypto perpetual: **Smart money ATAU Open Interest**
- Saham & crypto spot: **Smart money ATAU Volume**

| Label | Syarat |
|---|---|
| 🟢🟢 **HIGH BUY** / 🔴🔴 **HIGH SELL** | Semua sumber kecuali satu ✅ (**6/7** crypto perpetual, **5/6** saham & spot), berita material, ada bukti uang, tidak ada ❌ di indikator utama, funding tidak berlawanan |
| 🟢 **LOW BUY** / 🔴 **LOW SELL** | Minimal **3 dari 4 indikator utama ⭐ ✅** (paling banyak 1 berlawanan), ada bukti uang, funding tidak berlawanan |
| *(tidak dikirim)* | Selain itu |

Deteksi dini yang dihitung:
- **Akumulasi diam-diam**: OBV & CMF naik padahal harga 10 hari belum bergerak (±3%).
- **OI naik saat harga datar & funding ≤ 0**: short menumpuk, potensi short squeeze naik.
- **RSI 40–50 yang sedang naik**: momentum mulai pulih.
- **Breakout bervolume / lonjakan volume ≥ 2x**: uang baru masuk (saham & spot).

Aturan indikator (dicek oleh kode, bukan tebakan AI):
- **RSI**: Buy jika 50–75, baru keluar dari oversold (<30), atau 40–50 dan sedang naik (dini). Sell kebalikannya.
- **MACD**: Buy jika histogram positif atau bullish cross. Sell jika sebaliknya.
- **MA**: Buy jika Harga > MA20 > MA50 atau golden cross. Sell jika Harga < MA20 < MA50 atau death cross.
- **Open Interest**: Buy jika OI naik ≥3% bersama harga naik (uang baru masuk). ❌ jika harga naik karena short ditutup.
- **Funding**: ❌ untuk Buy jika ≥ +0,05%/8 jam (long terlalu ramai). ❌ untuk Sell jika ≤ −0,05%.

Semua ambang bisa diubah di `config.yaml` → `confluence`. Untuk menerima **HIGH saja**, set `send_low_conviction: false`.

> Konfluensi meningkatkan kualitas sinyal, tetapi **tidak ada sinyal yang pasti benar**. Pasar bisa bergerak
> berlawanan walaupun semua sumber searah. Selalu gunakan manajemen risiko (stop loss di level invalidasi).

## Smart money / whale tracker
**Crypto** (data gratis dari exchange, bisa diakses dari GitHub lewat OKX):
- **Whale trades**: transaksi besar terbaru (≥ $50 ribu, atau ≥ 0,01% volume 24 jam koin itu). Total beli vs jual.
- **Top trader long/short ratio**: posisi trader terbesar di OKX/Binance dan perubahannya dalam 24 jam.
- **Taker flow**: persentase volume beli agresif vs jual agresif selama 24 jam.

**Saham & crypto** (dari grafik harga + volume):
- **CMF (Chaikin Money Flow)**: positif = uang cenderung masuk.
- **OBV**: tren volume kumulatif.
- **Hari akumulasi/distribusi**: hari bervolume besar yang ditutup dekat harga tertinggi/terendah.

Smart money dianggap ✅ jika tanda beli lebih banyak dari tanda jual minimal 2 poin (untuk Buy), dan ❌ jika
tandanya berlawanan. **Untuk saham IDX, ini adalah perkiraan dari harga & volume**, bukan data broker
summary atau net buy asing, karena data itu tidak tersedia gratis dari server GitHub.

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
- Setelah itu sinyal tetap harus lolos **aturan konfluensi** di atas, sama seperti analisis Claude.
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
VPS Singapura (lihat "Alternatif" di atas). Di Binance, data top trader & taker flow juga tersedia. Urutan exchange bisa diubah di `config.yaml`.

### Open Interest & funding rate
| Kondisi | Arti | Untuk BUY | Untuk SELL |
|---|---|---|---|
| Harga naik + OI naik ≥ 3% | Posisi long baru masuk | ✅ | |
| Harga naik + OI turun | Short ditutup, bukan uang baru | ❌ | |
| Funding ≤ −0,05% + harga naik | Short terlalu ramai, potensi short squeeze | ✅ | |
| Funding ≥ +0,05% | Long terlalu ramai, rawan long squeeze | ❌ | |
| Harga turun + OI naik ≥ 3% | Posisi short baru masuk | | ✅ |
| Funding ≥ +0,10% + harga turun | Long terlalu ramai, rawan long squeeze | | ✅ |

OI dan funding adalah 2 dari 7 sumber konfluensi untuk crypto perpetual. Funding dinormalisasi ke per 8 jam
untuk semua exchange.

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
| `charts.enabled` / `charts.bars` | kirim gambar chart & jumlah candle yang ditampilkan |
| `model` | `claude-haiku-5-5` (murah) atau `claude-sonnet-5-5` (lebih tajam) |
| `send_low_conviction` | `false` = hanya kirim HIGH BUY / HIGH SELL |
| `min_confirmations_for_high` | jumlah indikator (dari RSI, MACD, MA) yang wajib searah untuk label HIGH |
| `max_candidates_stock` / `_crypto` | jumlah aset yang dianalisis Claude per putaran (memengaruhi biaya) |
| `universe.crypto.exchanges` | urutan exchange untuk daftar koin, OI, dan funding |
| `universe.crypto.min_volume_usd` | volume 24 jam minimum koin |
| `derivatives.*` | ambang funding dan OI |
| `x_sentiment.*` | berapa kandidat yang dicek di X (memengaruhi biaya X API) |
| `confluence.*` | jumlah sumber minimum untuk LOW dan batas sumber yang berlawanan |
| `smart_money.*` | ambang transaksi whale |
| `cooldown_hours` | jeda sebelum aset yang sama boleh di-alert lagi |
| `volume_spike_ratio`, `big_move_pct_*` | sensitivitas screener |
| `general_feeds` | tambahkan RSS berita favorit Anda |
| `universe.us.enabled` | nyalakan untuk saham AS |
| `charts.enabled` / `charts.bars` | kirim gambar chart & jumlah candle yang ditampilkan |
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
