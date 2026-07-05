import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Terminál Pro", page_icon="📈", layout="wide")
st.title("📈 Můj XTB Trading Terminál (Hedge Fund Edice)")
st.markdown("Kalkulačka rizik, Adaptivní Skener Všeho, Excel Audit, Backtest Stroj Času.")

# --- INICIALIZACE PAMĚTI ---
if 'journal' not in st.session_state:
    st.session_state.journal = []

# --- DATABÁZE TICKERŮ PRO SKENER (MULTI-ASSET) ---
TICKER_DATABASE = {
    "🇨🇿 ČR Akcie (BCPP)": ["CEZ.PR", "MONET.PR", "KOFOL.PR", "VIG.PR", "TABAK.PR"],
    "🇵🇱 Polsko (GPW)": ["PKO.WA", "PKN.WA", "ALE.WA", "KGH.WA", "PZU.WA", "CDR.WA", "DNP.WA"],
    "🇪🇺 Evropa Mainstream": ["BMW.DE", "SAP.DE", "SIE.DE", "AIR.PA", "MC.PA", "ASML.AS", "VOW3.DE"],
    "🇺🇸 US Akcie (Výběr)": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "WMT", "DIS", "XOM", "KO"],
    "🌍 Globální ETF": ["SPY", "QQQ", "IWM", "EEM", "VGK", "IAU", "VNQ"],
    "💱 Forex (Měny)": ["EURUSD=X", "USDJPY=X", "GBPUSD=X", "AUDUSD=X", "USDCAD=X", "EURGBP=X"],
    "🔥 Komodity & Indexy (CFD)": ["GC=F", "SI=F", "CL=F", "NG=F", "^GSPC", "^IXIC", "^GDAXI"],
    "₿ Kryptoměny (CFD)": ["BTC-USD", "ETH-USD", "SOL-USD"]
}

# --- SWAPOVÁ DATABÁZE (Varování pro Forex) ---
SWAP_WARNINGS = {
    "USDJPY=X": {"status": "⚠️ Pozor na Short pozice", "note": "Držení Short pozice přes noc má vysoký záporný swap kvůli úrokovému diferenciálu."},
    "EURUSD=X": {"status": "ℹ️ Nízké swapy", "note": "Swapy jsou relativně stabilní, vhodné pro swing na 1-3 dny."},
    "GBPUSD=X": {"status": "⚠️ Střední swapy", "note": "Při držení Long pozice sleduj vyhlášování BOE."},
    "EURGBP=X": {"status": "ℹ️ Nízké swapy", "note": "Vhodné pro trading v pásmu."}
}

# --- POMOCNÁ FUNKCE PRO VÝPOČET ADX (Směrový index pro trend) ---
def calculate_adx(df, period=14):
    df = df.copy()
    df['plus_DM'] = df['High'].diff()
    df['minus_DM'] = df['Low'].diff().shift(-1) # Hledání low posunu
    df['plus_DM'] = np.where((df['plus_DM'] > df['minus_DM']) & (df['plus_DM'] > 0), df['plus_DM'], 0)
    df['minus_DM'] = np.where((df['minus_DM'] > df['plus_DM']) & (df['minus_DM'] > 0), df['minus_DM'], 0)
    
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    df['TR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    
    df['ATR_adx'] = df['TR'].rolling(window=period).mean()
    df['plus_DI'] = 100 * (df['plus_DM'].rolling(window=period).mean() / df['ATR_adx'])
    df['minus_DI'] = 100 * (df['minus_DM'].rolling(window=period).mean() / df['ATR_adx'])
    
    df['DX'] = (np.abs(df['plus_DI'] - df['minus_DI']) / (df['plus_DI'] + df['minus_DI'])) * 100
    df['ADX'] = df['DX'].rolling(window=period).mean()
    return df['ADX']

# --- FUNKCE PRO STAŽENÍ DAT A INDIKÁTORY ---
@st.cache_data(ttl=300)
def get_market_data(ticker_symbol):
    try:
        yf_ticker = ticker_symbol
        if "/" in ticker_symbol:
            yf_ticker = ticker_symbol.replace("/", "") + "=X"
            
        df = yf.Ticker(yf_ticker).history(period="2y")
        
        if df is None or df.empty:
            return None
            
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Technické indikátory
        df['SMA_50'] = df['Close'].rolling(window=min(50, len(df))).mean()
        df['SMA_200'] = df['Close'].rolling(window=min(200, len(df))).mean()
        
        df_weekly = df.resample('W').agg({'Close': 'last'})
        df_weekly['SMA_50_W'] = df_weekly['Close'].rolling(window=min(50, len(df_weekly))).mean()
        df['Weekly_SMA_50'] = df_weekly['SMA_50_W'].reindex(df.index, method='ffill')
        
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rs = np.where(loss == 0, np.nan, gain / loss)
        df['RSI'] = np.where(loss == 0, 100, 100 - (100 / (1 + rs)))
        
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Up'] = df['BB_Mid'] + (df['BB_Std'] * 2)
        df['BB_Low'] = df['BB_Mid'] - (df['BB_Std'] * 2)

        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
        
        # Trendový ADX filtr
        df['ADX'] = calculate_adx(df)
        
        return df
    except Exception:
        return None

# --- GLOBÁLNÍ VYHLEDÁVÁNÍ ---
st.divider()
col_search, _ = st.columns([1, 2])
with col_search:
    ticker_input = st.text_input("🔍 Rychlá analýza jednoho instrumentu (např. AAPL, KOFOL.PR, USDJPY=X):", value="USDJPY=X").strip()

st.write("") 

tab_calc, tab_scanner, tab_journal, tab_backtest = st.tabs([
    "📊 Kalkulačka, Swapy & Break-Even", "📡 Multi-Asset Skener (Adaptivní)", "📓 Deník & Excel Audit z XTB", "⏪ Backtest Stroj Času"
])

# ==========================================
# ZÁLOŽKA 1: KALKULAČKA, SWAPY A BREAK-EVEN
# ==========================================
with tab_calc:
    current_price = 0.0
    atr = 1.0 
    
    if ticker_input:
        df = get_market_data(ticker_input)
        if df is not None and not df.empty:
            current_price = float(df['Close'].iloc[-1])
            atr = float(df['ATR'].iloc[-1]) if not pd.isna(df['ATR'].iloc[-1]) else 1.0
            st.success(f"✅ Aktuální tržní cena **{ticker_input}**: {current_price:.4f}")
            
            # Graf
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Cena'))
            if 'SMA_50' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1), name='SMA 50'))
            if 'BB_Low' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['BB_Low'], line=dict(color='gray', width=1, dash='dot'), name='BB Dolní'))
            fig.update_layout(xaxis_rangeslider_visible=False, height=400)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("🛡️ Pokročilý výpočet pozice s ochranou před swapy a Break-Even triggerem")
    calc_type = st.radio("Typ instrumentu:", ["📈 Akcie a ETF", "💱 CFD / Forex / Komodity"], horizontal=True)

    # Detekce swapového rizika
    if ticker_input in SWAP_WARNINGS or (ticker_input.replace("/", "") + "=X") in SWAP_WARNINGS:
        tk_key = ticker_input if ticker_input in SWAP_WARNINGS else ticker_input.replace("/", "") + "=X"
        st.warning(f"{SWAP_WARNINGS[tk_key]['status']}: {SWAP_WARNINGS[tk_key]['note']}")
        st.info("💡 Pro tento pár byla strategie automaticky upravena na rychlý odraz (RRR 1:1, držení max 48 hodin).")
        default_tp_mult = 2.0
        default_sl_mult = 2.0
    else:
        default_tp_mult = 4.0
        default_sl_mult = 2.0

    c1, c2 = st.columns(2)
    with c1:
        acc_bal = st.number_input("Zůstatek na účtu (CZK):", min_value=100.0, value=33000.0, step=1000.0)
        risk_pct = st.number_input("Risk na jeden obchod (%):", min_value=0.1, max_value=5.0, value=1.5, step=0.1)
    with c2:
        entry = st.number_input("Vstupní cena (Entry):", value=current_price if current_price > 0 else 100.0, format="%.4f")
        sl_mult = st.slider("Stop Loss (násobek ATR):", 1.0, 4.0, default_sl_mult)
        tp_mult = st.slider("Take Profit (násobek ATR):", 1.0, 8.0, default_tp_mult)

    calculated_sl = entry - (sl_mult * atr)
    calculated_tp = entry + (tp_mult * atr)
    be_trigger = entry + (1.0 * atr) # Break-even trigger při +1 ATR
    
    st.write(f"📐 **Navržené úrovně:** Stop Loss: **{calculated_sl:.4f}** | Take Profit: **{calculated_tp:.4f}**")

    if st.button("🚀 Spočítat parametry pozice", type="primary"):
        risk_amount = acc_bal * (risk_pct / 100)
        risk_per_unit = abs(entry - calculated_sl)
        
        if calc_type == "📈 Akcie a ETF":
            volume = risk_amount / risk_per_unit if risk_per_unit > 0 else 0
            total_profit = volume * abs(calculated_tp - entry)
            st.metric("Objem k nákupu (Kusy)", f"{volume:.2f} ks")
        else:
            volume = risk_amount / (risk_per_unit * 10) if risk_per_unit > 0 else 0
            total_profit = volume * abs(calculated_tp - entry) * 10
            st.metric("Velikost pozice (Loty)", f"{volume:.3f} Lotu")
            
        r1, r2, r3 = st.columns(3)
        r1.metric("Max. povolená ztráta", f"{risk_amount:.2f} CZK")
        r2.metric("Potenciální zisk", f"{total_profit:.2f} CZK")
        r3.metric("Risk:Reward Poměr", f"1 : {(tp_mult/sl_mult):.2f}")
        
        st.info(f"🛡️ **Pravidlo Break-Even:** Jakmile cena dosáhne **{be_trigger:.4f}** (+1 ATR), okamžitě posuň Stop Loss na hodnotu tvého vstupu ({entry:.4f}). Tím odstraníš riziko ztráty.")

# ==========================================
# ZÁLOŽKA 2: MULTI-ASSET ADAPTIVNÍ SKENER
# ==========================================
with tab_scanner:
    st.header("📡 Adaptivní Skener XTB Instrumentů (Hedge Fund Edice)")
    st.markdown("Skener se automaticky adaptuje na volatilitu a trend pomocí indikátoru ADX a ATR.")
    
    selected_category = st.selectbox("Vyber segment trhu ke skenování:", list(TICKER_DATABASE.keys()))
    tickers_to_scan = TICKER_DATABASE[selected_category]
    
    if st.button(f"🔍 Spustit adaptivní sken pro {selected_category}"):
        scan_results = []
        progress_bar = st.progress(0)
        
        for idx, ticker in enumerate(tickers_to_scan):
            df_scan = get_market_data(ticker)
            if df_scan is not None and not df_scan.empty:
                last_row = df_scan.iloc[-1]
                rsi_val = last_row['RSI'] if 'RSI' in df_scan.columns else 50
                close_val = last_row['Close']
                bb_low_val = last_row['BB_Low'] if 'BB_Low' in df_scan.columns else 0
                adx_val = last_row['ADX'] if 'ADX' in df_scan.columns else 20
                atr_val = last_row['ATR'] if 'ATR' in df_scan.columns else 1.0
                atr_mean = df_scan['ATR'].mean()
                
                # --- FLEXIBILNÍ LOGIKA VSTUPU ---
                # 1. Adaptivní RSI podle volatility (ATR)
                rsi_threshold = 30
                if atr_val > (atr_mean * 1.3):  # Pokud je na trhu extrémní panika a vysoké ATR
                    rsi_threshold = 20          # Zpřísníme vstup, nekupujeme padající nůž příliš brzy
                
                # 2. Market Regime Filter (ADX)
                if adx_val > 25:
                    regime = "📈 Silný Trend (Pozor na odrazy!)"
                    # V silném trendu vyžadujeme ještě hlubší propad
                    is_buy = (rsi_val < (rsi_threshold - 5)) and (close_val < (bb_low_val * 0.99))
                else:
                    regime = "⚖️ Pásmo / Chop (Odrazy fungují skvěle)"
                    is_buy = (rsi_val < rsi_threshold) and (close_val < bb_low_val)
                
                status = "⚪ Neutrální"
                if is_buy:
                    status = "🔥 ADAPTIVNÍ NÁKUP (Podmínky splněny)"
                elif rsi_val < (rsi_threshold + 5):
                    status = "61 Blízko nákupní zóny"
                elif rsi_val > 70:
                    status = "🔴 Překoupeno (Nekupovat)"
                    
                scan_results.append({
                    "Ticker": ticker,
                    "Cena": round(close_val, 2),
                    "RSI (14)": round(rsi_val, 1),
                    "ADX (Trend)": round(adx_val, 1) if not pd.isna(adx_val) else "N/A",
                    "Tržní režim": regime,
                    "Rozhodnutí asistenta": status
                })
            progress_bar.progress((idx + 1) / len(tickers_to_scan))
            
        df_results = pd.DataFrame(scan_results)
        st.dataframe(df_results, use_container_width=True)

# ==========================================
# ZÁLOŽKA 3: DENÍK A REÁLNÝ AUDIT Z EXCELU XTB
# ==========================================
with tab_journal:
    st.header("📓 Profesionální Audit tvého XTB Účtu")
    st.markdown("Nahraj svůj kompletní `.xlsx` report stažený z XTB platformy (Záložka Historie -> Export).")
    
    uploaded_file = st.file_uploader("Nahraj XTB Excel soubor (.xlsx)", type=["xlsx"])
    
    if uploaded_file is not None:
        try:
            df_raw = pd.read_excel(uploaded_file, sheet_name='CLOSED POSITION HISTORY')
            header_row_idx = None
            for idx in range(len(df_raw)):
                row_vals = df_raw.iloc[idx].astype(str).tolist()
                if any('Position' in val or 'Symbol' in val for val in row_vals):
                    header_row_idx = idx
                    break
                    
            if header_row_idx is not None:
                df_closed = pd.read_excel(uploaded_file, sheet_name='CLOSED POSITION HISTORY', skiprows=header_row_idx + 1)
                df_closed.columns = df_closed.columns.str.strip()
                df_closed = df_closed.dropna(subset=['Position', 'Gross P/L'])
                df_closed['Gross P/L'] = pd.to_numeric(df_closed['Gross P/L'], errors='coerce').fillna(0)
                
                # Výpočty statistik
                ziskove = df_closed[df_closed['Gross P/L'] > 0]
                ztratove = df_closed[df_closed['Gross P/L'] < 0]
                
                win_rate = (len(ziskove) / len(df_closed)) * 100 if len(df_closed) > 0 else 0
                avg_win = ziskove['Gross P/L'].mean() if len(ziskove) > 0 else 0
                avg_loss = abs(ztratove['Gross P/L'].mean()) if len(ztratove) > 0 else 0
                real_rrr = avg_win / avg_loss if avg_loss > 0 else 0
                profit_factor = ziskove['Gross P/L'].sum() / abs(ztratove['Gross P/L'].sum()) if ztratove['Gross P/L'].sum() != 0 else 1.0
                net_pl = df_closed['Gross P/L'].sum()
                
                # Karty s metrikami
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Uzavřené obchody", len(df_closed))
                m2.metric("Win Rate", f"{win_rate:.1f} %")
                m3.metric("Profit Factor", f"{profit_factor:.2f}")
                m4.metric("Čistý výsledek", f"{net_pl:.2f} CZK")
                
                st.info(f"📊 **Průměrný ziskový obchod:** {avg_win:.2f} CZK | **Průměrný ztrátový obchod:** -{avg_loss:.2f} CZK | **Reálné RRR:** 1 : {real_rrr:.2f}")
                
                if profit_factor > 1.4:
                    st.success("🎯 **Hedge Fund Zhodnocení:** Strategie vykazuje silnou ziskovost. Risk management funguje správně.")
                elif profit_factor >= 1.0:
                    st.warning("⚖️ **Hedge Fund Zhodnocení:** Účet je zhruba na svém (Break-Even). Doporučuje se zvýšit cílové RRR v kalkulačce.")
                else:
                    st.error("📉 **Hedge Fund Zhodnocení:** Systém pálí kapitál. Okamžitě začni dodržovat pevné Stop Lossy podle doporučení bota.")
                
                # Chronologický graf
                fig_xtb = go.Figure()
                fig_xtb.add_trace(go.Bar(
                    x=df_closed['Close time'],
                    y=df_closed['Gross P/L'],
                    marker_color=np.where(df_closed['Gross P/L'] >= 0, '#00cc96', '#ef553b'),
                    name="P/L"
                ))
                fig_xtb.update_layout(title="Chronologický vývoj uzavřených výsledků", height=380, xaxis_title="Čas uzavření", yaxis_title="CZK")
                st.plotly_chart(fig_xtb, use_container_width=True)
                
                st.dataframe(df_closed[['Position', 'Symbol', 'Type', 'Volume', 'Open price', 'Close price', 'Gross P/L', 'Comment']], use_container_width=True)
            else:
                st.error("V souboru nebyla nalezena tabulka s historií pozic. Ujisti se, že nahráváš správný list.")
        except Exception as e:
            st.error(f"Chyba při zpracování souboru: {e}")

# ==========================================
# ZÁLOŽKA 4: BACKTEST STROJ ČASU
# ==========================================
with tab_backtest:
    st.header("⏪ Otestuj strategii na historii trhu")
    bt_ticker = st.text_input("Zadej libovolný ticker pro backtest (např. USDJPY=X, EURUSD=X, GOLD):", value="USDJPY=X")
    
    if st.button("🚀 Spustit historickou simulaci"):
        df_bt = get_market_data(bt_ticker)
        if df_bt is not None and not df_bt.empty:
            with st.spinner("Počítám historii obchodů..."):
                capital = 10000.0
                trades = []
                in_trade = False
                
                df_bt = df_bt.dropna(subset=['ATR', 'RSI', 'BB_Low', 'ADX'])
                
                for date, row in df_bt.iterrows():
                    if not in_trade:
                        # Simulace naší adaptivní strategie (Nákup v pásmu při ADX < 25)
                        if row['RSI'] < 30 and row['Close'] < row['BB_Low'] and row['ADX'] < 25:
                            entry_p = row['Close']
                            sl_p = entry_p - (2 * row['ATR'])
                            tp_p = entry_p + (2 * row['ATR'])  # Poměr 1:1 pro bleskový odraz z pásma
                            in_trade = True
                    else:
                        if row['Low'] <= sl_p:
                            capital -= 150  # Risk 1.5 % z fixního kapitálu
                            trades.append(-150)
                            in_trade = False
                        elif row['High'] >= tp_p:
                            capital += 150
                            trades.append(150)
                            in_trade = False
                            
                st.success(f"Simulace dokončena. Konečný virtuální kapitál: {capital:.2f} USD (Počet vygenerovaných obchodů: {len(trades)})")
