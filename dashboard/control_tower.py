import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")
st.set_page_config(page_title="Operations Control Tower", layout="wide")
st.title("Supply Chain Operations Control Tower")


@st.cache_data(ttl=30)
def get(path: str):
    response = requests.get(f"{API}{path}", timeout=15)
    response.raise_for_status()
    return response.json()


try:
    summary = get("/kpis/summary")
    if not summary:
        st.info("No simulation data yet. Run a simulation from the API or CLI.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fill rate", f"{summary['fill_rate'] * 100:.1f}%")
    c2.metric("Demand units", f"{summary['demand_units']:,}")
    c3.metric("Inventory units", f"{summary['inventory_units']:,}")
    c4.metric("Daily total cost", f"${float(summary['total_cost']):,.0f}")

    network = pd.DataFrame(get("/kpis/network"))
    network["kpi_date"] = pd.to_datetime(network["kpi_date"])
    st.plotly_chart(
        px.line(network, x="kpi_date", y="fill_rate", title="Network Fill Rate Trend"),
        use_container_width=True,
    )
    st.plotly_chart(
        px.line(network, x="kpi_date", y=["inventory_units", "demand_units"], title="Inventory vs Demand"),
        use_container_width=True,
    )

    cost_columns = ["holding_cost", "ordering_cost", "transfer_cost", "shortage_cost"]
    cost_frame = network.melt(id_vars="kpi_date", value_vars=cost_columns, var_name="cost_type", value_name="cost")
    st.plotly_chart(
        px.area(cost_frame, x="kpi_date", y="cost", color="cost_type", title="Daily Cost Composition"),
        use_container_width=True,
    )

    warehouse = pd.DataFrame(get("/kpis/warehouse"))
    dimensions = get("/dimensions")
    warehouse_names = {item["id"]: item["code"] for item in dimensions["warehouses"]}
    warehouse["warehouse"] = warehouse["warehouse_id"].map(warehouse_names)
    latest_day = warehouse["kpi_date"].max()
    latest = warehouse[warehouse["kpi_date"] == latest_day]
    st.subheader("Latest warehouse performance")
    st.dataframe(
        latest[["warehouse", "fill_rate", "inventory_units", "stockout_units", "total_cost"]],
        use_container_width=True,
    )

    event_types = [
        "STOCKOUT",
        "BACKORDER_CREATED",
        "BACKORDER_FULFILLED",
        "SUPPLIER_DELAY",
        "PURCHASE_ORDER_CREATED",
        "SHIPMENT_RECEIVED",
        "INVENTORY_TRANSFER",
    ]
    selected_event_type = st.selectbox("Recent event filter", ["ALL", *event_types])
    event_path = "/events?limit=200"
    if selected_event_type != "ALL":
        event_path += f"&event_type={selected_event_type}"
    events = pd.DataFrame(get(event_path))
    st.subheader("Recent exceptions and events")
    st.dataframe(events, use_container_width=True)
except requests.RequestException as exc:
    st.error(f"Control tower cannot reach the API: {exc}")
except (KeyError, ValueError, TypeError) as exc:
    st.error(f"Control tower received unexpected data: {exc}")
