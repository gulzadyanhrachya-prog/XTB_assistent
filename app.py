import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta
from supabase import create_client, Client
import google.generativeai as genai

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Terminál Pro", page_icon="📈", layout="wide")
st.title("📈 Můj XTB Trading Terminál (Hedge Fund Edice)")
st.markdown("Kalkulačka, Skener, AI Zprávy, Deník, Backtest a **Forward-Testing Bota**.")

# --- INICIALIZACE PAMĚTI A DATABÁZE ---
if 'journal' not in st.session_state:
    st.session_state.journal = []

supabase_url = st.secrets.get("SUPABASE_URL", None)
supabase_key = st.secrets.get("SUPABASE_KEY", None)
db_client = None
if supabase_url and supabase_key:
    try:
        db_client = create_client(supabase_url, supabase_key)
    except Exception:
        pass

# --- FUNKCE PRO STAŽENÍ DAT A INDIKÁTORY ---
@st.cache_data(ttl=300)
def get_market_data(ticker_symbol):
    df = pd.DataFrame()
    
    # 1. Finnhub (US Akcie)
    finnhub_key = st.secrets.get("FINNHUB_API_KEY", None)
    if finnhub_key and "=" not in ticker_symbol and "^" not in ticker_symbol and "/" not in ticker_symbol:
        try:
            end = int(time.time())
            start = end - (2 * 365 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker_symbol}&resolution=D&from={start}&to={end}&token={finnhub_key}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({"Open": res["o"], "High": res["h"], "Low": res["l"], "Close": res["c"]}, index=pd.to_datetime(res["t"], unit="s"))
                df = df.sort_index()
        except Exception: pass

    # 2. Twelve Data (Forex / Indexy)
    twelve_key = st.secrets.get("TWELVEDATA_API_KEY", None)
    if df.empty and twelve_key and "/" in ticker_symbol:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={ticker_symbol}&interval=1day&outputsize=500&apikey={twelve_key}"
            res = requests.get(url).json()
            if "values" in res:
                df_td = pd.DataFrame(res["values"])
                df_td['datetime'] = pd.to_datetime(df_td['datetime'])
                df_td = df_td.set_index('datetime').astype(float)
                df_td = df_td.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
                df = df_td.sort_index()
        except Exception: pass
            
    # 3. Yahoo Finance (Záloha)
    if df.empty:
        try:
            yf_ticker = ticker_symbol
            # Yahoo Finance potřebuje pro Forex formát EURUSD=X místo EUR/USD
            if "/" in ticker_symbol:
                yf_ticker = ticker_symbol.replace("/", "") + "=X"
            df = yf.Ticker(yf_ticker).history(period="2y")
        except Exception: return None
        
    if df is None or df.empty:
        return None
        
    # --- VÝPOČET POKROČILÝCH INDIKÁTORŮ ---
    try:
        # Odstranění časové zóny (Yahoo Finance ji někdy přidává a rozbíjí to výpočty)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        df_weekly = df.resample('W').agg({'Close': 'last'})
        df_weekly['SMA_50_W'] = df_weekly['Close'].rolling(50).mean()
        df['Weekly_SMA_50'] = df_weekly['SMA_50_W'].reindex(df.index, method='ffill')

        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Up'] = df['BB_Mid'] + (df['BB_Std'] * 2)
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)

        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
    except Exception:
        pass
    return df

@st.cache_data(ttl=3600)
def check_earnings(ticker_symbol):
    api_key = st.secrets.get("FINNHUB_API_KEY", None)
    if not api_key or "=" in ticker_symbol or "^" in ticker_symbol or "/" in ticker_symbol:
        return False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        next_week = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={next_week}&symbol={ticker_symbol}&token={api_key}"
        res = requests.get(url).json()
        if "earningsCalendar" in res and len(res["earningsCalendar"]) > 0:
            return True
    except Exception: pass
    return False

# --- GLOBÁLNÍ VYHLEDÁVÁNÍ ---
st.divider()
col_search, _ = st.columns([1, 2])
with col_search:
    raw_input = st.text_input("🔍 Hledaný instrument:", value="AAPL").upper().strip()
    
    # AUTOMATICKÁ OPRAVA PRO FOREX (např. USDJPY -> USD/JPY)
    if len(raw_input) == 6 and "/" not in raw_input:
        forex_currencies = ["USD", "JPY", "EUR", "GBP", "CHF", "AUD", "CAD", "NZD"]
        if raw_input[:3] in forex_currencies or raw_input[3:] in forex_currencies:
            ticker_input = f"{raw_input[:3]}/{raw_input[3:]}"
        else:
            ticker_input = raw_input
    else:
        ticker_input = raw_input
        
st.write("") 

tab_calc, tab_scanner, tab_news, tab_journal, tab_backtest, tab_forward = st.tabs([
    "📊 Kalkulačka", "📡 Skener", "🤖 AI Zprávy", "📓 Deník", "⏪ Backtest", "🚀 Forward-Testing"
])

# ==========================================
# ZÁLOŽKA 1: ANALÝZA A KALKULAČKA
# ==========================================
with tab_calc:
    current_price = 0.0
    atr = 1.0 
    
    if ticker_input:
        df = get_market_data(ticker_input)
        if df is not None and not df.empty:
            current_price = float(df['Close'].iloc[-1]) if not pd.isna(df['Close'].iloc[-1]) else 0.0
            atr_val = df['ATR'].iloc[-1] if 'ATR' in df.columns else 1.0
            atr = float(atr_val) if not pd.isna(atr_val) else 1.0
            
            if check_earnings(ticker_input):
                st.error(f"⚠️ POZOR: {ticker_input} vyhlašuje do 14 dnů hospodářské výsledky! Hrozí vysoká volatilita a gapy.")

            st.success(f"✅ Aktuální cena **{ticker_input}**: {current_price:.2f}")
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Cena'))
            if 'SMA_50' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1), name='SMA 50'))
            if 'Weekly_SMA_50' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['Weekly_SMA_50'], line=dict(color='purple', width=3), name='Týdenní SMA 50 (MTF)'))
            if 'BB_Up' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Up'], line=dict(color='gray', width=1, dash='dot'), name='BB Horní'))
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Low'], line=dict(color='gray', width=1, dash='dot'), name='BB Dolní'))
                
            fig.update_layout(title=f'Cenový vývoj {ticker_input}', xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("⚠️ Data se nepodařilo načíst. Zkontroluj ticker nebo zadej cenu do kalkulačky ručně.")

    st.divider()
    st.subheader("🛡️ Výpočet Risku a Trailing Stopu")
    
    calc_type = st.radio("Vyber typ instrumentu pro výpočet:", ["📈 Akcie a ETF (Kusy)", "💱 CFD / Forex (Loty)"], horizontal=True)

    if calc_type == "📈 Akcie a ETF (Kusy)":
        c1, c2 = st.columns(2)
        with c1:
            acc_bal = st.number_input("Zůstatek na účtu:", min_value=100.0, value=2071.0, step=100.0)
            risk_pct = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=1.5, step=0.1)
        with c2:
            entry = st.number_input("Vstupní cena (Entry):", value=current_price if current_price > 0 else 150.0, step=1.0)
            sl = st.number_input("Stop Loss (SL):", value=(current_price - 2*atr) if current_price > 0 else 140.0, step=1.0)
            tp = st.number_input("Take Profit (TP):", value=(current_price + 4*atr) if current_price > 0 else 170.0, step=1.0)

        if st.button("Spočítat parametry (Akcie)", type="primary"):
            if entry == sl:
                st.error("Vstup a SL nesmí být stejné!")
            else:
                risk_amount = acc_bal * (risk_pct / 100)
                risk_per_share = abs(entry - sl)
                volume = risk_amount / risk_per_share if risk_per_share > 0 else 0
                total_profit = volume * abs(tp - entry)
                rrr = abs(tp - entry) / risk_per_share if risk_per_share > 0 else 0
                
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Max. Ztráta", f"{risk_amount:.2f}")
                r2.metric("Potenciální Zisk", f"{total_profit:.2f}")
                r3.metric("Velikost pozice (Kusy)", f"{volume:.2f}")
                r4.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}")
                
                st.info(f"🛡️ **Řízení pozice:** Jakmile cena dosáhne **{(entry + 1.5*atr):.2f}**, posuň Stop Loss na Break-Even (vstupní cenu {entry:.2f}).")
                
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input, "Typ": "Akcie",
                    "Vstup": entry, "SL": sl, "TP": tp, "Objem": round(volume, 2),
                    "Risk": round(risk_amount, 2), "Zisk": round(total_profit, 2), "RRR": f"1:{rrr:.2f}",
                    "Status": "Otevřeno"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod uložen do lokálního deníku!', icon='📓')

    else:
        st.info("Pro CFD zadej hodnotu 1 bodu. Logika výpočtu je stejná.")
        c3, c4 = st.columns(2)
        with c3:
            acc_bal_cfd = st.number_input("Zůstatek na účtu:", min_value=
100.0, value=2071.0, step=100.0, key="bal_cfd")
            risk_pct_cfd = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=1.5, step=0.1, key="risk_cfd")
        with c4:
            entry_cfd = st.number_input("Vstupní cena (Entry):", min_value=0.00001, value=current_price if current_price > 0 else 1.1000, format="%.5f", key="entry_cfd")
            sl_cfd = st.number_input("Cena Stop Loss (SL):", min_value=0.00001, value=(current_price - 2*atr) if current_price > 0 else 1.0950, format="%.5f", key="sl_cfd")
            tp_cfd = st.number_input("Take Profit (TP):", min_value=0.00001, value=(current_price + 4*atr) if current_price > 0 else 1.1100, format="%.5f", key="tp_cfd")
            point_value = st.number_input("Hodnota 1 bodu při objemu 1 Lot:", min_value=0.01, value=10.0, step=1.0)

        if st.button("Spočítat pro CFD/Forex", type="primary"):
            if entry_cfd == sl_cfd:
                st.error("Vstupní cena a Stop Loss nesmí být stejné!")
            else:
                risk_amount = acc_bal_cfd * (risk_pct_cfd / 100)
                points_at_risk = abs(entry_cfd - sl_cfd)
                points_profit = abs(tp_cfd - entry_cfd)
                
                risk_per_one_lot = points_at_risk * point_value
                profit_per_one_lot = points_profit * point_value
                
                lot_size = risk_amount / risk_per_one_lot if risk_per_one_lot > 0 else 0
                total_profit = lot_size * profit_per_one_lot
                rrr = points_profit / points_at_risk if points_at_risk > 0 else 0
                
                res5, res6, res7, res8 = st.columns(4)
                res5.metric("Max. Ztráta", f"{risk_amount:.2f}")
                res6.metric("Potenciální Zisk", f"{total_profit:.2f}")
                res7.metric("Velikost pozice (Loty)", f"{lot_size:.3f}")
                res8.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}")
                
                st.info(f"🛡️ **Řízení pozice:** Jakmile cena dosáhne **{(entry_cfd + 1.5*atr):.5f}**, posuň Stop Loss na Break-Even (vstupní cenu {entry_cfd:.5f}).")
                
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input, "Typ": "CFD/Forex",
                    "Vstup": entry_cfd, "SL": sl_cfd, "TP": tp_cfd, "Objem": round(lot_size, 2),
                    "Risk": round(risk_amount, 2), "Zisk": round(total_profit, 2), "RRR": f"1:{rrr:.2f}",
                    "Status": "Otevřeno"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod uložen do lokálního deníku!', icon='📓')

# ==========================================
# ZÁLOŽKA 5: BACKTESTING (Stroj času)
# ==========================================
with tab_backtest:
    st.header("⏪ Stroj času: Otestuj svou strategii na historii")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        bt_rsi = st.slider("Nakupovat, když RSI klesne pod:", 10, 50, 30)
        bt_mtf = st.checkbox("Povolit nákup POUZE pokud je týdenní trend rostoucí (MTF Filtr)", value=True)
    with col_b2:
        bt_sl_atr = st.slider("Stop Loss (násobek ATR):", 1.0, 5.0, 2.0)
        bt_tp_atr = st.slider("Take Profit (násobek ATR):", 1.0, 10.0, 4.0)
        
    if st.button("🚀 Spustit Backtest", type="primary"):
        if ticker_input:
            df_bt = get_market_data(ticker_input)
            if df_bt is not None and not df_bt.empty:
                with st.spinner("Simuluji obchody..."):
                    capital = 10000.0
                    risk_pct = 0.015
                    equity_curve = []
                    trades = []
                    in_trade = False
                    entry_price = 0; sl = 0; tp = 0; volume = 0
                    
                    for date, row in df_bt.iterrows():
                        if pd.isna(row['ATR']) or pd.isna(row['RSI']): continue
                        
                        if not in_trade:
                            trend_ok = (row['Close'] > row['Weekly_SMA_50']) if bt_mtf else True
                            if row['RSI'] < bt_rsi and row['Close'] < row['BB_Low'] and trend_ok:
                                entry_price = row['Close']
                                sl = entry_price - (bt_sl_atr * row['ATR'])
                                tp = entry_price + (bt_tp_atr * row['ATR'])
                                risk_amount = capital * risk_pct
                                volume = risk_amount / (entry_price - sl) if entry_price > sl else 0
                                in_trade = True
                        else:
                            if row['Low'] <= sl:
                                capital -= risk_amount
                                trades.append({'Výsledek': 'Ztráta', 'Zisk/Ztráta': -risk_amount})
                                in_trade = False
                            elif row['High'] >= tp:
                                profit = volume * (tp - entry_price)
                                capital += profit
                                trades.append({'Výsledek': 'Zisk', 'Zisk/Ztráta': profit})
                                in_trade = False
                                
                        equity_curve.append({'Datum': date, 'Kapitál': capital})
                    
                    st.subheader("📊 Výsledky simulace (Počáteční kapitál: 10 000)")
                    if len(trades) > 0:
                        df_trades = pd.DataFrame(trades)
                        win_rate = (len(df_trades[df_trades['Výsledek'] == 'Zisk']) / len(trades)) * 100
                        total_return = ((capital - 10000) / 10000) * 100
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Počet obchodů", len(trades))
                        m2.metric("Win Rate (Úspěšnost)", f"{win_rate:.1f} %")
                        m3.metric("Konečný kapitál", f"{capital:.2f}", f"{total_return:.1f} %")
                        
                        df_eq = pd.DataFrame(equity_curve)
                        fig_eq = go.Figure()
                        fig_eq.add_trace(go.Scatter(x=df_eq['Datum'], y=df_eq['Kapitál'], fill='tozeroy', line=dict(color='#00cc96')))
                        fig_eq.update_layout(title="Křivka růstu kapitálu (Equity Curve)", height=400)
                        st.plotly_chart(fig_eq, use_container_width=True)
                    else:
                        st.warning("Strategie nevygenerovala za poslední 2 roky žádný obchod.")

# ==========================================
# ZÁLOŽKA 6: FORWARD-TESTING (Signály Bota)
# ==========================================
with tab_forward:
    st.header("🚀 Papírové portfolio Bota (Forward-Testing)")
    st.markdown("Zde vidíš všechny signály, které tvůj bot na GitHubu vygeneroval a uložil do databáze.")
    
    if db_client:
        if st.button("🔄 Načíst signály od Bota"):
            try:
                res = db_client.table("bot_signals").select("*").order("Datum", desc=True).execute()
                if res.data:
                    df_signals = pd.DataFrame(res.data)
                    cols_to_show = [c for c in df_signals.columns if c not in ['id', 'created_at']]
                    st.dataframe(df_signals[cols_to_show], use_container_width=True)
                else:
                    st.info("Bot zatím nevygeneroval žádné signály.")
            except Exception as e:
                st.error(f"Chyba při načítání signálů: {e}")
    else:
        st.warning("Databáze není připojena.")

# ==========================================
# ZÁLOŽKA 4: CLOUDOVÝ DENÍK A DASHBOARD
# ==========================================
with tab_journal:
    st.header("📓 Můj obchodní deník a Statistiky")
    if db_client:
        col_db1, col_db2 = st.columns(2)
        with col_db1:
            if st.button("☁️ Odeslat nové obchody do cloudu", type="primary"):
                try:
                    for record in st.session_state.journal:
                        db_client.table("xtb_trades").insert(record).execute()
                    st.success("Data byla úspěšně odeslána do databáze!")
                    st.session_state.journal = [] 
                except Exception as e:
                    st.error(f"Chyba při odesílání: {e}")
        with col_db2:
            if st.button("📥 Načíst historii z cloudu"):
                try:
                    res = db_client.table("xtb_trades").select("*").execute()
                    if res.data:
                        st.session_state.journal = res.data
                        st.success(f"Úspěšně načteno {len(res.data)} obchodů z cloudu!")
                except Exception as e:
                    st.error(f"Chyba při načítání: {e}")
                    
    if len(st.session_state.journal) > 0:
        df_journal = pd.DataFrame(st.session_state.journal)
        df_journal['Risk'] = pd.to_numeric(df_journal['Risk'], errors='coerce').fillna(0)
        df_journal['Zisk'] = pd.to_numeric(df_journal['Zisk'], errors='coerce').fillna(0)
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Celkem obchodů", len(df_journal))
        m2.metric("Celkový Risk", f"{df_journal['Risk'].sum():.2f}")
        m3.metric("Potenciální Zisk", f"{df_journal['Zisk'].sum():.2f}")
        
        cols_to_show = [c for c in df_journal.columns if c not in ['id', 'created_at', 'RRR_num']]
        st.dataframe(df_journal[cols_to_show], use_container_width=True)

with tab_scanner:
    st.info("Skener je nyní plně automatizován přes tvého GitHub Bota.")
with tab_news:
    st.info("AI Zprávy fungují přes globální vyhledávání nahoře.")
