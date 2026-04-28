import os
import json
import requests
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TR_TZ = timezone(timedelta(hours=3))
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

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



def send(msg):
    max_len = 3900
    for i in range(0, len(msg), max_len):
        part = msg[i:i + max_len]
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": part}, timeout=30)


def now_tr():
    return datetime.now(TR_TZ)


def state_file():
    return DATA_DIR / f"daily_signals_{now_tr().strftime('%Y-%m-%d')}.json"


def load_state():
    path = state_file()
    if not path.exists():
        return {"AL": [], "TAKIP": [], "SAT": []}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"AL": [], "TAKIP": [], "SAT": []}


def save_state(state):
    path = state_file()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_signal(category, symbol):
    state = load_state()
    if symbol not in state[category]:
        state[category].append(symbol)
    save_state(state)


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
    if r >= 80:
        return "Aşırı alım, düzeltme riski"
    if r >= 70:
        return "Yüksek, dikkat"
    if r >= 55:
        return "Pozitif momentum"
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


def rr_comment(rr):
    if rr >= 2:
        return "İyi risk/ödül"
    if rr >= 1.5:
        return "Kabul edilebilir"
    return "Zayıf risk/ödül"


def warning_text(item):
    warnings = []

    if item["rsi"] >= 80:
        warnings.append("RSI çok yüksek; sert yükseliş sonrası düzeltme gelebilir.")
    elif item["rsi"] >= 70:
        warnings.append("RSI yüksek; girişte acele edilmemeli.")

    if item["vol"] < 1:
        warnings.append("Hacim zayıf; hareketin güvenilirliği düşük olabilir.")

    if item["rr"] < 1.5:
        warnings.append("Risk/ödül oranı zayıf.")

    if item["signal"] == "🔴 SAT":
        warnings.append("Portföyde varsa destek/stop seviyeleri ayrıca kontrol edilmeli.")

    if not warnings:
        warnings.append("Veriler genel olarak dengeli görünüyor.")

    return "\n".join([f"* {w}" for w in warnings])


def signal_label(curr, prev):
    sc = score(curr)
    prev_sc = score(prev)

    if curr["EMA20"] < curr["EMA50"] or curr["RSI"] < 40:
        return "🔴 SAT"

    if sc >= 70 and curr["EMA20"] > curr["EMA50"] and curr["VOL_RATIO"] >= 1:
        return "🟢 AL"

    if sc >= 55 and prev_sc < sc:
        return "🟡 TAKİP / ERKEN GİRİŞ"

    return "⚪ İZLE"


def breakout_label(curr, prev):
    if pd.isna(prev["HIGH_20"]) or pd.isna(prev["LOW_20"]):
        return "Veri yetersiz"

    if curr["Close"] > prev["HIGH_20"]:
        return "📈 Yukarı trend kırılımı"

    if curr["Close"] < prev["LOW_20"]:
        return "📉 Aşağı trend kırılımı"

    return "Kırılım yok"


def analyze(symbol):
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

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    entry = float(curr["Close"])
    atr_val = float(curr["ATR"])

    if pd.isna(atr_val):
        return None

    stop = entry - atr_val * 1.5
    risk = entry - stop
    target = entry + risk * 2
    rr = (target - entry) / risk if risk > 0 else 0

    item = {
        "symbol": symbol,
        "signal": signal_label(curr, prev),
        "breakout": breakout_label(curr, prev),
        "price": entry,
        "score": score(curr),
        "rsi": float(curr["RSI"]),
        "vol": float(curr["VOL_RATIO"]),
        "stop": stop,
        "target": target,
        "rr": rr
    }

    return item


def format_detail(x):
    return (
        f"{x['symbol']}\n"
        f"Sinyal: {x['signal']}\n"
        f"Kırılım: {x['breakout']}\n"
        f"Fiyat: {round(x['price'], 2)}\n"
        f"Skor: {x['score']} ({score_comment(x['score'])})\n"
        f"RSI: {round(x['rsi'], 1)} ({rsi_comment(x['rsi'])})\n"
        f"Hacim: {round(x['vol'], 2)} ({vol_comment(x['vol'])})\n"
        f"STOP: {round(x['stop'], 2)}\n"
        f"HEDEF: {round(x['target'], 2)}\n"
        f"R/R: {round(x['rr'], 2)} ({rr_comment(x['rr'])})\n"
        f"{warning_text(x)}\n\n"
    )


def categorize(results):
    al = []
    takip = []
    sat = []

    for x in results:
        if x["signal"] == "🟢 AL":
            al.append(x)
            record_signal("AL", x["symbol"])
        elif x["signal"] == "🔴 SAT":
            sat.append(x)
            record_signal("SAT", x["symbol"])
        elif x["signal"] in ["🟡 TAKİP / ERKEN GİRİŞ", "⚪ İZLE"]:
            takip.append(x)
            record_signal("TAKIP", x["symbol"])

    al = sorted(al, key=lambda x: x["score"], reverse=True)
    takip = sorted(takip, key=lambda x: x["score"], reverse=True)
    sat = sorted(sat, key=lambda x: x["score"])

    return al, takip, sat


def scan_market():
    results = []
    checked = 0
    errors = 0

    for symbol in BIST_LIST:
        try:
            item = analyze(symbol)
            checked += 1
            if item:
                results.append(item)
        except Exception:
            errors += 1

    al, takip, sat = categorize(results)

    msg = f"📊 BIST DURUM ({now_tr().strftime('%H:%M')})\n\n"

    msg += "🟢 AL Sinyalleri:\n\n"
    msg += "".join(format_detail(x) for x in al[:3]) if al else "Yok\n\n"

    msg += "🟡 TAKİP Sinyalleri:\n\n"
    msg += "".join(format_detail(x) for x in takip[:3]) if takip else "Yok\n\n"

    msg += "🔴 SAT Sinyalleri:\n\n"
    msg += "".join(format_detail(x) for x in sat[:3]) if sat else "Yok\n\n"

    msg += (
        "------\n"
        f"Toplam liste: {len(BIST_LIST)}\n"
        f"Kontrol edilen: {checked}\n"
        f"Hata: {errors}"
    )

    send(msg)


def morning_report():
    send(
        "🌅 Gün Öncesi BIST Değerlendirme\n\n"
        "Bugün bot seans boyunca her 15 dakikada bir tarama yapacak.\n"
        "AL, TAKİP ve SAT sinyalleri ayrı başlıklar altında gönderilecek.\n\n"
        "Notlar:\n"
        "* Açılışta ilk hareketler yanıltıcı olabilir.\n"
        "* RSI yüksek hisselerde kademeli hareket etmek daha sağlıklıdır.\n"
        "* Hacim düşükse sinyal güveni azalır.\n"
        "* Bu sistem karar destek amaçlıdır; nihai karar sende olmalı."
    )


def evening_report():
    state = load_state()

    def list_or_none(items):
        return "\n".join([f"- {x}" for x in items]) if items else "Yok"

    msg = (
        "🌙 Gün Sonu BIST Özeti\n\n"
        "🟢 Gün boyu AL sinyali gelenler:\n"
        f"{list_or_none(state.get('AL', []))}\n\n"
        "🟡 Gün boyu TAKİP sinyali gelenler:\n"
        f"{list_or_none(state.get('TAKIP', []))}\n\n"
        "🔴 Gün boyu SAT sinyali gelenler:\n"
        f"{list_or_none(state.get('SAT', []))}\n\n"
        "Genel değerlendirme:\n"
        "* AL listesi fırsat adaylarını gösterir.\n"
        "* TAKİP listesi teyit bekleyen hisselerdir.\n"
        "* SAT listesi portföyde varsa dikkat edilmesi gereken hisselerdir."
    )

    send(msg)


def run():
    mode = os.environ.get("MODE", "auto").lower()
    now = now_tr()

    if mode == "morning":
        morning_report()
        return

    if mode == "evening":
        evening_report()
        return

    if mode == "scan":
        scan_market()
        return

    if now.hour == 9:
        morning_report()
    elif 10 <= now.hour < 18:
        scan_market()
    elif now.hour >= 18:
        evening_report()
    else:
        send("⏰ Piyasa saati dışında. İşlem yapılmadı.")


if __name__ == "__main__":
    run()
