import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BIST_LIST = [
    "AEFES.IS", "AKBNK.IS", "ALARK.IS", "ARCLK.IS", "ASELS.IS",
    "ASTOR.IS", "BIMAS.IS", "BRYAT.IS", "CCOLA.IS", "CIMSA.IS",
    "DOHOL.IS", "DOAS.IS", "ENKAI.IS", "EREGL.IS", "FROTO.IS",
    "GARAN.IS", "GESAN.IS", "GUBRF.IS", "HALKB.IS", "HEKTS.IS",
    "ISCTR.IS", "ISDMR.IS", "KCHOL.IS", "KONTR.IS", "KOZAL.IS",
    "KOZAA.IS", "KRDMD.IS", "MGROS.IS", "ODAS.IS", "OTKAR.IS",
    "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS",
    "SELEC.IS", "SISE.IS", "SMRTG.IS", "TAVHL.IS", "TCELL.IS",
    "THYAO.IS", "TKFEN.IS", "TOASO.IS", "TSKB.IS", "TTKOM.IS",
    "TUPRS.IS", "ULKER.IS", "VAKBN.IS", "YKBNK.IS"
]

TR_TZ = timezone(timedelta(hours=3))


def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=30
    )


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

        atr_val = df["ATR"].iloc[-1]
        price = df["Close"].iloc[-1]

        last_close = df["Close"].iloc[-1]
        prev_close = df["Close"].iloc[-5]
        change = (last_close - prev_close) / prev_close

        return (
            vol_now >= vol_avg and
            atr_val / price >= 0.005 and
            abs(change) >= 0.01
        )

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

            df = clean_df(df)
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
                    "score": curr_score,
                    "rsi": float(curr["RSI"]),
                    "vol_ratio": float(curr["VOL_RATIO"])
                })

        except Exception:
            error_count += 1
            continue

    
    if not signals:
    msg = "⚠️ Sinyal yok ama filtreyi geçen hisseler:\n\n"

    for symbol in BIST_LIST:
        try:
            df = yf.download(symbol, period="20d", interval="1d", progress=False)

            if df.empty:
                continue

            df = clean_df(df)
            df = indicators(df)

            if is_tradeable(df):
                curr = df.iloc[-1]

                msg += (
                    f"{symbol}\n"
                    f"RSI: {round(curr['RSI'],1)}\n"
                    f"Hacim: {round(curr['VOL_RATIO'],2)}\n\n"
                )

        except:
            continue

    msg += (
        "------\n"
        "📊 Özet:\n"
        f"Toplam: {len(BIST_LIST)}\n"
        f"Filtre geçen: {tradeable_count}\n"
        f"Hata: {error_count}"
    )

    send(msg)
    return


if __name__ == "__main__":
    scan()
