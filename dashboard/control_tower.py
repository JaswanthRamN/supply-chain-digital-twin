import os
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")
st.set_page_config(page_title="Operations Control Tower", layout="wide")
st.title("Supply Chain Operations Control Tower")

@st.cache_data(ttl=30)
def get(path):
    r = requests.get(f"{API}{path}", timeout=15); r.raise_for_status(); return r.json()

try:
    summary = get("/kpis/summary")
    if not summary:
        st.info("No simulation data yet. Run a simulation from the API or CLI.")
        st.stop()
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Fill rate", f"{summary['fill_rate']*100:.1f}%")
    c2.metric("Demand units", f"{summary['demand_units']:,}")
    c3.metric("Inventory units", f"{summary['inventory_units']:,}")
    c4.metric("Daily total cost", f"${float(summary['total_cost']):,.0f}")

    network = pd.DataFrame(get("/kpis/network")); network["kpi_date"] = pd.to_datetime(network["kpi_date"])
    st.plotly_chart(px.line(network, x="kpi_date", y=["fill_rate"], title="Network Fill Rate Trend"), use_container_width=True)
    st.plotly_chart(px.line(network, x="kpi_date", y=["inventory_units","demand_units"], title="Inventory vs Demand"), use_container_width=True)

    wh = pd.DataFrame(get("/kpis/warehouse")); dims = get("/dimensions")
    names = {x['id']: x['code'] for x in dims['warehouses']}; wh['warehouse'] = wh['warehouse_id'].map(names)
    latest_day = wh['kpi_date'].max(); latest = wh[wh['kpi_date']==latest_day]
    st.subheader("Latest warehouse performance")
    st.dataframe(latest[["warehouse","fill_rate","inventory_units","stockout_units","total_cost"]], use_container_width=True)
    events = pd.DataFrame(get("/events?limit=100"))
    st.subheader("Recent exceptions and events")
    st.dataframe(events, use_container_width=True)
except Exception as exc:
    st.error(f"Control tower cannot reach the API: {exc}")
