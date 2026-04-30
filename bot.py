import yfinance as yf
import pandas as pd
import requests
import time
import os
from datetime import datetime

# --- NASTAVENÍ TVÉHO ÚČTU PRO VÝPOČET OBJEMU ---
ACCOUNT_BALANCE = 10000.0  # Zůstatek na účtu
RISK_PCT = 2.0             # Risk na jeden obchod v %
TICKERS_TO_SCAN = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN", "GOOGL", "META"] # Co má bot hlídat

# --- TAJNÉ KLÍČE Z GITHUB SECRETS ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_data(ticker):
    # Zjednodušené stahování dat přes Finnhub (nebo YFinance jako záloha)
    df = pd.DataFrame()
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker:
        try:
            end = int(time.time())
            start = end - (6 * 30 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
        except: pass
        
    if df.empty:
        try:
            df = yf.Ticker(ticker).history(period="6mo")
        except: return None
        
    if not df.empty:
        # Výpočet RSI a Bollinger Bands
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
        return df
    return None

def scan_markets():
    opportunities = []
    for ticker in TICKERS_TO_SCAN:
        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns:
            current_price = df['Close'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            bb_low = df['BB_Low'].iloc[-1]
            
            # LOGIKA: Kdy má bot poslat signál? (Např. RSI pod 30 nebo cena pod BB_Low)
            if rsi < 100 or current_price < bb_low:
                # Výpočet parametrů obchodu
                entry = current_price
                sl = entry * 0.95  # Stop Loss 5% pod vstupem
                tp = entry * 1.10  # Take Profit 10% nad vstupem
                
                risk_amount = ACCOUNT_BALANCE * (RISK_PCT / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                
                msg = f"🚨 *OBCHODNÍ PŘÍLEŽITOST: {ticker}* 🚨\n\n"
                msg += f"Trh je extrémně přeprodaný (RSI: {rsi:.1f}) a nabízí slevu!\n\n"
                msg += f"📊 *Parametry pro XTB:*\n"
                msg += f"• *Vstup (Entry):* {entry:.2f}\n"
                msg += f"• *Stop Loss (SL):* {sl:.2f}\n"
                msg += f"• *Take Profit (TP):* {tp:.2f}\n"
                msg += f"• *Doporučený objem:* {volume:.2f} kusů\n\n"
                msg += f"_(Riskováno {risk_amount:.2f} z účtu {ACCOUNT_BALANCE})_"
                
                opportunities.append(msg)
        time.sleep(1) # Pauza proti zablokování
        
    if opportunities:
        for opp in opportunities:
            send_telegram_message(opp)
    else:
        print("Trhy jsou klidné, žádný signál nebyl odeslán.")

if __name__ == "__main__":
    scan_markets()
