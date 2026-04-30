import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Terminál Pro", page_icon="📈", layout="wide")
st.title("📈 Můj XTB Trading Terminál")
st.markdown("Komplexní nástroj: Kalkulačka, Skener trhu, Zprávy a Cloudový deník.")

# --- INICIALIZACE PAMĚTI A DATABÁZE ---
if 'journal' not in st.session_state:
    st.session_state.journal = []

# Pokus o připojení k Supabase (pokud uživatel zadal klíče do Secrets)
supabase_url = st.secrets.get("SUPABASE_URL", None)
supabase_key = st.secrets.get("SUPABASE_KEY", None)
db_client = None
if supabase_url and supabase_key:
    try:
        db_client = create_client(supabase_url, supabase_key)
    except Exception:
        pass

# --- POMOCNÉ FUNKCE ---
@st.cache_data(ttl=300)
def get_market_data(ticker_symbol):
    df = pd.DataFrame()
    api_key = st.secrets.get("FINNHUB_API_KEY", None)
    
    if api_key and "=" not in ticker_symbol and "^" not in ticker_symbol:
        try:
            end = int(time.time())
            start = end - (6 * 30 * 24 * 60 * 60)
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker_symbol}&resolution=D&from={start}&to={end}&token={api_key}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({
                    "Open": res["o"], "High": res["h"], "Low": res["l"], "Close": res["c"]
                }, index=pd.to_datetime(res["t"], unit="s"))
        except Exception:
            pass
            
    if df.empty:
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="6mo")
        except Exception:
            return None
        
    if df is None or df.empty:
        return None
        
    try:
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        delta = df['Close'].diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        ema_gain = gain.ewm(com=13, adjust=False).mean()
        ema_loss = loss.ewm(com=13, adjust=False).mean()
        rs = ema_gain / ema_loss
        df['RSI'] = 100 - (100 / (1 + rs))
    except Exception:
        pass
    return df

@st.cache_data(ttl=3600)
def get_company_news(ticker_symbol):
    api_key = st.secrets.get("FINNHUB_API_KEY", None)
    if not api_key or "=" in ticker_symbol or "^" in ticker_symbol:
        return None
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker_symbol}&from={start_date}&to={end_date}&token={api_key}"
        res = requests.get(url).json()
        return res[:5] if isinstance(res, list) else None
    except Exception:
        return None

# --- HLAVNÍ NAVIGACE (ZÁLOŽKY) ---
tab_calc, tab_scanner, tab_news, tab_journal = st.tabs([
    "📊 Analýza & Kalkulačka", 
    "📡 Skener Trhu", 
    "📰 Zprávy a Fundamenty", 
    "📓 Obchodní deník"
])

# ==========================================
# ZÁLOŽKA 1: ANALÝZA A KALKULAČKA
# ==========================================
with tab_calc:
    st.header("🔍 Vyhledání a Risk Management")
    ticker_input = st.text_input("Zadej ticker (např. AAPL, TSLA, EURUSD=X):", value="AAPL").upper()
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
            fig.update_layout(title=f'Cenový vývoj {ticker_input}', xaxis_rangeslider_visible=False, height=400)
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
                st.toast('Obchod uložen do deníku!', icon='📓')

    with calc_tab2:
        st.info("Pro CFD zadej hodnotu 1 bodu. Logika výpočtu je stejná.")
        # Zde by byl kód pro CFD (zkráceno pro přehlednost)

# ==========================================
# ZÁLOŽKA 2: SKENER TRHU
# ==========================================
with tab_scanner:
    st.header("📡 Automatický Skener Trhu")
    st.markdown("Zadej seznam tickerů oddělených čárkou. Aplikace je projde a najde ty, které jsou přeprodané (RSI < 30) nebo překoupené (RSI > 70).")
    
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, TSLA, META, NVDA, AMD, INTC, NFLX"
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
                sma_200 = df_scan['SMA_200'].iloc[-1]
                
                trend = "Růst" if last_close > sma_200 else "Pokles"
                if last_rsi < 30:
                    signal = "🟢 PŘEPRODÁNO (Koupit?)"
                elif last_rsi > 70:
                    signal = "🔴 PŘEKOUPENO (Prodat?)"
                else:
                    signal = "⚪ Neutrální"
                    
                results.append({"Ticker": t, "Cena": round(last_close, 2), "RSI": round(last_rsi, 1), "Trend (vs SMA200)": trend, "Signál": signal})
            
            progress_bar.progress((i + 1) / len(tickers_to_scan))
            time.sleep(0.5) # Pauza kvůli limitům API
            
        status_text.text("Skenování dokončeno!")
        if results:
            st.dataframe(pd.DataFrame(results), use_container_width=True)

# ==========================================
# ZÁLOŽKA 3: ZPRÁVY A FUNDAMENTY
# ==========================================
with tab_news:
    st.header(f"📰 Nejnovější zprávy pro {ticker_input}")
    if not st.secrets.get("FINNHUB_API_KEY"):
        st.warning("⚠️ Pro zobrazení zpráv je potřeba nastavit FINNHUB_API_KEY v sekci Secrets.")
    else:
        news_data = get_company_news(ticker_input)
        if news_data:
            for article in news_data:
                with st.container():
                    st.subheader(article.get('headline', 'Bez titulku'))
                    st.write(article.get('summary', ''))
                    st.markdown(f"[Přečíst celý článek zde]({article.get('url', '#')})")
                    st.caption(f"Zdroj: {article.get('source', 'Neznámý')} | Vydáno: {datetime.fromtimestamp(article.get('datetime', 0)).strftime('%Y-%m-%d %H:%M')}")
                    st.divider()
        else:
            st.info("Žádné aktuální zprávy nebyly nalezeny nebo ticker není podporován (např. Forex).")

# ==========================================
# ZÁLOŽKA 4: OBCHODNÍ DENÍK A CLOUD
# ==========================================
with tab_journal:
    st.header("📓 Můj obchodní deník")
    
    # Zobrazení dat z paměti
    if len(st.session_state.journal) > 0:
        df_journal = pd.DataFrame(st.session_state.journal)
        st.dataframe(df_journal, use_container_width=True)
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            csv = df_journal.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Stáhnout jako CSV", data=csv, file_name="denik.csv", mime="text/csv")
        with col_btn2:
            if st.button("Vymazat lokální deník"):
                st.session_state.journal = []
                st.rerun()
    else:
        st.info("Lokální deník je zatím prázdný.")

    st.divider()
    st.subheader("☁️ Zálohování do cloudu (Supabase)")
    if db_client:
        st.success("✅ Připojeno k databázi Supabase!")
        if st.button("Odeslat lokální deník do cloudu"):
            try:
                for record in st.session_state.journal:
                    db_client.table("trades").insert(record).execute()
                st.success("Data byla úspěšně odeslána do databáze!")
            except Exception as e:
                st.error(f"Chyba při odesílání: {e}")
    else:
        st.warning("Databáze není připojena. Pro trvalé ukládání si vytvoř účet na Supabase.com a vlož klíče do Streamlit Secrets.")
