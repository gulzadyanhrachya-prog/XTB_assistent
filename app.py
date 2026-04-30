import streamlit as st
import yfinance as yf

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---\nst.set_page_config(page_title="XTB Analytický Asistent", page_icon="📈", layout="centered")

st.title("📈 Můj XTB Analytický Asistent")
st.markdown("Tato aplikace slouží jako podpora pro manuální obchodování. Spočítá ti přesné parametry obchodu tak, abys nikdy neriskoval více, než si určíš.")

st.divider()

# --- 1. MODUL: NAČTENÍ TRŽNÍCH DAT ---
st.header("🔍 1. Vyhledání instrumentu")
ticker_input = st.text_input("Zadej ticker akcie nebo ETF (např. AAPL, TSLA, SPY):", value="AAPL").upper()

# Pokusíme se načíst aktuální cenu z Yahoo Finance
current_price = 0.0
if ticker_input:
    try:
        # Vytvoření objektu tickeru a stažení historie za poslední den
        stock = yf.Ticker(ticker_input)
        hist = stock.history(period="1d")
        
        if not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            st.success(f"✅ Aktuální cena **{ticker_input}**: {current_price:.2f} USD")
        else:
            st.error(f"❌ Nepodařilo se najít data pro ticker '{ticker_input}'. Zkontroluj, zda je zadaný správně.")
    except Exception as e:
        st.error("⚠️ Došlo k chybě při komunikaci s Yahoo Finance.")

st.divider()

# --- 2. MODUL: RISK MANAGEMENT ---
st.header("🛡️ 2. Risk Management Kalkulačka")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Parametry účtu")
    account_balance = st.number_input("Zůstatek na účtu (v měně instrumentu):", min_value=100.0, value=10000.0, step=100.0)
    risk_pct = st.number_input("Maximální risk na obchod (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1)

with col2:
    st.subheader("Parametry obchodu")
    # Zde použijeme staženou cenu jako výchozí hodnotu (pokud se ji podařilo načíst)
    default_entry = current_price if current_price > 0 else 150.0
    entry_price = st.number_input("Vstupní cena (Entry):", min_value=0.1, value=default_entry, step=1.0)
    
    # Automatický návrh Stop Lossu (např. 5 % pod aktuální cenou)
    default_sl = entry_price * 0.95
    stop_loss = st.number_input("Cena Stop Loss (SL):", min_value=0.1, value=default_sl, step=1.0)

# --- VÝPOČETNÍ LOGIKA ---
if st.button("Spočítat parametry obchodu", type="primary"):
    if entry_price == stop_loss:
        st.error("Vstupní cena a Stop Loss nesmí být stejné!")
    else:
        risk_amount = account_balance * (risk_pct / 100)
        risk_per_share = abs(entry_price - stop_loss)
        position_size = risk_amount / risk_per_share
        total_investment = position_size * entry_price

        # --- ZOBRAZENÍ VÝSLEDKŮ ---
        st.divider()
        st.subheader("🟢 Tvůj Trade Setup pro xStation")
        
        res_col1, res_col2, res_col3 = st.columns(3)
        res_col1.metric("Max. povolená ztráta", f"{risk_amount:.2f}")
        res_col2.metric("Velikost pozice (Kusy)", f"{position_size:.2f}")
        res_col3.metric("Celková investice", f"{total_investment:.2f}")
        
        st.info(f"""
        **Jak to zadat do XTB:**
        1. Najdi si instrument **{ticker_input}**.
        2. Zadej objem: **{position_size:.2f}** (pokud XTB neumožňuje zlomkové akcie, zaokrouhli dolů na **{int(position_size)}**).
        3. Nastav Stop Loss přesně na: **{stop_loss:.2f}**.
        4. Pokud tě trh vyhodí na Stop Lossu, ztratíš přesně **{risk_amount:.2f}** (což jsou tvé {risk_pct} % účtu).
        """)
