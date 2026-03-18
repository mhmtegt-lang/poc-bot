"""
BTCUSDT PERP — Smart Money POC Sinyalleri → Telegram
Tek fiyat seviyesinde her 100 BTC eşiğinde bir bildirim (100, 200, 300...)
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
ESIK_ADIM        = 20       # her 0.5 BTC'de bir bildirim (0.5, 1.0, 1.5...)
TICK_SIZE        = 0.10      # fiyat adımı (10 cent = bir seviye)
# ══════════════════════════════════════════════

logging.basicConfig(format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger()

bars         = deque(maxlen=50)
# Fiyat seviyesi bazlı hacim
seviye_hacim: dict = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
# Her seviye için son gönderilen eşik: {seviye: {"buy": int, "sell": int}}
# örn: {71800.0: {"buy": 100, "sell": 0}} → 100 eşiği geçildi, 200 henüz geçilmedi
son_esik: dict = defaultdict(lambda: {"buy": 0, "sell": 0})


def seviyele(fiyat: float) -> float:
    return round(round(fiyat / TICK_SIZE) * TICK_SIZE, 2)


def poc_hesapla(seviyeler: dict) -> float:
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
    log.info(f"🚀 Başlatıldı | BTCUSDT PERP | {INTERVAL} | Eşik adımı: {ESIK_ADIM} BTC")

    async with aiohttp.ClientSession() as session:
        await telegram(session,
            f"✅ <b>POC Sinyal Botu Başladı</b>\n"
            f"BTCUSDT PERP | {INTERVAL}\n"
            f"Her {ESIK_ADIM} BTC artışında bildirim (tek fiyat seviyesi)\n"
            f"Örn: 100 → bildirim, 150 → yok, 200 → bildirim, 350 → yok, 400 → bildirim"
        )

        while True:
            try:
                async with websockets.connect(stream, ping_interval=20) as ws:
                    log.info("🔌 Binance PERP bağlandı")
                    async for raw in ws:
                        data = json.loads(raw)
                        tip  = data.get("stream", "")
                        d    = data.get("data", {})

                        # ── Tick: fiyat seviyesine göre biriktir ──────────
                        if "aggTrade" in tip:
                            fiyat  = float(d["p"])
                            miktar = float(d["q"])
                            alis   = not d["m"]
                            sev    = seviyele(fiyat)

                            if alis:
                                seviye_hacim[sev]["buy"] += miktar
                                yeni_hacim = seviye_hacim[sev]["buy"]
                                taraf = "buy"
                                emoji = "🟢"
                                taraf_tr = "ALIM"
                            else:
                                seviye_hacim[sev]["sell"] += miktar
                                yeni_hacim = seviye_hacim[sev]["sell"]
                                taraf = "sell"
                                emoji = "🔴"
                                taraf_tr = "SATIM"

                            # Hangi eşiği geçti?
                            gecilen_esik = int(yeni_hacim // ESIK_ADIM) * ESIK_ADIM
                            if gecilen_esik >= ESIK_ADIM and gecilen_esik > son_esik[sev][taraf]:
                                son_esik[sev][taraf] = gecilen_esik

                                # POC şu anki durumu
                                poc_simdi = poc_hesapla(seviye_hacim)
                                if len(bars) >= 1:
                                    poc_onceki = bars[-1]["poc"]
                                    poc_yonu = "↑" if poc_simdi > poc_onceki else "↓" if poc_simdi < poc_onceki else "→"
                                else:
                                    poc_yonu = "→"

                                mesaj = (
                                    f"{emoji} <b>{taraf_tr} {gecilen_esik} BTC EŞİĞİ</b>\n"
                                    f"BTCUSDT PERP | {INTERVAL}\n"
                                    f"Fiyat seviyesi: {sev}\n"
                                    f"Bu seviyede {taraf_tr}: {yeni_hacim:.1f} BTC\n"
                                    f"POC: {poc_simdi} {poc_yonu}\n"
                                    f"⏰ {time.strftime('%H:%M:%S')}"
                                )
                                await telegram(session, mesaj)

                        # ── Mum kapandı: buffer sıfırla ───────────────────
                        elif "kline" in tip and d["k"]["x"]:
                            k   = d["k"]
                            poc = poc_hesapla(seviye_hacim)
                            if poc == 0.0:
                                poc = round((float(k["h"]) + float(k["l"]) + float(k["c"])) / 3, 2)
                            cvd = sum(v["buy"] - v["sell"] for v in seviye_hacim.values())

                            bar = {
                                "open":  float(k["o"]),
                                "high":  float(k["h"]),
                                "low":   float(k["l"]),
                                "close": float(k["c"]),
                                "poc":   poc,
                                "cvd":   round(cvd, 2),
                            }
                            bars.append(bar)

                            log.info(
                                f"Mum kapandı | C={bar['close']} "
                                f"POC={bar['poc']} CVD={bar['cvd']:+.2f}"
                            )

                            # Yeni mum başlıyor — seviyeleri sıfırla
                            seviye_hacim = defaultdict(lambda: {"buy": 0.0, "sell": 0.0})
                            son_esik     = defaultdict(lambda: {"buy": 0, "sell": 0})

            except Exception as e:
                log.warning(f"Bağlantı koptu: {e} — 5s sonra tekrar...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(calistir())
