"""
Loads raw kestrel_ops.db, applies documented cleaning rules, writes a second
SQLite file (data/kestrel_clean.db) that the app reads from. Raw db is never
mutated. Every rule here is a judgement call recorded in DECISIONS.md.

Run: python etl/build_clean_db.py
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import config

CITY_CANON = {
    "Bangalore": "Bengaluru",
    "New Delhi": "Delhi",
}

CHILLED_MAX_C = 8.0  # excursion threshold for CHILLED band; AMBIENT has no excursion concept


def canon_city(city):
    if pd.isna(city):
        return city
    return CITY_CANON.get(city.strip(), city.strip())


def parse_created_at(row):
    val, src = row["created_at"], row["source_system"]
    if pd.isna(val):
        return pd.NaT
    try:
        if src == "ERP_WEB":
            return pd.to_datetime(val, format="%d/%m/%Y %H:%M")
        if src == "PARTNER_API":
            return pd.to_datetime(val, utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
        return pd.to_datetime(val, format="%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return pd.NaT


def parse_actual_arrival(row):
    val, vendor = row["actual_arrival"], row["telematics_vendor"]
    if pd.isna(val):
        return pd.NaT
    try:
        if vendor == "TELEMATICS_B":
            return pd.to_datetime(val, format="%d-%b-%Y %I:%M %p")
        return pd.to_datetime(val, format="%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return pd.NaT


def build_outlets(raw):
    df = raw["outlets"].copy()
    df["city_clean"] = df["city"].apply(canon_city)
    df["is_test_outlet"] = df["outlet_code"].str.startswith("TST", na=False)
    df["dup_group_key"] = (
        df["outlet_name"].str.strip().str.lower() + "|" + df["city_clean"].str.strip().str.lower()
    )
    dup_counts = df.groupby("dup_group_key")["outlet_id"].transform("count")
    df["possible_duplicate"] = dup_counts > 1
    # Usable-for-reporting flag: excludes closed/deleted/test outlets. Does NOT
    # deduplicate possible_duplicate rows -- merging risked conflating distinct
    # outlets since legal_name/GST are not reliable disambiguators (see DECISIONS.md).
    df["is_reportable"] = (
        (df["status"] == "ACTIVE") & (df["is_deleted"] == 0) & (~df["is_test_outlet"])
    )
    return df


def build_order_lines(raw):
    ol = raw["order_lines"].merge(
        raw["orders"][["order_id", "order_date", "order_status", "outlet_id", "region_id",
                        "route_id", "warehouse_id", "source_system"]],
        on="order_id", how="left",
    )
    ol = ol.merge(raw["products"][["product_id", "sku_code", "category", "is_chilled",
                                    "storage_temp_band", "discontinued_date", "case_pack"]],
                   on="product_id", how="left")

    def to_eaches(r, qty_col):
        qty = r[qty_col]
        if pd.isna(qty):
            return None
        if r["qty_uom"] == "CASE":
            return qty * r["case_pack_at_order"]
        return qty

    ol["ordered_eaches"] = ol.apply(lambda r: to_eaches(r, "ordered_qty"), axis=1)
    ol["allocated_eaches"] = ol.apply(lambda r: to_eaches(r, "allocated_qty"), axis=1)
    ol["delivered_eaches"] = ol.apply(lambda r: to_eaches(r, "delivered_qty"), axis=1)

    ol["order_date"] = pd.to_datetime(ol["order_date"], errors="coerce")
    ol["discontinued_date"] = pd.to_datetime(ol["discontinued_date"], errors="coerce")
    ol["ordered_after_discontinuation"] = (
        ol["discontinued_date"].notna() & (ol["order_date"] > ol["discontinued_date"])
    )
    return ol


def build_deliveries(raw, order_lines_clean):
    d = raw["deliveries"].copy()
    d["planned_arrival"] = pd.to_datetime(d["planned_arrival"], errors="coerce")
    d["actual_arrival"] = d.apply(parse_actual_arrival, axis=1)
    d["dispatch_datetime"] = pd.to_datetime(d["dispatch_datetime"], errors="coerce")

    chilled_orders = set(order_lines_clean.loc[order_lines_clean["is_chilled"] == 1, "order_id"])
    d["is_chilled_delivery"] = d["order_id"].isin(chilled_orders)
    # Derived excursion, not the raw flag: raw temperature_excursion_flag does not
    # correlate with max_temp_celsius (see DECISIONS.md) so it is not trusted downstream.
    d["excursion_derived"] = d["is_chilled_delivery"] & (d["max_temp_celsius"] > CHILLED_MAX_C)
    return d


def build_orders(raw):
    o = raw["orders"].copy()
    o["created_at_parsed"] = o.apply(parse_created_at, axis=1)
    o["order_date"] = pd.to_datetime(o["order_date"], errors="coerce")
    return o


def build_returns(raw):
    r = raw["returns_credit_notes"].copy()
    r["return_qty_abs"] = r["return_qty"].abs()
    r["return_date"] = pd.to_datetime(r["return_date"], errors="coerce")
    return r


def main():
    print(f"Reading raw db: {config.DB_PATH}")
    src = sqlite3.connect(config.DB_PATH)
    tables = [
        "regions", "warehouses", "routes", "salespeople", "outlets", "products",
        "product_price_history", "promotions", "orders", "order_lines", "deliveries",
        "inventory_snapshots", "returns_credit_notes",
    ]
    raw = {t: pd.read_sql(f"SELECT * FROM {t}", src) for t in tables}
    src.close()

    outlets = build_outlets(raw)
    orders = build_orders(raw)
    raw["orders"] = orders
    order_lines = build_order_lines(raw)
    deliveries = build_deliveries(raw, order_lines)
    returns = build_returns(raw)
    products = raw["products"].copy()
    products["discontinued_date"] = pd.to_datetime(products["discontinued_date"], errors="coerce")

    os.makedirs(os.path.dirname(config.CLEAN_DB_PATH), exist_ok=True)
    if os.path.exists(config.CLEAN_DB_PATH):
        os.remove(config.CLEAN_DB_PATH)
    out = sqlite3.connect(config.CLEAN_DB_PATH)

    outlets.to_sql("dim_outlets", out, index=False)
    products.to_sql("dim_products", out, index=False)
    raw["regions"].to_sql("dim_regions", out, index=False)
    raw["warehouses"].to_sql("dim_warehouses", out, index=False)
    raw["routes"].to_sql("dim_routes", out, index=False)
    orders.to_sql("fact_orders", out, index=False)
    order_lines.to_sql("fact_order_lines", out, index=False)
    deliveries.to_sql("fact_deliveries", out, index=False)
    returns.to_sql("fact_returns", out, index=False)
    raw["inventory_snapshots"].to_sql("fact_inventory_snapshots", out, index=False)
    raw["product_price_history"].to_sql("dim_product_price_history", out, index=False)

    for stmt in [
        "CREATE INDEX ix_fol_order ON fact_order_lines(order_id)",
        "CREATE INDEX ix_fol_product ON fact_order_lines(product_id)",
        "CREATE INDEX ix_fol_date ON fact_order_lines(order_date)",
        "CREATE INDEX ix_fd_order ON fact_deliveries(order_id)",
        "CREATE INDEX ix_fd_route ON fact_deliveries(route_id)",
        "CREATE INDEX ix_fo_outlet ON fact_orders(outlet_id)",
        "CREATE INDEX ix_fo_date ON fact_orders(order_date)",
        "CREATE INDEX ix_out_id ON dim_outlets(outlet_id)",
    ]:
        out.execute(stmt)
    out.commit()
    out.close()

    print(f"Wrote clean db: {config.CLEAN_DB_PATH}")
    print(f"  outlets: {len(outlets)} ({outlets['is_reportable'].sum()} reportable, "
          f"{outlets['possible_duplicate'].sum()} flagged possible duplicates)")
    print(f"  order_lines: {len(order_lines)} ({int(order_lines['ordered_after_discontinuation'].sum())} "
          f"ordered after SKU discontinuation)")
    print(f"  deliveries: {len(deliveries)} ({int(deliveries['excursion_derived'].sum())} derived cold-chain excursions)")


if __name__ == "__main__":
    main()
