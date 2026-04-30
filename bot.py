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

try:
    ACCOUNT_BALANCE = float(os.getenv("XTB_BALANCE", 10000.0))
except:
    ACCOUNT_BALANCE = 10000.0

RISK_PCT = 1.5  

# --- MEGA-SEZNAM NEJLEPŠÍCH TRHŮ ---
TICKERS_TO_SCAN = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "CSCO", "NFLX", 
    "AMD", "INTC", "IBM", "CRM", "BA", "CAT", "CVX", "GS", "HD", "JNJ", "JPM", "KO", 
    "MCD", "MMM", "NKE", "PG", "UNH", "V", "WMT", "DIS",
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD", 
    "^GSPC", "^IXIC", "^DJI", "BTC-USD", "ETH-USD", "SOL-USD"
]

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_data(ticker):
    df = pd.DataFrame()
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker:
        try:
            end = int(time.time())
            start = end - (2 * 365 * 24 * 60 * 60) # 2 roky historie pro AI učení
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"High": res["h"], "Low": res["l"], "Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
        except: pass

    if df.empty and TWELVE_KEY and "/" in ticker:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize=500&apikey={TWELVE_KEY}"
            res = requests.get(url).json()
            if "values" in res:
                df_td = pd.DataFrame(res["values"])
                df_td['datetime'] = pd.to_datetime(df_td['datetime'])
                df_td = df_td.set_index('datetime').astype(float)
                df_td = df_td.rename(columns={"high": "High", "low": "Low", "close": "Close"})
                df = df_td.sort_index()
        except: pass

    if df.empty:
        try:
            df = yf.Ticker(ticker).history(period="2y")
        except: return None
        
    if not df.empty and len(df) > 50:
        # Indikátory
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

def optimize_strategy(df):
    """
    AI MOZEK: Bleskově otestuje 18 různých strategií na historii daného trhu
    a vybere tu, která má největší zisk a Win Rate.
    """
    best_profit = -9999
    best_params = None
    
    # Převedeme data do slovníku pro extrémně rychlý výpočet (zlomek vteřiny)
    records = df[['High', 'Low', 'Close', 'RSI', 'BB_Low', 'ATR']].to_dict('records')
    
    # Testujeme různé kombinace RSI, Stop Lossu a Take Profitu
    for rsi_val in [30, 35, 40]:
        for sl_val in [1.5, 2.0, 3.0]:
            for tp_val in [3.0, 4.0, 5.0]:
                trades = 0
                wins = 0
                profit = 0
                in_trade = False
                entry = 0; sl = 0; tp = 0
                
                for row in records:
                    if pd.isna(row['RSI']) or pd.isna(row['ATR']): continue
                    
                    if not in_trade:
                        if row['RSI'] < rsi_val and row['Close'] < row['BB_Low']:
                            entry = row['Close']
                            sl = entry - (sl_val * row['ATR'])
                            tp = entry + (tp_val * row['ATR'])
                            in_trade = True
                    else:
                        if row['Low'] <= sl:
                            profit -= (entry - sl)
                            trades += 1
                            in_trade = False
                        elif row['High'] >= tp:
                            profit += (tp - entry)
                            wins += 1
                            trades += 1
                            in_trade = False
                            
                # Pokud je strategie zisková, uložíme ji jako nejlepší
                if trades > 0 and profit > best_profit:
                    best_profit = profit
                    best_params = {
                        "rsi": rsi_val, "sl_atr": sl_val, "tp_atr": tp_val, 
                        "win_rate": (wins/trades)*100, "trades": trades, "profit": profit
                    }
                    
    # Vrátíme parametry pouze pokud je trh historicky ziskový
    if best_params and best_params["profit"] > 0:
        return best_params
    return None

def scan_markets():
    opportunities = []
    print(f"Začínám AI skenování {len(TICKERS_TO_SCAN)} instrumentů...")
    
    for ticker in TICKERS_TO_SCAN:
        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns and 'ATR' in df.columns:
            
            # 1. KROK: Najdi nejlepší parametry pro tento konkrétní trh
            best_setup = optimize_strategy(df)
            
            # Pokud trh prodělává při jakémkoliv nastavení, bot ho přeskočí!
            if not best_setup:
                print(f"Ignoruji {ticker} - historicky neziskový trh.")
                continue
                
            # 2. KROK: Zkontroluj dnešní cenu podle nejlepších parametrů
            current_price = df['Close'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            bb_low = df['BB_Low'].iloc[-1]
            atr = df['ATR'].iloc[-1]
            
            if rsi < best_setup['rsi'] and current_price < bb_low:
                
                # Výpočet přesných hodnot podle vítězné strategie
                entry = current_price
                sl = entry - (best_setup['sl_atr'] * atr)
                tp = entry + (best_setup['tp_atr'] * atr)
                
                risk_amount = ACCOUNT_BALANCE * (RISK_PCT / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                
                msg = f"🚨 *AI SIGNÁL: {ticker}* 🚨\n\n"
                msg += f"Trh je ve slevě (RSI: {rsi:.1f})!\n\n"
                msg += f"🧠 *Auto-Tuning (Historie 2 roky):*\n"
                msg += f"Bot zjistil, že tento trh nejlépe funguje s RSI < {best_setup['rsi']} a SL {best_setup['sl_atr']}x ATR.\n"
                msg += f"Úspěšnost strategie: *{best_setup['win_rate']:.1f} %* ({best_setup['trades']} obchodů)\n\n"
                
                msg += f"📊 *Parametry pro XTB (Risk {RISK_PCT}%):*\n"
                msg += f"• *Vstup (Entry):* {entry:.4f}\n"
                msg += f"• *Stop Loss (SL):* {sl:.4f}\n"
                msg += f"• *Take Profit (TP):* {tp:.4f}\n"
                
                if "/" in ticker:
                    msg += f"• *Objem:* {volume:.2f} Lotů *(Zkontroluj hodnotu bodu!)*\n\n"
                else:
                    msg += f"• *Objem:* {volume:.2f} Kusů\n\n"
                    
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
