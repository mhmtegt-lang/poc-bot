"""
BTCUSDT PERP — Smart Money POC Sinyalleri → Telegram
Tek fiyat seviyesinde her 100 BTC artışında bildirim (100, 200, 300...)
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
#  AYARLAR
# ══════════════════════════════════════════════
TELEGRAM_TOKEN   = "8724532574:AAFqpq8GmEpicc1oKfYfnYNMo7AExT8Y14U"
TELEGRAM_CHAT    = "7133383868"
SEMBOL           = "btcusdt"
INTERVAL         = "5m"
ESIK_ADIM        = 100      # her 100 BTC'de bir bildirim (100, 200, 300...)
TICK_SIZE        = 0.10     # fiyat adımı (10 cent = bir seviye)
# ══════════════════════════════════════════════

logging.basicConfig(format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger()

bars         = deque(maxlen=50)
seviye_hacim = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
son_esik     = defaultdict(lambda: {"buy": 0, "sell": 0})


def seviyele(fiyat):
    return round(round(fiyat / TICK_SIZE) * TICK_SIZE, 2)


def poc_hesapla(seviyeler):
    if not seviyeler:
        return 0.0
    return max(seviyeler, key=lambda s: seviyeler[s]["buy"] + seviyeler[s]["sell"])


async def telegram(session, mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        await session.post(url, json={"chat_id": TELEGRAM_CHAT, "text": mesaj, "parse_mode": "HTML"})
        log.info(f"📨 {mesaj[:80]}")
    except Exception as e:
        log.warning(f"Telegram hatası: {e}")


async def calistir():
    global seviye_hacim, son_esik

    stream = (
        f"wss://fstream.binance.com/stream?streams="
        f"{SEMBOL}@kline_{INTERVAL}/{SEMBOL}@aggTrade"
    )
    log.info(f"🚀 Başlatıldı | BTCUSDT PERP | {INTERVAL} | Eşik: her {ESIK_ADIM} BTC")

    async with aiohttp.ClientSession() as session:
        await telegram(session,
            f"✅ <b>POC Sinyal Botu Başladı</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Tek fiyat seviyesinde her {ESIK_ADIM} BTC artışında bildirim\n"
            f"100 BTC → bildirim, 200 BTC → bildirim, 300 BTC → bildirim..."
        )

        while True:
            try:
                async with websockets.connect(stream, ping_interval=20) as ws:
                    log.info("🔌 Binance PERP bağlandı")
                    async for raw in ws:
                        data = json.loads(raw)
                        tip  = data.get("stream", "")
                        d    = data.get("data", {})

                        # ── Tick biriktir ─────────────────────────────────
                        if "aggTrade" in tip:
                            fiyat  = float(d["p"])
                            miktar = float(d["q"])
                            alis   = not d["m"]
                            sev    = seviyele(fiyat)

                            if alis:
                                seviye_hacim[sev]["buy"] += miktar
                                yeni = seviye_hacim[sev]["buy"]
                                taraf = "buy"
                                emoji = "🟢"
                                taraf_tr = "ALIM"
                            else:
                                seviye_hacim[sev]["sell"] += miktar
                                yeni = seviye_hacim[sev]["sell"]
                                taraf = "sell"
                                emoji = "🔴"
                                taraf_tr = "SATIM"

                            # Hangi eşiği geçti?
                            gecilen = int(yeni // ESIK_ADIM) * ESIK_ADIM
                            if gecilen >= ESIK_ADIM and gecilen > son_esik[sev][taraf]:
                                son_esik[sev][taraf] = gecilen
                                poc = poc_hesapla(seviye_hacim)
                                await telegram(session,
                                    f"{emoji} <b>{taraf_tr} {gecilen} BTC</b>\n"
                                    f"BTCUSDT PERP | {INTERVAL}\n"
                                    f"Fiyat seviyesi: {sev}\n"
                                    f"Toplam {taraf_tr}: {yeni:.1f} BTC\n"
                                    f"POC: {poc}\n"
                                    f"⏰ {time.strftime('%H:%M:%S')}"
                                )

                        # ── Mum kapandı: sıfırla ──────────────────────────
                        elif "kline" in tip and d["k"]["x"]:
                            k   = d["k"]
                            poc = poc_hesapla(seviye_hacim)
                            if poc == 0.0:
                                poc = round((float(k["h"]) + float(k["l"]) + float(k["c"])) / 3, 2)
                            cvd = sum(v["buy"] - v["sell"] for v in seviye_hacim.values())
                            bars.append({
                                "open":  float(k["o"]),
                                "high":  float(k["h"]),
                                "low":   float(k["l"]),
                                "close": float(k["c"]),
                                "poc":   poc,
                                "cvd":   round(cvd, 2),
                            })
                            log.info(f"Mum kapandı | C={k['c']} POC={poc} CVD={cvd:+.2f}")
                            seviye_hacim = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
                            son_esik     = defaultdict(lambda: {"buy": 0, "sell": 0})

            except Exception as e:
                log.warning(f"Bağlantı koptu: {e} — 5s sonra tekrar...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(calistir())
