import os
from datetime import date

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


def post(path: str, json: dict | None = None, params: dict | None = None):
    response = requests.post(f"{API}{path}", json=json, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


# ── Sidebar: Simulation controls ─────────────────────────────────────────────
with st.sidebar:
    st.header("Run Simulation")
    sim_days = st.number_input("Days", min_value=1, max_value=365, value=30)
    sim_seed = st.number_input("Seed", value=42)
    sim_start = st.date_input("Start date", value=date(2026, 1, 1))
    if st.button("▶ Run baseline simulation"):
        try:
            result = post(
                "/simulation/run",
                params={"days": sim_days, "seed": sim_seed, "start_date": str(sim_start)},
            )
            st.success(f"Simulation complete: {result['start_date']} → {result['end_date']}")
            st.cache_data.clear()
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Simulation failed: {exc}")

    st.divider()
    st.header("Run Scenario")
    scn_name = st.text_input("Scenario name", "my-scenario")
    scn_days = st.number_input("Scenario days", min_value=1, max_value=365, value=30, key="scn_days")
    scn_seed = st.number_input("Scenario seed", value=42, key="scn_seed")
    scn_start = st.date_input("Scenario start", value=date(2026, 1, 1), key="scn_start")
    st.subheader("Demand spike (optional)")
    spike_mult = st.slider("Multiplier", 1.0, 5.0, 2.0, 0.1)
    spike_from = st.date_input("Spike from", value=date(2026, 1, 5), key="spike_from")
    spike_to = st.date_input("Spike to", value=date(2026, 1, 10), key="spike_to")
    st.subheader("Supplier shutdown (optional)")
    sup_id = st.number_input("Supplier ID (0 = none)", min_value=0, max_value=5, value=0)
    sup_from = st.date_input("Shutdown from", value=date(2026, 1, 5), key="sup_from")
    sup_to = st.date_input("Shutdown to", value=date(2026, 1, 10), key="sup_to")
    st.subheader("Transfer delay (optional)")
    xfer_days = st.number_input("Extra transfer days (0 = none)", min_value=0, value=0)
    xfer_from = st.date_input("Delay from", value=date(2026, 1, 5), key="xfer_from")
    xfer_to = st.date_input("Delay to", value=date(2026, 1, 10), key="xfer_to")

    if st.button("▶ Run disruption scenario"):
        body: dict = {
            "name": scn_name,
            "days": int(scn_days),
            "seed": int(scn_seed),
            "start_date": str(scn_start),
            "compare_to_baseline": True,
            "demand_spikes": (
                [
                    {
                        "multiplier": spike_mult,
                        "start_date": str(spike_from),
                        "end_date": str(spike_to),
                    }
                ]
                if spike_mult != 1.0
                else []
            ),
            "supplier_shutdowns": (
                [{"supplier_id": sup_id, "start_date": str(sup_from), "end_date": str(sup_to)}]
                if sup_id > 0
                else []
            ),
            "transfer_delays": (
                [{"extra_days": xfer_days, "start_date": str(xfer_from), "end_date": str(xfer_to)}]
                if xfer_days > 0
                else []
            ),
        }
        try:
            result = post("/simulation/scenario", json=body)
            st.success(
                f"Scenario '{result['name']}' complete. "
                f"Δ fill rate: {result.get('delta_fill_rate', 0):.3f}, "
                f"Δ cost: {result.get('delta_total_cost', 0)}"
            )
            st.cache_data.clear()
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Scenario failed: {exc}")

# ── Main dashboard ────────────────────────────────────────────────────────────
try:
    summary = get("/kpis/summary")
    if not summary:
        st.info("No simulation data yet. Run a simulation from the sidebar.")
        st.stop()

    # ── KPI headline metrics ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fill rate", f"{summary['fill_rate'] * 100:.1f}%")
    c2.metric("Demand units", f"{summary['demand_units']:,}")
    c3.metric("Inventory units", f"{summary['inventory_units']:,}")
    c4.metric("Daily total cost", f"${float(summary['total_cost']):,.0f}")

    # ── Date range filter ────────────────────────────────────────────────────
    network_df = pd.DataFrame(get("/kpis/network"))
    network_df["kpi_date"] = pd.to_datetime(network_df["kpi_date"])
    min_date = network_df["kpi_date"].min().date()
    max_date = network_df["kpi_date"].max().date()
    col_l, col_r = st.columns(2)
    date_from = col_l.date_input("From", value=min_date, min_value=min_date, max_value=max_date, key="df")
    date_to = col_r.date_input("To", value=max_date, min_value=min_date, max_value=max_date, key="dt")
    mask = (network_df["kpi_date"].dt.date >= date_from) & (network_df["kpi_date"].dt.date <= date_to)
    net = network_df[mask]

    # ── Network charts ────────────────────────────────────────────────────────
    st.plotly_chart(
        px.line(net, x="kpi_date", y="fill_rate", title="Network Fill Rate Trend"),
        use_container_width=True,
    )
    st.plotly_chart(
        px.line(net, x="kpi_date", y=["inventory_units", "demand_units"], title="Inventory vs Demand"),
        use_container_width=True,
    )
    cost_columns = ["holding_cost", "ordering_cost", "transfer_cost", "shortage_cost"]
    cost_frame = net.melt(id_vars="kpi_date", value_vars=cost_columns, var_name="cost_type", value_name="cost")
    st.plotly_chart(
        px.area(cost_frame, x="kpi_date", y="cost", color="cost_type", title="Daily Cost Composition"),
        use_container_width=True,
    )

    # ── Per-warehouse fill rate ───────────────────────────────────────────────
    st.subheader("Warehouse Fill Rate Trends")
    wh_df = pd.DataFrame(
        get(f"/kpis/warehouse?date_from={date_from}&date_to={date_to}")
    )
    if not wh_df.empty:
        dims = get("/dimensions")
        wh_names = {item["id"]: item["code"] for item in dims["warehouses"]}
        wh_df["warehouse"] = wh_df["warehouse_id"].map(wh_names)
        wh_df["kpi_date"] = pd.to_datetime(wh_df["kpi_date"])
        st.plotly_chart(
            px.line(wh_df, x="kpi_date", y="fill_rate", color="warehouse", title="Fill Rate by Warehouse"),
            use_container_width=True,
        )

        latest_day = wh_df["kpi_date"].max()
        latest = wh_df[wh_df["kpi_date"] == latest_day]
        st.subheader("Latest warehouse performance")
        st.dataframe(
            latest[["warehouse", "fill_rate", "inventory_units", "stockout_units", "total_cost"]],
            use_container_width=True,
        )

    # ── SKU stockout heatmap ──────────────────────────────────────────────────
    st.subheader("SKU Stockout Heatmap")
    sku_kpis = pd.DataFrame(get("/kpis/sku"))
    if not sku_kpis.empty:
        sku_kpis["fill_rate_pct"] = sku_kpis["fill_rate"] * 100
        fig_heat = px.bar(
            sku_kpis.sort_values("total_stockout_units", ascending=False).head(20),
            x="sku_code",
            y="total_stockout_units",
            color="fill_rate_pct",
            color_continuous_scale="RdYlGn",
            title="Top 20 SKUs by Stockout Units (colour = fill rate %)",
            labels={"fill_rate_pct": "Fill rate %"},
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    # ── Supplier performance ──────────────────────────────────────────────────
    st.subheader("Supplier Performance")
    sup_kpis = pd.DataFrame(get("/kpis/supplier"))
    if not sup_kpis.empty:
        sup_kpis["delay_rate_pct"] = sup_kpis["delay_rate"] * 100
        st.dataframe(
            sup_kpis[["supplier_code", "name", "total_purchase_orders", "total_delays", "delay_rate_pct", "avg_delay_days"]],
            use_container_width=True,
        )

    # ── Low stock alerts ─────────────────────────────────────────────────────
    st.subheader("Low Stock Alerts")
    low_stock = pd.DataFrame(get("/inventory/low-stock"))
    if low_stock.empty:
        st.success("No low-stock items on the latest snapshot date.")
    else:
        st.warning(f"{len(low_stock)} low-stock alerts")
        st.dataframe(low_stock, use_container_width=True)

    # ── Scenario runs ────────────────────────────────────────────────────────
    st.subheader("Scenario Runs")
    scenarios = pd.DataFrame(get("/simulation/scenarios"))
    if scenarios.empty:
        st.info("No scenario runs yet. Use the sidebar to run a disruption scenario.")
    else:
        st.dataframe(
            scenarios[["id", "name", "created_at", "days", "delta_fill_rate", "delta_total_cost", "delta_stockout_units"]],
            use_container_width=True,
        )

    # ── Recent events ────────────────────────────────────────────────────────
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
    events_df = pd.DataFrame(get(event_path))
    st.subheader("Recent exceptions and events")
    st.dataframe(events_df, use_container_width=True)

except requests.RequestException as exc:
    st.error(f"Control tower cannot reach the API: {exc}")
except (KeyError, ValueError, TypeError) as exc:
    st.error(f"Control tower received unexpected data: {exc}")
