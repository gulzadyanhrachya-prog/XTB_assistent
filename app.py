import streamlit as st

# --- ZÁKLADNÍ NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="XTB Analytický Asistent", page_icon="📈", layout="centered")

st.title("📈 Můj XTB Analytický Asistent")
st.markdown("Tato aplikace slouží jako podpora pro manuální obchodování. Spočítá ti přesné parametry obchodu tak, abys nikdy neriskoval více, než si určíš.")

st.divider()

# --- RISK MANAGEMENT MODUL ---
st.header("🛡️ Risk Management Kalkulačka (Akcie / ETF)")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Parametry účtu")
    account_balance = st.number_input("Zůstatek na účtu (např. v USD nebo CZK):", min_value=100.0, value=10000.0, step=100.0)
    risk_pct = st.number_input("Maximální risk na obchod (%):", min_value=0.1, max_value=10.0, value=2.0, step=0.1)

with col2:
    st.subheader("Parametry obchodu")
    entry_price = st.number_input("Vstupní cena (Entry):", min_value=0.1, value=150.0, step=1.0)
    stop_loss = st.number_input("Cena Stop Loss (SL):", min_value=0.1, value=140.0, step=1.0)

# --- VÝPOČETNÍ LOGIKA ---
is_long = entry_price > stop_loss

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
        1. Najdi si daný instrument.
        2. Zadej objem: **{position_size:.2f}** (pokud XTB neumožňuje zlomkové akcie, zaokrouhli dolů na **{int(position_size)}**).
        3. Nastav Stop Loss přesně na: **{stop_loss}**.
        4. Pokud tě trh vyhodí na Stop Lossu, ztratíš přesně **{risk_amount:.2f}** (což jsou tvé {risk_pct} % účtu).
        """)
