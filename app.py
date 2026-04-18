import os

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client

from procurement_logic import (
    CURRENT_YEAR,
    LOCAL_MARKET_FILE,
    LOCAL_STOCK_FILE,
    MASTER_CATALOG_FILE,
    compute_demand_score,
    compute_internal_stock_signal,
    compute_market_valuation,
    compute_procurement_metrics,
    evaluate_procurement_decision,
    get_catalog_price,
    get_deductions,
    load_csv_dataset,
    normalize_catalog_schema,
    normalize_inventory_schema,
    build_comparable_pool,
)


st.set_page_config(page_title="DealerIntel Pro | Procurement", page_icon="🚗", layout="wide")

st.markdown(
    """
    <style>
    .main {background-color: #0E1117;}
    h1, h2, h3 {color: #E2E8F0;}
    .metric-box {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 10px; padding: 20px; border: 1px solid #334155;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3); text-align: center; margin-bottom: 15px;
        min-height: 220px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .value-box {
        background: linear-gradient(135deg, #0F172A 0%, #020617 100%);
        border-radius: 10px; padding: 15px; border: 1px solid #1E293B;
        text-align: center; margin-bottom: 20px;
    }
    .profit-positive {color: #10B981; font-size: 26px; font-weight: bold;}
    .profit-negative {color: #EF4444; font-size: 26px; font-weight: bold;}
    .buy-text {color: #3B82F6; font-size: 24px; font-weight: bold;}
    .caption-text {color: #94A3B8; font-size: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


RUPEE = "\u20B9"


def get_optional_secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return ""


SUPABASE_URL = os.getenv("SUPABASE_URL") or get_optional_secret("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or get_optional_secret("SUPABASE_KEY")


def export_csv(df):
    return df.to_csv(index=False).encode("utf-8")


@st.cache_resource
def init_connection():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)


@st.cache_data(ttl=300)
def load_cloud_data():
    client = init_connection()
    if client is None:
        return None, "Supabase credentials not configured."

    try:
        response = client.table("dealership_database").select("*").range(0, 4999).execute()
        data = response.data or []
        return normalize_inventory_schema(pd.DataFrame(data)), ""
    except Exception as exc:
        return None, f"Failed to load cloud inventory: {exc}"


@st.cache_data
def load_local_market():
    return load_csv_dataset(LOCAL_MARKET_FILE, normalize_inventory_schema)


@st.cache_data
def load_internal_stock():
    return load_csv_dataset(LOCAL_STOCK_FILE, normalize_inventory_schema)


@st.cache_data
def load_master_catalog():
    return load_csv_dataset(MASTER_CATALOG_FILE, normalize_catalog_schema)


cloud_df, cloud_error = load_cloud_data()
local_market_df, local_market_error = load_local_market()
internal_stock_df, internal_stock_error = load_internal_stock()
master_catalog_df, catalog_error = load_master_catalog()

market_df = cloud_df if cloud_df is not None and not cloud_df.empty else local_market_df
market_source = "Supabase live inventory" if cloud_df is not None and not cloud_df.empty else f"Local market file ({LOCAL_MARKET_FILE})"
market_warning = ""
if market_df is None or market_df.empty:
    market_df = local_market_df
    market_warning = cloud_error or local_market_error
elif cloud_error:
    market_warning = cloud_error

if market_df is None:
    market_df = pd.DataFrame()
if internal_stock_df is None:
    internal_stock_df = pd.DataFrame()
if master_catalog_df is None:
    master_catalog_df = pd.DataFrame()

with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except Exception:
        st.markdown("### DealerIntel Cloud")

    st.markdown("---")
    if market_warning:
        st.warning(market_warning)
    if internal_stock_error and "not found" not in internal_stock_error:
        st.warning(internal_stock_error)
    if catalog_error and "not found" not in catalog_error:
        st.warning(catalog_error)

    with st.expander("Check Market Inventory"):
        if not market_df.empty:
            st.write(f"**Source:** {market_source}")
            st.write(f"**Listings:** {len(market_df)}")
            st.dataframe(
                market_df.groupby(["Make/Brand", "Model"]).size().reset_index(name="Listings").sort_values("Listings", ascending=False).head(50),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.write("Market inventory unavailable.")

    st.header("1. Car Identity")
    show_discontinued = st.checkbox("Include Discontinued Models", value=True)
    active_catalog = master_catalog_df
    if not master_catalog_df.empty and not show_discontinued and "Market_Status" in master_catalog_df.columns:
        active_catalog = master_catalog_df[master_catalog_df["Market_Status"] == "Active"]

    brands = sorted(active_catalog["Make"].replace("", None).dropna().unique().tolist()) if not active_catalog.empty else sorted(market_df["Make/Brand"].replace("Unknown", None).dropna().unique().tolist()) if not market_df.empty else ["No Data"]
    selected_brand = st.selectbox("Make/Brand", brands if brands else ["No Data"])

    models = (
        sorted(active_catalog[active_catalog["Make"] == selected_brand]["Model"].replace("", None).dropna().unique().tolist())
        if not active_catalog.empty
        else sorted(market_df[market_df["Make/Brand"] == selected_brand]["Model"].replace("Unknown", None).dropna().unique().tolist()) if not market_df.empty else ["No Data"]
    )
    selected_model = st.selectbox("Model", models if models else ["No Data"])

    variants = []
    if not active_catalog.empty:
        variants.extend(active_catalog[(active_catalog["Make"] == selected_brand) & (active_catalog["Model"] == selected_model)]["Variant"].replace("", None).dropna().tolist())
    if not market_df.empty:
        variants.extend(market_df[(market_df["Make/Brand"] == selected_brand) & (market_df["Model"] == selected_model)]["Variant"].replace("Unknown", None).dropna().tolist())
    selected_variant = st.selectbox("Variant", ["Any Variant"] + sorted(set(variants)))

    st.header("2. Vehicle Profile")
    selected_year = st.selectbox("Registration Year", ["Any Year"] + list(range(CURRENT_YEAR, CURRENT_YEAR - 15, -1)))
    selected_location = st.selectbox("State / Location", ["All India"] + sorted(market_df["Location"].replace("Unknown", None).dropna().unique().tolist()) if not market_df.empty else ["All India"])
    selected_fuel = st.selectbox("Fuel Type", ["Any Fuel"] + sorted(market_df[(market_df["Make/Brand"] == selected_brand) & (market_df["Model"] == selected_model)]["Fuel_Type"].replace("Unknown", None).dropna().unique().tolist()) if not market_df.empty else ["Any Fuel"])
    selected_transmission = st.selectbox("Transmission", ["Any Transmission"] + sorted(market_df[(market_df["Make/Brand"] == selected_brand) & (market_df["Model"] == selected_model)]["Transmission"].replace("Unknown", None).dropna().unique().tolist()) if not market_df.empty else ["Any Transmission"])
    current_km = st.number_input("Current Kilometer", min_value=0, value=0, step=1000)
    owner_count = st.selectbox("Owner Count", [0, 1, 2, 3, 4], format_func=lambda x: "Unknown" if x == 0 else f"{x} Owner")

    st.header("3. Deal & Margin")
    seller_asking = st.number_input("Seller Asking Price (₹)", min_value=0, value=0, step=10000)
    target_margin = st.slider("Required Gross Margin (%)", min_value=5, max_value=30, value=15, step=1)

    st.header("4. Physical Condition")
    tyre_cond = st.selectbox("Tyre Condition", ["Good (0 deduction)", "Average (-₹15k)", "Needs Replacement (-₹30k)"])
    paint_cond = st.selectbox("Paint / Body", ["Clean (0 deduction)", "Minor Scratches (-₹15k)", "Major Dents/Repaint (-₹40k)"])
    mech_cond = st.selectbox("Engine / Mechanical", ["Smooth (0 deduction)", "Minor Issues/Suspension (-₹20k)", "Major Work Needed (-₹50k)"])
    color_appeal = st.selectbox("Color Appeal", ["High/Neutral", "Low/Unpopular (-₹25k)"])
    interior_cond = st.checkbox("Interior repair needed (-₹10k)")
    accidental_repair = st.checkbox("Accidental / structural work (-₹35k)")
    service_gap = st.checkbox("Poor service history (-₹15k)")
    electrical_work = st.checkbox("Electrical / AC work (-₹20k)")

    st.header("5. New Car Benchmark")
    known_new_price = st.number_input("Manual New Car Price (₹)", min_value=0, value=0, step=50000)

catalog_price, price_source, market_status = get_catalog_price(
    active_catalog,
    selected_brand,
    selected_model,
    selected_variant,
    selected_fuel,
    selected_transmission,
    known_new_price,
)

base_pool, weighted_pool, comparable_pool = build_comparable_pool(
    market_df,
    selected_brand,
    selected_model,
    selected_variant,
    selected_year,
    selected_location,
    selected_fuel,
    selected_transmission,
    owner_count,
    current_km,
)

valuation, est_new_price = compute_market_valuation(
    comparable_pool,
    weighted_pool,
    catalog_price,
    selected_year,
    current_km,
    market_status,
    selected_brand,
)
demand_score, demand_label, demand_note = compute_demand_score(base_pool, comparable_pool)
base_stock_count, exact_stock_count, stock_note = compute_internal_stock_signal(
    internal_stock_df,
    selected_brand,
    selected_model,
    selected_variant,
    selected_fuel,
    selected_transmission,
)

deductions = get_deductions(
    tyre_cond,
    paint_cond,
    mech_cond,
    color_appeal,
    interior_cond,
    accidental_repair,
    service_gap,
    electrical_work,
)
procurement = compute_procurement_metrics(
    valuation["retail_market_price"],
    deductions,
    target_margin,
    demand_score,
    exact_stock_count,
    owner_count,
)
decision = evaluate_procurement_decision(
    valuation,
    procurement,
    seller_asking,
    demand_score,
    exact_stock_count,
)

target_buy_price = procurement["target_buy_price"]
walkaway_price = procurement["walkaway_price"]
post_refurb_retail = procurement["post_refurb_retail"]
actual_profit = post_refurb_retail - seller_asking
profit_margin_pct = (actual_profit / post_refurb_retail) * 100 if seller_asking > 0 and post_refurb_retail > 0 else 0

st.title(f"Deal Analyzer: {selected_brand} {selected_model}")

if valuation["retail_market_price"] == 0:
    st.error("No usable price signal found. Add a specific year and benchmark or load market data before using this for buying.")
else:
    if valuation["is_synthetic"]:
        st.warning("Synthetic pricing is active. Use this only as a fallback benchmark, not as a final approval price.")
    else:
        st.success(f"Market-backed pricing is active from {market_source}. Scope: {valuation['pricing_scope']}.")

    st.markdown(
        f"""
        <div class="value-box">
            <p style="color:#94A3B8; margin:0;">Pricing Method</p>
            <h4>{valuation["price_method"]}</h4>
            <p class="caption-text">Demand: <span style="font-weight:600;">{demand_label} ({demand_score}/100)</span></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if decision["decision_color"] == "success":
        st.success(f"Approval Status: {decision['decision']}")
    elif decision["decision_color"] == "warning":
        st.warning(f"Approval Status: {decision['decision']}")
    elif decision["decision_color"] == "error":
        st.error(f"Approval Status: {decision['decision']}")
    else:
        st.info(f"Approval Status: {decision['decision']}")

    if decision["reasons"]:
        st.caption("Decision basis: " + " | ".join(decision["reasons"]))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='metric-box'><p style='color:#94A3B8;'>Seller Asking Price</p><h3 style='color:#F8FAFC;'>{RUPEE}{seller_asking/100000:,.2f} Lakhs</h3><p class='caption-text'>Current buy-side ask</p></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-box'><p style='color:#94A3B8;'>Expected Retail Market</p><h3 style='color:#F8FAFC;'>{RUPEE}{valuation['retail_market_price']/100000:,.2f} Lakhs</h3><p class='caption-text'>Range: {RUPEE}{valuation['retail_price_low']/100000:,.2f}L - {RUPEE}{valuation['retail_price_high']/100000:,.2f}L</p></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-box'><p style='color:#94A3B8;'>Target Buy Price</p><p class='buy-text'>{RUPEE}{target_buy_price/100000:,.2f} Lakhs</p><p class='caption-text'>Walk-away above: {RUPEE}{walkaway_price/100000:,.2f}L</p></div>", unsafe_allow_html=True)
    with c4:
        profit_class = "profit-positive" if actual_profit > 0 else "profit-negative"
        label = f"Projected Gross Profit ({profit_margin_pct:.1f}%)" if seller_asking > 0 else "Projected Gross Profit"
        value = f"{RUPEE}{actual_profit:,.0f}" if seller_asking > 0 else "---"
        st.markdown(f"<div class='metric-box'><p style='color:#94A3B8;'>{label}</p><p class='{profit_class}'>{value}</p><p class='caption-text'>After refurb estimate</p></div>", unsafe_allow_html=True)

    if seller_asking > 0:
        if decision["decision"] == "Approve Buy":
            st.success(f"Buy zone. The ask is inside your target buy limit of {RUPEE}{target_buy_price:,.0f}.")
        elif decision["decision"] == "Negotiate":
            st.warning(f"Borderline buy. The ask is above target and close to walk-away. Push toward {RUPEE}{target_buy_price:,.0f}.")
        elif decision["decision"] == "Manual Review":
            st.warning(f"Manual review required. Even if the ask looks workable, the comp quality is not strong enough for auto-approval.")
        else:
            st.error(f"Pass or renegotiate. Current ask is too high for this risk profile. Disciplined buy number: about {RUPEE}{target_buy_price:,.0f}.")
    else:
        st.info("Enter the seller asking price to get the final procurement call.")

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("New Car Price", f"{RUPEE}{est_new_price/100000:,.2f}L")
        st.caption(price_source if price_source else "Estimated benchmark")
    with s2:
        st.metric("Market Status", market_status if market_status else "Unknown")
        st.caption(f"Depreciation: {valuation['depreciation_percent']:.1f}%")
    with s3:
        st.metric("Refurb Estimate", f"{RUPEE}{procurement['refurb_cost']:,.0f}")
        st.caption(f"Post-refurb retail: {RUPEE}{post_refurb_retail:,.0f}")
    with s4:
        st.metric("Internal Stock", exact_stock_count)
        st.caption(stock_note)

    i1, i2, i3 = st.columns(3)
    with i1:
        st.metric("Model Listings in Market", len(base_pool))
        st.caption(demand_note)
    with i2:
        st.metric("Comps Used", valuation["comps_used"])
        st.caption(f"Exact comps: {valuation['exact_comps_used']} | Model stock: {base_stock_count}")
    with i3:
        km_coverage = comparable_pool["Kilometer"].notna().mean() * 100 if not comparable_pool.empty else 0
        st.metric("KM Coverage in Comps", f"{km_coverage:.0f}%")
        st.caption(f"Source: {market_source}")

    if not decision["trust_gate_passed"]:
        st.info("Trust gate failed. The tool is intentionally preventing automatic approval because the comparable data is not strong enough.")

    if not comparable_pool.empty:
        st.markdown("---")
        st.subheader("Market Proof")
        g1, g2 = st.columns(2)
        with g1:
            fig1 = px.histogram(comparable_pool, x="Price_Lakhs", nbins=15, title="Comparable asking prices", color_discrete_sequence=["#3B82F6"])
            if seller_asking > 0:
                fig1.add_vline(x=seller_asking / 100000, line_dash="dash", line_color="red", annotation_text="Seller Ask")
            fig1.add_vline(x=valuation["retail_market_price"] / 100000, line_dash="dot", line_color="#10B981", annotation_text="Retail Benchmark")
            fig1.add_vline(x=target_buy_price / 100000, line_dash="dot", line_color="#F59E0B", annotation_text="Target Buy")
            fig1.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
            st.plotly_chart(fig1, use_container_width=True)
        with g2:
            fig2 = px.scatter(comparable_pool, x="Kilometer", y="Price_Lakhs", color="Reg_Year", hover_data=["Variant", "Location", "Source", "Owner"], title="Mileage vs Market Price", color_continuous_scale=px.colors.sequential.Plasma)
            fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Comparable Inventory")
        st.download_button("Download CSV", export_csv(comparable_pool), file_name=f"{selected_brand}_{selected_model}_{selected_variant}_Data.csv", mime="text/csv")
        cols = [c for c in ["Make/Brand", "Model", "Variant", "Reg_Year", "Kilometer", "Owner", "Fuel_Type", "Transmission", "Location", "Price_Lakhs", "Source", "Listing_Days", "comp_weight", "pricing_scope", "Listing_URL"] if c in comparable_pool.columns]
        st.dataframe(comparable_pool[cols].sort_values(["pricing_scope", "comp_weight"], ascending=[True, False]), use_container_width=True, hide_index=True)
