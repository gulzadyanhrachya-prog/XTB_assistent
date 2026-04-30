import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime
from supabase import create_client, Client

# --- TAJNÉ KLÍČE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    ACCOUNT_BALANCE = float(os.getenv("XTB_BALANCE", 10000.0))
except:
    ACCOUNT_BALANCE = 10000.0

RISK_PCT = 1.5  

# Připojení k databázi
db_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        db_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except: pass

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

def check_market_panic():
    """Zkontroluje Index strachu (VIX). Pokud je nad 30, trh panikaří."""
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if not vix.empty and vix['Close'].iloc[-1] > 30:
            return True
    except: pass
    return False

def monitor_open_positions():
    """Hlídač pozic: Zkontroluje otevřené obchody a upozorní na posun Stop Lossu."""
    if not db_client: return
    try:
        open_trades = db_client.table("xtb_trades").select("*").eq("Status", "Otevřeno").execute().data
        for trade in open_trades:
            ticker = trade['Instrument']
            entry = float(trade['Vstup'])
            df = yf.Ticker(ticker).history(period="1mo")
            if not df.empty:
                curr_price = df['Close'].iloc[-1]
                atr = df['High'].iloc[-1] - df['Low'].iloc[-1] # Zjednodušené ATR pro rychlost
                be_level = entry + (1.5 * atr)
                
                if curr_price >= be_level:
                    msg = f"🛡️ *TRAILING STOP ALERT: {ticker}* 🛡️\n\n"
                    msg += f"Tvůj obchod je v krásném zisku! Cena dosáhla bezpečné úrovně ({curr_price:.2f}).\n"
                    msg += f"👉 **Okamžitě posuň Stop Loss na vstupní cenu ({entry:.2f})**, abys chránil kapitál!"
                    send_telegram_message(msg)
                    # Označíme v databázi jako zajištěno, ať to nespamuje každou hodinu
                    db_client.table("xtb_trades").update({"Status": "Zajištěno (BE)"}).eq("id", trade["id"]).execute()
    except Exception as e:
        print(f"Chyba při kontrole pozic: {e}")

def get_data(ticker):
    df = pd.DataFrame()
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker:
        try:
            end = int(time.time())
            start = end - (2 * 365 * 24 * 60 * 60) 
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
    best_profit = -9999
    best_params = None
    records = df[['High', 'Low', 'Close', 'RSI', 'BB_Low', 'ATR']].to_dict('records')
    
    for rsi_val in [30, 35, 40]:
        for sl_val in [1.5, 2.0, 3.0]:
            for tp_val in [3.0, 4.0, 5.0]:
                trades = 0; wins = 0; profit = 0; in_trade = False
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
                            
                if trades > 0 and profit > best_profit:
                    best_profit = profit
                    best_params = {"rsi": rsi_val, "sl_atr": sl_val, "tp_atr": tp_val, "win_rate": (wins/trades)*100, "trades": trades, "profit": profit}
                    
    if best_params and best_params["profit"] > 0:
        return best_params
    return None

def scan_markets():
    # 1. Kontrola paniky na trhu
    if check_market_panic():
        print("Trh panikaří (VIX > 30). Zastavuji nákupy.")
        send_telegram_message("🚨 *TRŽNÍ PANIKA (VIX > 30)* 🚨\nTrhy krvácejí. Bot pozastavuje nákupy pro ochranu kapitálu.")
        return

    # 2. Kontrola otevřených pozic
    monitor_open_positions()

    opportunities = []
    print(f"Začínám AI skenování {len(TICKERS_TO_SCAN)} instrumentů...")
    
    for ticker in TICKERS_TO_SCAN:
        # INTELIGENTNÍ FOREX FILTR PRO MALÉ ÚČTY
        if "/" in ticker and ACCOUNT_BALANCE < 10000:
            print(f"Ignoruji {ticker} - Forex je pro účet {ACCOUNT_BALANCE} CZK příliš drahý (vysoký risk na 0.01 lotu).")
            continue

        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns and 'ATR' in df.columns:
            best_setup = optimize_strategy(df)
            if not best_setup:
                continue
                
            current_price = df['Close'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            bb_low = df['BB_Low'].iloc[-1]
            atr = df['ATR'].iloc[-1]
            
            if rsi < best_setup['rsi'] and current_price < bb_low:
                entry = current_price
                sl = entry - (best_setup['sl_atr'] * atr)
                tp = entry + (best_setup['tp_atr'] * atr)
                
                risk_amount = ACCOUNT_BALANCE * (RISK_PCT / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                
                rrr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                profit_amount = risk_amount * rrr
                
                msg = f"🚨 *AI SIGNÁL: {ticker}* 🚨\n\n"
                msg += f"🧠 *Auto-Tuning:* RSI < {best_setup['rsi']}, SL {best_setup['sl_atr']}x ATR.\n"
                msg += f"Úspěšnost strategie: *{best_setup['win_rate']:.1f} %* ({best_setup['trades']} obchodů)\n\n"
                msg += f"📊 *Parametry pro XTB (Risk {RISK_PCT}%):*\n"
                msg += f"• *Vstup (Entry):* {entry:.4f}\n"
                msg += f"• *Stop Loss (SL):* {sl:.4f}\n"
                msg += f"• *Take Profit (TP):* {tp:.4f}\n"
                msg += f"• *Objem:* {volume:.2f} Kusů\n\n"
                msg += f"💰 *Finance:* Risk **{risk_amount:.2f} CZK** ➡️ Zisk cca **{profit_amount:.2f} CZK** (RRR 1:{rrr:.2f})\n"
                msg += f"🏦 _(Zůstatek účtu: {ACCOUNT_BALANCE})_"
                
                opportunities.append(msg)

                # FORWARD-TESTING: Zápis signálu do Supabase
                if db_client:
                    try:
                        record = {
                            "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "Instrument": ticker, "Typ": "Akcie",
                            "Vstup": round(entry, 4), "SL": round(sl, 4), "TP": round(tp, 4),
                            "Objem": round(volume, 2), "Risk": round(risk_amount, 2), 
                            "Zisk": round(profit_amount, 2), "RRR": f"1:{rrr:.2f}"
                        }
                        db_client.table("bot_signals").insert(record).execute()
                    except Exception as e:
                        print(f"Chyba zápisu signálu: {e}")
                
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
