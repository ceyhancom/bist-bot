# -*- coding: utf-8 -*-
"""
BIST100 Telegram Tarama Botu - SEVİYE 3

Eklenen Seviye 3 Özellikleri:
- Trend + kırılım + pullback yakalama
- AL / TAKİP / SAT aksiyon sınıflandırması
- Sadece en güçlü AL sinyallerini gönderme
- Fake sinyal filtresi
- Açık işlem takibi
- Trailing stop mantığı
- Gün sonu performans özeti
- Telegram mesajlarında daha net aksiyon dili

GitHub Secrets / Ortam Değişkenleri:
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID

requirements.txt:
yfinance
pandas
requests
pytz
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
import pytz


# =========================
# GENEL AYARLAR
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TZ = pytz.timezone("Europe/Istanbul")

PERIOD = "90d"
INTERVAL = "1h"

STATE_FILE = Path("gunluk_sinyaller.json")
PERFORMANCE_FILE = Path("performance.json")
OPEN_TRADES_FILE = Path("open_trades.json")

MAX_AL_SIGNAL = 10
MAX_TAKIP_SIGNAL = 10
MAX_SAT_SIGNAL = 10

# Portföyünde olan hisseleri ve maliyetlerini buraya yaz.
# BIST100 içinde olmasa bile bu hisseler ayrıca analiz edilir.
# Örnek:
# PORTFOLIO = [
#     {"symbol": "ASELS.IS", "entry": 58.00},
#     {"symbol": "THYAO.IS", "entry": 285.00},
# ]
PORTFOLIO = [
    # {"symbol": "ASTOR.IS", "entry": 196.80},
    # {"symbol": "DESPC.IS", "entry": 43.90},
    # {"symbol": "EMPAE.IS", "entry": 48.68},
    # {"symbol": "ISKPL.IS", "entry": 13.41},
    # {"symbol": "MRGYO.IS", "entry": 1.93},
    # {"symbol": "SERNT.IS", "entry": 9.40},
    # {"symbol": "TAVHL.IS", "entry": 323.00},
]

PORTFOLIO_LIST = [item["symbol"] for item in PORTFOLIO]

# Sinyal eşikleri
COK_GUCLU_AL_ESIK = 85
GUCLU_AL_ESIK = 70
TAKIP_ESIK = 55
SAT_ESIK = 35

# Kalite filtreleri
MAX_RSI_FOR_AL = 80
MIN_VOL_RATIO_FOR_AL = 1.0
MIN_RR_FOR_AL = 1.5

# Trailing stop ayarları
TRAILING_START_PROFIT = 3.0      # %3 kârdan sonra takip stop aktif olur
TRAILING_STOP_DISTANCE = 2.0     # En yüksek fiyattan %2 aşağı trailing stop


BIST_LIST = [
    "AEFES.IS", "AGHOL.IS", "AKBNK.IS", "AKSA.IS", "AKSEN.IS",
    "ALARK.IS", "ALTNY.IS", "ANSGR.IS", "ARCLK.IS", "ASELS.IS",
    "ASTOR.IS", "BALSU.IS", "BIMAS.IS", "BRSAN.IS", "BRYAT.IS",
    "BTCIM.IS", "CANTE.IS", "CCOLA.IS", "CIMSA.IS", "CLEBI.IS",
    "CWENE.IS", "DOAS.IS", "DOHOL.IS", "DSTKF.IS", "EFORC.IS",
    "EGEEN.IS", "EKGYO.IS", "ENERY.IS", "ENJSA.IS", "ENKAI.IS",
    "EREGL.IS", "EUPWR.IS", "FROTO.IS", "GARAN.IS", "GENIL.IS",
    "GESAN.IS", "GRSEL.IS", "GUBRF.IS", "HALKB.IS", "HEKTS.IS",
    "IEYHO.IS", "ISCTR.IS", "ISMEN.IS", "KCAER.IS", "KCHOL.IS",
    "KLRHO.IS", "KONTR.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS",
    "KTLEV.IS", "KUYAS.IS", "MAGEN.IS", "MAVI.IS", "MGROS.IS",
    "MIATK.IS", "MPARK.IS", "OBAMS.IS", "ODAS.IS", "OTKAR.IS",
    "OYAKC.IS", "PASEU.IS", "PETKM.IS", "PGSUS.IS", "RALYH.IS",
    "REEDR.IS", "SAHOL.IS", "SASA.IS", "SISE.IS", "SKBNK.IS",
    "SMRTG.IS", "SOKM.IS", "TABGD.IS", "TAVHL.IS", "TCELL.IS",
    "THYAO.IS", "TKFEN.IS", "TOASO.IS", "TSKB.IS", "TTKOM.IS",
    "TTRAK.IS", "TUKAS.IS", "TUPRS.IS", "TUREX.IS", "TURSG.IS",
    "ULKER.IS", "VAKBN.IS", "VESTL.IS", "YEOTK.IS", "YKBNK.IS",
    "ZOREN.IS"
]


# =========================
# TELEGRAM
# =========================

def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik. Mesaj gönderilmedi.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code != 200:
            print("Telegram hata:", response.status_code, response.text)
    except Exception as e:
        print("Telegram gönderim hatası:", e)


def split_and_send(title: str, messages: list[str], max_chars: int = 3500) -> None:
    if not messages:
        return

    text = title + "\n\n"

    for msg in messages:
        if len(text) + len(msg) + 2 > max_chars:
            send_telegram(text.strip())
            text = title + "\n\n"
        text += msg + "\n\n"

    if text.strip() != title:
        send_telegram(text.strip())


# =========================
# JSON İŞLEMLERİ
# =========================

def read_json(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    state = read_json(STATE_FILE, {})

    if state.get("date") != today:
        state = {
            "date": today,
            "al": [],
            "takip": [],
            "sat": [],
            "errors": []
        }

    return state


def save_state(state: dict) -> None:
    write_json(STATE_FILE, state)


def add_unique(state: dict, key: str, symbol: str) -> None:
    if symbol not in state[key]:
        state[key].append(symbol)


def load_performance() -> list[dict]:
    return read_json(PERFORMANCE_FILE, [])


def save_performance(data: list[dict]) -> None:
    write_json(PERFORMANCE_FILE, data)


def load_open_trades() -> list[dict]:
    return read_json(OPEN_TRADES_FILE, [])


def save_open_trades(data: list[dict]) -> None:
    write_json(OPEN_TRADES_FILE, data)


# =========================
# TEKNİK GÖSTERGELER
# =========================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA100"] = df["Close"].ewm(span=100, adjust=False).mean()
    df["RSI"] = calc_rsi(df["Close"], 14)
    df["ATR"] = calc_atr(df, 14)
    df["VOL_AVG"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG"]
    df["HIGH20_PREV"] = df["High"].rolling(20).max().shift(1)
    df["LOW20_PREV"] = df["Low"].rolling(20).min().shift(1)
    df["HIGH50_PREV"] = df["High"].rolling(50).max().shift(1)
    df["LOW50_PREV"] = df["Low"].rolling(50).min().shift(1)

    return df


# =========================
# YORUMLAR
# =========================

def rsi_comment(rsi: float) -> str:
    if rsi >= 80:
        return "Aşırı alım var, dikkat!"
    if rsi >= 70:
        return "Güçlü ama düzeltme riski var!"
    if rsi >= 55:
        return "Sağlıklı pozitif momentum var"
    if rsi >= 45:
        return "Kararsız / nötr"
    if rsi >= 30:
        return "Zayıf momentum var"
    return "Aşırı satım var, tepki gelebilir"


def volume_comment(vol_ratio: float) -> str:
    if vol_ratio >= 2:
        return "Çok yüksek hacim"
    if vol_ratio >= 1.5:
        return "Güçlü hacim"
    if vol_ratio >= 1.2:
        return "Destekli hacim"
    if vol_ratio >= 1:
        return "Normal hacim"
    return "Zayıf hacim"


def score_comment(score: int) -> str:
    if score >= 85:
        return "Çok güçlü"
    if score >= 70:
        return "Güçlü"
    if score >= 55:
        return "Takip"
    if score >= 35:
        return "Zayıf"
    return "Negatif"


def setup_comment(setup_type: str) -> str:
    comments = {
        "BREAKOUT": "Direnç kırılımı ile momentum oluşmuş.",
        "PULLBACK": "Yükselen trend içinde EMA20 çevresinden tepki arıyor.",
        "TREND": "Trend güçlü fakat net kırılım yok.",
        "BREAKDOWN": "Destek kırılımı nedeniyle risk yüksek.",
        "WEAK": "Teknik teyit zayıf."
    }
    return comments.get(setup_type, "Teknik görünüm karışık.")


def action_comment(action: str) -> str:
    comments = {
        "AL": "Aksiyon: AL için güçlü aday. Stop seviyesine mutlaka uyulmalı.",
        "TAKIP": "Aksiyon: İzle. Net kırılım veya hacim teyidi beklenebilir.",
        "SAT": "Aksiyon: Riskli. Yeni alım için uygun görünmüyor.",
        "BEKLE": "Aksiyon: Bekle. Sinyal kalitesi düşük."
    }
    return comments.get(action, "Aksiyon: Bekle.")


def setup_label(setup_type: str) -> str:
    labels = {
        "BREAKOUT": "Yukarı Kırılım",
        "PULLBACK": "Trend İçi Geri Çekilme",
        "TREND": "Güçlü Trend",
        "BREAKDOWN": "Aşağı Kırılım",
        "WEAK": "Zayıf Görünüm"
    }
    return labels.get(setup_type, setup_type)


def action_label(action: str) -> str:
    labels = {
        "AL": "AL",
        "TAKIP": "TAKİP",
        "SAT": "SAT / UZAK DUR",
        "BEKLE": "BEKLE"
    }
    return labels.get(action, action)


# =========================
# SEVİYE 3 SETUP ANALİZİ
# =========================

def detect_setup(close, ema9, ema20, ema50, ema100, rsi, vol_ratio, high20_prev, low20_prev, high50_prev, low50_prev) -> tuple[str, int, str]:
    """
    Dönüş:
    setup_type, setup_bonus, kirilim
    """
    trend_strong = close > ema20 > ema50
    trend_super = close > ema20 > ema50 > ema100
    breakout_20 = close > high20_prev
    breakout_50 = close > high50_prev
    breakdown_20 = close < low20_prev
    breakdown_50 = close < low50_prev

    # Pullback: Ana trend pozitif, fiyat EMA20 çevresine yaklaşmış ve tekrar üstte.
    near_ema20 = abs(close - ema20) / close <= 0.025
    pullback = trend_strong and near_ema20 and 45 <= rsi <= 65 and vol_ratio >= 0.8

    if breakdown_50:
        return "BREAKDOWN", -30, "📉 Güçlü destek kırılımı"
    if breakdown_20:
        return "BREAKDOWN", -20, "📉 Kısa vadeli destek kırılımı"

    if breakout_50 and trend_super and vol_ratio >= 1.2:
        return "BREAKOUT", 35, "🚀 Güçlü yukarı kırılım"
    if breakout_20 and trend_strong:
        return "BREAKOUT", 25, "📈 Yukarı trend / direnç kırılımı"

    if pullback:
        return "PULLBACK", 25, "🟢 Trend içi pullback / tepki adayı"

    if trend_super:
        return "TREND", 15, "📊 Ana trend güçlü"
    if trend_strong:
        return "TREND", 10, "📊 Kısa vadeli trend pozitif"

    return "WEAK", 0, "➖ Net kırılım yok"


# =========================
# HİSSE ANALİZİ
# =========================

def analyze_symbol(symbol: str) -> dict | None:
    df = yf.download(symbol, period=PERIOD, interval=INTERVAL, progress=False, auto_adjust=False)

    if df is None or df.empty or len(df) < 110:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = prepare_indicators(df).dropna()

    if len(df) < 5:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = float(last["Close"])
    prev_close = float(prev["Close"])
    ema9 = float(last["EMA9"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    ema100 = float(last["EMA100"])
    rsi = float(last["RSI"])
    atr = float(last["ATR"])
    vol_ratio = float(last["VOL_RATIO"])
    high20_prev = float(last["HIGH20_PREV"])
    low20_prev = float(last["LOW20_PREV"])
    high50_prev = float(last["HIGH50_PREV"])
    low50_prev = float(last["LOW50_PREV"])

    score = 0
    reasons = []

    # Trend puanı
    if close > ema20 > ema50 > ema100:
        score += 35
        reasons.append("Ana trend çok güçlü")
    elif close > ema20 > ema50:
        score += 30
        reasons.append("Trend pozitif")
    elif close > ema20:
        score += 15
        reasons.append("Kısa vadeli toparlanma")
    else:
        score -= 15
        reasons.append("Fiyat EMA20 altında")

    # EMA9 momentum
    if close > ema9:
        score += 10
        reasons.append("Fiyat EMA9 üzerinde")
    else:
        score -= 5
        reasons.append("Fiyat EMA9 altında")

    # RSI puanı
    if 50 < rsi <= 65:
        score += 25
        reasons.append("RSI sağlıklı yükseliş bölgesinde")
    elif 65 < rsi <= 75:
        score += 20
        reasons.append("RSI güçlü")
    elif 75 < rsi <= 80:
        score += 8
        reasons.append("RSI yüksek, dikkat")
    elif 40 < rsi <= 50:
        score += 8
        reasons.append("RSI toparlanma denemesinde")
    elif rsi <= 35:
        score -= 10
        reasons.append("RSI zayıf")

    # Hacim puanı
    if vol_ratio >= 2:
        score += 30
        reasons.append("Çok yüksek hacim")
    elif vol_ratio >= 1.5:
        score += 25
        reasons.append("Güçlü hacim")
    elif vol_ratio >= 1.2:
        score += 15
        reasons.append("Hacim destekli")
    elif vol_ratio >= 1.0:
        score += 5
        reasons.append("Normal hacim")
    else:
        score -= 10
        reasons.append("Hacim zayıf")

    # Setup tespiti
    setup_type, setup_bonus, kirilim = detect_setup(
        close, ema9, ema20, ema50, ema100, rsi, vol_ratio,
        high20_prev, low20_prev, high50_prev, low50_prev
    )

    score += setup_bonus
    reasons.append(setup_comment(setup_type))

    # Son mum momentum
    if close > prev_close:
        score += 5
        reasons.append("Son mum pozitif")
    else:
        score -= 5
        reasons.append("Son mum negatif")

    # Stop / hedef / R:R
    entry = close

    # Pullback setup için stop EMA50 ve ATR ile daha kontrollü
    if setup_type == "PULLBACK":
        stop = min(entry - 1.2 * atr, ema50)
    else:
        stop = entry - 1.5 * atr

    risk = entry - stop
    target = entry + 2 * risk
    rr = (target - entry) / risk if risk > 0 else 0

    # Sinyal sınıflandırma
    if setup_type == "BREAKDOWN" or score <= SAT_ESIK:
        signal = "🔴 SAT / UZAK DUR"
        signal_key = "sat"
        action = "SAT"

    elif score >= COK_GUCLU_AL_ESIK:
        signal = "🔥 ÇOK GÜÇLÜ AL"
        signal_key = "al"
        action = "AL"

    elif score >= GUCLU_AL_ESIK:
        signal = "🟢 GÜÇLÜ AL"
        signal_key = "al"
        action = "AL"

    elif score >= TAKIP_ESIK:
        signal = "🟡 TAKİP"
        signal_key = "takip"
        action = "TAKIP"

    else:
        signal = "⚪ BEKLE"
        signal_key = "none"
        action = "BEKLE"

    # Fake sinyal filtresi
    filter_reason = None

    if signal_key == "al":
        if rsi > MAX_RSI_FOR_AL:
            filter_reason = "RSI çok yüksek"
        elif vol_ratio < MIN_VOL_RATIO_FOR_AL:
            filter_reason = "Hacim zayıf"
        elif rr < MIN_RR_FOR_AL:
            filter_reason = "Risk/ödül zayıf"

        if filter_reason:
            signal = "🟡 TAKİP"
            signal_key = "takip"
            action = "TAKIP"
            reasons.append(f"AL sinyali filtrelendi: {filter_reason}")

    warning = ""
    if rsi >= 80:
        warning = "⚠️ RSI çok yüksek. Kâr satışı / düzeltme riski artmış olabilir."

    return {
        "symbol": symbol,
        "signal": signal,
        "signal_key": signal_key,
        "action": action,
        "setup_type": setup_type,
        "kirillim": kirilim,
        "price": close,
        "score": int(round(score)),
        "rsi": rsi,
        "vol_ratio": vol_ratio,
        "ema20": ema20,
        "ema50": ema50,
        "atr": atr,
        "stop": stop,
        "target": target,
        "rr": rr,
        "reasons": reasons,
        "warning": warning,
        "general": setup_comment(setup_type),
        "action_text": action_comment(action),
    }


def format_signal(result: dict) -> str:
    warning_line = f"\n{result['warning']}\n" if result["warning"] else ""
    reasons_text = ", ".join(result["reasons"][:4])

    return f"""<b>{result['symbol']}</b>

Sinyal: {result['signal']}
Setup: {setup_label(result['setup_type'])}
Kırılım: {result['kirillim']}
Fiyat: {result['price']:.2f}

Skor: {result['score']} ({score_comment(result['score'])})
RSI: {result['rsi']:.1f} ({rsi_comment(result['rsi'])})
Hacim: {result['vol_ratio']:.2f} ({volume_comment(result['vol_ratio'])})

STOP: {result['stop']:.2f}
HEDEF: {result['target']:.2f}
R/R: {result['rr']:.2f} (İyi risk/ödül)
{warning_line}
Öne çıkan nedenler:
{reasons_text}

Genel değerlendirme:
{result['general']}
{result['action_text']}


# =========================
# AÇIK İŞLEM / TRAILING STOP
# =========================

def add_open_trade(result: dict) -> None:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    trades = load_open_trades()

    for trade in trades:
        if trade.get("symbol") == result["symbol"] and trade.get("status") == "open":
            return

    trades.append({
        "symbol": result["symbol"],
        "date": today,
        "entry": round(result["price"], 4),
        "highest_price": round(result["price"], 4),
        "stop": round(result["stop"], 4),
        "target": round(result["target"], 4),
        "trailing_stop": None,
        "score": result["score"],
        "setup_type": result["setup_type"],
        "status": "open"
    })

    save_open_trades(trades)

    perf = load_performance()
    perf.append({
        "symbol": result["symbol"],
        "date": today,
        "entry": round(result["price"], 4),
        "score": result["score"],
        "rsi": round(result["rsi"], 2),
        "vol_ratio": round(result["vol_ratio"], 2),
        "stop": round(result["stop"], 4),
        "target": round(result["target"], 4),
        "setup_type": result["setup_type"],
        "status": "open"
    })
    save_performance(perf)


def update_open_trades() -> list[str]:
    """
    Açık işlemleri günceller.
    Stop, hedef veya trailing stop tetiklenirse kapatır.
    """
    trades = load_open_trades()
    perf = load_performance()
    alerts = []
    changed = False
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    for trade in trades:
        if trade.get("status") != "open":
            continue

        symbol = trade["symbol"]

        try:
            df = yf.download(symbol, period="5d", interval="1h", progress=False, auto_adjust=False)

            if df is None or df.empty:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]

            last_price = float(df["Close"].iloc[-1])
            high_price = float(df["High"].max())
            low_price = float(df["Low"].min())

            entry = float(trade["entry"])
            stop = float(trade["stop"])
            target = float(trade["target"])

            if high_price > float(trade["highest_price"]):
                trade["highest_price"] = round(high_price, 4)
                changed = True

            profit_pct = (last_price - entry) / entry * 100

            if profit_pct >= TRAILING_START_PROFIT:
                trailing_stop = float(trade["highest_price"]) * (1 - TRAILING_STOP_DISTANCE / 100)
                old_trailing = trade.get("trailing_stop")

                if old_trailing is None or trailing_stop > float(old_trailing):
                    trade["trailing_stop"] = round(trailing_stop, 4)
                    changed = True

            close_reason = None
            exit_price = last_price

            if low_price <= stop:
                close_reason = "STOP"
                exit_price = stop
            elif high_price >= target:
                close_reason = "HEDEF"
                exit_price = target
            elif trade.get("trailing_stop") is not None and low_price <= float(trade["trailing_stop"]):
                close_reason = "TRAILING STOP"
                exit_price = float(trade["trailing_stop"])

            if close_reason:
                result_pct = round((exit_price - entry) / entry * 100, 2)
                trade["status"] = "closed"
                trade["exit"] = round(exit_price, 4)
                trade["exit_date"] = today
                trade["result_pct"] = result_pct
                trade["close_reason"] = close_reason
                changed = True

                alerts.append(
                    f"📌 <b>{symbol}</b>\n"
                    f"İşlem kapandı: {close_reason}\n"
                    f"Giriş: {entry:.2f}\n"
                    f"Çıkış: {exit_price:.2f}\n"
                    f"Sonuç: %{result_pct}"
                )

                for p in perf:
                    if p.get("symbol") == symbol and p.get("status") == "open":
                        p["status"] = "closed"
                        p["exit"] = round(exit_price, 4)
                        p["exit_date"] = today
                        p["result_pct"] = result_pct
                        p["close_reason"] = close_reason
                        break

            else:
                trade["last_price"] = round(last_price, 4)
                trade["live_result_pct"] = round(profit_pct, 2)
                changed = True

        except Exception as e:
            trade["error"] = str(e)
            changed = True

    if changed:
        save_open_trades(trades)
        save_performance(perf)

    return alerts


def performance_stats() -> dict:
    data = load_performance()
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    closed_today = [
        t for t in data
        if t.get("status") == "closed" and t.get("exit_date") == today
    ]

    open_trades = [
        t for t in load_open_trades()
        if t.get("status") == "open"
    ]

    if not closed_today:
        return {
            "closed_count": 0,
            "avg": 0,
            "success_rate": 0,
            "best": None,
            "worst": None,
            "open_count": len(open_trades)
        }

    results = [float(t.get("result_pct", 0)) for t in closed_today]
    success = [r for r in results if r > 0]

    best = max(closed_today, key=lambda x: x.get("result_pct", -999))
    worst = min(closed_today, key=lambda x: x.get("result_pct", 999))

    return {
        "closed_count": len(closed_today),
        "avg": round(sum(results) / len(results), 2),
        "success_rate": round(len(success) / len(results) * 100, 1),
        "best": best,
        "worst": worst,
        "open_count": len(open_trades)
    }


def format_performance_summary(stats: dict) -> str:
    if stats["closed_count"] == 0:
        return f"📈 Performans: Bugün kapanan işlem yok.\nAçık işlem: {stats['open_count']}"

    best = stats["best"]
    worst = stats["worst"]

    return f"""📈 <b>PERFORMANS</b>
Kapanan işlem: {stats['closed_count']}
Açık işlem: {stats['open_count']}
Ortalama getiri: %{stats['avg']}
Başarı oranı: %{stats['success_rate']}
En iyi: {best['symbol']} %{best['result_pct']} ({best['close_reason']})
En zayıf: {worst['symbol']} %{worst['result_pct']} ({worst['close_reason']})"""



# =========================
# PORTFÖY MODU
# =========================

def analyze_portfolio() -> tuple[list[str], list[dict]]:
    """
    PORTFOLIO içindeki hisseleri her durumda analiz eder.
    Hisse BIST100 listesinde olmasa bile çalışır.
    Dönüş:
    - Telegram'a gönderilecek portföy analiz mesajları
    - SAT sinyali veren portföy sonuçları
    """
    portfolio_messages = []
    portfolio_sat_results = []

    if not PORTFOLIO:
        return portfolio_messages, portfolio_sat_results

    for item in PORTFOLIO:
        symbol = item.get("symbol")
        entry = float(item.get("entry", 0))

        if not symbol or entry <= 0:
            continue

        try:
            result = analyze_symbol(symbol)

            if not result:
                portfolio_messages.append(
                    f"<b>{symbol}</b>\n\n"
                    f"Durum: Veri alınamadı veya yeterli mum yok.\n"
                    f"Giriş: {entry:.2f}"
                )
                continue

            current = float(result["price"])
            change = (current - entry) / entry * 100

            # Portföy için daha korumacı stop:
            # teknik stop ile EMA20'den düşük olanı alıyoruz.
            smart_stop = min(float(result["stop"]), float(result["ema20"]))

            if result["signal_key"] == "sat":
                status = "🔴 SAT SİNYALİ"
                portfolio_sat_results.append(result)
            elif change >= 5:
                status = "🟢 KÂRDA - Güçlü"
            elif change > 0:
                status = "🟡 KÂRDA"
            elif change > -3:
                status = "⚪ NÖTR"
            else:
                status = "🔻 ZARARDA"

            portfolio_messages.append(f"""<b>{symbol}</b>

Durum: {status}
Giriş/Maliyet: {entry:.2f}
Güncel Fiyat: {current:.2f}
Getiri: %{change:.2f}

Sinyal: {result['signal']}
Setup: {setup_label(result['setup_type'])}
Skor: {result['score']} ({score_comment(result['score'])})
RSI: {result['rsi']:.1f} ({rsi_comment(result['rsi'])})
Hacim: {result['vol_ratio']:.2f} ({volume_comment(result['vol_ratio'])})

Önerilen STOP: {smart_stop:.2f}
Teknik HEDEF: {result['target']:.2f}
R/R: {result['rr']:.2f}

Yorum:
{result['general']}""".strip())

        except Exception as e:
            portfolio_messages.append(
                f"<b>{symbol}</b>\n\n"
                f"Portföy analiz hatası: {str(e)}"
            )

    return portfolio_messages, portfolio_sat_results


def send_urgent_portfolio_warnings(portfolio_sat_results: list[dict]) -> None:
    """
    Portföydeki hisselerden SAT / UZAK DUR sinyali verenleri ayrıca uyarır.
    """
    if not portfolio_sat_results:
        return

    urgent_messages = []

    for result in portfolio_sat_results:
        urgent_messages.append(f"""🚨 <b>PORTFÖY SAT UYARISI</b>

<b>{result['symbol']}</b>
Fiyat: {result['price']:.2f}
Sinyal: {result['signal']}
Setup: {setup_label(result['setup_type'])}
Kırılım: {result['kirillim']}

Skor: {result['score']}
RSI: {result['rsi']:.1f}
Hacim: {result['vol_ratio']:.2f}

Yorum:
{result['general']}""".strip())

    split_and_send("🚨 <b>ACİL PORTFÖY UYARILARI</b>", urgent_messages)



# =========================
# TARAMA
# =========================

def scan_market(mode: str = "intraday") -> None:
    now = datetime.now(TZ)
    state = load_state()

    # Önce açık işlemleri güncelle
    trade_alerts = update_open_trades()
    if trade_alerts:
        split_and_send("📌 <b>AÇIK İŞLEM GÜNCELLEMELERİ</b>", trade_alerts)

    portfolio_messages, portfolio_sat_from_portfolio = analyze_portfolio()

    if portfolio_messages:
        split_and_send("💼 <b>PORTFÖY ANALİZİ</b>", portfolio_messages)

    if portfolio_sat_from_portfolio:
        send_urgent_portfolio_warnings(portfolio_sat_from_portfolio)

    al_results = []
    takip_results = []
    sat_results = []
    portfolio_sat_results = []
    errors = []

    for symbol in BIST_LIST:
        try:
            result = analyze_symbol(symbol)

            if result is None:
                errors.append(symbol)
                continue

            key = result["signal_key"]

            if key == "al":
                add_unique(state, "al", symbol)
                al_results.append(result)
                add_open_trade(result)

            elif key == "takip":
                add_unique(state, "takip", symbol)
                takip_results.append(result)

            elif key == "sat":
                add_unique(state, "sat", symbol)
                sat_results.append(result)

                if symbol in PORTFOLIO_LIST:
                    portfolio_sat_results.append(result)

            time.sleep(0.25)

        except Exception as e:
            errors.append(symbol)
            state["errors"].append(f"{symbol}: {str(e)}")
            print(symbol, e)

    save_state(state)

    al_results = sorted(al_results, key=lambda x: x["score"], reverse=True)[:MAX_AL_SIGNAL]
    takip_results = sorted(takip_results, key=lambda x: x["score"], reverse=True)[:MAX_TAKIP_SIGNAL]
    # BIST taramasından gelen portföy SAT uyarıları + ayrı portföy analizinden gelenleri birleştir.
    seen_portfolio_sat = {r["symbol"] for r in portfolio_sat_results}
    for r in portfolio_sat_from_portfolio:
        if r["symbol"] not in seen_portfolio_sat:
            portfolio_sat_results.append(r)
            seen_portfolio_sat.add(r["symbol"])

    sat_results = sorted(sat_results, key=lambda x: x["score"])[:MAX_SAT_SIGNAL]
    portfolio_sat_results = sorted(portfolio_sat_results, key=lambda x: x["score"])

    if mode == "evening":
        stats = performance_stats()
        send_evening_summary(state, stats, len(errors))
        return

    title = get_title(mode, now)
    summary = f"""{title}

Taranan hisse: {len(BIST_LIST)}
AL sinyali: {len(al_results)}
TAKİP: {len(takip_results)}
SAT / UZAK DUR: {len(sat_results)}
Portföy SAT uyarısı: {len(portfolio_sat_results)}
Hata/atlanan: {len(errors)}

Seviye 3 aktif:
✅ Kırılım
✅ Pullback
✅ Açık işlem takibi
✅ Trailing stop"""
    send_telegram(summary)

    if al_results:
        split_and_send("🟢 <b>EN GÜÇLÜ AL SİNYALLERİ</b>", [format_signal(r) for r in al_results])
    else:
        send_telegram("✅ Tarama tamamlandı. Kaliteli AL sinyali bulunamadı.")

    if takip_results:
        split_and_send("🟡 <b>TAKİP EDİLECEK HİSSELER</b>", [format_signal(r) for r in takip_results])
    else:
        send_telegram("🟡 Takip edilecek hisse bulunamadı.")

    if sat_results:
        split_and_send("🔴 <b>SAT / UZAK DUR SİNYALLERİ</b>", [format_signal(r) for r in sat_results])

    if portfolio_sat_results:
        split_and_send(
            "🚨 <b>PORTFÖYÜNDEKİ SAT UYARILARI</b>",
            [format_signal(r) for r in portfolio_sat_results]
        )


def get_title(mode: str, now: datetime) -> str:
    if mode == "morning":
        return f"🌅 <b>BIST100 SABAH GENEL DEĞERLENDİRME</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"
    if mode == "evening":
        return f"🌙 <b>BIST100 GÜN SONU ÖZETİ</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"
    return f"📊 <b>BIST100 15 DK TARAMA</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"


def send_evening_summary(state: dict, stats: dict, error_count: int = 0) -> None:
    portfolio_sat_symbols = [s for s in state.get("sat", []) if s in PORTFOLIO_LIST]

    text = f"""🌙 <b>BIST100 GÜN SONU GENEL ÖZET - SEVİYE 3</b>

Tarih: {datetime.now(TZ).strftime('%d.%m.%Y')}

🟢 Gün Boyu AL Sinyali Gelenler:
{format_symbol_list(state.get('al', []))}

🟡 Gün Boyu TAKİP Sinyali Gelenler:
{format_symbol_list(state.get('takip', []))}

🔴 Gün Boyu SAT / UZAK DUR Sinyali Gelenler:
{format_symbol_list(state.get('sat', []))}

🚨 Portföyündeki SAT Uyarıları:
{format_symbol_list(portfolio_sat_symbols)}

{format_performance_summary(stats)}

Hata/atlanan: {error_count}

Not:
Bu çalışma teknik tarama amaçlıdır. Tek başına yatırım tavsiyesi değildir.
Stop seviyesi, pozisyon büyüklüğü ve risk yönetimi mutlaka kullanılmalıdır.
"""
    send_telegram(text)


def format_symbol_list(symbols: list[str]) -> str:
    if not symbols:
        return "Yok"
    return "\n".join(f"- {symbol}" for symbol in symbols)


# =========================
# ZAMANLAMA
# =========================

def is_weekday() -> bool:
    return datetime.now(TZ).weekday() < 5


def market_session() -> str:
    """
    GitHub Actions 15 dakikada bir çalışabilir.
    Bot hangi mesajı atacağını saate göre seçer.

    Sabah değerlendirme: 09:30 - 09:45
    Gün içi tarama: 10:00 - 18:00
    Gün sonu özet: 18:10 - 18:30
    """
    now = datetime.now(TZ)
    hour = now.hour
    minute = now.minute

    if not is_weekday():
        return "closed"

    if hour == 9 and 30 <= minute < 45:
        return "morning"

    if 10 <= hour < 18:
        return "intraday"

    if hour == 18 and 10 <= minute < 30:
        return "evening"

    return "closed"


def main() -> None:
    session = market_session()

    if session == "closed":
        now = datetime.now(TZ)
        print(f"Piyasa dışı saat. Çalışma zamanı: {now.strftime('%d.%m.%Y %H:%M')}")
        return

    scan_market(session)


if __name__ == "__main__":
    main()
