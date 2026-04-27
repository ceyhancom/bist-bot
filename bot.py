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


def score_comment(s):
    if s >= 70:
        return "Çok güçlü"
    if s >= 55:
        return "Güçlü"
    if s >= 40:
        return "Orta"
    return "Zayıf"


def rsi_comment(r):
    if r >= 75:
        return "Aşırı alım, dikkat"
    if r >= 60:
        return "Güçlü momentum"
    if r >= 45:
        return "Normal"
    if r >= 30:
        return "Zayıf"
    return "Aşırı satım"


def vol_comment(v):
    if v >= 2:
        return "Çok yüksek hacim"
    if v >= 1.3:
        return "Yüksek hacim"
    if v >= 1:
        return "Normal üstü"
    return "Zayıf hacim"


def signal_label(curr, prev):
    curr_score = score(curr)
    prev_score = score(prev)

    if curr_score >= 70 and curr["EMA20"] > curr["EMA50"] and curr["RSI"] > 55:
        return "🟢 AL"

    if curr_score >= 55 and prev_score < curr_score and curr["Close"] > curr["EMA20"]:
        return "🟡 ERKEN GİRİŞ"

    if curr["EMA20"] < curr["EMA50"] or curr["RSI"] < 40:
        return "🔴 SAT / ZAYIFLAMA"

    return "⚪ İZLE"


def breakout_label(curr, prev):
    if pd.isna(prev["HIGH_20"]) or pd.isna(prev["LOW_20"]):
        return "Veri yetersiz"

    if curr["Close"] > prev["HIGH_20"]:
        return "📈 Yukarı trend kırılımı"

    if curr["Close"] < prev["LOW_20"]:
        return "📉 Aşağı trend kırılımı"

    return "Kırılım yok"


def is_tradeable(df):
    try:
        curr = df.iloc[-1]
        prev5 = df.iloc[-5]

        vol_avg = df["Volume"].rolling(20).mean().iloc[-1]
        vol_now = curr["Volume"]

        atr_val = curr["ATR"]
        price = curr["Close"]

        change = (curr["Close"] - prev5["Close"]) / prev5["Close"]

        return (
            vol_now >= vol_avg
            and atr_val / price >= 0.005
            and abs(change) >= 0.01
        )
    except Exception:
        return False


def is_market_open():
    now = datetime.now(TR_TZ)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 18


def analyze_symbol(symbol):
    df = yf.download(
        symbol,
        period="60d",
        interval="1h",
        progress=False,
        auto_adjust=False
    )

    if df.empty or len(df) < 50:
        return None

    df = clean_df(df)
    df = indicators(df)

    if not is_tradeable(df):
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    curr_score = score(curr)
    sig = signal_label(curr, prev)
    brk = breakout_label(curr, prev)

    entry = float(curr["Close"])
    atr_val = float(curr["ATR"])

    stop = entry - atr_val * 1.5
    risk = entry - stop
    target = entry + risk * 2

    rr = 0
    if risk > 0:
        rr = (target - entry) / risk

    return {
        "symbol": symbol,
        "price": entry,
        "score": curr_score,
        "rsi": float(curr["RSI"]),
        "vol_ratio": float(curr["VOL_RATIO"]),
        "signal": sig,
        "breakout": brk,
        "stop": stop,
        "target": target,
        "rr": rr
    }


def scan():
    now_text = datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M")
    send(f"🔍 BIST bot çalıştı. Tarama başladı.\nSaat: {now_text}")

    if not is_market_open():
        send("⏰ Piyasa kapalı. Tarama yapılmadı.")
        return

    results = []
    checked_count = 0
    error_count = 0

    for symbol in BIST_LIST:
        try:
            result = analyze_symbol(symbol)
            checked_count += 1

            if result:
                results.append(result)

        except Exception:
            error_count += 1
            continue

    if not results:
        send(
            "✅ Tarama tamamlandı. Uygun aday bulunamadı.\n"
            f"Toplam liste: {len(BIST_LIST)}\n"
            f"Kontrol edilen: {checked_count}\n"
            f"Hata: {error_count}"
        )
        return

    results = sorted(results, key=lambda x: x["score"], reverse=True)

    msg = f"📊 BIST ADAYLAR ({datetime.now(TR_TZ).strftime('%H:%M')})\n"
    msg += f"Filtreyi geçen: {len(results)}\n"
    msg += "En iyi adaylar:\n\n"

    for item in results[:5]:
        msg += (
            f"{item['symbol']}\n"
            f"Sinyal: {item['signal']}\n"
            f"Kırılım: {item['breakout']}\n"
            f"Fiyat: {round(item['price'], 2)}\n"
            f"Skor: {item['score']} ({score_comment(item['score'])})\n"
            f"RSI: {round(item['rsi'], 1)} ({rsi_comment(item['rsi'])})\n"
            f"Hacim: {round(item['vol_ratio'], 2)} ({vol_comment(item['vol_ratio'])})\n"
            f"STOP: {round(item['stop'], 2)}\n"
            f"HEDEF: {round(item['target'], 2)}\n"
            f"R/R: {round(item['rr'], 2)}\n\n"
        )

    send(msg)


if __name__ == "__main__":
    scan()
