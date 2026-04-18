import datetime
import re

import pandas as pd

CURRENT_YEAR = datetime.datetime.now().year
LOCAL_MARKET_FILE = "master_market_data.csv.csv"
LOCAL_STOCK_FILE = "combined_inventory.csv"
MASTER_CATALOG_FILE = "master_car_prices.csv"

def safe_numeric(series):
@@ -55,6 +21,50 @@ def first_existing_column(df, candidates):
    return None

def normalize_text(value):
    if pd.isna(value):
        return ""
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def parse_owner_rank(value):
    text = normalize_text(value)
    if not text:
        return pd.NA
    if "first" in text or "1st" in text:
        return 1
    if "second" in text or "2nd" in text:
        return 2
    if "third" in text or "3rd" in text:
        return 3
    if "fourth" in text or "4th" in text:
        return 4
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else pd.NA

def parse_listing_days(value):
    text = normalize_text(value)
    if not text:
        return pd.NA
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    if "day" in text:
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
    if "-" in str(value):
        parsed = pd.to_datetime(str(value), format="%b-%d", errors="coerce")
        if pd.notna(parsed):
            parsed = parsed.replace(year=CURRENT_YEAR)
            return max((pd.Timestamp.today().normalize() - parsed).days, 0)
    return pd.NA

def normalize_inventory_schema(df):
    if df.empty:
        return df
@@ -67,6 +77,7 @@ def normalize_inventory_schema(df):
        "Model": ["Model"],
        "Variant": ["Variant", "Version", "Trim"],
        "Location": ["Location", "City", "State"],
        "State": ["State", "Region"],
        "Listing_URL": ["Listing_URL", "Detail_URL", "URL"],
        "Source": ["Source", "Dealer", "Marketplace"],
        "Price_Raw": ["Price_Raw", "PriceRaw", "Price_Value"],
@@ -76,6 +87,9 @@ def normalize_inventory_schema(df):
        "Fuel_Type": ["Fuel_Type", "Fuel"],
        "Transmission": ["Transmission"],
        "Status": ["Status"],
        "Owner": ["Owner", "Overview_Owner"],
        "Dealer_Name": ["Dealer_Name"],
        "Listing_Date": ["Listing_Date"],
    }.items():
        existing = first_existing_column(df, candidates)
        if existing and existing != canonical:
@@ -89,17 +103,22 @@ def normalize_inventory_schema(df):
        "Model",
        "Variant",
        "Location",
        "State",
        "Fuel_Type",
        "Transmission",
        "Source",
        "Status",
        "Owner",
        "Dealer_Name",
    ]:
        if text_col not in df.columns:
            df[text_col] = "Unknown"
        df[text_col] = df[text_col].fillna("Unknown").astype(str).str.strip()

    if "Listing_URL" not in df.columns:
        df["Listing_URL"] = ""
    if "Listing_Date" not in df.columns:
        df["Listing_Date"] = pd.NA

    if "Price_Raw" in df.columns:
        df["Price_Raw"] = safe_numeric(df["Price_Raw"])
@@ -108,9 +127,7 @@ def normalize_inventory_schema(df):

    if "Kilometer" in df.columns:
        df["Kilometer"] = safe_numeric(df["Kilometer"])
        df.loc[df["Kilometer"] <= 0, "Kilometer"] = pd.NA

    else:
        df["Kilometer"] = pd.Series(dtype="float64")

@@ -127,9 +144,15 @@ def normalize_inventory_schema(df):
    df["Age"] = df["Age"].fillna(CURRENT_YEAR - df["Reg_Year"])
    df.loc[df["Age"] < 0, "Age"] = 0

    df["Owner_Rank"] = df["Owner"].apply(parse_owner_rank)
    df["Listing_Days"] = df["Listing_Date"].apply(parse_listing_days)
    df["Make_Key"] = df["Make/Brand"].apply(normalize_text)
    df["Model_Key"] = df["Model"].apply(normalize_text)
    df["Variant_Key"] = df["Variant"].apply(normalize_text)
    df["Fuel_Key"] = df["Fuel_Type"].apply(normalize_text)
    df["Transmission_Key"] = df["Transmission"].apply(normalize_text)
    df["Price_Lakhs"] = df["Price_Raw"] / 100000
    df = df.dropna(subset=["Make/Brand", "Model", "Price_Raw"], how="any")
    return df

@@ -140,7 +163,7 @@ def normalize_catalog_schema(df):
    df = df.copy()
    df.columns = df.columns.str.strip()

    for col in ["Make", "Model", "Variant", "Market_Status", "Fuel_Type", "Transmission"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
@@ -149,656 +172,349 @@ def normalize_catalog_schema(df):
        df["Ex_Showroom_Price"] = pd.Series(dtype="float64")
    df["Ex_Showroom_Price"] = safe_numeric(df["Ex_Showroom_Price"])
    df.loc[df["Ex_Showroom_Price"] <= 0, "Ex_Showroom_Price"] = pd.NA
    df["Make_Key"] = df["Make"].apply(normalize_text)
    df["Model_Key"] = df["Model"].apply(normalize_text)
    df["Variant_Key"] = df["Variant"].apply(normalize_text)
    df["Fuel_Key"] = df["Fuel_Type"].apply(normalize_text)
    df["Transmission_Key"] = df["Transmission"].apply(normalize_text)
    return df

def load_csv_dataset(path, normalizer):

    try:
        return normalizer(pd.read_csv(path)), ""
    except FileNotFoundError:
        return pd.DataFrame(), f"{path} not found."
    except Exception as exc:
        return pd.DataFrame(), f"Failed to load {path}: {exc}"


def get_catalog_price(active_catalog, brand, model, variant, fuel_type, transmission, manual_price):
    if manual_price > 0:
        return manual_price, "Manual Input", "Unknown"

    if active_catalog.empty:
        return 0, "", "Unknown"

    pool = active_catalog[
        (active_catalog["Make_Key"] == normalize_text(brand))
        & (active_catalog["Model_Key"] == normalize_text(model))

    ].copy()

    fuel_key = normalize_text(fuel_type) if fuel_type != "Any Fuel" else ""
    transmission_key = normalize_text(transmission) if transmission != "Any Transmission" else ""
    variant_key = normalize_text(variant) if variant != "Any Variant" else ""

    if fuel_key:
        exact_fuel = pool[pool["Fuel_Key"] == fuel_key]
        if not exact_fuel.empty:
            pool = exact_fuel
    if transmission_key:
        exact_transmission = pool[pool["Transmission_Key"] == transmission_key]
        if not exact_transmission.empty:
            pool = exact_transmission
    if variant_key:
        exact_variant = pool[pool["Variant_Key"] == variant_key]
        if not exact_variant.empty:
            valid = exact_variant["Ex_Showroom_Price"].dropna()
            if not valid.empty:
                market_status = exact_variant["Market_Status"].iloc[0] if "Market_Status" in exact_variant.columns else "Unknown"
                return float(valid.iloc[0]), "Exact Master Catalog", market_status

    valid = pool["Ex_Showroom_Price"].dropna()
    if valid.empty:
        return 0, "", "Unknown"

    status_mode = pool["Market_Status"].mode()
    market_status = status_mode.iloc[0] if not status_mode.empty else "Unknown"
    return float(valid.mean()), "Catalog Average", market_status

def build_comparable_pool(market_df, brand, model, variant, year, location, fuel_type, transmission, owner_count, current_km):
    if market_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    base_pool = market_df[
        (market_df["Make_Key"] == normalize_text(brand))
        & (market_df["Model_Key"] == normalize_text(model))
        & (market_df["Price_Raw"].notna())
    ].copy()
    if base_pool.empty:
        return base_pool, base_pool, base_pool

    weighted = base_pool.copy()
    weighted["variant_penalty"] = 0.0
    weighted["year_penalty"] = 0.0
    weighted["km_penalty"] = 0.0
    weighted["location_penalty"] = 0.0
    weighted["fuel_penalty"] = 0.0
    weighted["transmission_penalty"] = 0.0
    weighted["owner_penalty"] = 0.0

    variant_key = normalize_text(variant) if variant != "Any Variant" else ""
    fuel_key = normalize_text(fuel_type) if fuel_type != "Any Fuel" else ""
    transmission_key = normalize_text(transmission) if transmission != "Any Transmission" else ""

    if variant_key:
        weighted["variant_penalty"] = weighted["Variant_Key"].ne(variant_key).astype(float) * 2.0
    if year != "Any Year":
        weighted["year_penalty"] = (weighted["Reg_Year"] - float(year)).abs().fillna(3).clip(0, 5) * 0.8
    if current_km > 0:
        weighted["km_penalty"] = ((weighted["Kilometer"] - current_km).abs() / 10000).fillna(3).clip(0, 8) * 0.7
    if location != "All India":
        weighted["location_penalty"] = weighted["Location"].ne(location).astype(float) * 0.75
    if fuel_key:
        weighted["fuel_penalty"] = weighted["Fuel_Key"].ne(fuel_key).astype(float) * 1.5
    if transmission_key:
        weighted["transmission_penalty"] = weighted["Transmission_Key"].ne(transmission_key).astype(float) * 1.25
    if owner_count > 0:
        weighted["owner_penalty"] = (weighted["Owner_Rank"] - owner_count).abs().fillna(1).clip(0, 3) * 0.7

    weighted["match_score"] = (
        1.0
        + weighted["variant_penalty"]
        + weighted["year_penalty"]
        + weighted["km_penalty"]
        + weighted["location_penalty"]
        + weighted["fuel_penalty"]
        + weighted["transmission_penalty"]
        + weighted["owner_penalty"]
    )
    weighted["comp_weight"] = 1 / weighted["match_score"]

    exact_pool = weighted.copy()
    if variant_key:
        exact_pool = exact_pool[exact_pool["Variant_Key"] == variant_key]
    if fuel_key:
        exact_pool = exact_pool[exact_pool["Fuel_Key"] == fuel_key]
    if transmission_key:
        exact_pool = exact_pool[exact_pool["Transmission_Key"] == transmission_key]
    if year != "Any Year":
        exact_pool = exact_pool[exact_pool["Reg_Year"].between(float(year) - 1, float(year) + 1, inclusive="both")]
    if current_km > 0:
        exact_pool = exact_pool[exact_pool["Kilometer"].fillna(current_km).between(max(current_km - 20000, 0), current_km + 20000, inclusive="both")]
    if owner_count > 0:
        exact_pool = exact_pool[exact_pool["Owner_Rank"].fillna(owner_count).between(owner_count - 1, owner_count + 1, inclusive="both")]

    q1 = weighted["Price_Raw"].quantile(0.25)
    q3 = weighted["Price_Raw"].quantile(0.75)
    iqr = q3 - q1

    if pd.notna(iqr) and iqr > 0:
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        weighted = weighted[weighted["Price_Raw"].between(lower, upper)].copy()
        exact_pool = exact_pool[exact_pool["Price_Raw"].between(lower, upper)].copy()

    comparable_pool = exact_pool.copy() if not exact_pool.empty else weighted.copy()
    comparable_pool["pricing_scope"] = "Exact Comparable" if not exact_pool.empty else "Broader Comparable"
    return base_pool, weighted, comparable_pool


def compute_confidence_score(exact_comps, strong_comps, km_coverage, owner_coverage, source_count, is_synthetic):
    if is_synthetic:
        return 20, "Low"

    score = 15
    score += min(exact_comps, 8) * 7
    score += min(strong_comps, 12) * 2
    score += min(source_count, 5) * 4
    score += int(km_coverage * 12)
    score += int(owner_coverage * 8)
    score = max(0, min(score, 100))
    if score >= 75:
        return score, "High"
    if score >= 50:
        return score, "Medium"
    return score, "Low"

def compute_demand_score(base_pool, comparable_pool):
    if base_pool.empty:
        return 0, "Unknown", "No market depth available."

    supply_count = len(comparable_pool)
    source_count = comparable_pool["Source"].nunique() if "Source" in comparable_pool.columns else 1
    median_days = comparable_pool["Listing_Days"].dropna().median() if "Listing_Days" in comparable_pool.columns else pd.NA

    score = 50
    score += max(0, 4 - supply_count) * 7
    score += min(source_count, 4) * 3

    if pd.notna(median_days):
        if median_days <= 7:
            score += 15
        elif median_days <= 21:
            score += 5
        elif median_days > 45:
            score -= 12


    if supply_count >= 12:
        score -= 15
    elif supply_count >= 8:
        score -= 8

    score = max(0, min(score, 100))
    if score >= 70:
        return score, "High Demand", "Market supply is tight or moving quickly."
    if score >= 45:
        return score, "Balanced", "The car has tradable demand, but pricing discipline still matters."
    return score, "Slow Demand", "Supply looks heavy or listings appear to move slowly."

def compute_internal_stock_signal(stock_df, brand, model, variant, fuel_type, transmission):
    if stock_df.empty:
        return 0, 0, "Internal stock file not available."

    base_stock = stock_df[
        (stock_df["Make_Key"] == normalize_text(brand))
        & (stock_df["Model_Key"] == normalize_text(model))
    ].copy()
    exact_stock = base_stock.copy()
    if variant != "Any Variant":
        exact_stock = exact_stock[exact_stock["Variant_Key"] == normalize_text(variant)]
    if fuel_type != "Any Fuel":
        exact_stock = exact_stock[exact_stock["Fuel_Key"] == normalize_text(fuel_type)]
    if transmission != "Any Transmission":
        exact_stock = exact_stock[exact_stock["Transmission_Key"] == normalize_text(transmission)]

    if len(exact_stock) > 0:
        note = f"You already have {len(exact_stock)} near-identical car(s) in internal stock."
    elif len(base_stock) > 0:
        note = f"You already have {len(base_stock)} car(s) of this model in internal stock."
    else:
        note = "This model is not currently seen in internal stock."
    return len(base_stock), len(exact_stock), note


def get_deductions(tyre_cond, paint_cond, mech_cond, color_appeal, interior_cond, accidental_repair, service_gap, electrical_work):
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
    if accidental_repair:
        deductions += 35000
    if service_gap:
        deductions += 15000
    if electrical_work:
        deductions += 20000
    return deductions

def compute_synthetic_market_price(est_new_price, year, current_km, market_status, brand):
    if est_new_price <= 0 or year == "Any Year":
        return 0.0, 0.0, 0.0, "Segment-Aware Synthetic Model"

    age = max(0, CURRENT_YEAR - int(year))
    km_reference = current_km if current_km > 0 else age * 12000
    luxury_brands = {"bmw", "mercedes benz", "mercedes", "audi", "volvo", "jaguar", "land rover", "lexus", "mini", "porsche", "jeep"}

    depreciation = 0.12 + (age * 0.07)
    if normalize_text(brand) in luxury_brands:
        depreciation += 0.05
    if normalize_text(market_status) == "discontinued":
        depreciation += 0.04
    if km_reference > age * 12000 and age > 0:
        depreciation += min(((km_reference - age * 12000) / 10000) * 0.01, 0.06)

    depreciation = min(max(depreciation, 0.20), 0.82)
    price = est_new_price * (1 - depreciation)
    return float(price), float(age), float(km_reference), "Segment-Aware Synthetic Model"

def compute_market_valuation(comparable_pool, weighted_pool, est_new_price, year, current_km, market_status, brand):
    valuation = {
        "is_synthetic": False,
        "retail_market_price": 0.0,
        "retail_price_low": 0.0,
        "retail_price_high": 0.0,
        "avg_age": 0.0,
        "avg_km": 0.0,
        "depreciation_percent": 0.0,
        "price_method": "",
        "comps_used": 0,
        "exact_comps_used": 0,
        "confidence_score": 0,
        "confidence_label": "Low",
        "pricing_scope": "Synthetic",
    }

    if not comparable_pool.empty:
        weighted_price = ((comparable_pool["Price_Raw"] * comparable_pool["comp_weight"]).sum() / comparable_pool["comp_weight"].sum())
        median_price = comparable_pool["Price_Raw"].median()
        valuation["retail_market_price"] = float((weighted_price * 0.6) + (median_price * 0.4))
        valuation["retail_price_low"] = float(comparable_pool["Price_Raw"].quantile(0.25))
        valuation["retail_price_high"] = float(comparable_pool["Price_Raw"].quantile(0.75))
        valuation["avg_age"] = float(comparable_pool["Age"].dropna().median()) if comparable_pool["Age"].notna().any() else 0.0
        valuation["avg_km"] = float(comparable_pool["Kilometer"].dropna().median()) if comparable_pool["Kilometer"].notna().any() else float(current_km)
        valuation["comps_used"] = int(len(comparable_pool))
        valuation["exact_comps_used"] = int(len(comparable_pool)) if comparable_pool["pricing_scope"].iloc[0] == "Exact Comparable" else 0
        valuation["price_method"] = "Strict Comparable Pricing"
        valuation["pricing_scope"] = comparable_pool["pricing_scope"].iloc[0]

        score, label = compute_confidence_score(
            valuation["exact_comps_used"],
            len(weighted_pool),
            comparable_pool["Kilometer"].notna().mean(),
            comparable_pool["Owner_Rank"].notna().mean(),
            comparable_pool["Source"].nunique() if "Source" in comparable_pool.columns else 1,
            False,
        )
        valuation["confidence_score"] = score
        valuation["confidence_label"] = label

        if est_new_price <= 0:
            est_new_price = valuation["retail_market_price"] * 1.45
        if est_new_price > 0:
            valuation["depreciation_percent"] = max(0.0, ((est_new_price - valuation["retail_market_price"]) / est_new_price) * 100)
        return valuation, est_new_price

    valuation["is_synthetic"] = True
    valuation["confidence_score"] = 20
    valuation["confidence_label"] = "Low"
    price, avg_age, avg_km, method = compute_synthetic_market_price(est_new_price, year, current_km, market_status, brand)
    valuation["retail_market_price"] = price
    valuation["retail_price_low"] = price * 0.94 if price else 0.0
    valuation["retail_price_high"] = price * 1.06 if price else 0.0
    valuation["avg_age"] = avg_age
    valuation["avg_km"] = avg_km
    valuation["price_method"] = method
    if est_new_price > 0 and price > 0:
        valuation["depreciation_percent"] = max(0.0, ((est_new_price - price) / est_new_price) * 100)
    return valuation, est_new_price

def compute_procurement_metrics(retail_market_price, deductions, target_margin, demand_score, exact_stock_count, owner_count):
    risk_buffer = 15000
    if demand_score < 45:
        risk_buffer += 25000
    elif demand_score < 60:
        risk_buffer += 10000
    if exact_stock_count > 0:
        risk_buffer += min(exact_stock_count * 10000, 40000)
    if owner_count >= 3:
        risk_buffer += 15000

    post_refurb_retail = max(0, retail_market_price - deductions)
    target_buy_price = max(0, post_refurb_retail * ((100 - target_margin) / 100) - risk_buffer)
    walkaway_price = max(0, target_buy_price - 25000)

    return {
        "refurb_cost": deductions,
        "risk_buffer": risk_buffer,
        "post_refurb_retail": post_refurb_retail,
        "target_buy_price": target_buy_price,
        "walkaway_price": walkaway_price,
    }
