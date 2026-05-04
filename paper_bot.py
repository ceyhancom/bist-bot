```python
import yfinance as yf
import pandas as pd
import time
import datetime
import requests

# ====== AYARLAR ======
START_CASH = 100000
POSITION_SIZE = 0.20
MAX_POSITIONS = 3

TAKE_PROFIT = 0.04
STOP_LOSS = 0.025

SCAN_INTERVAL = 900  # 15 dk

COMMISSION_RATE = 0.001945
BSMV_RATE = 0.05

TELEGRAM_TOKEN = "8430571544:AAEB9MsGZM7BSQSfglCO95by74a6YlIuzJo"
TELEGRAM_CHAT_ID = "7915786971"

BIST100 = ["THYAO.IS", "ASELS.IS", "SISE.IS", "EREGL.IS", "KCHOL.IS"]

portfolio = {
    "cash": START_CASH,
    "positions": [],
    "trades": []
}

closed_today = False
reported_today = False

# ====== TELEGRAM ======
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

# TEST (BURAYA KOY)
send_telegram("✅ PAPER BOT TEST MESAJI")

# ====== VERİ ======
def get_data(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="15m", progress=False)
        return df
    except:
        return pd.DataFrame()

# ====== SİNYAL ======
def check_signal(df):
    if df is None or len(df) < 50:
        return False
    
    df["ema20"] = df["Close"].ewm(span=20).mean()
    df["ema50"] = df["Close"].ewm(span=50).mean()
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    trend = last["ema20"] > last["ema50"]
    breakout = last["Close"] > prev["High"]
    volume = last["Volume"] > df["Volume"].rolling(20).mean().iloc[-1]
    
    return trend and breakout and volume

# ====== AL ======
def buy(symbol, price):
    if len(portfolio["positions"]) >= MAX_POSITIONS:
        return
    
    # Aynı hisseden tekrar alma
    for p in portfolio["positions"]:
        if p["symbol"] == symbol:
            return
    
    budget = portfolio["cash"] * POSITION_SIZE
    qty = int(budget / price)
    
    if qty <= 0:
        return
    
    trade_value = price * qty
    
    commission = trade_value * COMMISSION_RATE
    bsmv = commission * BSMV_RATE
    
    total_cost = trade_value + commission + bsmv
    
    if portfolio["cash"] < total_cost:
        return
    
    portfolio["cash"] -= total_cost
    
    position = {
        "symbol": symbol,
        "qty": qty,
        "buy_price": price,
        "target": price * (1 + TAKE_PROFIT),
        "stop": price * (1 - STOP_LOSS),
        "cost": total_cost
    }
    
    portfolio["positions"].append(position)
    
    msg = f"🟢 ALINDI\n{symbol}\nAdet: {qty}\nFiyat: {price:.2f}"
    send_telegram(msg)
    print(msg)

# ====== SAT ======
def sell(position, price):
    trade_value = price * position["qty"]
    
    commission = trade_value * COMMISSION_RATE
    bsmv = commission * BSMV_RATE
    
    net = trade_value - commission - bsmv
    profit = net - position["cost"]
    
    portfolio["cash"] += net
    portfolio["trades"].append(profit)
    
    msg = f"🔴 SATILDI\n{position['symbol']}\nFiyat: {price:.2f}\nKar/Zarar: {profit:.2f} TL"
    send_telegram(msg)
    print(msg)
    
    portfolio["positions"].remove(position)

# ====== POZİSYON KONTROL ======
def check_positions():
    for position in portfolio["positions"][:]:
        df = get_data(position["symbol"])
        if df.empty:
            continue
        
        price = df["Close"].iloc[-1]
        
        if price >= position["target"]:
            sell(position, price)
        
        elif price <= position["stop"]:
            sell(position, price)

# ====== TÜMÜNÜ KAPAT ======
def close_all_positions():
    for position in portfolio["positions"][:]:
        df = get_data(position["symbol"])
        if df.empty:
            continue
        
        price = df["Close"].iloc[-1]
        sell(position, price)
    
    send_telegram("⏰ Gün sonu tüm pozisyonlar kapatıldı")

# ====== RAPOR ======
def end_of_day():
    total_profit = sum(portfolio["trades"])
    
    wins = len([p for p in portfolio["trades"] if p > 0])
    losses = len([p for p in portfolio["trades"] if p <= 0])
    
    total_trades = len(portfolio["trades"])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    report = f"""
📊 GÜNLÜK RAPOR

Başlangıç: {START_CASH:.2f} TL
Bitiş: {portfolio['cash']:.2f} TL

Toplam İşlem: {total_trades}
Kazanan: {wins}
Kaybeden: {losses}

Net Kar/Zarar: {total_profit:.2f} TL
Başarı Oranı: %{win_rate:.1f}
"""
    
    send_telegram(report)
    print(report)

# ====== ANA LOOP ======
send_telegram("🚀 Paper Trade Bot Başladı")

while True:
    now = datetime.datetime.now()
    
    # 17:55 → pozisyonları kapat (1 kere)
    if now.hour == 17 and now.minute >= 55 and not closed_today:
        close_all_positions()
        closed_today = True
    
    # 18:15 → rapor gönder (1 kere)
    if now.hour == 18 and now.minute >= 15 and not reported_today:
        end_of_day()
        reported_today = True
        break
    
    # NORMAL ÇALIŞMA
    if now.hour >= 10 and now.hour < 18:
        for symbol in BIST100:
            df = get_data(symbol)
            if df.empty:
                continue
            
            if check_signal(df):
                price = df["Close"].iloc[-1]
                buy(symbol, price)
        
        check_positions()
    
    time.sleep(SCAN_INTERVAL)
```
