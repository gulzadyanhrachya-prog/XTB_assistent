import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Analytický Asistent Pro", page_icon="📈", layout="wide")

st.title("📈 Můj XTB Analytický Asistent (Ultimate Verze)")
st.markdown("Obsahuje Profi API, výpočet RRR a integrovaný obchodní deník.")
st.divider()

# --- INICIALIZACE DENÍKU V PAMĚTI ---
if 'journal' not in st.session_state:
    st.session_state.journal = []

# --- FUNKCE PRO STAŽENÍ DAT (FINNHUB + YFINANCE ZÁLOHA) ---
@st.cache_data(ttl=300)
def get_market_data(ticker_symbol):
    df = pd.DataFrame()
    
    # 1. Pokus o stažení přes Finnhub (pokud máme API klíč)
    api_key = st.secrets.get("FINNHUB_API_KEY", None)
    if api_key and "=" not in ticker_symbol and "^" not in ticker_symbol:
        try:
            end = int(time.time())
            start = end - (6 * 30 * 24 * 60 * 60) # 6 měsíců zpět
            url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker_symbol}&resolution=D&from={start}&to={end}&token={api_key}"
            res = requests.get(url).json()
            if res.get("s") == "ok":
                df = pd.DataFrame({
                    "Open": res["o"], "High": res["h"], "Low": res["l"], "Close": res["c"]
                }, index=pd.to_datetime(res["t"], unit="s"))
        except Exception:
            pass # Pokud Finnhub selže, jdeme tiše dál na zálohu
            
    # 2. Záloha přes Yahoo Finance (pro Forex, Indexy nebo při chybě)
    if df.empty:
        try:
            stock = yf.Ticker(ticker_symbol)
            df = stock.history(period="6mo")
        except Exception:
            return None # Záchranná síť: Pokud Yahoo spadne, vrátíme prázdná data místo pádu aplikace
        
    if df is None or df.empty:
        return None
        
    # Výpočet indikátorů
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
        pass # Pokud se nepovede spočítat indikátory, nevadí
    
    return df

# --- 1. MODUL: VYHLEDÁNÍ A ANALÝZA ---
st.header("🔍 1. Vyhledání a Technická analýza")
ticker_input = st.text_input("Zadej ticker (např. AAPL, TSLA, EURUSD=X):", value="AAPL").upper()

current_price = 0.0

if ticker_input:
    try:
        df = get_market_data(ticker_input)
        if df is not None and not df.empty:
            current_price = float(df['Close'].iloc[-1])
            st.success(f"✅ Aktuální cena **{ticker_input}**: {current_price:.2f}")
            
            # Vykreslení grafu
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Cena'))
            if 'SMA_50' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], line=dict(color='blue', width=1), name='SMA 50'))
            if 'SMA_200' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], line=dict(color='orange', width=2), name='SMA 200'))
            fig.update_layout(title=f'Cenový vývoj {ticker_input}', xaxis_rangeslider_visible=False, height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("⚠️ Yahoo Finance momentálně blokuje stahování dat a Finnhub API není dostupné. Grafy jsou dočasně vypnuté.")
            st.info("💡 **Kalkulačka níže je ale stále plně funkční!** Zadej si cenu ručně.")
    except Exception as e:
        st.warning("⚠️ Došlo k chybě při stahování dat. Kalkulačka níže je ale stále plně funkční.")

st.divider()

# --- 2. MODUL: RISK MANAGEMENT A RRR ---
st.header("🛡️ 2. Risk Management & Obchodní plán")

tab1, tab2 = st.tabs(["📈 Akcie a ETF (Kusy)", "💱 Forex a Indexy (Loty)"])

# --- ZÁLOŽKA 1: AKCIE ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Parametry účtu")
        acc_bal = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0)
        risk_pct = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1)
        save_trade = st.checkbox("Po výpočtu uložit obchod do deníku", value=True, key="save_stock")

    with col2:
        st.subheader("Parametry obchodu")
        entry = st.number_input("Vstupní cena (Entry):", min_value=0.0001, value=current_price if current_price > 0 else 150.0, step=1.0)
        sl = st.number_input("Stop Loss (SL):", min_value=0.0001, value=(current_price * 0.95) if current_price > 0 else 140.0, step=1.0)
        tp = st.number_input("Take Profit (TP):", min_value=0.0001, value=(current_price * 1.10) if current_price > 0 else 170.0, step=1.0)

    if st.button("Spočítat a vyhodnotit (Akcie)", type="primary"):
        if entry == sl:
            st.error("Vstup a SL nesmí být stejné!")
        else:
            risk_amount = acc_bal * (risk_pct / 100)
            risk_per_share = abs(entry - sl)
            profit_per_share = abs(tp - entry)
            position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0
            total_profit = position_size * profit_per_share
            rrr = profit_per_share / risk_per_share if risk_per_share > 0 else 0
            
            st.success("✅ Výpočet dokončen")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Max. Ztráta", f"{risk_amount:.2f}")
            r2.metric("Potenciální Zisk", f"{total_profit:.2f}")
            r3.metric("Velikost pozice (Kusy)", f"{position_size:.2f}")
            
            if rrr >= 2:
                r4.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Skvělé RRR")
            elif rrr >= 1.5:
                r4.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Přijatelné RRR", delta_color="off")
            else:
                r4.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Špatné RRR (Nedoporučeno)", delta_color="inverse")
                
            if save_trade:
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input,
                    "Typ": "Akcie/ETF",
                    "Vstup": entry, "SL": sl, "TP": tp,
                    "Objem": round(position_size, 2),
                    "Risk": round(risk_amount, 2),
                    "Potenciální Zisk": round(total_profit, 2),
                    "RRR": f"1:{rrr:.2f}"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod byl úspěšně uložen do deníku!', icon='📓')

# --- ZÁLOŽKA 2: CFD (FOREX, INDEXY) ---
with tab2:
    st.info("💡 U CFD kontraktů (Forex, Indexy) se neobchoduje na kusy, ale na Loty. Pro správný výpočet potřebuješ znát hodnotu 1 bodu pro 1 Lot (najdeš v kalkulačce přímo v xStation).")
    
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Parametry účtu")
        acc_bal_cfd = st.number_input("Zůstatek na účtu:", min_value=100.0, value=10000.0, step=100.0, key="bal_cfd")
        risk_pct_cfd = st.number_input("Maximální risk (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1, key="risk_cfd")
        save_trade_cfd = st.checkbox("Po výpočtu uložit obchod do deníku", value=True, key="save_cfd")
        
    with col4:
        st.subheader("Parametry obchodu")
        entry_cfd = st.number_input("Vstupní cena (Entry):", min_value=0.00001, value=current_price if current_price > 0 else 1.1000, format="%.5f", key="entry_cfd")
        sl_cfd = st.number_input("Cena Stop Loss (SL):", min_value=0.00001, value=(current_price * 0.99) if current_price > 0 else 1.0950, format="%.5f", key="sl_cfd")
        tp_cfd = st.number_input("Take Profit (TP):", min_value=0.00001, value=(current_price * 1.02) if current_price > 0 else 1.1100, format="%.5f", key="tp_cfd")
        point_value = st.number_input("Hodnota 1 bodu při objemu 1 Lot (v měně účtu):", min_value=0.01, value=10.0, step=1.0)

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
            
            st.success("✅ Výpočet dokončen")
            res5, res6, res7, res8 = st.columns(4)
            res5.metric("Max. Ztráta", f"{risk_amount:.2f}")
            res6.metric("Potenciální Zisk", f"{total_profit:.2f}")
            res7.metric("Velikost pozice (Loty)", f"{lot_size:.3f}")
            
            if rrr >= 2:
                res8.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Skvělé RRR")
            elif rrr >= 1.5:
                res8.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Přijatelné RRR", delta_color="off")
            else:
                res8.metric("Risk:Reward (RRR)", f"1 : {rrr:.2f}", "Špatné RRR", delta_color="inverse")
            
            st.warning(f"V xStation zadej objem: **{lot_size:.2f} Lotu** (případně zaokrouhli podle možností instrumentu).")
            
            if save_trade_cfd:
                trade_record = {
                    "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Instrument": ticker_input,
                    "Typ": "CFD/Forex",
                    "Vstup": entry_cfd, "SL": sl_cfd, "TP": tp_cfd,
                    "Objem": round(lot_size, 2),
                    "Risk": round(risk_amount, 2),
                    "Potenciální Zisk": round(total_profit, 2),
                    "RRR": f"1:{rrr:.2f}"
                }
                st.session_state.journal.append(trade_record)
                st.toast('Obchod byl úspěšně uložen do deníku!', icon='📓')

st.divider()

# --- 3. MODUL: OBCHODNÍ DENÍK ---
st.header("📓 Můj obchodní deník")
if len(st.session_state.journal) > 0:
    df_journal = pd.DataFrame(st.session_state.journal)
    st.dataframe(df_journal, use_container_width=True)
    
    csv = df_journal.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Stáhnout deník jako CSV (Excel)",
        data=csv,
        file_name=f"obchodni_denik_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
    
    if st.button("Vymazat deník"):
        st.session_state.journal = []
        st.rerun()
else:
    st.info("Deník je zatím prázdný. Spočítáním obchodu se záznam automaticky přidá sem.")
