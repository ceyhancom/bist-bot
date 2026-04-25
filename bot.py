import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BIST_LIST = [
    "ASELS.IS", "THYAO.IS", "KCHOL.IS", "GARAN.IS", "AKBNK.IS",
    "SISE.IS", "EREGL.IS", "BIMAS.IS", "TUPRS.IS"
]

TR_TZ = timezone(timedelta(hours=3))

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def add_indicators(df):
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI"] = rsi(df["Close"], 14)
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG20"]
    return df

def calc_score(row):
    score = 0
    if row["EMA20"] > row["EMA50"]:
        score += 25
    if row["RSI"] > 55:
        score += 20
    if row["VOL_RATIO"] > 1.2:
        score += 15
    return score

def is_bist_session_time():
    now = datetime.now(TR_TZ)
    if now.weekday() >= 5:
        return False
    current_minutes = now.hour * 60 + now.minute
    return 10 * 60 <= current_minutes < 18 * 60

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=30
    )

def scan():
    if not is_bist_session_time():
        return

    new_signals = []

    for symbol in BIST_LIST:
        try:
            df = yf.download(
                symbol,
                period="45d",
                interval="1h",
                auto_adjust=False,
                progress=False
            )

            if df.empty or len(df) < 80:
                continue

            df = add_indicators(df)

            prev = df.iloc[-2]
            curr = df.iloc[-1]

            required_cols = ["EMA20", "EMA50", "RSI", "VOL_RATIO", "Close"]
            if any(pd.isna(prev[col]) for col in required_cols):
                continue
            if any(pd.isna(curr[col]) for col in required_cols):
                continue

            prev_score = calc_score(prev)
            curr_score = calc_score(curr)

            if prev_score < 45 and curr_score >= 45:
                new_signals.append({
                    "symbol": symbol,
                    "score": curr_score,
                    "price": float(curr["Close"]),
                    "rsi": float(curr["RSI"]),
                    "vol_ratio": float(curr["VOL_RATIO"])
                })

        except Exception:
            continue

    if not new_signals:
        return

    new_signals = sorted(new_signals, key=lambda x: x["score"], reverse=True)

    lines = [f"📈 BIST Yeni Sinyaller ({datetime.now(TR_TZ).strftime('%H:%M')})", ""]
    for item in new_signals[:5]:
        lines.append(
            f"{item['symbol']} | Skor: {item['score']} | "
            f"Fiyat: {item['price']:.2f} | RSI: {item['rsi']:.1f} | "
            f"Hacim: {item['vol_ratio']:.2f}"
        )

    send_telegram("\n".join(lines))

if __name__ == "__main__":
    scan()