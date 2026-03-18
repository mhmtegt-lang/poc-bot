"""
BTCUSDT PERP — Smart Money POC Sinyalleri → Telegram
Tek fiyat seviyesinde 150 BTC+ alım VEYA satım → sinyal
Çalıştır: python poc_sinyal.py
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

import aiohttp
import websockets

# ══════════════════════════════════════════════
#  AYARLAR — sadece buraya dokun
# ══════════════════════════════════════════════
TELEGRAM_TOKEN   = "8724532574:AAFqpq8GmEpicc1oKfYfnYNMo7AExT8Y14U"
TELEGRAM_CHAT    = "7133383868"
SEMBOL           = "btcusdt"
INTERVAL         = "5m"
ALERT_COOLDOWN   = 60        # aynı sinyali kaç saniyede bir tekrarla
MIN_SEVIYE_HACIM = 150       # tek fiyat seviyesinde min BTC (alım VEYA satım)
TICK_SIZE        = 0.10      # BTC fiyat adımı (10 cent = bir seviye)
# ══════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger()

bars        = deque(maxlen=50)
seviye_hacim: dict = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
last_alert  = 0.0


def seviyele(fiyat: float) -> float:
    return round(round(fiyat / TICK_SIZE) * TICK_SIZE, 2)


def poc_hesapla(seviyeler: dict) -> float:
    if not seviyeler:
        return 0.0
    poc = max(seviyeler, key=lambda s: seviyeler[s]["buy"] + seviyeler[s]["sell"])
    return poc


def max_seviye_hacim(seviyeler: dict):
    if not seviyeler:
        return 0.0, 0.0
    max_buy  = max(v["buy"]  for v in seviyeler.values())
    max_sell = max(v["sell"] for v in seviyeler.values())
    return max_buy, max_sell


async def telegram(session, mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": mesaj,
            "parse_mode": "HTML",
        })
        log.info(f"📨 Telegram: {mesaj[:80]}")
    except Exception as e:
        log.warning(f"Telegram hatası: {e}")


async def sinyal_kontrol(session):
    global last_alert

    if len(bars) < 3:
        return
    if time.time() - last_alert < ALERT_COOLDOWN:
        return

    curr, prev, prev2 = bars[-1], bars[-2], bars[-3]

    max_buy_sev  = curr["max_buy_sev"]
    max_sell_sev = curr["max_sell_sev"]

    if max_buy_sev < MIN_SEVIYE_HACIM and max_sell_sev < MIN_SEVIYE_HACIM:
        log.info(
            f"⏭ Seviye hacmi yetersiz | "
            f"MaxAlım={max_buy_sev:.1f}  MaxSatım={max_sell_sev:.1f} BTC "
            f"(min {MIN_SEVIYE_HACIM}) — atlandı"
        )
        return

    taraf = "ALIM" if max_buy_sev >= MIN_SEVIYE_HACIM else "SATIM"
    tetik = max(max_buy_sev, max_sell_sev)

    mesajlar = []

    if curr["poc"] > prev["poc"]:
        mesajlar.append(
            f"📈 <b>POC YUKARI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"POC: {prev['poc']} → {curr['poc']}\n"
            f"CVD: {curr['cvd']:+.2f} | Fiyat: {curr['close']}\n"
            f"🔥 {taraf} tarafı | Tek seviyede {tetik:.1f} BTC"
        )
    elif curr["poc"] < prev["poc"]:
        mesajlar.append(
            f"📉 <b>POC AŞAĞI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"POC: {prev['poc']} → {curr['poc']}\n"
            f"CVD: {curr['cvd']:+.2f} | Fiyat: {curr['close']}\n"
            f"🔥 {taraf} tarafı | Tek seviyede {tetik:.1f} BTC"
        )

    if curr["high"] > prev["high"] > prev2["high"] and curr["poc"] < prev["poc"]:
        mesajlar.append(
            f"⚡ <b>BOĞA YORULMASI</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Fiyat yeni zirve: {curr['high']}\n"
            f"Ama POC düştü: {prev['poc']} → {curr['poc']}\n"
            f"⚠️ Olası dönüş! | {taraf}: {tetik:.1f} BTC"
        )

    if curr["low"] < prev["low"] < prev2["low"] and curr["poc"] > prev["poc"]:
        mesajlar.append(
            f"🛡 <b>AYI ABSORPSIYONU</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Fiyat yeni dip: {curr['low']}\n"
            f"Ama POC yükseldi: {prev['poc']} → {curr['poc']}\n"
            f"💡 Güçlü destek! | {taraf}: {tetik:.1f} BTC"
        )

    for m in mesajlar:
        await telegram(session, m)
        last_alert = time.time()


async def calistir():
    global seviye_hacim

    stream = (
        f"wss://fstream.binance.com/stream?streams="
        f"{SEMBOL}@kline_{INTERVAL}/{SEMBOL}@aggTrade"
    )
    log.info(f"🚀 Başlatıldı | BTCUSDT PERP | {INTERVAL}")
    log.info(f"📱 Telegram: {TELEGRAM_CHAT} | Min seviye: {MIN_SEVIYE_HACIM} BTC")

    async with aiohttp.ClientSession() as session:
        await telegram(session,
            f"✅ <b>POC Sinyal Botu Başladı</b>\n"
            f"Sembol: BTCUSDT PERP | {INTERVAL}\n"
            f"Filtre: Tek fiyat seviyesinde ≥{MIN_SEVIYE_HACIM} BTC alım VEYA satım\n"
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

                        if "aggTrade" in tip:
                            fiyat  = float(d["p"])
                            miktar = float(d["q"])
                            alis   = not d["m"]
                            sev    = seviyele(fiyat)
                            if alis:
                                seviye_hacim[sev]["buy"]  += miktar
                            else:
                                seviye_hacim[sev]["sell"] += miktar

                        elif "kline" in tip and d["k"]["x"]:
                            k = d["k"]

                            poc = poc_hesapla(seviye_hacim)
                            if poc == 0.0:
                                poc = round(
                                    (float(k["h"]) + float(k["l"]) + float(k["c"])) / 3, 2
                                )

                            max_buy, max_sell = max_seviye_hacim(seviye_hacim)
                            cvd = sum(v["buy"] - v["sell"] for v in seviye_hacim.values())

                            bar = {
                                "open":         float(k["o"]),
                                "high":         float(k["h"]),
                                "low":          float(k["l"]),
                                "close":        float(k["c"]),
                                "vol":          float(k["v"]),
                                "poc":          poc,
                                "cvd":          round(cvd, 2),
                                "max_buy_sev":  round(max_buy,  2),
                                "max_sell_sev": round(max_sell, 2),
                            }
                            bars.append(bar)
                            seviye_hacim = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})

                            log.info(
                                f"Mum kapandı | C={bar['close']} POC={bar['poc']} "
                                f"CVD={bar['cvd']:+.2f} | "
                                f"MaxAlım={bar['max_buy_sev']:.1f} "
                                f"MaxSatım={bar['max_sell_sev']:.1f} BTC"
                            )

                            await sinyal_kontrol(session)

            except Exception as e:
                log.warning(f"Bağlantı koptu: {e} — 5s sonra tekrar...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(calistir())
