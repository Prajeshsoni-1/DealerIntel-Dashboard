import datetime
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client


st.set_page_config(
    page_title="DealerIntel Pro | Procurement",
    page_icon="🚗",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main {background-color: #0E1117;}
    h1, h2, h3 {color: #E2E8F0;}
    .metric-box {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 10px; padding: 20px; border: 1px solid #334155;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3); text-align: center; margin-bottom: 15px;
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


CURRENT_YEAR = datetime.datetime.now().year
SUPABASE_URL = os.getenv("SUPABASE_URL", st.secrets.get("SUPABASE_URL", ""))
SUPABASE_KEY = os.getenv("SUPABASE_KEY", st.secrets.get("SUPABASE_KEY", ""))
RUPEE = "\u20B9"


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def first_existing_column(df, candidates):
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def normalize_inventory_schema(df):
    if df.empty:
        return df

    df = df.copy()
    rename_map = {}

    for canonical, candidates in {
        "Make/Brand": ["Make/Brand", "Make", "Brand"],
        "Model": ["Model"],
        "Variant": ["Variant", "Version", "Trim"],
        "Location": ["Location", "City", "State"],
        "Listing_URL": ["Listing_URL", "Detail_URL", "URL"],
        "Source": ["Source", "Dealer", "Marketplace"],
        "Price_Raw": ["Price_Raw", "PriceRaw", "Price_Value"],
        "Kilometer": ["Kilometer", "KM", "Mileage"],
        "Reg_Year": ["Reg_Year", "Year", "Registration_Year"],
        "Age": ["Age"],
        "Fuel_Type": ["Fuel_Type", "Fuel"],
        "Transmission": ["Transmission"],
        "Status": ["Status"],
    }.items():
        existing = first_existing_column(df, candidates)
        if existing and existing != canonical:
            rename_map[existing] = canonical

    if rename_map:
        df = df.rename(columns=rename_map)

    for text_col in [
        "Make/Brand",
        "Model",
        "Variant",
        "Location",
        "Fuel_Type",
        "Transmission",
        "Source",
        "Status",
    ]:
        if text_col not in df.columns:
            df[text_col] = "Unknown"
        df[text_col] = df[text_col].fillna("Unknown").astype(str).str.strip()

    if "Listing_URL" not in df.columns:
        df["Listing_URL"] = ""

    if "Price_Raw" in df.columns:
        df["Price_Raw"] = safe_numeric(df["Price_Raw"])
    else:
        df["Price_Raw"] = pd.Series(dtype="float64")

    if "Kilometer" in df.columns:
        df["Kilometer"] = safe_numeric(df["Kilometer"])
        df.loc[df["Kilometer"] < 0, "Kilometer"] = pd.NA
        # Zero often means missing in scraped classifieds rather than a true odometer.
        df.loc[df["Kilometer"] == 0, "Kilometer"] = pd.NA
    else:
        df["Kilometer"] = pd.Series(dtype="float64")

    if "Reg_Year" in df.columns:
        df["Reg_Year"] = safe_numeric(df["Reg_Year"])
        df.loc[(df["Reg_Year"] < 1990) | (df["Reg_Year"] > CURRENT_YEAR), "Reg_Year"] = pd.NA
    else:
        df["Reg_Year"] = pd.Series(dtype="float64")

    if "Age" in df.columns:
        df["Age"] = safe_numeric(df["Age"])
    else:
        df["Age"] = pd.NA
    df["Age"] = df["Age"].fillna(CURRENT_YEAR - df["Reg_Year"])
    df.loc[df["Age"] < 0, "Age"] = 0

    df = df.dropna(subset=["Make/Brand", "Model", "Price_Raw"], how="any")
    df["Price_Lakhs"] = df["Price_Raw"] / 100000

    return df


def normalize_catalog_schema(df):
    if df.empty:
        return df

    df = df.copy()
    df.columns = df.columns.str.strip()

    for col in ["Make", "Model", "Variant", "Market_Status"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    if "Ex_Showroom_Price" not in df.columns:
        df["Ex_Showroom_Price"] = pd.Series(dtype="float64")
    df["Ex_Showroom_Price"] = safe_numeric(df["Ex_Showroom_Price"])
    df.loc[df["Ex_Showroom_Price"] <= 0, "Ex_Showroom_Price"] = pd.NA

    return df


def get_supabase_credentials():
    if SUPABASE_URL and SUPABASE_KEY:
        return SUPABASE_URL, SUPABASE_KEY
    return None, None


@st.cache_resource
def init_connection():
    url, key = get_supabase_credentials()
    if not url or not key:
        return None
    return create_client(url, key)


supabase = init_connection()


@st.cache_data(ttl=300)
def load_cloud_data():
    if supabase is None:
        return pd.DataFrame(), "Supabase credentials not configured. Set SUPABASE_URL and SUPABASE_KEY in environment variables or Streamlit secrets."

    all_data = []
    limit = 1000
    offset = 0

    while True:
        try:
            response = (
                supabase.table("dealership_database")
                .select("*")
                .range(offset, offset + limit - 1)
                .execute()
            )
            data = response.data or []
            if not data:
                break
            all_data.extend(data)
            if len(data) < limit:
                break
            offset += limit
        except Exception as exc:
            return pd.DataFrame(), f"Failed to load cloud inventory: {exc}"

    df = normalize_inventory_schema(pd.DataFrame(all_data))
    return df, ""


@st.cache_data
def load_master_catalog():
    if not os.path.exists("master_car_prices.csv"):
        return pd.DataFrame(), "master_car_prices.csv not found."

    try:
        temp_df = pd.read_csv("master_car_prices.csv")
        return normalize_catalog_schema(temp_df), ""
    except Exception as exc:
        return pd.DataFrame(), f"Failed to load master catalog: {exc}"


@st.cache_data
def convert_df(df):
    return df.to_csv(index=False).encode("utf-8")


def get_catalog_price(active_catalog, selected_brand, selected_model, selected_variant, known_new_price):
    if known_new_price > 0:
        return known_new_price, "Manual Input"

    if active_catalog.empty:
        return 0, ""

    if selected_variant != "Any Variant":
        exact_match = active_catalog[
            (active_catalog["Make"] == selected_brand)
            & (active_catalog["Model"] == selected_model)
            & (active_catalog["Variant"] == selected_variant)
        ]
        if not exact_match.empty:
            exact_price = exact_match["Ex_Showroom_Price"].dropna()
            if not exact_price.empty:
                return float(exact_price.iloc[0]), "Exact Master Catalog"

    avg_match = active_catalog[
        (active_catalog["Make"] == selected_brand)
        & (active_catalog["Model"] == selected_model)
    ]
    valid_prices = avg_match["Ex_Showroom_Price"].dropna()
    if not valid_prices.empty:
        return float(valid_prices.mean()), "Catalog Average"

    return 0, ""


def compute_confidence_score(comps_count, has_variant_match, has_year_match, has_location_match, km_coverage):
    score = 20
    score += min(comps_count, 10) * 5
    if has_variant_match:
        score += 15
    if has_year_match:
        score += 10
    if has_location_match:
        score += 5
    score += int(km_coverage * 10)
    score = max(0, min(score, 100))

    if score >= 75:
        label = "High"
    elif score >= 45:
        label = "Medium"
    else:
        label = "Low"
    return score, label


def build_comparable_pool(df, selected_brand, selected_model, selected_year, selected_location, selected_variant):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    base_pool = df[
        (df["Make/Brand"] == selected_brand)
        & (df["Model"] == selected_model)
        & (df["Price_Raw"].notna())
    ].copy()

    if base_pool.empty:
        return base_pool, base_pool

    weighted_pool = base_pool.copy()

    weighted_pool["year_penalty"] = 0.0
    weighted_pool["variant_penalty"] = 0.0
    weighted_pool["location_penalty"] = 0.0

    if selected_year != "Any Year":
        weighted_pool["year_penalty"] = (
            weighted_pool["Reg_Year"] - float(selected_year)
        ).abs().fillna(3).clip(0, 5)

    if selected_variant != "Any Variant":
        weighted_pool["variant_penalty"] = (
            weighted_pool["Variant"].ne(selected_variant).astype(float) * 1.5
        )

    if selected_location != "All India":
        weighted_pool["location_penalty"] = (
            weighted_pool["Location"].ne(selected_location).astype(float) * 1.0
        )

    weighted_pool["match_score"] = (
        1.0
        + weighted_pool["year_penalty"]
        + weighted_pool["variant_penalty"]
        + weighted_pool["location_penalty"]
    )
    weighted_pool["comp_weight"] = 1 / weighted_pool["match_score"]

    q1 = weighted_pool["Price_Raw"].quantile(0.25)
    q3 = weighted_pool["Price_Raw"].quantile(0.75)
    iqr = q3 - q1

    if pd.notna(iqr) and iqr > 0:
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        weighted_pool = weighted_pool[
            weighted_pool["Price_Raw"].between(lower_bound, upper_bound)
        ].copy()

    return base_pool, weighted_pool


def compute_market_valuation(filtered_pool, est_new_price, selected_year):
    valuation = {
        "is_synthetic": False,
        "avg_market_price": 0.0,
        "avg_age": 0.0,
        "avg_km": 0.0,
        "depreciation_percent": 0.0,
        "price_method": "",
        "comps_used": 0,
        "confidence_score": 0,
        "confidence_label": "Low",
    }

    if not filtered_pool.empty:
        weighted_price = (
            (filtered_pool["Price_Raw"] * filtered_pool["comp_weight"]).sum()
            / filtered_pool["comp_weight"].sum()
        )
        median_price = filtered_pool["Price_Raw"].median()
        valuation["avg_market_price"] = float((weighted_price + median_price) / 2)
        valuation["avg_age"] = float(filtered_pool["Age"].dropna().median())
        valuation["avg_km"] = float(filtered_pool["Kilometer"].dropna().median())
        valuation["comps_used"] = int(len(filtered_pool))
        valuation["price_method"] = "Robust Comparable Pricing"

        has_variant_match = bool((filtered_pool["variant_penalty"] == 0).any())
        has_year_match = bool((filtered_pool["year_penalty"] == 0).any()) if "year_penalty" in filtered_pool else True
        has_location_match = bool((filtered_pool["location_penalty"] == 0).any()) if "location_penalty" in filtered_pool else True
        km_coverage = filtered_pool["Kilometer"].notna().mean()
        score, label = compute_confidence_score(
            valuation["comps_used"],
            has_variant_match,
            has_year_match,
            has_location_match,
            km_coverage,
        )
        valuation["confidence_score"] = score
        valuation["confidence_label"] = label

        if est_new_price <= 0:
            est_new_price = valuation["avg_market_price"] * 1.45
        if est_new_price > 0:
            valuation["depreciation_percent"] = max(
                0.0,
                ((est_new_price - valuation["avg_market_price"]) / est_new_price) * 100,
            )
        return valuation, est_new_price

    valuation["is_synthetic"] = True
    valuation["price_method"] = "Synthetic Depreciation Model"
    valuation["confidence_score"] = 25
    valuation["confidence_label"] = "Low"

    if est_new_price > 0 and selected_year != "Any Year":
        avg_age = max(0, CURRENT_YEAR - int(selected_year))
        base_depreciation = min(0.18 + (avg_age * 0.08), 0.78)
        valuation["avg_market_price"] = est_new_price * (1 - base_depreciation)
        valuation["avg_age"] = float(avg_age)
        valuation["avg_km"] = float(avg_age * 12000)
        valuation["depreciation_percent"] = base_depreciation * 100

    return valuation, est_new_price


def get_deductions(tyre_cond, paint_cond, mech_cond, color_appeal, interior_cond):
    deductions = 0
    if "Average" in tyre_cond:
        deductions += 15000
    elif "Replacement" in tyre_cond:
        deductions += 30000

    if "Minor Scratches" in paint_cond:
        deductions += 15000
    elif "Major Dents" in paint_cond:
        deductions += 40000

    if "Minor Issues" in mech_cond:
        deductions += 20000
    elif "Major Work" in mech_cond:
        deductions += 50000

    if "Low/Unpopular" in color_appeal:
        deductions += 25000

    if interior_cond:
        deductions += 10000

    return deductions


df, cloud_error = load_cloud_data()
master_catalog_df, catalog_error = load_master_catalog()


with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except Exception:
        st.markdown("### DealerIntel Cloud")

    st.markdown("---")

    if cloud_error:
        st.warning(cloud_error)
    if catalog_error and "not found" not in catalog_error:
        st.warning(catalog_error)

    with st.expander("Check Live Cloud Inventory"):
        if not df.empty:
            st.write(f"**Total Cars Scraped:** {len(df)}")
            inventory_summary = (
                df.groupby(["Make/Brand", "Model"])
                .size()
                .reset_index(name="Available Data")
                .sort_values("Available Data", ascending=False)
            )
            st.dataframe(inventory_summary, hide_index=True, use_container_width=True)
        else:
            st.write("Cloud inventory is currently unavailable or empty.")

    st.header("1. Market Filters")

    show_discontinued = st.checkbox("Include Discontinued Models", value=True)

    if not master_catalog_df.empty:
        if not show_discontinued and "Market_Status" in master_catalog_df.columns:
            active_catalog = master_catalog_df[master_catalog_df["Market_Status"] == "Active"]
        else:
            active_catalog = master_catalog_df
    else:
        active_catalog = pd.DataFrame()

    if not active_catalog.empty and "Make" in active_catalog.columns:
        brands = sorted(active_catalog["Make"].replace("", pd.NA).dropna().unique().tolist())
    else:
        brands = sorted(df["Make/Brand"].replace("Unknown", pd.NA).dropna().unique().tolist()) if not df.empty else []
    if not brands:
        brands = ["No Data"]
    selected_brand = st.selectbox("Make/Brand", brands)

    if not active_catalog.empty and "Model" in active_catalog.columns:
        models = sorted(
            active_catalog[active_catalog["Make"] == selected_brand]["Model"]
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
    else:
        models = sorted(
            df[df["Make/Brand"] == selected_brand]["Model"]
            .replace("Unknown", pd.NA)
            .dropna()
            .unique()
            .tolist()
        ) if not df.empty else []
    if not models:
        models = ["No Data"]
    selected_model = st.selectbox("Model", models)

    all_years = ["Any Year"] + list(range(CURRENT_YEAR, CURRENT_YEAR - 15, -1))
    selected_year = st.selectbox("Registration Year", all_years)

    locations = (
        ["All India"]
        + sorted(
            df["Location"].replace("Unknown", pd.NA).dropna().unique().tolist()
        )
        if not df.empty
        else ["All India"]
    )
    selected_location = st.selectbox("State / Location", locations)

    raw_variants = []
    if not active_catalog.empty and "Variant" in active_catalog.columns:
        csv_vars = (
            active_catalog[
                (active_catalog["Make"] == selected_brand)
                & (active_catalog["Model"] == selected_model)
            ]["Variant"]
            .replace("", pd.NA)
            .dropna()
            .astype(str)
            .tolist()
        )
        raw_variants.extend(csv_vars)

    if not df.empty:
        cloud_vars = (
            df[
                (df["Make/Brand"] == selected_brand)
                & (df["Model"] == selected_model)
            ]["Variant"]
            .replace("Unknown", pd.NA)
            .dropna()
            .astype(str)
            .tolist()
        )
        raw_variants.extend(cloud_vars)

    variants = ["Any Variant"] + sorted(set(raw_variants)) if raw_variants else ["Any Variant"]
    selected_variant = st.selectbox("Variant (Optional)", variants)

    st.markdown("---")
    st.header("2. Deal Specifics")
    seller_asking = st.number_input("Seller's Asking Price (₹)", min_value=0, value=0, step=10000)
    target_margin = st.slider("Required Profit Margin (%)", min_value=5, max_value=30, value=15, step=1)

    st.markdown("---")
    st.header("3. Physical Appraisal")
    st.caption("Adjust the market estimate based on lot inspection.")

    tyre_cond = st.selectbox("Tyre Condition", ["Good (0 deduction)", "Average (-₹15k)", "Needs Replacement (-₹30k)"])
    paint_cond = st.selectbox("Exterior & Paint", ["Clean (0 deduction)", "Minor Scratches (-₹15k)", "Major Dents/Repaint (-₹40k)"])
    mech_cond = st.selectbox("Mechanical & Engine", ["Smooth (0 deduction)", "Minor Issues/Suspension (-₹20k)", "Major Work Needed (-₹50k)"])
    color_appeal = st.selectbox("Color Market Appeal", ["High/Neutral (White/Silver/Black)", "Low/Unpopular (e.g. Red) (-₹25k)"])
    interior_cond = st.checkbox("Interior Needs Deep Clean/Repair (-₹10k)")

    st.markdown("---")
    st.header("4. Asset Valuation")
    known_new_price = st.number_input("Manual Override New Price (₹)", min_value=0, value=0, step=50000)


catalog_price, price_source = get_catalog_price(
    active_catalog,
    selected_brand,
    selected_model,
    selected_variant,
    known_new_price,
)

base_pool, comparable_pool = build_comparable_pool(
    df,
    selected_brand,
    selected_model,
    selected_year,
    selected_location,
    selected_variant,
)

valuation, est_new_price = compute_market_valuation(
    comparable_pool,
    catalog_price,
    selected_year,
)

deductions = get_deductions(tyre_cond, paint_cond, mech_cond, color_appeal, interior_cond)
appraised_market_price = max(0, valuation["avg_market_price"] - deductions)

margin_multiplier = (100 - target_margin) / 100
target_buy_price = appraised_market_price * margin_multiplier
actual_profit = appraised_market_price - seller_asking
profit_margin_pct = (actual_profit / appraised_market_price) * 100 if appraised_market_price > 0 else 0

st.title(f"Deal Analyzer: {selected_brand} {selected_model}")

if valuation["avg_market_price"] == 0:
    st.error(
        "No usable price signal found. Pick a specific registration year and variant, or enter a manual new-car price to activate the fallback model."
    )
else:
    if valuation["is_synthetic"]:
        st.warning(
            f"Synthetic pricing is active. No live comparables were available, so the app is using a depreciation model with {valuation['confidence_label'].lower()} confidence."
        )
    else:
        st.success(
            f"Comparable pricing is active. Using {valuation['comps_used']} cleaned market comps after outlier filtering."
        )

    confidence_color = {
        "High": "#10B981",
        "Medium": "#F59E0B",
        "Low": "#EF4444",
    }[valuation["confidence_label"]]

    st.markdown(
        f"""
        <div class="value-box">
            <p style="color:#94A3B8; margin:0;">Pricing Method</p>
            <h4>{valuation["price_method"]}</h4>
            <p class="caption-text">Confidence:
            <span style="color:{confidence_color}; font-weight:600;">{valuation["confidence_label"]} ({valuation["confidence_score"]}/100)</span>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        display_asking = f"{RUPEE}{seller_asking/100000:,.2f} Lakhs" if seller_asking > 0 else f"{RUPEE}0.00 Lakhs"
        st.markdown(
            f"""
            <div class="metric-box">
                <p style="color:#94A3B8; margin-bottom:0px;">Seller's Asking Price</p>
                <h3 style="color:#F8FAFC;">{display_asking}</h3>
                <p style="color:#94A3B8; font-size:12px;">The price on the table</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="metric-box">
                <p style="color:#94A3B8; margin-bottom:0px;">Appraised Market Value</p>
                <h3 style="color:#F8FAFC;">{RUPEE}{appraised_market_price/100000:,.2f} Lakhs</h3>
                <p style="color:#10B981; font-size:12px;">Base estimate: {RUPEE}{valuation["avg_market_price"]/100000:,.2f}L | Reconditioning: -{RUPEE}{deductions:,.0f}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div class="metric-box">
                <p style="color:#94A3B8; margin-bottom:0px;">Target Buy Price</p>
                <p class="buy-text">{RUPEE}{target_buy_price/100000:,.2f} Lakhs</p>
                <p style="color:#3B82F6; font-size:12px;">To hit {target_margin}% gross margin</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        if seller_asking > 0:
            profit_class = "profit-positive" if actual_profit > 0 else "profit-negative"
            profit_label = f"Projected Profit ({profit_margin_pct:.1f}%)" if actual_profit > 0 else "Projected Loss"
            val_display = f"{RUPEE}{actual_profit:,.0f}"
            sub_text = "If bought at the asking price"
        else:
            profit_class = "buy-text"
            profit_label = "Projected Profit"
            val_display = "---"
            sub_text = "Enter the asking price"

        st.markdown(
            f"""
            <div class="metric-box">
                <p style="color:#94A3B8; margin-bottom:0px;">{profit_label}</p>
                <p class="{profit_class}">{val_display}</p>
                <p style="color:#94A3B8; font-size:12px;">{sub_text}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if seller_asking > 0:
        if actual_profit < 0:
            st.error(
                f"Bad deal at the current ask. Buying for {RUPEE}{seller_asking:,.0f} likely creates a loss. A safer buy price is {RUPEE}{target_buy_price:,.0f} or below."
            )
        elif profit_margin_pct < target_margin:
            st.warning(
                f"Borderline deal. It makes money, but the projected margin is {profit_margin_pct:.1f}% versus your {target_margin}% target. Try reducing the buy by {RUPEE}{max(seller_asking - target_buy_price, 0):,.0f}."
            )
        else:
            st.success(
                f"Healthy deal. Buying at {RUPEE}{seller_asking:,.0f} clears your {target_margin}% target margin."
            )
    else:
        st.info("Enter the seller's asking price in the sidebar to run the deal decision engine.")

    st.markdown("### Vehicle Asset Valuation")
    vcol1, vcol2, vcol3, vcol4 = st.columns(4)
    with vcol1:
        source_text = price_source if price_source else "Estimated"
        st.markdown(
            f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Current New Price ({source_text})</p><h4>{RUPEE}{est_new_price/100000:,.2f} L</h4></div>",
            unsafe_allow_html=True,
        )
    with vcol2:
        st.markdown(
            f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Total Market Depreciation</p><h4 style='color:#EF4444;'>↓ {valuation['depreciation_percent']:.1f}%</h4></div>",
            unsafe_allow_html=True,
        )
    with vcol3:
        st.markdown(
            f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Estimated Age</p><h4>{valuation['avg_age']:.1f} Years</h4></div>",
            unsafe_allow_html=True,
        )
    with vcol4:
        st.markdown(
            f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Estimated Odometer</p><h4>{valuation['avg_km']:,.0f} km</h4></div>",
            unsafe_allow_html=True,
        )

    insight_col1, insight_col2, insight_col3 = st.columns(3)
    with insight_col1:
        st.metric("Raw Market Listings", len(base_pool))
    with insight_col2:
        st.metric("Clean Comparable Listings", valuation["comps_used"])
    with insight_col3:
        km_coverage = comparable_pool["Kilometer"].notna().mean() * 100 if not comparable_pool.empty else 0
        st.metric("KM Data Coverage", f"{km_coverage:.0f}%")

    if valuation["confidence_label"] == "Low":
        st.info(
            "Confidence is low because the result is based on sparse or weakly matched data. Treat this as an opening benchmark, not a final bid."
        )

    if not valuation["is_synthetic"] and not comparable_pool.empty:
        st.markdown("---")
        st.subheader("Market Proof")
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            fig1 = px.histogram(
                comparable_pool,
                x="Price_Lakhs",
                nbins=15,
                title="Comparable asking prices",
                color_discrete_sequence=["#3B82F6"],
            )
            if seller_asking > 0:
                fig1.add_vline(
                    x=seller_asking / 100000,
                    line_dash="dash",
                    line_color="red",
                    annotation_text="Seller Ask",
                )
            fig1.add_vline(
                x=appraised_market_price / 100000,
                line_dash="dot",
                line_color="#10B981",
                annotation_text="Appraised Value",
            )
            fig1.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font_color="white",
            )
            st.plotly_chart(fig1, use_container_width=True)

        with chart_col2:
            fig2 = px.scatter(
                comparable_pool,
                x="Kilometer",
                y="Price_Lakhs",
                color="Reg_Year",
                hover_data=["Variant", "Location", "Source"],
                title="Mileage vs Market Price",
                color_continuous_scale=px.colors.sequential.Plasma,
            )
            fig2.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font_color="white",
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Comparable Inventory")
        csv_data = convert_df(comparable_pool)
        st.download_button(
            label="Download CSV",
            data=csv_data,
            file_name=f"{selected_brand}_{selected_model}_{selected_variant}_Data.csv",
            mime="text/csv",
        )

        display_columns = [
            "Make/Brand",
            "Model",
            "Variant",
            "Reg_Year",
            "Kilometer",
            "Location",
            "Price_Lakhs",
            "Source",
            "Listing_URL",
            "comp_weight",
        ]
        display_columns = [col for col in display_columns if col in comparable_pool.columns]
        st.dataframe(
            comparable_pool[display_columns].sort_values("comp_weight", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
