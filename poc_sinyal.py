"""
BTCUSDT PERP — Smart Money POC Sinyalleri → Telegram
Çalıştır: python poc_sinyal.py
"""

import asyncio
import json
import logging
from collections import defaultdict, deque

import aiohttp
import websockets

# ══════════════════════════════════════════════
#  AYARLAR — sadece buraya dokun
# ══════════════════════════════════════════════
TELEGRAM_TOKEN  = "8724532574:AAFqpq8GmEpicc1oKfYfnYNMo7AExT8Y14U"
TELEGRAM_CHAT   = "7133383868"
SEMBOL          = "btcusdt"          # küçük harf
INTERVAL        = "5m"              # 1m 3m 5m 15m 1h
ALERT_COOLDOWN  = 60                 # aynı sinyali kaç saniyede bir tekrarla
MIN_ALIS_HACIM  = 150                # alım VEYA satım tarafı için minimum BTC hacmi
# ══════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger()

# ── Durum ─────────────────────────────────────
bars          = deque(maxlen=50)
tick_prices   = []
tick_buys     = []
tick_sells    = []
last_alert    = 0.0


# ── POC hesapla ───────────────────────────────
def poc_hesapla(prices, buys, sells):
    if not prices:
        return 0.0
    lo, hi = min(prices), max(prices)
    if hi == lo:
        return hi
    step = (hi - lo) / 20
    kovalar = defaultdict(float)
    for p, b, s in zip(prices, buys, sells):
        i = min(int((p - lo) / step), 19)
        kovalar[i] += b + s
    en_iyi = max(kovalar, key=kovalar.get)
    return round(lo + (en_iyi + 0.5) * step, 2)


# ── Telegram gönder ───────────────────────────
async def telegram(session, mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": mesaj,
            "parse_mode": "HTML",
        })
        log.info(f"📨 Telegram: {mesaj[:60]}")
    except Exception as e:
        log.warning(f"Telegram hatası: {e}")


# ── Sinyal üret ───────────────────────────────
async def sinyal_kontrol(session):
    global last_alert
    import time

    if len(bars) < 3:
        return
    if time.time() - last_alert < ALERT_COOLDOWN:
        return

    curr, prev, prev2 = bars[-1], bars[-2], bars[-3]

    # Alım VEYA satım tarafından biri 150 BTC üzerindeyse sinyal gönder
    satis_hacim = curr["vol"] - curr["buy_vol"]
    if curr["buy_vol"] < MIN_ALIS_HACIM and satis_hacim < MIN_ALIS_HACIM:
        log.info(
            f"⏭ Hacim yetersiz | "
            f"Alım={curr['buy_vol']:.1f}  Satım={satis_hacim:.1f} BTC "
            f"(min {MIN_ALIS_HACIM} BTC) — sinyal atlandı"
        )
        return

    mesajlar = []

    # POC Migration
    if curr["poc"] > prev["poc"]:
        mesajlar.append(
            f"📈 <b>POC YUKARI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"POC: {prev['poc']} → {curr['poc']}\n"
            f"CVD: {curr['cvd']:+.2f} | Fiyat: {curr['close']}"
        )
    elif curr["poc"] < prev["poc"]:
        mesajlar.append(
            f"📉 <b>POC AŞAĞI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"POC: {prev['poc']} → {curr['poc']}\n"
            f"CVD: {curr['cvd']:+.2f} | Fiyat: {curr['close']}"
        )

    # Boğa Yorulması
    if curr["high"] > prev["high"] > prev2["high"] and curr["poc"] < prev["poc"]:
        mesajlar.append(
            f"⚡ <b>BOĞA YORULMASI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Fiyat yeni zirve: {curr['high']}\n"
            f"Ama POC düştü: {prev['poc']} → {curr['poc']}\n"
            f"⚠️ Olası dönüş sinyali!"
        )

    # Ayı Absorpsiyonu
    if curr["low"] < prev["low"] < prev2["low"] and curr["poc"] > prev["poc"]:
        mesajlar.append(
            f"🛡 <b>AYI ABSORPSIYONU</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Fiyat yeni dip: {curr['low']}\n"
            f"Ama POC yükseldi: {prev['poc']} → {curr['poc']}\n"
            f"💡 Güçlü destek sinyali!"
        )

    for m in mesajlar:
        await telegram(session, m)
        last_alert = time.time()


# ── Ana döngü ─────────────────────────────────
async def calistir():
    stream = (
        f"wss://fstream.binance.com/stream?streams="
        f"{SEMBOL}@kline_{INTERVAL}/{SEMBOL}@aggTrade"
    )
    log.info(f"🚀 Başlatıldı | BTCUSDT PERP | {INTERVAL}")
    log.info(f"📱 Telegram chat: {TELEGRAM_CHAT}")

    async with aiohttp.ClientSession() as session:
        # Başlangıç mesajı
        await telegram(session,
            f"✅ <b>POC Sinyal Botu Başladı</b>\n"
            f"Sembol: BTCUSDT PERP\n"
            f"Interval: {INTERVAL}\n"
            f"Sinyaller burada görünecek 👇"
        )

        while True:
            try:
                async with websockets.connect(stream, ping_interval=20) as ws:
                    log.info("🔌 Binance PERP bağlandı")
                    async for raw in ws:
                        data = json.loads(raw)
                        tip  = data.get("stream", "")
                        d    = data.get("data", {})

                        # Tick biriktir
                        if "aggTrade" in tip:
                            fiyat  = float(d["p"])
                            miktar = float(d["q"])
                            alis   = not d["m"]
                            tick_prices.append(fiyat)
                            tick_buys.append(miktar if alis else 0.0)
                            tick_sells.append(0.0 if alis else miktar)

                        # Mum kapandı
                        elif "kline" in tip and d["k"]["x"]:
                            k = d["k"]
                            poc = poc_hesapla(tick_prices, tick_buys, tick_sells)
                            if poc == 0.0:
                                poc = round(
                                    (float(k["h"]) + float(k["l"]) + float(k["c"])) / 3, 2
                                )
                            cvd = sum(tick_buys) - sum(tick_sells)
                            bar = {
                                "open":  float(k["o"]),
                                "high":  float(k["h"]),
                                "low":   float(k["l"]),
                                "close": float(k["c"]),
                                "vol":   float(k["v"]),
                                "buy_vol": float(k["V"]),
                                "poc":   poc,
                                "cvd":   round(cvd, 2),
                            }
                            bars.append(bar)
                            tick_prices.clear(); tick_buys.clear(); tick_sells.clear()
                            log.info(
                                f"Mum kapandı | C={bar['close']} "
                                f"POC={bar['poc']} CVD={bar['cvd']:+.2f} "
                                f"Alım={bar['buy_vol']:.1f} BTC"
                            )
                            await sinyal_kontrol(session)

            except Exception as e:
                log.warning(f"Bağlantı koptu: {e} — 5s sonra tekrar...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(calistir())
