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
FRED_KEY = os.getenv("FRED_API_KEY")

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

def get_usd_czk_rate():
    try:
        df = yf.Ticker("USDCZK=X").history(period="1d")
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except: pass
    return 23.5

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

def get_macro_regime():
    if not FRED_KEY:
        return "⚪ Neznámé (Chybí FRED API)", False
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&api_key={FRED_KEY}&file_type=json&sort_order=desc&limit=1"
        res = requests.get(url, timeout=10).json()
        val = float(res['observations'][0]['value'])
        if val < 0:
            return f"🔴 Riziko recese (Inverzní křivka: {val}%)", True 
        else:
            return f"🟢 Normální růst (Křivka: {val}%)", False
    except Exception as e:
        print(f"FRED Chyba: {e}")
        return "⚪ Neznámé (Chyba API)", False

def check_insider_sentiment(ticker):
    if not FINNHUB_KEY or "=" in ticker or "^" in ticker or "/" in ticker or "-USD" in ticker:
        return "⚪ N/A"
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/stock/insider-sentiment?symbol={ticker}&from={start_date}&to={end_date}&token={FINNHUB_KEY}"
        res = requests.get(url, timeout=10).json()
        if "data" in res and len(res["data"]) > 0:
            avg_mspr = sum([item['mspr'] for item in res['data']]) / len(res['data'])
            if avg_mspr > 0: return f"🟢 Nakupují (MSPR: {avg_mspr:.2f})"
            elif avg_mspr < 0: return f"🔴 Prodávají (MSPR: {avg_mspr:.2f})"
            else: return "⚪ Neutrální"
    except: pass
    return "⚪ Nedostatek dat"

def ai_investment_committee(ticker, strategy, rsi, insider_status, macro_status):
    if not GEMINI_KEY:
        return "⚠️ Chybí GEMINI_API_KEY", "SCHVÁLENO"
    if not FINNHUB_KEY or "=" in ticker or "^" in ticker or "/" in ticker:
        return "Bez AI kontroly (Forex/Index)", "SCHVÁLENO"
        
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={start_date}&to={end_date}&token={FINNHUB_KEY}"
        news = requests.get(url, timeout=10).json()
        news_text = "\n".join([f"- {a.get('headline')}" for a in news[:5]]) if news else "Žádné zprávy."
        
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        Jsi hlavní risk manažer kvantitativního hedge fondu. Tvůj algoritmus navrhl obchod pro {ticker}.
        Zde jsou data k posouzení:
        - Strategie: {strategy}
        - Aktuální RSI: {rsi:.1f}
        - Aktivita ředitelů (Insider): {insider_status}
        - Makroekonomika (FED): {macro_status}
        - Dnešní zprávy o firmě:
        {news_text}

        Zhodnoť toto riziko. Napiš stručné odůvodnění (max 3 věty).
        Na úplný konec napiš na nový řádek přesně jedno slovo: 'VERDIKT: SCHVALENO' nebo 'VERDIKT: ZAMITNUTO'.
        Zamítni to POUZE pokud zprávy naznačují bankrot, podvod, nebo pokud je makro v recesi a zároveň ředitelé masivně prodávají.
        """
        response = model.generate_content(prompt).text.strip()
        
        verdict = "SCHVÁLENO"
        if "ZAMITNUTO" in response.upper() or "ZAMÍTNUTO" in response.upper():
            verdict = "ZAMÍTNUTO"
            
        return response, verdict
    except Exception as e:
        print(f"AI Chyba: {e}")
        return f"Chyba AI: {e}", "SCHVÁLENO"

def was_signal_sent_recently(ticker, hours=24):
    """NEPRŮSTŘELNÝ ANTI-SPAM: Počítá časový rozdíl přímo v Pythonu."""
    if not db_client: return False 
    try:
        # Stáhneme jen ten úplně poslední signál pro daný ticker
        res = db_client.table("bot_signals").select("Datum").eq("Instrument", ticker).order("Datum", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            last_date_str = res.data[0]['Datum']
            # Převedeme text z databáze na skutečný čas
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d %H:%M")
            # Pokud od posledního signálu uběhlo méně než X hodin, je to spam
            if (datetime.now() - last_date) < timedelta(hours=hours):
                return True 
    except Exception as e:
        print(f"Chyba Anti-Spamu: {e}")
    return False

def get_data(ticker):
    df = pd.DataFrame()
    if FINNHUB_KEY and "=" not in ticker and "^" not in ticker and "/" not in ticker and "-USD" not in ticker:
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

def optimize_strategy(df, is_defensive_mode):
    best_sortino = -9999
    best_params = None
    try:
        records = df[['High', 'Low', 'Close', 'RSI', 'BB_Low', 'ATR', 'High_20', 'MACD', 'MACD_Signal']].to_dict('records')
        
        for rsi_val in [30, 35, 40]:
            for sl_val in [1.5, 2.0, 3.0]:
                for tp_val in [3.0, 4.0, 5.0]:
                    trade_results = []
                    in_trade = False
                    entry = 0; sl = 0; tp = 0
                    for row in records:
                        if pd.isna(row['RSI']) or pd.isna(row['ATR']): continue
                        if not in_trade:
                            if row['RSI'] < rsi_val and row['Close'] < row['BB_Low']:
                                entry = row['Close']; sl = entry - (sl_val * row['ATR']); tp = entry + (tp_val * row['ATR'])
                                in_trade = True
                        else:
                            if row['Low'] <= sl: 
                                trade_results.append(-(entry - sl))
                                in_trade = False
                            elif row['High'] >= tp: 
                                trade_results.append(tp - entry)
                                in_trade = False
                                
                    if len(trade_results) > 0:
                        total_profit = sum(trade_results)
                        if total_profit > 0:
                            returns = np.array(trade_results)
                            expected_return = np.mean(returns)
                            downside_returns = returns[returns < 0]
                            downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1e-5
                            sortino = expected_return / downside_std
                            
                            if sortino > best_sortino:
                                best_sortino = sortino
                                wins = len(returns[returns > 0])
                                best_params = {"type": "Sleva (Mean-Reversion)", "rsi": rsi_val, "sl_atr": sl_val, "tp_atr": tp_val, "win_rate": (wins/len(trade_results))*100, "trades": len(trade_results), "profit": total_profit, "sortino": sortino}

        if not is_defensive_mode:
            for sl_val in [1.5, 2.0]:
                for tp_val in [3.0, 5.0, 7.0]:
                    trade_results = []
                    in_trade = False
                    entry = 0; sl = 0; tp = 0
                    for row in records:
                        if pd.isna(row['High_20']) or pd.isna(row['ATR']): continue
                        if not in_trade:
                            if row['Close'] > row['High_20'] and row['MACD'] > row['MACD_Signal']:
                                entry = row['Close']; sl = entry - (sl_val * row['ATR']); tp = entry + (tp_val * row['ATR'])
                                in_trade = True
                        else:
                            if row['Low'] <= sl: 
                                trade_results.append(-(entry - sl))
                                in_trade = False
                            elif row['High'] >= tp: 
                                trade_results.append(tp - entry)
                                in_trade = False
                                
                    if len(trade_results) > 0:
                        total_profit = sum(trade_results)
                        if total_profit > 0:
                            returns = np.array(trade_results)
                            expected_return = np.mean(returns)
                            downside_returns = returns[returns < 0]
                            downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1e-5
                            sortino = expected_return / downside_std
                            
                            if sortino > best_sortino:
                                best_sortino = sortino
                                wins = len(returns[returns > 0])
                                best_params = {"type": "Trend (Breakout)", "sl_atr": sl_val, "tp_atr": tp_val, "win_rate": (wins/len(trade_results))*100, "trades": len(trade_results), "profit": total_profit, "sortino": sortino}
                    
        if best_params and best_params["profit"] > 0:
            return best_params
    except Exception as e:
        print(f"Chyba optimalizace: {e}")
    return None

def scan_markets():
    if check_market_panic():
        send_telegram_message("🚨 *TRŽNÍ PANIKA (VIX > 30)* 🚨\nTrhy krvácejí. Bot pozastavuje nákupy pro ochranu kapitálu.")
        return

    macro_status, is_defensive = get_macro_regime()
    usd_czk_rate = get_usd_czk_rate()
    
    raw_signals = []
    print(f"Začínám AI skenování {len(TICKERS_TO_SCAN)} instrumentů...")
    
    for ticker in TICKERS_TO_SCAN:
        if "/" in ticker and ACCOUNT_BALANCE < 10000:
            continue 

        df = get_data(ticker)
        if df is not None and not df.empty and 'RSI' in df.columns and 'ATR' in df.columns:
            best_setup = optimize_strategy(df, is_defensive)
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
                    print(f"Anti-Spam: Signál pro {ticker} přeskočen.")
                    continue
                
                dynamic_risk_pct = round(max(0.5, min(2.5, 1.0 * (best_setup['win_rate'] / 50))), 2)
                
                entry = current_price
                sl = entry - (best_setup['sl_atr'] * atr)
                tp = entry + (best_setup['tp_atr'] * atr)
                
                if "/" in ticker:
                    risk_amount_czk = ACCOUNT_BALANCE * (dynamic_risk_pct / 100)
                    volume = 0; profit_amount_czk = 0
                    rrr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                else:
                    risk_amount_czk = ACCOUNT_BALANCE * (dynamic_risk_pct / 100)
                    risk_per_share_usd = abs(entry - sl)
                    risk_per_share_czk = risk_per_share_usd * usd_czk_rate
                    
                    volume = risk_amount_czk / risk_per_share_czk if risk_per_share_czk > 0 else 0
                    max_affordable_volume = ACCOUNT_BALANCE / (entry * usd_czk_rate) if entry > 0 else 0
                    
                    if volume > max_affordable_volume:
                        volume = max_affordable_volume
                        risk_amount_czk = volume * risk_per_share_czk
                        
                    profit_amount_czk = volume * abs(tp - entry) * usd_czk_rate
                    rrr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                
                raw_signals.append({
                    "ticker": ticker, "sector": SECTORS.get(ticker, "Other"),
                    "setup": best_setup, "entry": entry, "sl": sl, "tp": tp,
                    "risk_pct": dynamic_risk_pct, "risk_czk": risk_amount_czk, "profit_czk": profit_amount_czk,
                    "volume": volume, "rrr": rrr, "rsi": current_rsi 
                })
        time.sleep(1.5) 
        
    filtered_signals = []
    sectors_used = set()
    raw_signals.sort(key=lambda x: x['setup']['sortino'], reverse=True)
    
    for sig in raw_signals:
        if sig['sector'] not in sectors_used or sig['sector'] == "Other":
            filtered_signals.append(sig)
            sectors_used.add(sig['sector'])

    if filtered_signals:
        for sig in filtered_signals:
            ticker = sig['ticker']
            
            insider_status = check_insider_sentiment(ticker)
            ai_reasoning, ai_verdict = ai_investment_committee(
                ticker, sig['setup']['type'], sig['rsi'], insider_status, macro_status
            )
            
            if ai_verdict == "ZAMÍTNUTO":
                print(f"AI Komise ZAMÍTLA nákup {ticker}!")
                send_telegram_message(f"🛑 *AI KOMISE ZAMÍTLA OBCHOD: {ticker}* 🛑\n\nTechnika hlásí nákup, ale AI risk manažer obchod zablokoval.\n\n*Odůvodnění AI:*\n_{ai_reasoning}_")
                continue
            
            msg = f"🚨 *AI SIGNÁL: {ticker}* ({sig['sector']}) 🚨\n\n"
            msg += f"🎯 *Strategie:* {sig['setup']['type']}\n"
            msg += f"📈 *Aktuální RSI:* {sig['rsi']:.1f}\n" 
            msg += f"🧠 *Auto-Tuning:* Úspěšnost *{sig['setup']['win_rate']:.1f} %* ({sig['setup']['trades']} obchodů)\n"
            msg += f"🛡️ *Sortino Ratio:* {sig['setup']['sortino']:.2f}\n"
            msg += f"🕵️‍♂️ *Insider Trading:* {insider_status}\n"
            msg += f"🏦 *Makro (FED):* {macro_status}\n\n"
            
            msg += f"⚖️ *AI Komise (Gemini):* ✅ {ai_verdict}\n"
            msg += f"_{ai_reasoning}_\n\n"
            
            msg += f"📊 *Parametry pro XTB (Risk {sig['risk_pct']}%):*\n"
            msg += f"• *Vstup (Entry):* {sig['entry']:.4f}\n"
            msg += f"• *Stop Loss (SL):* {sig['sl']:.4f}\n"
            msg += f"• *Take Profit (TP):* {sig['tp']:.4f}\n"
            
            if "/" in ticker:
                msg += f"• *Objem pro XTB:* ⚠️ **Spočítej v platformě!**\n"
                msg += f"_(Zadej SL {sig['sl']:.4f} a upravuj Loty, dokud ztráta nebude cca {sig['risk_czk']:.0f} CZK)_\n\n"
            else:
                msg += f"• *Objem pro XTB:* {sig['volume']:.2f} Kusů\n\n"
                msg += f"💰 *Finance:* Risk **{sig['risk_czk']:.2f} CZK** ➡️ Zisk cca **{sig['profit_czk']:.2f} CZK** (RRR 1:{sig['rrr']:.2f})\n"
                
            msg += f"🏦 _(Zůstatek účtu: {ACCOUNT_BALANCE} CZK)_\n"
            
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
            time.sleep(1)
        print(f"Odesláno {len(filtered_signals)} filtrovaných signálů.")
    else:
        print("Trhy jsou klidné, žádný signál nebyl odeslán.")

if __name__ == "__main__":
    try:
        scan_markets()
    except Exception as e:
        print(f"Kritická chyba bota: {e}")
