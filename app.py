import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta
from supabase import create_client, Client
import google.generativeai as genai

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Terminál Pro", page_icon="📈", layout="wide")
st.title("📈 Můj XTB Trading Terminál (Gemini AI Edice)")
st.markdown("Komplexní nástroj: Kalkulačka, Pokročilý Skener, Google Gemini Zprávy a Cloudový deník.")

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
    
    # 1. Finnhub
    finnhub_key = st.secrets.get("FINNHUB_API_KEY", None)
    if finnhub_key and "=" not in ticker_symbol and "^" not in ticker_symbol and "/" not in ticker_symbol:
        try:
            end = int(time.time())
            start = end - (6 * 30 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker_symbol}&resolution=D&from={start}&to={end}&token={finnhub_key}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({
                    "Open": res["o"], "High": res["h"], "Low": res["l"], "Close": res["c"]
                }, index=pd.to_datetime(res["t"], unit="s"))
                df = df.sort_index()
        except Exception:
            pass

    # 2. Twelve Data
    twelve_key = st.secrets.get("TWELVEDATA_API_KEY", None)
    if df.empty and twelve_key:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={ticker_symbol}&interval=1day&outputsize=130&apikey={twelve_key}"
            res = requests.get(url).json()
            if "values" in res:
                df_td = pd.DataFrame(res["values"])
                df_td['datetime'] = pd.to_datetime(df_td['datetime'])
                df_td = df_td.set_index('datetime').astype(float)
                df_td = df_td.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
                df = df_td.sort_index()
        except Exception:
            pass
            
    # 3. Yahoo Finance
    if df.empty:
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="6mo")
        except Exception:
            return None
        
    if df is None or df.empty:
        return None
        
    # --- VÝPOČET POKROČILÝCH INDIKÁTORŮ ---
    try:
        # SMA
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
        
        # MACD
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # Bollinger Bands (BB)
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Up'] = df['BB_Mid'] + (df['BB_Std'] * 2)
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    except Exception:
        pass
    return df

@st.cache_data(ttl=3600)
def get_company_news(ticker_symbol):
    api_key = st.secrets.get("FINNHUB_API_KEY", None)
    if not api_key or "=" in ticker_symbol or "^" in ticker_symbol or "/" in ticker_symbol:
        return None
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker_symbol}&from={start_date}&to={end_date}&token={api_key}"
        res = requests.get(url).json()
        return res[:5] if isinstance(res, list) else None
    except Exception:
        return None

# --- HLAVNÍ NAVIGACE ---
tab_calc, tab_scanner, tab_news, tab_journal = st.tabs([
    "📊 Analýza & Kalkulačka", 
    "📡 Pokročilý Skener", 
    "🤖 AI Zprávy", 
    "📓 Cloudový Deník"
])

# ==========================================
# ZÁLOŽKA 1: ANALÝZA A KALKULAČKA
# ==========================================
with tab_calc:
    st.header("🔍 Vyhledání a Risk Management")
    ticker_input = st.text_input("Zadej ticker (např. AAPL, EUR/USD, SPX):", value="AAPL").upper()
    current_price = 0.0

    if ticker_input:
        df = get_market_data(ticker_input)
        if df is not None and not df.empty:
            current_price = float(df['Close'].iloc[-1])
            st.success(f"✅ Aktuální cena **{ticker_input}**: {current_price:.2f}")
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Cena'))
            if 'SMA_50' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1), name='SMA 50'))
            if 'SMA_200' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='orange', width=2), name='SMA 200'))
            if 'BB_Up' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Up'], line=dict(color='gray', width=1, dash='dot'), name='BB Horní'))
                fig.add_trace(go.Scatter(x=df.index, y=df['BB_Low'], line=dict(color='gray', width=1, dash='dot'), name='BB Dolní'))
                
            fig.update_layout(title=f'Cenový vývoj {ticker_input}', xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("⚠️ Data se nepodařilo načíst. Zadej cenu do kalkulačky ručně.")

    st.divider()
    calc_tab1, calc_tab2 = st.tabs(["📈 Akcie a ETF (Kusy)", "💱 CFD / Forex (Loty)"])

    with calc_tab1:
        c1, c2 = st.columns(2)
        with c1:
            acc_bal = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0)
            risk_pct = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1)
        with c2:
            entry = st.number_input("Vstupní cena (Entry):", min_value=0.0001, value=current_price if current_price > 0 else 150.0, step=1.0)
            sl = st.number_input("Stop Loss (SL):", min_value=0.0001, value=(current_price * 0.95) if current_price > 0 else 140.0, step=1.0)
            tp = st.number_input("Take Profit (TP):", min_value=0.0001, value=(current_price * 1.10) if current_price > 0 else 170.0, step=1.0)

        if st.button("Spočítat (Akcie)", type="primary"):
            if entry == sl:
                st.error("Vstup a SL nesmí být stejné!")
            else:
                risk_amount = acc_bal * (risk_pct / 100)
                risk_per_share = abs(entry - sl)
                profit_per_share = abs(tp - entry)
                position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0
                total_profit = position_size * profit_per_share
                rrr = profit_per_share / risk_per_share if risk_per_share > 0 else 0
                
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Max. Ztráta", f"{risk_amount:.2f}")
                r2.metric("Potenciální Zisk", f"{total_profit:.2f}")
                r3.metric("Velikost pozice (Kusy)", f"{position_size:.2f}")
                r4.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Doporučeno" if rrr >= 1.5 else "Nedoporučeno")
                
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input, "Typ": "Akcie",
                    "Vstup": entry, "SL": sl, "TP": tp, "Objem": round(position_size, 2),
                    "Risk": round(risk_amount, 2), "Zisk": round(total_profit, 2), "RRR": f"1:{rrr:.2f}"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod uložen do lokálního deníku!', icon='📓')

    with calc_tab2:
        st.info("Pro CFD zadej hodnotu 1 bodu. Logika výpočtu je stejná.")
        c3, c4 = st.columns(2)
        with c3:
            acc_bal_cfd = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0, key="bal_cfd")
            risk_pct_cfd = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1, key="risk_cfd")
        with c4:
            entry_cfd = st.number_input("Vstupní cena (Entry):", min_value=0.00001, value=current_price if current_price > 0 else 1.1000, format="%.5f", key="entry_cfd")
            sl_cfd = st.number_input("Cena Stop Loss (SL):", min_value=0.00001, value=(current_price * 0.99) if current_price > 0 else 1.0950, format="%.5f", key="sl_cfd")
            tp_cfd = st.number_input("Take Profit (TP):", min_value=0.00001, value=(current_price * 1.02) if current_price > 0 else 1.1100, format="%.5f", key="tp_cfd")
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
                res8.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Doporučeno" if rrr >= 1.5 else "Nedoporučeno")
                
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input, "Typ": "CFD/Forex",
                    "Vstup": entry_cfd, "SL": sl_cfd, "TP": tp_cfd, "Objem": round(lot_size, 2),
                    "Risk": round(risk_amount, 2), "Zisk": round(total_profit, 2), "RRR": f"1:{rrr:.2f}"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod uložen do lokálního deníku!', icon='📓')

# ==========================================
# ZÁLOŽKA 2: POKROČILÝ SKENER TRHU
# ==========================================
with tab_scanner:
    st.header("📡 Pokročilý Skener Trhu")
    st.markdown("Skener nyní vyhodnocuje RSI, MACD momentum a Bollingerova pásma.")
    
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, TSLA, EUR/USD, GBP/USD, SPX"
    scan_input = st.text_area("Tickery ke skenování:", value=default_tickers)
    
    if st.button("Spustit Skener", type="primary"):
        tickers_to_scan = [t.strip().upper() for t in scan_input.split(",") if t.strip()]
        results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, t in enumerate(tickers_to_scan):
            status_text.text(f"Skenuji {t} ({i+1}/{len(tickers_to_scan)})...")
            df_scan = get_market_data(t)
            if df_scan is not None and not df_scan.empty and 'RSI' in df_scan.columns:
                last_close = df_scan['Close'].iloc[-1]
                last_rsi = df_scan['RSI'].iloc[-1]
                macd = df_scan['MACD'].iloc[-1] if 'MACD' in df_scan.columns else 0
                macd_sig = df_scan['MACD_Signal'].iloc[-1] if 'MACD_Signal' in df_scan.columns else 0
                bb_up = df_scan['BB_Up'].iloc[-1] if 'BB_Up' in df_scan.columns else 0
                bb_low = df_scan['BB_Low'].iloc[-1] if 'BB_Low' in df_scan.columns else 0
                
                # Vyhodnocení RSI
                if last_rsi < 30: rsi_sig = "🟢 Přeprodáno"
                elif last_rsi > 70: rsi_sig = "🔴 Překoupeno"
                else: rsi_sig = "⚪ Neutrální"
                
                # Vyhodnocení MACD
                macd_sig_text = "🟢 Býčí (Růst)" if macd > macd_sig else "🔴 Medvědí (Pokles)"
                
                # Vyhodnocení Bollinger Bands
                if last_close < bb_low: bb_sig_text = "🟢 Pod dolní (Sleva)"
                elif last_close > bb_up: bb_sig_text = "🔴 Nad horní (Drahé)"
                else: bb_sig_text = "⚪ Uvnitř pásem"
                    
                results.append({
                    "Ticker": t, 
                    "Cena": round(last_close, 2), 
                    "RSI": f"{round(last_rsi, 1)} ({rsi_sig})", 
                    "MACD Momentum": macd_sig_text, 
                    "Bollinger Bands": bb_sig_text
                })
            
            progress_bar.progress((i + 1) / len(tickers_to_scan))
            time.sleep(0.5)
            
        status_text.text("Skenování dokončeno!")
        if results:
            st.dataframe(pd.DataFrame(results), use_container_width=True)

# ==========================================
# ZÁLOŽKA 3: AI ZPRÁVY A FUNDAMENTY
# ==========================================
with tab_news:
    st.header(f"🤖 AI Analýza zpráv pro {ticker_input}")
    gemini_key = st.secrets.get("GEMINI_API_KEY", None)
    
    if not st.secrets.get("FINNHUB_API_KEY"):
        st.warning("⚠️ Pro stahování zpráv je potřeba nastavit FINNHUB_API_KEY.")
    else:
        news_data = get_company_news(ticker_input)
        if news_data:
            # --- AI ANALÝZA PŘES GOOGLE GEMINI ---
            if gemini_key:
                st.subheader("🧠 Shrnutí od Google Gemini AI")
                st.info("💡 Google poskytuje 5 dotazů za minutu zdarma. Kliknutím na tlačítko níže spustíš analýzu.")
                
                if st.button("✨ Vygenerovat AI Shrnutí zpráv", type="primary"):
                    with st.spinner("Gemini právě čte a analyzuje zprávy..."):
                        try:
                            # Nastavení Gemini klíče
                            genai.configure(api_key=gemini_key)
                            # Použití aktuálního modelu 2.5 Flash
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            
                            news_text = "\n".join([f"- {a.get('headline')}: {a.get('summary')}" for a in news_data])
                            prompt = f"Přečti si tyto aktuální zprávy o {ticker_input}:\n{news_text}\n\nNapiš česky velmi stručné shrnutí (max 3 věty) toho nejdůležitějšího. Na úplný konec napiš na nový řádek 'Celkový sentiment: Pozitivní / Negativní / Neutrální'."
                            
                            response = model.generate_content(prompt)
                            st.success("✅ Analýza dokončena!")
                            st.write(response.text)
                        except Exception as e:
                            st.error(f"Nepodařilo se spojit s Gemini AI: {e}")
            else:
                st.info("💡 Tip: Pokud do Streamlit Secrets přidáš GEMINI_API_KEY, umělá inteligence ti tyto zprávy automaticky shrne a vyhodnotí jejich sentiment!")
            
            st.divider()
            st.subheader("📰 Původní články")
            for article in news_data:
                with st.container():
                    st.write(f"**{article.get('headline', 'Bez titulku')}**")
                    st.caption(f"Zdroj: {article.get('source', 'Neznámý')} | [Přečíst celý článek]({article.get('url', '#')})")
        else:
            st.info("Žádné aktuální zprávy nebyly nalezeny nebo ticker není podporován (např. Forex).")

# ==========================================
# ZÁLOŽKA 4: CLOUDOVÝ DENÍK
# ==========================================
with tab_journal:
    st.header("📓 Můj obchodní deník (Supabase)")
    
    if db_client:
        st.success("✅ Připojeno k databázi Supabase!")
        
        col_db1, col_db2 = st.columns(2)
        with col_db1:
            if st.button("☁️ Odeslat nové obchody do cloudu", type="primary"):
                try:
                    for record in st.session_state.journal:
                        db_client.table("xtb_trades").insert(record).execute()
                    st.success("Data byla úspěšně odeslána do databáze!")
                    st.session_state.journal = [] # Vymažeme lokální paměť po odeslání
                except Exception as e:
                    st.error(f"Chyba při odesílání: {e}")
                    
        with col_db2:
            if st.button("📥 Načíst historii z cloudu"):
                try:
                    res = db_client.table("xtb_trades").select("*").execute()
                    if res.data:
                        st.session_state.journal = res.data
                        st.success(f"Úspěšně načteno {len(res.data)} obchodů z cloudu!")
                    else:
                        st.info("Databáze je zatím prázdná.")
                except Exception as e:
                    st.error(f"Chyba při načítání: {e}")
    else:
        st.warning("Databáze není připojena. Zkontroluj SUPABASE_URL a SUPABASE_KEY.")

    st.divider()
    
    if len(st.session_state.journal) > 0:
        df_journal = pd.DataFrame(st.session_state.journal)
        # Skryjeme sloupec 'id' a 'created_at' pokud přišly ze Supabase, ať je tabulka hezčí
        cols_to_show = [c for c in df_journal.columns if c not in ['id', 'created_at']]
        st.dataframe(df_journal[cols_to_show], use_container_width=True)
        
        csv = df_journal[cols_to_show].to_csv(index=False).encode('utf-8')
        st.download_button("📥 Stáhnout tabulku jako CSV", data=csv, file_name="denik.csv", mime="text/csv")
    else:
        st.info("Tabulka je prázdná. Spočítej si obchod nebo klikni na 'Načíst historii z cloudu'.")
