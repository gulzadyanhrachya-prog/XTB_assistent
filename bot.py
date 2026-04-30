import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime, timedelta

# --- TAJNÉ KLÍČE Z GITHUB SECRETS ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

try:
    ACCOUNT_BALANCE = float(os.getenv("XTB_BALANCE", 10000.0))
except:
    ACCOUNT_BALANCE = 10000.0

RISK_PCT = 1.5  

TICKERS_TO_SCAN = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "CSCO", "NFLX", 
    "AMD", "INTC", "IBM", "CRM", "BA", "CAT", "CVX", "GS", "HD", "JNJ", "JPM", "KO", 
    "EUR/USD", "GBP/USD", "USD/JPY", "^GSPC", "^IXIC", "BTC-USD", "ETH-USD"
] # Zkráceno pro ukázku, klidně si doplň zbytek

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def check_earnings(ticker):
    """Zjistí, zda firma do 14 dnů vyhlašuje výsledky (Earnings)"""
    if not FINNHUB_KEY or "=" in ticker or "^" in ticker or "/" in ticker:
        return False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        next_week = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={next_week}&symbol={ticker}&token={FINNHUB_KEY}"
        res = requests.get(url).json()
        if "earningsCalendar" in res and len(res["earningsCalendar"]) > 0:
            return True
    except: pass
    return False

def get_data(ticker):
    df = pd.DataFrame()
    # Stahujeme 2 roky dat, abychom mohli spočítat dlouhodobý týdenní trend (MTF)
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker:
        try:
            end = int(time.time())
            start = end - (2 * 365 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"High": res["h"], "Low": res["l"], "Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
        except: pass

    if df.empty:
        try:
            df = yf.Ticker(ticker).history(period="2y")
        except: return None
        
    if not df.empty and len(df) > 50:
        # --- MULTI-TIMEFRAME ANALÝZA (Týdenní trend) ---
        # Převedeme denní data na týdenní a spočítáme SMA 50
        df_weekly = df.resample('W').agg({'Close': 'last'})
        df_weekly['SMA_50_W'] = df_weekly['Close'].rolling(50).mean()
        # Přeneseme týdenní SMA zpět do denního grafu
        df['Weekly_SMA_50'] = df_weekly['SMA_50_W'].reindex(df.index, method='ffill')

        # --- DENNÍ INDIKÁTORY ---
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
        
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
        
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
            weekly_sma = df['Weekly_SMA_50'].iloc[-1]
            
            # 1. MTF FILTR: Je trh v dlouhodobém růstu?
            is_uptrend = current_price > weekly_sma if not pd.isna(weekly_sma) else True
            
            # LOGIKA: RSI < 30 + Jsme v dlouhodobém Uptrendu
            if (rsi < 30 or current_price < bb_low) and is_uptrend:
                
                # 2. FUNDAMENTÁLNÍ FILTR: Nejsou blízko Earnings?
                has_earnings = check_earnings(ticker)
                if has_earnings:
                    print(f"Ignoruji {ticker} - blížící se Earnings!")
                    continue # Přeskočíme tuto akcii
                
                # --- VÝPOČET RISKU A TRAILING STOPU ---
                entry = current_price
                sl = entry - (2 * atr)
                tp = entry + (4 * atr)
                be_level = entry + (1.5 * atr) # Kdy posunout na Break-Even
                
                risk_amount = ACCOUNT_BALANCE * (RISK_PCT / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                
                msg = f"🚨 *OBCHODNÍ PŘÍLEŽITOST: {ticker}* 🚨\n\n"
                msg += f"✅ *MTF Potvrzení:* Dlouhodobý trend je RŮSTOVÝ.\n"
                msg += f"✅ *Fundamenty:* Žádné blížící se Earnings.\n\n"
                msg += f"🤖 *AI Vypočítaný Setup (Risk {RISK_PCT}%):*\n"
                msg += f"• *Vstup (Entry):* {entry:.4f}\n"
                msg += f"• *Stop Loss (SL):* {sl:.4f} _(2x ATR)_\n"
                msg += f"• *Take Profit (TP):* {tp:.4f} _(RRR 1:2)_\n"
                
                if "/" in ticker:
                    msg += f"• *Objem pro XTB:* {volume:.2f} Lotů\n\n"
                else:
                    msg += f"• *Objem pro XTB:* {volume:.2f} Kusů\n\n"
                    
                msg += f"🛡️ *Řízení pozice (Trailing Stop):*\n"
                msg += f"Jakmile cena dosáhne *{be_level:.2f}*, posuň Stop Loss na vstupní cenu ({entry:.2f}), abys chránil kapitál!\n\n"
                msg += f"_(Riskováno {risk_amount:.2f} ze zůstatku {ACCOUNT_BALANCE})_"
                
                opportunities.append(msg)
                
        time.sleep(1.5) 
        
    if opportunities:
        for opp in opportunities:
            send_telegram_message(opp)
            time.sleep(1)
        print(f"Odesláno {len(opportunities)} signálů.")
    else:
        print("Trhy jsou klidné, žádný signál nebyl odeslán.")

if __name__ == "__main__":
    scan_markets()
