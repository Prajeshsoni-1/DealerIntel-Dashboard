import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import os
import datetime

# --- PAGE SETUP & UI THEME ---
st.set_page_config(page_title="DealerIntel Pro | Procurement", page_icon="🏎️", layout="wide")

st.markdown("""
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
    </style>
""", unsafe_allow_html=True)

# --- CLOUD DATABASE SETUP ---
SUPABASE_URL = "https://ayedgiyciuwyousmfhvr.supabase.co"
SUPABASE_KEY = "sb_publishable_SsA9pIMsjpC-uF6Zsh31Jw_-MSZKEDF"

@st.cache_resource
def init_connection():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_connection()

@st.cache_data(ttl=300) 
def load_cloud_data():
    all_data = []
    limit = 1000
    offset = 0
    current_year = datetime.datetime.now().year
    
    while True:
        try:
            response = supabase.table('dealership_database').select("*").range(offset, offset + limit - 1).execute()
            data = response.data
            if not data: break  
            all_data.extend(data)
            if len(data) < limit: break  
            offset += limit
        except Exception:
            break
        
    df = pd.DataFrame(all_data)
    if not df.empty:
        if 'Price_Raw' in df.columns:
            df['Price_Raw'] = pd.to_numeric(df['Price_Raw'], errors='coerce')
            df['Price_Lakhs'] = df['Price_Raw'] / 100000 
        if 'Kilometer' in df.columns:
            df['Kilometer'] = pd.to_numeric(df['Kilometer'], errors='coerce')
        if 'Reg_Year' in df.columns:
            df['Reg_Year'] = pd.to_numeric(df['Reg_Year'], errors='coerce')
        if 'Age' not in df.columns and 'Reg_Year' in df.columns:
            df['Age'] = current_year - df['Reg_Year']
        elif 'Age' in df.columns:
            df['Age'] = pd.to_numeric(df['Age'], errors='coerce')
    return df

@st.cache_data
def load_master_catalog():
    if os.path.exists("master_car_prices.csv"):
        try:
            temp_df = pd.read_csv("master_car_prices.csv")
            temp_df.columns = temp_df.columns.str.strip() 
            return temp_df
        except Exception:
            pass
    return pd.DataFrame()

df = load_cloud_data()
master_catalog_df = load_master_catalog()

@st.cache_data
def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')

# --- SIDEBAR & FILTERS ---
with st.sidebar:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.markdown("### 🏎️ DealerIntel Cloud")
    
    st.markdown("---")
    
    with st.expander("☁️ Check Live Cloud Inventory"):
        if not df.empty:
            st.write(f"**Total Cars Scraped:** {len(df)}")
            inventory_summary = df.groupby(['Make/Brand', 'Model']).size().reset_index(name='Available Data')
            st.dataframe(inventory_summary, hide_index=True, use_container_width=True)
        else:
            st.write("Database is currently empty.")
            
    st.header("1. Market Filters")

    show_discontinued = st.checkbox("Include Discontinued Models", value=True)
    
    if not master_catalog_df.empty:
        if not show_discontinued and 'Market_Status' in master_catalog_df.columns:
            active_catalog = master_catalog_df[master_catalog_df['Market_Status'] == 'Active']
        else:
            active_catalog = master_catalog_df
    else:
        active_catalog = pd.DataFrame()

    if not active_catalog.empty and 'Make' in active_catalog.columns:
        brands = sorted(active_catalog['Make'].dropna().unique().tolist())
    else:
        brands = sorted(df['Make/Brand'].dropna().unique().tolist()) if not df.empty else ["No Data"]
    selected_brand = st.selectbox("Make/Brand", brands)

    if not active_catalog.empty and 'Model' in active_catalog.columns:
        models = sorted(active_catalog[active_catalog['Make'] == selected_brand]['Model'].dropna().unique().tolist())
    else:
        models = sorted(df[df['Make/Brand'] == selected_brand]['Model'].dropna().unique().tolist()) if not df.empty else ["No Data"]
    selected_model = st.selectbox("Model", models)

    # Synthetic Engine needs a specific year to calculate depreciation
    # We offer the last 15 years as options
    current_year = datetime.datetime.now().year
    all_years = ["Any Year"] + list(range(current_year, current_year - 15, -1))
    selected_year = st.selectbox("Registration Year", all_years)

    locations = ["All India"] + sorted(df['Location'].dropna().unique().tolist()) if not df.empty else ["All India"]
    selected_location = st.selectbox("State / Location", locations)

    raw_variants = []
    if not active_catalog.empty and 'Variant' in active_catalog.columns:
        csv_vars = active_catalog[(active_catalog['Make'] == selected_brand) & (active_catalog['Model'] == selected_model)]['Variant'].dropna().astype(str).tolist()
        raw_variants.extend(csv_vars)
        
    if not df.empty:
        cloud_vars = df[(df['Make/Brand'] == selected_brand) & (df['Model'] == selected_model)]['Variant'].dropna().astype(str).tolist()
        raw_variants.extend(cloud_vars)
        
    if raw_variants:
        variants = ["Any Variant"] + sorted(list(set(raw_variants)))
    else:
        variants = ["Any Variant"]
        
    selected_variant = st.selectbox("Variant (Optional)", variants)
    
    st.markdown("---")
    st.header("2. Deal Specifics")
    seller_asking = st.number_input("Seller's Asking Price (₹)", min_value=0, value=0, step=10000)
    target_margin = st.slider("Required Profit Margin (%)", min_value=5, max_value=30, value=15, step=1)
    
    st.markdown("---")
    st.header("3. Physical Appraisal")
    st.caption("Adjust AI price based on lot inspection.")
    
    tyre_cond = st.selectbox("Tyre Condition", ["Good (0 deduction)", "Average (-₹15k)", "Needs Replacement (-₹30k)"])
    paint_cond = st.selectbox("Exterior & Paint", ["Clean (0 deduction)", "Minor Scratches (-₹15k)", "Major Dents/Repaint (-₹40k)"])
    mech_cond = st.selectbox("Mechanical & Engine", ["Smooth (0 deduction)", "Minor Issues/Suspension (-₹20k)", "Major Work Needed (-₹50k)"])
    color_appeal = st.selectbox("Color Market Appeal", ["High/Neutral (White/Silver/Black)", "Low/Unpopular (e.g., Red) (-₹25k)"])
    interior_cond = st.checkbox("Interior Needs Deep Clean/Repair (-₹10k)")

    st.markdown("---")
    st.header("4. Asset Valuation")
    known_new_price = st.number_input("Manual Override New Price (₹)", min_value=0, value=0, step=50000)

# ==========================================
# --- CORE LOGIC: LIVE DB vs SYNTHETIC ENGINE ---
# ==========================================
mask = pd.Series([True] * len(df)) if not df.empty else pd.Series(dtype=bool)

if not df.empty:
    mask = (df['Make/Brand'] == selected_brand) & (df['Model'] == selected_model)
    if selected_year != "Any Year":
        mask = mask & (df['Reg_Year'] == int(selected_year)) 
    if selected_location != "All India":
        mask = mask & (df['Location'] == selected_location)
    if selected_variant != "Any Variant":
        mask = mask & (df['Variant'] == selected_variant)

filtered_data = df[mask] if not df.empty else pd.DataFrame()

# 1. Determine the Ex-Showroom Price FIRST (We need this for synthetic math)
est_new_price = 0
price_source = ""

if known_new_price > 0:
    est_new_price = known_new_price
    price_source = "(Manual Input)"
elif not active_catalog.empty and 'Make' in active_catalog.columns and 'Ex_Showroom_Price' in active_catalog.columns:
    if selected_variant != "Any Variant":
        exact_match = active_catalog[(active_catalog['Make'] == selected_brand) & 
                                     (active_catalog['Model'] == selected_model) & 
                                     (active_catalog['Variant'] == selected_variant)]
        if not exact_match.empty and exact_match['Ex_Showroom_Price'].values[0] > 0:
            est_new_price = exact_match['Ex_Showroom_Price'].values[0]
            price_source = f"(Exact Master Catalog)"
    
    if est_new_price == 0:
        avg_match = active_catalog[(active_catalog['Make'] == selected_brand) & (active_catalog['Model'] == selected_model)]
        valid_prices = avg_match[avg_match['Ex_Showroom_Price'] > 0]
        if not valid_prices.empty:
            est_new_price = valid_prices['Ex_Showroom_Price'].mean()
            price_source = "(Catalog Average)"

# 2. Determine Base AI Price (Live Scraped vs Ideal Depreciation)
is_synthetic = False
avg_market_price = 0
avg_age = 0
avg_km = 0
depreciation_percent = 0

if not filtered_data.empty:
    # We have live data! Use the real market average.
    avg_market_price = filtered_data['Price_Raw'].mean()
    avg_age = filtered_data['Age'].mean()
    avg_km = filtered_data['Kilometer'].mean()
    if est_new_price == 0:
        est_new_price = avg_market_price * 1.5 
        price_source = "(AI Estimated - Missing)"
    depreciation_percent = ((est_new_price - avg_market_price) / est_new_price) * 100 if est_new_price > 0 else 0

else:
    # SYNTHETIC MODE! We don't have scraped data, so calculate mathematically.
    is_synthetic = True
    if est_new_price > 0 and selected_year != "Any Year":
        avg_age = current_year - int(selected_year)
        avg_age = max(0, avg_age) # Prevent negative age
        
        # Standard Depreciation Curve Logic
        # Y1: 20%, Y2: 30%, Y3: 40%, Y4: 50%, Y5: 60%
        depreciation_rate = min(0.20 + (avg_age * 0.10), 0.85)
        avg_market_price = est_new_price * (1 - depreciation_rate)
        
        avg_km = avg_age * 12000 # Assume average Indian driver does 12,000km/year
        depreciation_percent = depreciation_rate * 100
        

# --- DASHBOARD UI ---
st.title(f"Deal Analyzer: {selected_brand} {selected_model}")

if avg_market_price == 0:
    # Failsafe: No cloud data AND user didn't give us a year/price to do the math.
    st.error("⚠️ **No Data Found.** To calculate an Ideal Depreciation Price, please select a specific **Registration Year** from the sidebar, and ensure the Variant is selected or use the Manual Override New Price.")
else:
    if is_synthetic:
        st.warning(f"⚠️ **Synthetic Engine Active:** No live market data found in Supabase. Using the Mathematical Depreciation Model (-{int(depreciation_percent)}%) based on the New Car Price.")
    else:
        st.success(f"☁️ **Cloud Sync Active:** Benchmarking strictly against {len(filtered_data)} vehicles currently on the market.")

    # 3. Apply Physical Deductions to the Base Price (Live or Synthetic)
    deductions = 0
    if "Average" in tyre_cond: deductions += 15000
    elif "Replacement" in tyre_cond: deductions += 30000
    
    if "Minor Scratches" in paint_cond: deductions += 15000
    elif "Major Dents" in paint_cond: deductions += 40000
    
    if "Minor Issues" in mech_cond: deductions += 20000
    elif "Major Work" in mech_cond: deductions += 50000
    
    if "Low/Unpopular" in color_appeal: deductions += 25000
    
    if interior_cond: deductions += 10000
    
    # 4. Final Appraised Value
    appraised_market_price = max(0, avg_market_price - deductions)
    
    margin_multiplier = (100 - target_margin) / 100
    target_buy_price = appraised_market_price * margin_multiplier
    
    actual_profit = appraised_market_price - seller_asking
    profit_margin_pct = (actual_profit / appraised_market_price) * 100 if appraised_market_price > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        display_asking = f"₹{seller_asking/100000:,.2f} Lakhs" if seller_asking > 0 else "₹0.00 Lakhs"
        st.markdown(f"""
        <div class="metric-box">
            <p style="color:#94A3B8; margin-bottom:0px;">Seller's Asking Price</p>
            <h3 style="color:#F8FAFC;">{display_asking}</h3>
            <p style="color:#94A3B8; font-size:12px;">The price on the table</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-box">
            <p style="color:#94A3B8; margin-bottom:0px;">Appraised Market Value</p>
            <h3 style="color:#F8FAFC;">₹{appraised_market_price/100000:,.2f} Lakhs</h3>
            <p style="color:#10B981; font-size:12px;">Base AI: ₹{avg_market_price/100000:,.2f}L | Deductions: -₹{deductions:,.0f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-box">
            <p style="color:#94A3B8; margin-bottom:0px;">Target Buy Price</p>
            <p class="buy-text">₹{target_buy_price/100000:,.2f} Lakhs</p>
            <p style="color:#3B82F6; font-size:12px;">To hit {target_margin}% Margin</p>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        if seller_asking > 0:
            profit_class = "profit-positive" if actual_profit > 0 else "profit-negative"
            profit_label = f"Projected Profit ({profit_margin_pct:.1f}%)" if actual_profit > 0 else "Projected Loss!"
            val_display = f"₹{actual_profit:,.0f}"
            sub_text = "If bought right now"
        else:
            profit_class = "buy-text"
            profit_label = "Projected Profit"
            val_display = "---"
            sub_text = "Enter Asking Price"
            
        st.markdown(f"""
        <div class="metric-box">
            <p style="color:#94A3B8; margin-bottom:0px;">{profit_label}</p>
            <p class="{profit_class}">{val_display}</p>
            <p style="color:#94A3B8; font-size:12px;">{sub_text}</p>
        </div>
        """, unsafe_allow_html=True)

    if seller_asking > 0:
        if actual_profit < 0:
            st.error(f"🛑 BAD DEAL: Buying for ₹{seller_asking:,.0f} means a likely loss. Negotiate down to at least ₹{target_buy_price:,.0f}.")
        elif profit_margin_pct < target_margin:
            st.warning(f"⚠️ RISKY DEAL: Makes a profit, but at {profit_margin_pct:.1f}%, it misses the {target_margin}% goal. Drop the seller by ₹{(seller_asking - target_buy_price):,.0f}.")
        else:
            st.success(f"✅ GREAT DEAL: Buying at ₹{seller_asking:,.0f} secures your {target_margin}% margin. Lock it in.")
    else:
        st.info("ℹ️ Enter the Seller's Asking Price in the sidebar to run the Deal Decision Engine.")

    st.markdown("### 📉 Vehicle Asset Valuation")
    vcol1, vcol2, vcol3, vcol4 = st.columns(4)
    with vcol1:
        st.markdown(f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Current New Price {price_source}</p><h4>₹{est_new_price/100000:,.2f} L</h4></div>", unsafe_allow_html=True)
    with vcol2:
        st.markdown(f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Total Market Depreciation</p><h4 style='color:#EF4444;'>↓ {depreciation_percent:.1f}%</h4></div>", unsafe_allow_html=True)
    with vcol3:
        st.markdown(f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Estimated Age</p><h4>{avg_age:.1f} Years</h4></div>", unsafe_allow_html=True)
    with vcol4:
        st.markdown(f"<div class='value-box'><p style='color:#94A3B8; margin:0;'>Estimated Odometer</p><h4>{avg_km:,.0f} km</h4></div>", unsafe_allow_html=True)

    # Only show the charts and table if we have REAL live data
    if not is_synthetic:
        st.markdown("---")
        st.subheader("📊 Market Proof (Negotiation Tools)")
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            fig1 = px.histogram(filtered_data, x="Price_Lakhs", nbins=15, 
                                title="Where other sellers are pricing this car",
                                color_discrete_sequence=['#3B82F6'])
            if seller_asking > 0:
                fig1.add_vline(x=seller_asking/100000, line_dash="dash", line_color="red", annotation_text="Seller's Price")
            fig1.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
            st.plotly_chart(fig1, use_container_width=True)

        with chart_col2:
            fig2 = px.scatter(filtered_data, x="Kilometer", y="Price_Lakhs", 
                              color="Reg_Year", hover_data=["Variant", "Location"],
                              title="Mileage vs. Market Price",
                              color_continuous_scale=px.colors.sequential.Plasma)
            fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="white")
            st.plotly_chart(fig2, use_container_width=True)

        colA, colB = st.columns([0.8, 0.2])
        with colA:
            st.subheader("🚗 Live Market Inventory")
        with colB:
            csv_data = convert_df(filtered_data)
            st.download_button(
                label="📥 Download as Excel/CSV",
                data=csv_data,
                file_name=f"{selected_brand}_{selected_model}_{selected_variant}_Data.csv",
                mime="text/csv"
            )

        desired_columns = ['Make/Brand', 'Model', 'Variant', 'Reg_Year', 'Kilometer', 'Location', 'Price_Lakhs', 'Source', 'Listing_URL']
        display_columns = [col for col in desired_columns if col in filtered_data.columns]
        
        st.dataframe(
            filtered_data[display_columns],
            use_container_width=True,
            hide_index=True
        )
