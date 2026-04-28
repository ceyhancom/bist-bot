# -*- coding: utf-8 -*-
"""
BIST100 Telegram Tarama Botu - Temiz PRO Sürüm

Özellikler:
- BIST100 teknik tarama
- RSI + EMA + Hacim + Kırılım + ATR + R/R puanlama
- Fake sinyal filtresi
- Sadece en güçlü 10 AL sinyalini gönderme
- Gün içi TAKİP / SAT listesi
- Gün sonu AL / TAKİP / SAT özeti
- Basit performans takibi

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

PERIOD = "60d"
INTERVAL = "1h"

STATE_FILE = Path("gunluk_sinyaller.json")
PERFORMANCE_FILE = Path("performance.json")

MAX_AL_SIGNAL = 10

# Sinyal eşikleri
COK_GUCLU_AL_ESIK = 80
GUCLU_AL_ESIK = 65
TAKIP_ESIK = 50
SAT_ESIK = 35

# Kalite filtreleri
MIN_SCORE_FOR_SIGNAL = 60
MAX_RSI_FOR_AL = 80
MIN_VOL_RATIO_FOR_AL = 1.0
MIN_RR_FOR_AL = 1.5

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
# JSON DOSYA İŞLEMLERİ
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


# =========================
# PERFORMANS TAKİBİ
# =========================

def load_performance() -> list[dict]:
    return read_json(PERFORMANCE_FILE, [])


def save_performance(data: list[dict]) -> None:
    write_json(PERFORMANCE_FILE, data)


def save_trade_signal(result: dict) -> None:
    """
    Aynı hisse aynı gün tekrar AL verdiyse tekrar kaydetmez.
    """
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    data = load_performance()

    for trade in data:
        if trade.get("symbol") == result["symbol"] and trade.get("date") == today:
            return

    data.append({
        "symbol": result["symbol"],
        "date": today,
        "entry": round(result["price"], 4),
        "score": result["score"],
        "rsi": round(result["rsi"], 2),
        "vol_ratio": round(result["vol_ratio"], 2),
        "stop": round(result["stop"], 4),
        "target": round(result["target"], 4),
        "status": "open"
    })

    save_performance(data)


def check_performance() -> dict:
    """
    Açık işlemleri son fiyatla kontrol eder.
    Hedef/stop görülürse kapatır.
    En az 1 gün geçmiş açık kayıtları da güncel fiyattan kapatır.
    """
    data = load_performance()
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    changed = False

    for trade in data:
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
            high_max = float(df["High"].max())
            low_min = float(df["Low"].min())

            entry = float(trade["entry"])
            stop = float(trade["stop"])
            target = float(trade["target"])

            change_pct = (last_price - entry) / entry * 100

            close_reason = None
            close_price = last_price

            if low_min <= stop:
                close_reason = "STOP"
                close_price = stop
            elif high_max >= target:
                close_reason = "HEDEF"
                close_price = target
            elif trade.get("date") != today:
                close_reason = "GÜN SONU KAPANIŞ"
                close_price = last_price

            if close_reason:
                trade["status"] = "closed"
                trade["exit"] = round(close_price, 4)
                trade["exit_date"] = today
                trade["result_pct"] = round((close_price - entry) / entry * 100, 2)
                trade["close_reason"] = close_reason
                changed = True
            else:
                trade["last_price"] = round(last_price, 4)
                trade["live_result_pct"] = round(change_pct, 2)
                changed = True

        except Exception as e:
            trade["performance_error"] = str(e)
            changed = True

    if changed:
        save_performance(data)

    closed_today = [
        t for t in data
        if t.get("status") == "closed" and t.get("exit_date") == today
    ]

    if not closed_today:
        return {
            "count": 0,
            "avg": 0,
            "success_rate": 0,
            "best": None,
            "worst": None
        }

    results = [float(t.get("result_pct", 0)) for t in closed_today]
    success = [r for r in results if r > 0]

    best = max(closed_today, key=lambda x: x.get("result_pct", -999))
    worst = min(closed_today, key=lambda x: x.get("result_pct", 999))

    return {
        "count": len(closed_today),
        "avg": round(sum(results) / len(results), 2),
        "success_rate": round(len(success) / len(results) * 100, 1),
        "best": best,
        "worst": worst
    }


def format_performance_summary(stats: dict) -> str:
    if stats["count"] == 0:
        return "📈 Performans: Bugün kapanan işlem yok."

    best = stats["best"]
    worst = stats["worst"]

    return f"""📈 <b>PERFORMANS</b>
Kapanan işlem: {stats['count']}
Ortalama getiri: %{stats['avg']}
Başarı oranı: %{stats['success_rate']}
En iyi: {best['symbol']} %{best['result_pct']} ({best['close_reason']})
En zayıf: {worst['symbol']} %{worst['result_pct']} ({worst['close_reason']})"""


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

    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI"] = calc_rsi(df["Close"], 14)
    df["ATR"] = calc_atr(df, 14)
    df["VOL_AVG"] = df["Volume"].rolling(20).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG"]
    df["HIGH20_PREV"] = df["High"].rolling(20).max().shift(1)
    df["LOW20_PREV"] = df["Low"].rolling(20).min().shift(1)

    return df


# =========================
# YORUM FONKSİYONLARI
# =========================

def rsi_comment(rsi: float) -> str:
    if rsi >= 80:
        return "Aşırı alım, dikkat"
    if rsi >= 70:
        return "Güçlü ama düzeltme riski var"
    if rsi >= 55:
        return "Sağlıklı pozitif momentum"
    if rsi >= 45:
        return "Kararsız / nötr"
    if rsi >= 30:
        return "Zayıf momentum"
    return "Aşırı satım, tepki gelebilir"


def volume_comment(vol_ratio: float) -> str:
    if vol_ratio >= 2:
        return "Çok yüksek hacim"
    if vol_ratio >= 1.5:
        return "Güçlü hacim"
    if vol_ratio >= 1.2:
        return "Hacim destekli"
    if vol_ratio >= 1:
        return "Normal hacim"
    return "Zayıf hacim"


def score_comment(score: int) -> str:
    if score >= 80:
        return "Çok güçlü"
    if score >= 65:
        return "Güçlü"
    if score >= 50:
        return "Takip"
    if score >= 35:
        return "Zayıf"
    return "Negatif"


def create_general_comment(score, rsi, vol_ratio, breakout_up, breakdown_down, ema20, ema50) -> str:
    if breakdown_down:
        return "Destek kırılımı var. Risk yükselmiş durumda."

    if score >= 80 and breakout_up and vol_ratio >= 1.2:
        return "Trend, hacim ve kırılım aynı yönde. Sinyal güçlü; stop seviyesi takip edilmeli."

    if score >= 65:
        return "Teknik görünüm pozitif. Hacim ve RSI destekliyorsa yükseliş devam edebilir."

    if score >= 50:
        return "Takip edilebilir. Net alım için hacim veya kırılım teyidi beklenebilir."

    if ema20 < ema50:
        return "Trend zayıf. EMA20'nin EMA50 üzerine çıkması beklenebilir."

    return "Sinyal zayıf. Daha net teknik teyit beklemek daha sağlıklı olur."


# =========================
# HİSSE ANALİZİ
# =========================

def analyze_symbol(symbol: str) -> dict | None:
    df = yf.download(symbol, period=PERIOD, interval=INTERVAL, progress=False, auto_adjust=False)

    if df is None or df.empty or len(df) < 55:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = prepare_indicators(df).dropna()

    if len(df) < 3:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = float(last["Close"])
    prev_close = float(prev["Close"])
    ema20 = float(last["EMA20"])
    ema50 = float(last["EMA50"])
    rsi = float(last["RSI"])
    atr = float(last["ATR"])
    vol_ratio = float(last["VOL_RATIO"])
    high20_prev = float(last["HIGH20_PREV"])
    low20_prev = float(last["LOW20_PREV"])

    score = 0
    reasons = []

    # Trend
    if ema20 > ema50:
        score += 30
        reasons.append("EMA20 > EMA50")
    else:
        score -= 10
        reasons.append("EMA20 < EMA50")

    # RSI
    if 50 < rsi <= 65:
        score += 25
        reasons.append("RSI sağlıklı yükselişte")
    elif 65 < rsi <= 75:
        score += 20
        reasons.append("RSI güçlü")
    elif 75 < rsi <= 85:
        score += 10
        reasons.append("RSI yüksek")
    elif 40 < rsi <= 50:
        score += 5
        reasons.append("RSI toparlanıyor")
    elif rsi <= 35:
        score -= 10
        reasons.append("RSI zayıf")

    # Hacim
    if vol_ratio >= 1.5:
        score += 25
        reasons.append("Hacim çok güçlü")
    elif vol_ratio >= 1.2:
        score += 15
        reasons.append("Hacim destekli")
    elif vol_ratio >= 1.0:
        score += 5
        reasons.append("Hacim normal")
    else:
        score -= 10
        reasons.append("Hacim zayıf")

    # Kırılım
    breakout_up = close > high20_prev
    breakdown_down = close < low20_prev

    if breakout_up:
        score += 20
        kirilim = "📈 Yukarı trend / direnç kırılımı"
        reasons.append("20 periyot direnç kırılımı")
    elif breakdown_down:
        score -= 20
        kirilim = "📉 Aşağı destek kırılımı"
        reasons.append("20 periyot destek kırılımı")
    else:
        kirilim = "➖ Net kırılım yok"

    # Momentum
    if close > prev_close:
        score += 5
        reasons.append("Son mum pozitif")
    else:
        score -= 5
        reasons.append("Son mum negatif")

    # Stop / hedef / R:R
    entry = close
    stop = entry - 1.5 * atr
    risk = entry - stop
    target = entry + 2 * risk
    rr = (target - entry) / risk if risk > 0 else 0

    # Ana sinyal
    if score >= COK_GUCLU_AL_ESIK:
        signal = "🔥 ÇOK GÜÇLÜ AL"
        signal_key = "al"
    elif score >= GUCLU_AL_ESIK:
        signal = "🟢 GÜÇLÜ AL"
        signal_key = "al"
    elif score >= TAKIP_ESIK:
        signal = "🟡 TAKİP"
        signal_key = "takip"
    elif score <= SAT_ESIK or breakdown_down:
        signal = "🔴 SAT / UZAK DUR"
        signal_key = "sat"
    else:
        signal = "⚪ ZAYIF"
        signal_key = "none"

    # Fake sinyal / kalite filtresi
    filter_reason = None

    if signal_key == "al":
        if rsi > MAX_RSI_FOR_AL:
            filter_reason = "RSI çok yüksek"
        elif vol_ratio < MIN_VOL_RATIO_FOR_AL:
            filter_reason = "Hacim zayıf"
        elif rr < MIN_RR_FOR_AL:
            filter_reason = "Risk/ödül zayıf"
        elif score < MIN_SCORE_FOR_SIGNAL:
            filter_reason = "Skor düşük"

        if filter_reason:
            signal = "🟡 TAKİP"
            signal_key = "takip"
            reasons.append(f"AL sinyali filtrelendi: {filter_reason}")

    warning = ""
    if rsi >= 80:
        warning = "⚠️ RSI çok yüksek. Kâr satışı / düzeltme riski artmış olabilir."

    general = create_general_comment(score, rsi, vol_ratio, breakout_up, breakdown_down, ema20, ema50)

    return {
        "symbol": symbol,
        "signal": signal,
        "signal_key": signal_key,
        "kirillim": kirilim,
        "price": close,
        "score": int(round(score)),
        "rsi": rsi,
        "vol_ratio": vol_ratio,
        "stop": stop,
        "target": target,
        "rr": rr,
        "reasons": reasons,
        "warning": warning,
        "general": general
    }


def format_signal(result: dict) -> str:
    warning_line = f"\n{result['warning']}\n" if result["warning"] else ""

    return f"""<b>{result['symbol']}</b>

Sinyal: {result['signal']}
Kırılım: {result['kirillim']}
Fiyat: {result['price']:.2f}

Skor: {result['score']} ({score_comment(result['score'])})
RSI: {result['rsi']:.1f} ({rsi_comment(result['rsi'])})
Hacim: {result['vol_ratio']:.2f} ({volume_comment(result['vol_ratio'])})

STOP: {result['stop']:.2f}
HEDEF: {result['target']:.2f}
R/R: {result['rr']:.2f} (İyi risk/ödül)
{warning_line}
Genel değerlendirme:
{result['general']}""".strip()


# =========================
# TARAMA
# =========================

def scan_market(mode: str = "intraday") -> None:
    now = datetime.now(TZ)
    state = load_state()

    al_results = []
    takip_results = []
    sat_results = []
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
                save_trade_signal(result)

            elif key == "takip":
                add_unique(state, "takip", symbol)
                takip_results.append(result)

            elif key == "sat":
                add_unique(state, "sat", symbol)
                sat_results.append(result)

            time.sleep(0.25)

        except Exception as e:
            errors.append(symbol)
            state["errors"].append(f"{symbol}: {str(e)}")
            print(symbol, e)

    save_state(state)

    al_results = sorted(al_results, key=lambda x: x["score"], reverse=True)[:MAX_AL_SIGNAL]
    takip_results = sorted(takip_results, key=lambda x: x["score"], reverse=True)[:10]
    sat_results = sorted(sat_results, key=lambda x: x["score"])[:10]

    if mode == "evening":
        stats = check_performance()
        send_evening_summary(state, stats, len(errors))
        return

    title = get_title(mode, now)

    summary = f"""{title}

Taranan hisse: {len(BIST_LIST)}
AL sinyali: {len(al_results)}
TAKİP: {len(takip_results)}
SAT / UZAK DUR: {len(sat_results)}
Hata/atlanan: {len(errors)}

Not: AL tarafında yalnızca en güçlü {MAX_AL_SIGNAL} sinyal gönderilir."""
    send_telegram(summary)

    if al_results:
        split_and_send("🟢 <b>EN GÜÇLÜ AL SİNYALLERİ</b>", [format_signal(r) for r in al_results])
    else:
        send_telegram("✅ Tarama tamamlandı. Kaliteli AL sinyali bulunamadı.")

    if mode == "morning" and takip_results:
        split_and_send("🟡 <b>TAKİP LİSTESİ</b>", [format_signal(r) for r in takip_results])

    if mode == "morning" and sat_results:
        split_and_send("🔴 <b>RİSKLİ / UZAK DUR LİSTESİ</b>", [format_signal(r) for r in sat_results])


def get_title(mode: str, now: datetime) -> str:
    if mode == "morning":
        return f"🌅 <b>BIST100 SABAH GENEL DEĞERLENDİRME</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"
    if mode == "evening":
        return f"🌙 <b>BIST100 GÜN SONU ÖZETİ</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"
    return f"📊 <b>BIST100 15 DK TARAMA</b>\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"


def send_evening_summary(state: dict, stats: dict, error_count: int = 0) -> None:
    text = f"""🌙 <b>BIST100 GÜN SONU GENEL ÖZET</b>

Tarih: {datetime.now(TZ).strftime('%d.%m.%Y')}

🟢 Gün Boyu AL Sinyali Gelenler:
{format_symbol_list(state.get('al', []))}

🟡 Gün Boyu TAKİP Sinyali Gelenler:
{format_symbol_list(state.get('takip', []))}

🔴 Gün Boyu SAT / UZAK DUR Sinyali Gelenler:
{format_symbol_list(state.get('sat', []))}

{format_performance_summary(stats)}

Hata/atlanan: {error_count}

Not:
Bu çalışma teknik tarama amaçlıdır. Tek başına yatırım tavsiyesi değildir.
Stop seviyesi ve risk yönetimi mutlaka kullanılmalıdır.
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
