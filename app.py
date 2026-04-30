import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Analytický Asistent", page_icon="📈", layout="wide")

st.title("📈 Můj XTB Analytický Asistent (Pro verze)")
st.markdown("Komplexní nástroj pro analýzu trhu a výpočet Risk Managementu pro Akcie, ETF i CFD.")
st.divider()

# --- FUNKCE PRO STAŽENÍ DAT A VÝPOČET INDIKÁTORŮ ---
@st.cache_data(ttl=300)
def get_market_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    # Stáhneme data za posledních 6 měsíců
    df = stock.history(period="6mo")
    
    if df.empty:
        return None
    
    # Výpočet klouzavých průměrů (SMA 50 a SMA 200)
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    
    # Výpočet RSI (Relative Strength Index)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    ema_gain = gain.ewm(com=13, adjust=False).mean()
    ema_loss = loss.ewm(com=13, adjust=False).mean()
    rs = ema_gain / ema_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# --- 1. MODUL: VYHLEDÁNÍ A ANALÝZA ---
st.header("🔍 1. Vyhledání a Technická analýza")
ticker_input = st.text_input("Zadej ticker (např. AAPL, TSLA, EURUSD=X pro Forex, ^GSPC pro S&P 500):", value="AAPL").upper()

current_price = 0.0

if ticker_input:
    try:
        df = get_market_data(ticker_input)
        
        if df is not None:
            current_price = float(df['Close'].iloc[-1])
            current_rsi = float(df['RSI'].iloc[-1])
            current_sma50 = float(df['SMA_50'].iloc[-1])
            current_sma200 = float(df['SMA_200'].iloc[-1])
            
            st.success(f"✅ Aktuální cena **{ticker_input}**: {current_price:.2f}")
            
            # --- ZOBRAZENÍ INDIKÁTORŮ ---
            st.subheader("📊 Technické indikátory")
            ind1, ind2, ind3 = st.columns(3)
            
            # Vyhodnocení RSI
            if current_rsi > 70:
                rsi_status = "🔴 Překoupeno (Riziko poklesu)"
            elif current_rsi < 30:
                rsi_status = "🟢 Přeprodáno (Možný nákup)"
            else:
                rsi_status = "⚪ Neutrální"
                
            ind1.metric("RSI (14 dní)", f"{current_rsi:.1f}", rsi_status)
            
            # Vyhodnocení Trendu (Cena vs SMA 200)
            if pd.isna(current_sma200):
                trend_status = "Nedostatek dat"
            elif current_price > current_sma200:
                trend_status = "🟢 Dlouhodobý Růst (Uptrend)"
            else:
                trend_status = "🔴 Dlouhodobý Pokles (Downtrend)"
                
            ind2.metric("Trend (vs SMA 200)", trend_status)
            
            # Krátkodobé momentum (SMA 50)
            if not pd.isna(current_sma50):
                ind3.metric("SMA 50 (Krátkodobý trend)", f"{current_sma50:.2f}")
            
            # --- VYKRESLENÍ GRAFU ---
            fig = go.Figure()
            # Svíčkový graf
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Cena'))
            # Přidání SMA
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1), name='SMA 50'))
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='orange', width=2), name='SMA 200'))
            
            fig.update_layout(title=f'Cenový vývoj {ticker_input} (6 měsíců)', xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.error(f"❌ Nepodařilo se najít data pro ticker '{ticker_input}'.")
    except Exception as e:
        st.error(f"⚠️ Došlo k chybě: {e}")

st.divider()

# --- 2. MODUL: RISK MANAGEMENT ---
st.header("🛡️ 2. Risk Management Kalkulačka")

# Rozdělení na Akcie a CFD pomocí záložek (Tabs)
tab1, tab2 = st.tabs(["📈 Akcie a ETF (Kusy)", "💱 Forex, Indexy, Komodity (Loty)"])

# --- ZÁLOŽKA 1: AKCIE A ETF ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Parametry účtu")
        acc_bal_stocks = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0, key="bal_stocks")
        risk_pct_stocks = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1, key="risk_stocks")

    with col2:
        st.subheader("Parametry obchodu")
        entry_stocks = st.number_input("Vstupní cena (Entry):", min_value=0.0001, value=current_price if current_price > 0 else 150.0, step=1.0, key="entry_stocks")
        sl_stocks = st.number_input("Cena Stop Loss (SL):", min_value=0.0001, value=(current_price * 0.95) if current_price > 0 else 140.0, step=1.0, key="sl_stocks")

    if st.button("Spočítat pro Akcie/ETF", type="primary"):
        if entry_stocks == sl_stocks:
            st.error("Vstupní cena a Stop Loss nesmí být stejné!")
        else:
            risk_amount = acc_bal_stocks * (risk_pct_stocks / 100)
            risk_per_share = abs(entry_stocks - sl_stocks)
            position_size = risk_amount / risk_per_share
            
            st.success("✅ Výpočet dokončen")
            res1, res2, res3 = st.columns(3)
            res1.metric("Max. povolená ztráta", f"{risk_amount:.2f}")
            res2.metric("Velikost pozice (Kusy)", f"{position_size:.2f}")
            res3.metric("Celková investice", f"{(position_size * entry_stocks):.2f}")

# --- ZÁLOŽKA 2: CFD (FOREX, INDEXY) ---
with tab2:
    st.info("💡 U CFD kontraktů (Forex, Indexy) se neobchoduje na kusy, ale na Loty. Pro správný výpočet potřebuješ znát hodnotu 1 bodu pro 1 Lot (najdeš v kalkulačce přímo v xStation).")
    
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Parametry účtu")
        acc_bal_cfd = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0, key="bal_cfd")
        risk_pct_cfd = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1, key="risk_cfd")
        
    with col4:
        st.subheader("Parametry obchodu")
        entry_cfd = st.number_input("Vstupní cena (Entry):", min_value=0.00001, value=current_price if current_price > 0 else 1.1000, format="%.5f", key="entry_cfd")
        sl_cfd = st.number_input("Cena Stop Loss (SL):", min_value=0.00001, value=(current_price * 0.99) if current_price > 0 else 1.0950, format="%.5f", key="sl_cfd")
        point_value = st.number_input("Hodnota 1 bodu při objemu 1 Lot (v měně účtu):", min_value=0.01, value=10.0, step=1.0, help="Např. pokud se cena pohne o 1 bod (z 1.1000 na 1.1001) a ty máš 1 Lot, kolik peněz vyděláš/proděláš?")

    if st.button("Spočítat pro CFD/Forex", type="primary"):
        if entry_cfd == sl_cfd:
            st.error("Vstupní cena a Stop Loss nesmí být stejné!")
        else:
            risk_amount = acc_bal_cfd * (risk_pct_cfd / 100)
            # Rozdíl v bodech (absolutní hodnota)
            points_at_risk = abs(entry_cfd - sl_cfd)
            # Finanční risk na 1 celý Lot
            risk_per_one_lot = points_at_risk * point_value
            # Výpočet lotů
            lot_size = risk_amount / risk_per_one_lot
            
            st.success("✅ Výpočet dokončen")
            res4, res5, res6 = st.columns(3)
            res4.metric("Max. povolená ztráta", f"{risk_amount:.2f}")
            res5.metric("Vzdálenost SL (Body)", f"{points_at_risk:.5f}")
            res6.metric("Velikost pozice (Loty)", f"{lot_size:.3f}")
            
            st.warning(f"V xStation zadej objem: **{lot_size:.2f} Lotu** (případně zaokrouhli podle možností instrumentu, např. 0.01).")
