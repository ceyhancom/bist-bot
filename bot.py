import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BIST_LIST = [
    "ASELS.IS", "THYAO.IS", "KCHOL.IS",
    "GARAN.IS", "AKBNK.IS", "SISE.IS",
    "EREGL.IS", "BIMAS.IS", "TUPRS.IS",
    "SAHOL.IS", "YKBNK.IS", "ISCTR.IS",
    "ASTOR.IS", "KRDMD.IS", "PETKM.IS",
    "FROTO.IS", "TOASO.IS", "GUBRF.IS"
]

TR_TZ = timezone(timedelta(hours=3))

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()

def indicators(df):
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)
    df["VOL_AVG"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG"]
    return df

def is_tradeable(df):
    try:
        vol_avg = df["Volume"].rolling(20).mean().iloc[-1]
        vol_now = df["Volume"].iloc[-1]

        if vol_now < vol_avg:
            return False

        atr_val = df["ATR"].iloc[-1]
        price = df["Close"].iloc[-1]

        if atr_val / price < 0.01:
            return False

        last_close = df["Close"].iloc[-1]
        prev_close = df["Close"].iloc[-5]
        change = (last_close - prev_close) / prev_close

        if abs(change) < 0.02:
            return False

        return True

    except Exception:
        return False

def score(row):
    s = 0
    if row["EMA20"] > row["EMA50"]:
        s += 25
    if row["RSI"] > 55:
        s += 20
    if row["VOL_RATIO"] > 1.2:
        s += 15
    return s

def is_market_open():
    now = datetime.now(TR_TZ)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 18

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=30
    )

def scan():
    now_text = datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M")
    send(f"🔍 BIST bot çalıştı. Tarama başladı.\nSaat: {now_text}")

    if not is_market_open():
        send("⏰ Piyasa kapalı. Tarama yapılmadı.")
        return

    signals = []
    checked_count = 0
    tradeable_count = 0
    error_count = 0

    for symbol in BIST_LIST:
        try:
            df = yf.download(
                symbol,
                period="45d",
                interval="1h",
                progress=False,
                auto_adjust=False
            )

            if df.empty or len(df) < 50:
                continue

            checked_count += 1
            df = indicators(df)

            if not is_tradeable(df):
                continue

            tradeable_count += 1

            prev = df.iloc[-2]
            curr = df.iloc[-1]

            if pd.isna(curr["ATR"]):
                continue

            prev_score = score(prev)
            curr_score = score(curr)

            if prev_score < 50 and curr_score >= 50:
                entry = float(curr["Close"])
                atr_val = float(curr["ATR"])

                stop = entry - atr_val * 1.5
                risk = entry - stop
                target = entry + (risk * 2)

                if risk <= 0:
                    continue

                rr = (target - entry) / risk

                if rr < 1.5:
                    continue

                signals.append({
                    "symbol": symbol,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "rr": rr,
                    "score": curr_score
                })

        except Exception:
            error_count += 1
            continue

    if not signals:
        send(
            "✅ Tarama tamamlandı. Uygun sinyal bulunamadı.\n"
            f"Toplam liste: {len(BIST_LIST)}\n"
            f"Verisi alınan: {checked_count}\n"
            f"Filtreyi geçen: {tradeable_count}\n"
            f"Hata: {error_count}"
        )
        return

    msg = f"📈 BIST SİNYAL ({datetime.now(TR_TZ).strftime('%H:%M')})\n\n"

    for s in signals[:5]:
        msg += (
            f"{s['symbol']}\n"
            f"Skor: {s['score']}\n"
            f"Giriş: {round(s['entry'], 2)}\n"
            f"STOP: {round(s['stop'], 2)}\n"
            f"HEDEF: {round(s['target'], 2)}\n"
            f"R/R: {round(s['rr'], 2)}\n\n"
        )

    send(msg)

if __name__ == "__main__":
    scan()
