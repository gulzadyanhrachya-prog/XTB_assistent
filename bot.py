import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime

# --- TAJNÉ KLÍČE Z GITHUB SECRETS ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

# --- NASTAVENÍ ÚČTU A RISKU ---
# Bot si načte tvůj zůstatek z GitHub Secrets (pokud tam není, použije 10000 jako zálohu)
try:
    ACCOUNT_BALANCE = float(os.getenv("XTB_BALANCE", 10000.0))
except:
    ACCOUNT_BALANCE = 10000.0

RISK_PCT = 1.5  # Bot bude riskovat přesně 1.5 % tvého účtu na každý obchod

# --- MEGA-SEZNAM INSTRUMENTŮ PRO XTB ---
# Tento seznam obsahuje přes 80 nejlepších trhů (Akcie, Forex, Indexy, Krypto)
TICKERS_TO_SCAN = [
    # Top US Tech & Blue Chips
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "CSCO", "NFLX", 
    "AMD", "INTC", "IBM", "CRM", "BA", "CAT", "CVX", "GS", "HD", "JNJ", "JPM", "KO", 
    "MCD", "MMM", "NKE", "PG", "UNH", "V", "WMT", "DIS",
    # Top EU Akcie (Yahoo formát)
    "ASML", "SAP", "NVO", "TMUS", "SNY", "MC.PA", "OR.PA", "RMS.PA",
    # Hlavní Forex Páry (TwelveData/Yahoo formát)
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD", 
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "CHF/JPY", "EUR/AUD", "EUR/CHF", "AUD/JPY",
    # Indexy (Yahoo formát)
    "^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^FTSE", "^N225",
    # Krypto (Yahoo formát)
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD"
]

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_data(ticker):
    df = pd.DataFrame()
    
    # 1. Pokus přes Finnhub (US Akcie)
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker:
        try:
            end = int(time.time())
            start = end - (6 * 30 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"High": res["h"], "Low": res["l"], "Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
        except: pass

    # 2. Pokus přes Twelve Data (Forex)
    if df.empty and TWELVE_KEY and "/" in ticker:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize=130&apikey={TWELVE_KEY}"
            res = requests.get(url).json()
            if "values" in res:
                df_td = pd.DataFrame(res["values"])
                df_td['datetime'] = pd.to_datetime(df_td['datetime'])
                df_td = df_td.set_index('datetime').astype(float)
                df_td = df_td.rename(columns={"high": "High", "low": "Low", "close": "Close"})
                df = df_td.sort_index()
        except: pass

    # 3. Záloha přes Yahoo Finance
    if df.empty:
        try:
            df = yf.Ticker(ticker).history(period="6mo")
        except: return None
        
    if not df.empty and len(df) > 20:
        # --- VÝPOČET INDIKÁTORŮ ---
        # RSI
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        # Bollinger Bands
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
        
        # ATR (Average True Range) - Pro automatický výpočet Stop Lossu
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['ATR'] = true_range.rolling(14).mean()
        
        return df
    return None

def scan_markets():
    opportunities = []
    print(f"Začínám skenovat {len(TICKERS_TO_SCAN)} instrumentů...")
    
    for ticker in TICKERS_TO_SCAN:
        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns and 'ATR' in df.columns:
            current_price = df['Close'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            bb_low = df['BB_Low'].iloc[-1]
            atr = df['ATR'].iloc[-1]
            
            # LOGIKA: Kdy má bot poslat signál? (RSI pod 30 = extrémní sleva)
            if rsi < 50 or current_price < bb_low:
                
                # --- AUTOMATICKÝ VÝPOČET RISKU A POZICE ---
                entry = current_price
                
                # Stop Loss nastavíme 2x ATR pod vstupní cenu (chrání před běžným šumem trhu)
                sl = entry - (2 * atr)
                
                # Take Profit nastavíme 4x ATR nad vstupní cenu (RRR 1:2)
                tp = entry + (4 * atr)
                
                # Výpočet objemu (Kolik kusů/lotů koupit)
                risk_amount = ACCOUNT_BALANCE * (RISK_PCT / 100)
                risk_per_share = abs(entry - sl)
                
                if risk_per_share > 0:
                    volume = risk_amount / risk_per_share
                else:
                    volume = 0
                
                # Formátování zprávy
                msg = f"🚨 *OBCHODNÍ PŘÍLEŽITOST: {ticker}* 🚨\n\n"
                msg += f"Trh je extrémně přeprodaný (RSI: {rsi:.1f})!\n\n"
                msg += f"🤖 *AI Vypočítaný Setup (Risk {RISK_PCT}%):*\n"
                msg += f"• *Vstup (Entry):* {entry:.4f}\n"
                msg += f"• *Stop Loss (SL):* {sl:.4f} _(dle ATR)_\n"
                msg += f"• *Take Profit (TP):* {tp:.4f} _(RRR 1:2)_\n"
                
                if "/" in ticker:
                    msg += f"• *Objem pro XTB:* {volume:.2f} Lotů *(Zkontroluj hodnotu bodu!)*\n\n"
                else:
                    msg += f"• *Objem pro XTB:* {volume:.2f} Kusů\n\n"
                    
                msg += f"_(Riskováno {risk_amount:.2f} ze zůstatku {ACCOUNT_BALANCE})_"
                
                opportunities.append(msg)
                
        # Bezpečnostní pauza 1.5 vteřiny, aby nás API nezablokovalo za spamování
        time.sleep(1.5) 
        
    if opportunities:
        for opp in opportunities:
            send_telegram_message(opp)
            time.sleep(1) # Pauza mezi odesíláním zpráv na Telegram
        print(f"Odesláno {len(opportunities)} signálů na Telegram.")
    else:
        print("Trhy jsou klidné, žádný signál nebyl odeslán.")

if __name__ == "__main__":
    scan_markets()
