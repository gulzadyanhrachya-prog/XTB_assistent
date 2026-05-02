import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime, timedelta
from supabase import create_client, Client
import google.generativeai as genai

# --- TAJNÉ KLÍČE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

try:
    ACCOUNT_BALANCE = float(os.getenv("XTB_BALANCE", 10000.0))
except:
    ACCOUNT_BALANCE = 10000.0

# Připojení k databázi
db_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        db_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e: 
        print(f"Chyba připojení k Supabase: {e}")

# --- KORELAČNÍ MAPA (Sektory) ---
SECTORS = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AVGO": "Tech", "AMD": "Tech", "INTC": "Tech", "CSCO": "Tech", "IBM": "Tech",
    "GOOGL": "Comm", "META": "Comm", "NFLX": "Comm", "DIS": "Comm",
    "AMZN": "Consumer", "TSLA": "Consumer", "HD": "Consumer", "MCD": "Consumer", "NKE": "Consumer",
    "JPM": "Finance", "GS": "Finance", "V": "Finance",
    "JNJ": "Health", "UNH": "Health",
    "CVX": "Energy", "CAT": "Industrials", "BA": "Industrials", "MMM": "Industrials",
    "KO": "Staples", "PG": "Staples", "WMT": "Staples",
    "BTC-USD": "Crypto", "ETH-USD": "Crypto", "SOL-USD": "Crypto"
}

TICKERS_TO_SCAN = list(SECTORS.keys()) + ["EUR/USD", "GBP/USD", "USD/JPY", "^GSPC", "^IXIC"]

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Chyba odesílání Telegramu: {e}")

def check_market_panic():
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if not vix.empty and vix['Close'].iloc[-1] > 30:
            return True
    except: pass
    return False

def check_ai_sentiment(ticker):
    if not GEMINI_KEY:
        return "⚠️ Chybí GEMINI_API_KEY v GitHub Secrets!"
    if not FINNHUB_KEY or "=" in ticker or "^" in ticker or "/" in ticker:
        return "Bez AI kontroly (Forex/Index)"
        
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={start_date}&to={end_date}&token={FINNHUB_KEY}"
        news = requests.get(url, timeout=10).json()
        
        if news and isinstance(news, list):
            news_text = "\n".join([f"- {a.get('headline')}" for a in news[:5]])
            genai.configure(api_key=GEMINI_KEY)
            model = genai.GenerativeModel('gemini-2.5-flash')
            prompt = f"Zde jsou dnešní titulky zpráv pro {ticker}:\n{news_text}\n\nOdpověz pouze jedním slovem: 'KRIZE' (pokud firma čelí bankrotu, obří žalobě nebo fatálnímu skandálu) nebo 'BEZPECNE' (pokud jde o běžné zprávy nebo pozitivní vývoj)."
            response = model.generate_content(prompt).text.strip().upper()
            return response
    except Exception as e:
        print(f"AI Chyba: {e}")
    return "BEZPECNE"

def was_signal_sent_recently(ticker, hours=24):
    if not db_client:
        return False 
    try:
        time_threshold = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        res = db_client.table("bot_signals").select("Datum").eq("Instrument", ticker).gte("Datum", time_threshold).execute()
        if res.data and len(res.data) > 0:
            return True 
    except Exception as e:
        print(f"Chyba při kontrole historie signálů: {e}")
    return False

def get_data(ticker):
    df = pd.DataFrame()
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker:
        try:
            end = int(time.time())
            start = end - (2 * 365 * 24 * 60 * 60) 
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
            res = requests.get(url, timeout=10).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"High": res["h"], "Low": res["l"], "Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
        except: pass

    if df.empty and TWELVE_KEY and "/" in ticker:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize=500&apikey={TWELVE_KEY}"
            res = requests.get(url, timeout=10).json()
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
        try:
            delta = df['Close'].diff()
            gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
            loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
            df['RSI'] = 100 - (100 / (1 + (gain / loss)))
            
            df['BB_Mid'] = df['Close'].rolling(window=20).mean()
            df['BB_Std'] = df['Close'].rolling(window=20).std()
            df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
            
            df['High_20'] = df['High'].rolling(window=20).max().shift(1)
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = ema12 - ema26
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            high_low = df['High'] - df['Low']
            high_close = np.abs(df['High'] - df['Close'].shift())
            low_close = np.abs(df['Low'] - df['Close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
            return df
        except Exception as e:
            print(f"Chyba výpočtu indikátorů pro {ticker}: {e}")
    return None

def optimize_strategy(df):
    best_profit = -9999
    best_params = None
    try:
        records = df[['High', 'Low', 'Close', 'RSI', 'BB_Low', 'ATR', 'High_20', 'MACD', 'MACD_Signal']].to_dict('records')
        
        for rsi_val in [30, 35, 40]:
            for sl_val in [1.5, 2.0, 3.0]:
                for tp_val in [3.0, 4.0, 5.0]:
                    trades = 0; wins = 0; profit = 0; in_trade = False
                    entry = 0; sl = 0; tp = 0
                    for row in records:
                        if pd.isna(row['RSI']) or pd.isna(row['ATR']): continue
                        if not in_trade:
                            if row['RSI'] < rsi_val and row['Close'] < row['BB_Low']:
                                entry = row['Close']; sl = entry - (sl_val * row['ATR']); tp = entry + (tp_val * row['ATR'])
                                in_trade = True
                        else:
                            if row['Low'] <= sl: profit -= (entry - sl); trades += 1; in_trade = False
                            elif row['High'] >= tp: profit += (tp - entry); wins += 1; trades += 1; in_trade = False
                    if trades > 0 and profit > best_profit:
                        best_profit = profit
                        best_params = {"type": "Sleva (Mean-Reversion)", "rsi": rsi_val, "sl_atr": sl_val, "tp_atr": tp_val, "win_rate": (wins/trades)*100, "trades": trades, "profit": profit}

        for sl_val in [1.5, 2.0]:
            for tp_val in [3.0, 5.0, 7.0]:
                trades = 0; wins = 0; profit = 0; in_trade = False
                entry = 0; sl = 0; tp = 0
                for row in records:
                    if pd.isna(row['High_20']) or pd.isna(row['ATR']): continue
                    if not in_trade:
                        if row['Close'] > row['High_20'] and row['MACD'] > row['MACD_Signal']:
                            entry = row['Close']; sl = entry - (sl_val * row['ATR']); tp = entry + (tp_val * row['ATR'])
                            in_trade = True
                        else:
                            if row['Low'] <= sl: profit -= (entry - sl); trades += 1; in_trade = False
                            elif row['High'] >= tp: profit += (tp - entry); wins += 1; trades += 1; in_trade = False
                if trades > 0 and profit > best_profit:
                    best_profit = profit
                    best_params = {"type": "Trend (Breakout)", "sl_atr": sl_val, "tp_atr": tp_val, "win_rate": (wins/trades)*100, "trades": trades, "profit": profit}
                        
        if best_params and best_params["profit"] > 0:
            return best_params
    except Exception as e:
        print(f"Chyba optimalizace: {e}")
    return None

def scan_markets():
    if check_market_panic():
        send_telegram_message("🚨 *TRŽNÍ PANIKA (VIX > 30)* 🚨\nTrhy krvácejí. Bot pozastavuje nákupy pro ochranu kapitálu.")
        return

    raw_signals = []
    print(f"Začínám AI skenování {len(TICKERS_TO_SCAN)} instrumentů...")
    
    for ticker in TICKERS_TO_SCAN:
        if "/" in ticker and ACCOUNT_BALANCE < 10000:
            continue 

        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns and 'ATR' in df.columns:
            best_setup = optimize_strategy(df)
            if not best_setup: continue
                
            current_price = df['Close'].iloc[-1]
            atr = df['ATR'].iloc[-1]
            current_rsi = df['RSI'].iloc[-1] 
            signal_triggered = False
            
            if best_setup['type'] == "Sleva (Mean-Reversion)":
                if current_rsi < best_setup['rsi'] and current_price < df['BB_Low'].iloc[-1]:
                    signal_triggered = True
            elif best_setup['type'] == "Trend (Breakout)":
                if current_price > df['High_20'].iloc[-1] and df['MACD'].iloc[-1] > df['MACD_Signal'].iloc[-1]:
                    signal_triggered = True
            
            if signal_triggered:
                if was_signal_sent_recently(ticker, hours=24):
                    print(f"Anti-Spam: Signál pro {ticker} už byl odeslán za posledních 24 hodin. Přeskakuji.")
                    continue
                
                dynamic_risk_pct = round(max(0.5, min(2.5, 1.0 * (best_setup['win_rate'] / 50))), 2)
                
                entry = current_price
                sl = entry - (best_setup['sl_atr'] * atr)
                tp = entry + (best_setup['tp_atr'] * atr)
                
                risk_amount = ACCOUNT_BALANCE * (dynamic_risk_pct / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                rrr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                profit_amount = risk_amount * rrr
                
                raw_signals.append({
                    "ticker": ticker, "sector": SECTORS.get(ticker, "Other"),
                    "setup": best_setup, "entry": entry, "sl": sl, "tp": tp,
                    "risk_pct": dynamic_risk_pct, "risk_czk": risk_amount, "profit_czk": profit_amount,
                    "volume": volume, "rrr": rrr, "rsi": current_rsi 
                })
        time.sleep(1.5) 
        
    filtered_signals = []
    sectors_used = set()
    raw_signals.sort(key=lambda x: x['setup']['profit'], reverse=True)
    
    for sig in raw_signals:
        if sig['sector'] not in sectors_used or sig['sector'] == "Other":
            filtered_signals.append(sig)
            sectors_used.add(sig['sector'])

    if filtered_signals:
        for sig in filtered_signals:
            ticker = sig['ticker']
            
            ai_status = check_ai_sentiment(ticker)
            if "KRIZE" in ai_status:
                print(f"AI zablokovalo nákup {ticker} kvůli špatným zprávám!")
                send_telegram_message(f"🛑 *AI ZABLOKOVALO NÁKUP: {ticker}*\nTechnika hlásí nákup, ale Google Gemini detekoval fundamentální KRIZI ve zprávách. Obchod zrušen.")
                continue
            
            msg = f"🚨 *AI SIGNÁL: {ticker}* ({sig['sector']}) 🚨\n\n"
            msg += f"🎯 *Strategie:* {sig['setup']['type']}\n"
            msg += f"📈 *Aktuální RSI:* {sig['rsi']:.1f}\n" 
            msg += f"🧠 *Auto-Tuning:* Úspěšnost *{sig['setup']['win_rate']:.1f} %* ({sig['setup']['trades']} obchodů)\n"
            msg += f"📰 *AI Sentiment:* {ai_status}\n\n"
            
            msg += f"⚖️ *Dynamický Risk:* {sig['risk_pct']}% (Upraveno dle Win Rate)\n"
            msg += f"• *Vstup (Entry):* {sig['entry']:.4f}\n"
            msg += f"• *Stop Loss (SL):* {sig['sl']:.4f}\n"
            msg += f"• *Take Profit (TP):* {sig['tp']:.4f}\n"
            
            if "/" in ticker:
                msg += f"• *Objem pro XTB:* ⚠️ **Spočítej v platformě!**\n"
                msg += f"_(Zadej SL {sig['sl']:.4f} a upravuj Loty, dokud ztráta nebude cca {sig['risk_czk']:.0f} CZK)_\n\n"
            else:
                msg += f"• *Objem pro XTB:* {sig['volume']:.2f} Kusů\n\n"
                
            msg += f"💰 *Finance:* Risk **{sig['risk_czk']:.2f} CZK** ➡️ Zisk cca **{sig['profit_czk']:.2f} CZK** (RRR 1:{sig['rrr']:.2f})\n"
            msg += f"🏦 _(Zůstatek účtu: {ACCOUNT_BALANCE})_"
            
            send_telegram_message(msg)
            
            if db_client:
                try:
                    record = {
                        "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Instrument": ticker, "Typ": sig['setup']['type'],
                        "Vstup": round(sig['entry'], 4), "SL": round(sig['sl'], 4), "TP": round(sig['tp'], 4),
                        "Objem": round(sig['volume'], 2), "Risk": round(sig['risk_czk'], 2), 
                        "Zisk": round(sig['profit_czk'], 2), "RRR": f"1:{sig['rrr']:.2f}",
                        "Status": "Forward-Test"
                    }
                    db_client.table("bot_signals").insert(record).execute()
                except Exception as e: 
                    print(f"Chyba zápisu do DB: {e}")
                    send_telegram_message(f"⚠️ *CHYBA ANTI-SPAMU:* Nepodařilo se zapsat signál do Supabase. Zkontroluj, zda má tabulka `bot_signals` všechny sloupce (včetně `Status`).\nDetail: `{e}`")
            else:
                send_telegram_message("⚠️ *CHYBA ANTI-SPAMU:* Bot není připojen k Supabase. Zkontroluj `SUPABASE_URL` a `SUPABASE_KEY` v GitHub Secrets!")
                
            time.sleep(1)
        print(f"Odesláno {len(filtered_signals)} filtrovaných signálů.")
    else:
        print("Trhy jsou klidné, žádný signál nebyl odeslán.")

if __name__ == "__main__":
    try:
        scan_markets()
    except Exception as e:
        print(f"Kritická chyba bota: {e}")
