import os
import sqlite3
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


@st.cache_data
def load_clean_tables():
    if not os.path.exists(config.CLEAN_DB_PATH):
        return None
    conn = sqlite3.connect(config.CLEAN_DB_PATH)
    tables = {
        "outlets": "dim_outlets",
        "products": "dim_products",
        "regions": "dim_regions",
        "warehouses": "dim_warehouses",
        "routes": "dim_routes",
        "orders": "fact_orders",
        "order_lines": "fact_order_lines",
        "deliveries": "fact_deliveries",
        "returns": "fact_returns",
        "inventory": "fact_inventory_snapshots",
    }
    data = {k: pd.read_sql(f"SELECT * FROM {v}", conn) for k, v in tables.items()}
    conn.close()

    # SQLite has no bool type -- these round-tripped through to_sql/read_sql as 0/1
    # ints, which pandas boolean indexing silently misinterprets as column labels.
    data["outlets"]["is_reportable"] = data["outlets"]["is_reportable"].astype(bool)
    data["outlets"]["possible_duplicate"] = data["outlets"]["possible_duplicate"].astype(bool)
    data["outlets"]["is_test_outlet"] = data["outlets"]["is_test_outlet"].astype(bool)
    data["deliveries"]["is_chilled_delivery"] = data["deliveries"]["is_chilled_delivery"].astype(bool)
    data["deliveries"]["excursion_derived"] = data["deliveries"]["excursion_derived"].astype(bool)
    data["order_lines"]["ordered_after_discontinuation"] = (
        data["order_lines"]["ordered_after_discontinuation"].astype(bool)
    )
    data["returns"]["is_settled"] = data["returns"]["is_settled"].astype(bool)

    for col in ["order_date"]:
        data["order_lines"][col] = pd.to_datetime(data["order_lines"][col], errors="coerce")
    data["orders"]["order_date"] = pd.to_datetime(data["orders"]["order_date"], errors="coerce")
    data["returns"]["return_date"] = pd.to_datetime(data["returns"]["return_date"], errors="coerce")
    data["inventory"]["snapshot_date"] = pd.to_datetime(data["inventory"]["snapshot_date"], errors="coerce")
    data["deliveries"]["planned_arrival"] = pd.to_datetime(data["deliveries"]["planned_arrival"], errors="coerce")
    data["deliveries"]["actual_arrival"] = pd.to_datetime(data["deliveries"]["actual_arrival"], errors="coerce")
    return data


@st.cache_data
def load_freight():
    if not os.path.exists(config.FREIGHT_CACHE_PATH):
        return pd.DataFrame()
    df = pd.read_csv(config.FREIGHT_CACHE_PATH)
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    return df


@st.cache_data
def load_price_matches():
    if not os.path.exists(config.PRICE_MATCH_CACHE_PATH):
        return pd.DataFrame()
    return pd.read_csv(config.PRICE_MATCH_CACHE_PATH)


def data_status():
    """What's actually available, so the UI can degrade instead of crash."""
    return {
        "clean_db": os.path.exists(config.CLEAN_DB_PATH),
        "freight": os.path.exists(config.FREIGHT_CACHE_PATH),
        "price_matches": os.path.exists(config.PRICE_MATCH_CACHE_PATH),
    }
