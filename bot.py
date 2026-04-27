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
    "EMPAE.IS", "MRGYO.IS", "SISE.IS", "ESEN.IS", "KZBYG.IS"
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
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()


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
    if row["EMA20"] > row["EMA50"]:
        s += 25
    if row["RSI"] > 55:
        s += 20
    if row["VOL_RATIO"] > 1.2:
        s += 15
    if row["Close"] > row["EMA20"]:
        s += 10
    if row["Close"] > row["EMA50"]:
        s += 10
    return s


def signal_label(curr, prev):
    curr_score = score(curr)
    prev_score = score(prev)

    if curr_score >= 70 and curr["EMA20"] > curr["EMA50"] and curr["RSI"] > 55:
        return "🟢 AL"

    if curr_score >= 55 and prev_score < curr_score:
        return "🟡 ERKEN GİRİŞ"

    if curr["EMA20"] < curr["EMA50"]:
        return "🔴 SAT"

    return "⚪ İZLE"


def breakout_label(curr, prev):
    if curr["Close"] > prev["HIGH_20"]:
        return "📈 Yukarı kırılım"
    if curr["Close"] < prev["LOW_20"]:
        return "📉 Aşağı kırılım"
    return "Kırılım yok"


def is_tradeable(df):
    try:
        curr = df.iloc[-1]
        prev5 = df.iloc[-5]

        vol_avg = df["Volume"].rolling(20).mean().iloc[-1]
        change = (curr["Close"] - prev5["Close"]) / prev5["Close"]

        return (
            curr["Volume"] >= vol_avg and
            curr["ATR"] / curr["Close"] >= 0.005 and
            abs(change) >= 0.01
        )
    except:
        return False


def analyze_symbol(symbol):
    df = yf.download(symbol, period="60d", interval="1h", progress=False)

    if df.empty:
        return None

    df = clean_df(df)
    df = indicators(df)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    return {
        "symbol": symbol,
        "price": float(curr["Close"]),
        "score": score(curr),
        "rsi": float(curr["RSI"]),
        "vol": float(curr["VOL_RATIO"]),
        "signal": signal_label(curr, prev),
        "breakout": breakout_label(curr, prev),
        "tradeable": is_tradeable(df)
    }


def scan():
    send("🔍 Tarama başladı")

    strong = []
    watch = []

    for symbol in BIST_LIST:
        try:
            r = analyze_symbol(symbol)
            if not r:
                continue

            # 🔥 Güçlü sinyal (hacim şartı eklendi)
            if r["signal"] == "🟢 AL" and r["vol"] >= 1:
                strong.append(r)

            # 🔥 Takip listesi (güçlü olanları tekrar ekleme)
            elif r["tradeable"]:
                watch.append(r)

        except:
            continue

    strong = sorted(strong, key=lambda x: x["score"], reverse=True)
    watch = sorted(watch, key=lambda x: x["score"], reverse=True)

    msg = "📊 BIST DURUM\n\n"

    msg += "🟢 Güçlü Sinyaller:\n"
    if strong:
        for s in strong[:3]:
            msg += f"{s['symbol']} | Fiyat:{round(s['price'],2)} | Skor:{s['score']}\n"
    else:
        msg += "Yok\n"

    msg += "\n🟡 Takip Edilecekler:\n"
    if watch:
        for w in watch[:5]:
            msg += f"{w['symbol']} | Skor:{w['score']} | RSI:{round(w['rsi'],1)}\n"
    else:
        msg += "Yok\n"

    send(msg)


if __name__ == "__main__":
    scan()
