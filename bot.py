# -*- coding: utf-8 -*-
"""
BIST100 Telegram Tarama Botu
- Sabah genel değerlendirme
- Gün içi AL / TAKİP / SAT takip taraması
- Gün sonu özet
- RSI + EMA + Hacim + Kırılım + ATR + R/R

Gerekli GitHub Secrets / Ortam Değişkenleri:
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
# AYARLAR
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TZ = pytz.timezone("Europe/Istanbul")

PERIOD = "60d"
INTERVAL = "1h"

STATE_FILE = Path("gunluk_sinyaller.json")

# Sinyal eşikleri
AL_ESIK = 65
COK_GUCLU_AL_ESIK = 80
TAKIP_ESIK = 50
SAT_ESIK = 35

# Risk / ödül filtresi
MIN_RR = 1.5

# Hacim filtresi
MIN_VOL_RATIO_FOR_AL = 1.0

# BIST100 listesi zamanla değişebilir. Gerekirse sadece bu listeyi güncelle.
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
        r = requests.post(url, data=payload, timeout=20)
        if r.status_code != 200:
            print("Telegram hata:", r.status_code, r.text)
    except Exception as e:
        print("Telegram gönderim hatası:", e)


def split_and_send(title: str, lines: list[str], max_chars: int = 3500) -> None:
    if not lines:
        send_telegram(title)
        return

    msg = title + "\n\n"
    for line in lines:
        if len(msg) + len(line) + 2 > max_chars:
            send_telegram(msg)
            msg = ""
        msg += line + "\n\n"

    if msg.strip():
        send_telegram(msg.strip())


# =========================
# GÜNLÜK HAFIZA
# =========================

def load_state() -> dict:
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    if data.get("date") != today:
        data = {
            "date": today,
            "al": [],
            "takip": [],
            "sat": [],
            "errors": []
        }

    return data


def save_state(data: dict) -> None:
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_unique(state: dict, key: str, symbol: str) -> None:
    if symbol not in state[key]:
        state[key].append(symbol)


# =========================
# GÖSTERGELER
# =========================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


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
# ANALİZ
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
        reasons.append("EMA20 > EMA50, trend pozitif")
    else:
        score -= 10
        reasons.append("EMA20 < EMA50, trend zayıf")

    # RSI
    if 50 < rsi <= 65:
        score += 25
        reasons.append("RSI sağlıklı yükseliş bölgesinde")
    elif 65 < rsi <= 75:
        score += 20
        reasons.append("RSI güçlü ama dikkat bölgesinde")
    elif 75 < rsi <= 85:
        score += 10
        reasons.append("RSI aşırı alım bölgesine yakın")
    elif 40 < rsi <= 50:
        score += 5
        reasons.append("RSI toparlanma denemesinde")
    elif rsi <= 35:
        score -= 10
        reasons.append("RSI zayıf / aşırı satıma yakın")

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
        reasons.append("20 periyotluk direnç yukarı kırıldı")
    elif breakdown_down:
        score -= 20
        kirilim = "📉 Aşağı destek kırılımı"
        reasons.append("20 periyotluk destek aşağı kırıldı")
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

    # Sinyal sınıflandırma
    if score >= COK_GUCLU_AL_ESIK and rr >= MIN_RR and vol_ratio >= MIN_VOL_RATIO_FOR_AL:
        signal = "🔥 ÇOK GÜÇLÜ AL"
        signal_key = "al"
    elif score >= AL_ESIK and rr >= MIN_RR and vol_ratio >= MIN_VOL_RATIO_FOR_AL:
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

    # RSI çok aşırıysa uyarı ekle
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


def create_general_comment(score, rsi, vol_ratio, breakout_up, breakdown_down, ema20, ema50) -> str:
    if breakdown_down:
        return "Destek kırılımı görüldüğü için risk artmış durumda. Yeni alım için acele edilmemeli."

    if score >= 80 and breakout_up and vol_ratio >= 1.2:
        return "Trend, hacim ve kırılım aynı yönde. Sinyal güçlü; yine de stop seviyesi takip edilmeli."

    if score >= 65:
        return "Teknik görünüm pozitif. Hacim ve RSI destekliyorsa yükseliş devam edebilir."

    if score >= 50:
        return "Hisse takip listesine alınabilir. Net alım için hacim veya kırılım teyidi beklenebilir."

    if ema20 < ema50:
        return "Trend zayıf. Güçlü alım için EMA20'nin EMA50 üzerine çıkması daha sağlıklı olur."

    return "Sinyal zayıf. Daha net bir teknik teyit beklemek daha güvenli olur."


def format_signal(result: dict) -> str:
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

{result['warning']}

Genel değerlendirme:
{result['general']}""".strip()


# =========================
# TARAMA MODLARI
# =========================

def scan_market(mode: str = "intraday") -> None:
    now = datetime.now(TZ)
    state = load_state()

    title_map = {
        "morning": f"🌅 BIST100 SABAH GENEL DEĞERLENDİRME\nSaat: {now.strftime('%d.%m.%Y %H:%M')}",
        "intraday": f"📊 BIST100 15 DK TARAMA\nSaat: {now.strftime('%d.%m.%Y %H:%M')}",
        "evening": f"🌙 BIST100 GÜN SONU ÖZETİ\nSaat: {now.strftime('%d.%m.%Y %H:%M')}"
    }

    al_lines = []
    takip_lines = []
    sat_lines = []
    errors = []

    for i, symbol in enumerate(BIST_LIST, start=1):
        try:
            result = analyze_symbol(symbol)

            if result is None:
                errors.append(symbol)
                continue

            key = result["signal_key"]

            if key == "al":
                add_unique(state, "al", symbol)
                al_lines.append(format_signal(result))
            elif key == "takip":
                add_unique(state, "takip", symbol)
                takip_lines.append(format_signal(result))
            elif key == "sat":
                add_unique(state, "sat", symbol)
                sat_lines.append(format_signal(result))

            time.sleep(0.25)

        except Exception as e:
            errors.append(symbol)
            state["errors"].append(f"{symbol}: {str(e)}")
            print(symbol, e)

    save_state(state)

    if mode == "evening":
        send_evening_summary(state, len(errors))
        return

    header = title_map.get(mode, "📊 BIST100 TARAMA")
    short_summary = (
        f"{header}\n\n"
        f"Taranan hisse: {len(BIST_LIST)}\n"
        f"AL sinyali: {len(al_lines)}\n"
        f"TAKİP: {len(takip_lines)}\n"
        f"SAT / UZAK DUR: {len(sat_lines)}\n"
        f"Hata/atlanan: {len(errors)}"
    )
    send_telegram(short_summary)

    if al_lines:
        split_and_send("🟢 AL Sinyalleri", al_lines)
    else:
        send_telegram("✅ Tarama tamamlandı. Uygun AL sinyali bulunamadı.")

    if takip_lines and mode == "morning":
        split_and_send("🟡 Takip Listesi", takip_lines[:10])

    if sat_lines and mode == "morning":
        split_and_send("🔴 Riskli / Uzak Dur Listesi", sat_lines[:10])


def send_evening_summary(state: dict, error_count: int = 0) -> None:
    text = f"""🌙 <b>BIST100 GÜN SONU GENEL ÖZET</b>

Tarih: {datetime.now(TZ).strftime('%d.%m.%Y')}

🟢 Gün Boyu AL Sinyali Gelenler:
{format_symbol_list(state.get('al', []))}

🟡 Gün Boyu TAKİP Sinyali Gelenler:
{format_symbol_list(state.get('takip', []))}

🔴 Gün Boyu SAT / UZAK DUR Sinyali Gelenler:
{format_symbol_list(state.get('sat', []))}

Hata/atlanan: {error_count}

Not:
Bu çalışma teknik tarama amaçlıdır. Tek başına yatırım tavsiyesi değildir.
Stop seviyesi ve risk yönetimi mutlaka kullanılmalıdır.
"""
    send_telegram(text)


def format_symbol_list(symbols: list[str]) -> str:
    if not symbols:
        return "Yok"
    return "\n".join(f"- {s}" for s in symbols)


# =========================
# ZAMAN KONTROLÜ
# =========================

def is_weekday() -> bool:
    return datetime.now(TZ).weekday() < 5


def market_session() -> str:
    """
    GitHub Actions her 15 dakikada bir çalıştırılabilir.
    Bot bu saate göre hangi raporu atacağını kendi belirler.

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
