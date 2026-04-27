import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BIST_LIST = [
    "ARENA.IS", "AKBNK.IS", "ALARK.IS", "ARCLK.IS", "ASELS.IS",
    "ASTOR.IS", "BIMAS.IS", "BRYAT.IS", "CCOLA.IS", "CIMSA.IS",
    "DOHOL.IS", "DOAS.IS", "ENKAI.IS", "EREGL.IS", "FROTO.IS",
    "GARAN.IS", "GESAN.IS", "GUBRF.IS", "HALKB.IS", "HEKTS.IS",
    "ISCTR.IS", "ISDMR.IS", "KCHOL.IS", "KONTR.IS", "KOZAL.IS",
    "KOZAA.IS", "KRDMD.IS", "MGROS.IS", "ODAS.IS", "OTKAR.IS",
    "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS",
    "SELEC.IS", "SISE.IS", "SMRTG.IS", "TAVHL.IS", "TCELL.IS",
    "THYAO.IS", "TKFEN.IS", "TOASO.IS", "TSKB.IS", "TTKOM.IS",
    "TUPRS.IS", "ULKER.IS", "VAKBN.IS", "YKBNK.IS", "ISKPL.IS",
    "EMPAE.IS", "MRGYO.IS", "SISE.IS", "ESEN.IS", "KZBYG.IS",
    "SERNT.IS", "DESPC.IS", "MEYSU.IS", "HURGZ.IS", "TERA.IS"
]

TR_TZ = timezone(timedelta(hours=3))


def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=30)


def clean_df(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


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
    return ranges.max(axis=1).rolling(period).mean()


def indicators(df):
    df["EMA20"] = df["Close"].ewm(span=20).mean()
    df["EMA50"] = df["Close"].ewm(span=50).mean()
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)
    df["VOL_AVG"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG"]
    df["HIGH_20"] = df["High"].rolling(20).max()
    df["LOW_20"] = df["Low"].rolling(20).min()
    return df


def score(row):
    s = 0
    if row["EMA20"] > row["EMA50"]: s += 25
    if row["RSI"] > 55: s += 20
    if row["VOL_RATIO"] > 1.2: s += 15
    if row["Close"] > row["EMA20"]: s += 10
    if row["Close"] > row["EMA50"]: s += 10
    return s


# 🔥 YENİ EKLER

def confidence_score(s, rsi, vol):
    c = s
    if vol > 1.5: c += 10
    if 50 < rsi < 70: c += 10
    return min(100, c)


def timing(rsi):
    if rsi > 80:
        return "Geç kalınmış"
    if rsi > 70:
        return "Dikkatli giriş"
    if rsi > 50:
        return "Uygun"
    return "Erken"


def warning_text(rsi_val, vol):
    warnings = []

    if rsi_val > 75:
        warnings.append("RSI yüksek → düzeltme riski")

    if vol < 1:
        warnings.append("Hacim zayıf")

    if not warnings:
        return "Durum sağlıklı"

    return " | ".join(warnings)


def signal_label(curr, prev):
    sc = score(curr)
    prev_sc = score(prev)

    if sc >= 70 and curr["EMA20"] > curr["EMA50"]:
        return "🟢 AL"

    if sc >= 55 and prev_sc < sc:
        return "🟡 ERKEN GİRİŞ"

    if curr["EMA20"] < curr["EMA50"]:
        return "🔴 SAT"

    return "⚪ İZLE"


def breakout(curr, prev):
    if curr["Close"] > prev["HIGH_20"]:
        return "📈 Yukarı kırılım"
    if curr["Close"] < prev["LOW_20"]:
        return "📉 Aşağı kırılım"
    return "Kırılım yok"


def analyze(symbol):
    df = yf.download(symbol, period="60d", interval="1h", progress=False)

    if df.empty:
        return None

    df = clean_df(df)
    df = indicators(df)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    entry = float(curr["Close"])
    atr_val = float(curr["ATR"])

    stop = entry - atr_val * 1.5
    risk = entry - stop
    target = entry + risk * 2
    rr = (target - entry) / risk if risk > 0 else 0

    sc = score(curr)

    return {
        "symbol": symbol,
        "signal": signal_label(curr, prev),
        "breakout": breakout(curr, prev),
        "price": entry,
        "score": sc,
        "confidence": confidence_score(sc, curr["RSI"], curr["VOL_RATIO"]),
        "timing": timing(curr["RSI"]),
        "rsi": float(curr["RSI"]),
        "vol": float(curr["VOL_RATIO"]),
        "stop": stop,
        "target": target,
        "rr": rr,
        "warn": warning_text(curr["RSI"], curr["VOL_RATIO"])
    }


def format_full(x):
    return (
        f"{x['symbol']}\n"
        f"Sinyal: {x['signal']}\n"
        f"Kırılım: {x['breakout']}\n"
        f"Fiyat: {round(x['price'],2)}\n"
        f"Skor: {x['score']} | Güven: %{x['confidence']}\n"
        f"Zamanlama: {x['timing']}\n"
        f"RSI: {round(x['rsi'],1)}\n"
        f"Hacim: {round(x['vol'],2)}\n"
        f"STOP: {round(x['stop'],2)}\n"
        f"HEDEF: {round(x['target'],2)}\n"
        f"R/R: {round(x['rr'],2)}\n"
        f"⚠️ {x['warn']}\n\n"
    )


def scan():
    send("🔍 Tarama başladı")

    buy, watch, sell = [], [], []

    for s in BIST_LIST:
        try:
            r = analyze(s)
            if not r:
                continue

            if r["signal"] == "🟢 AL" and r["vol"] >= 1:
                buy.append(r)
            elif r["signal"] == "🔴 SAT":
                sell.append(r)
            else:
                watch.append(r)

        except:
            continue

    buy = sorted(buy, key=lambda x: x["score"], reverse=True)
    watch = sorted(watch, key=lambda x: x["score"], reverse=True)
    sell = sorted(sell, key=lambda x: x["score"])

    msg = "📊 BIST DURUM\n\n"

    msg += "🟢 AL Sinyalleri:\n\n"
    msg += "".join(format_full(x) for x in buy[:3]) if buy else "Yok\n\n"

    msg += "🟡 Takip Sinyalleri:\n\n"
    msg += "".join(format_full(x) for x in watch[:3]) if watch else "Yok\n\n"

    msg += "🔴 SAT Sinyalleri:\n\n"
    msg += "".join(format_full(x) for x in sell[:3]) if sell else "Yok\n\n"

    send(msg)


if __name__ == "__main__":
    scan()
