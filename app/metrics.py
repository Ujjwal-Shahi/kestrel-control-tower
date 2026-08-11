"""
KPI definitions. Every non-obvious threshold or denominator choice is a
judgement call -- see DECISIONS.md, not buried here as a magic number.
"""
import pandas as pd

ON_TIME_GRACE_MINUTES = 0  # delay_minutes <= this counts as on-time
LATE_THRESHOLD_MINUTES = 120  # ">2 hours late" per brief Q5


def enrich_order_lines(data):
    ol = data["order_lines"].merge(
        data["orders"][["order_id", "region_id", "warehouse_id", "route_id", "outlet_id", "order_status"]],
        on="order_id", how="left", suffixes=("", "_o"),
    )
    ol = ol.merge(data["regions"][["region_id", "region_name"]], on="region_id", how="left")
    ol = ol.merge(data["warehouses"][["warehouse_id", "warehouse_code", "warehouse_name"]],
                   on="warehouse_id", how="left")
    ol = ol.merge(data["routes"][["route_id", "route_code"]], on="route_id", how="left")
    ol = ol.merge(
        data["outlets"][["outlet_id", "outlet_name", "city_clean", "channel", "is_reportable"]],
        on="outlet_id", how="left",
    )
    return ol


def enrich_deliveries(data):
    # deliveries already carries its own warehouse_id/route_id -- pull only the
    # columns orders adds that deliveries doesn't have, to avoid _x/_y collisions.
    d = data["deliveries"].merge(
        data["orders"][["order_id", "region_id", "outlet_id", "order_date", "order_status"]],
        on="order_id", how="left",
    )
    d = d.merge(data["regions"][["region_id", "region_name"]], on="region_id", how="left")
    d = d.merge(data["warehouses"][["warehouse_id", "warehouse_code", "warehouse_name"]],
                on="warehouse_id", how="left")
    d = d.merge(data["routes"][["route_id", "route_code"]], on="route_id", how="left")
    d = d.merge(
        data["outlets"][["outlet_id", "outlet_name", "city_clean", "channel", "is_reportable"]],
        on="outlet_id", how="left",
    )
    return d


FULFILLED_STATUSES = ("DELIVERED", "PARTIAL")


def fill_rate_eaches(ol, group_cols, reportable_only=True):
    """Case fill rate reported in eaches per Rakesh's override. Denominator
    is orders that reached fulfillment (DELIVERED/PARTIAL) -- CANCELLED orders
    never shipped and OPEN orders haven't concluded, so neither belongs in a
    fill-rate denominator."""
    df = ol[ol["order_status"].isin(FULFILLED_STATUSES)]
    if reportable_only:
        df = df[df["is_reportable"]]
    g = df.groupby(group_cols).agg(
        ordered_eaches=("ordered_eaches", "sum"),
        delivered_eaches=("delivered_eaches", "sum"),
    ).reset_index()
    g["fill_rate_pct"] = (g["delivered_eaches"] / g["ordered_eaches"] * 100).round(1)
    return g.sort_values("fill_rate_pct")


def otif(deliveries, order_lines, group_cols, reportable_only=True):
    """OTIF at order grain: on-time (delay_minutes <= grace) AND in-full.

    'In full' compares delivered_eaches to ALLOCATED_eaches, not ordered_eaches.
    In this data delivered_qty never once reaches ordered_qty for any order
    (max observed fill ratio 99.4%, most orders 75-90%) -- the ordered-to-
    allocated gap is an availability/backorder problem, already captured by
    fill_rate_eaches. Measuring OTIF's 'in full' leg against ordered_eaches
    would make OTIF read ~0% everywhere and double-count that same gap. The
    allocated-to-delivered leg is the actual pick/pack/dispatch execution
    question OTIF is meant to answer. See DECISIONS.md."""
    line_fill = order_lines.groupby("order_id").agg(
        allocated_eaches=("allocated_eaches", "sum"), delivered_eaches=("delivered_eaches", "sum"),
    ).reset_index()
    line_fill["in_full"] = line_fill["delivered_eaches"] >= line_fill["allocated_eaches"]

    d = deliveries.merge(line_fill[["order_id", "in_full"]], on="order_id", how="left")
    if reportable_only:
        d = d[d["is_reportable"]]
    d["on_time"] = d["delay_minutes"] <= ON_TIME_GRACE_MINUTES
    d["otif"] = d["on_time"] & d["in_full"].fillna(False)
    g = d.groupby(group_cols).agg(deliveries=("order_id", "count"), otif_count=("otif", "sum")).reset_index()
    g["otif_pct"] = (g["otif_count"] / g["deliveries"] * 100).round(1)
    return g.sort_values("otif_pct")


def cold_chain_excursions_by_month(deliveries):
    d = deliveries[deliveries["is_chilled_delivery"]].copy()
    d["month"] = d["order_date"].dt.to_period("M").astype(str)
    g = d.groupby("month").agg(
        chilled_deliveries=("delivery_id", "count"), excursions=("excursion_derived", "sum"),
    ).reset_index()
    g["excursions_per_100"] = (g["excursions"] / g["chilled_deliveries"] * 100).round(1)
    return g.sort_values("month")


def late_routes(deliveries, min_delivery_count=10):
    """Routes where >1 in 10 deliveries are more than LATE_THRESHOLD_MINUTES late."""
    d = deliveries.copy()
    d["is_very_late"] = d["delay_minutes"] > LATE_THRESHOLD_MINUTES
    g = d.groupby("route_code").agg(
        deliveries=("delivery_id", "count"), very_late=("is_very_late", "sum"),
    ).reset_index()
    g = g[g["deliveries"] >= min_delivery_count]
    g["very_late_rate_pct"] = (g["very_late"] / g["deliveries"] * 100).round(1)
    return g[g["very_late_rate_pct"] > 10].sort_values("very_late_rate_pct", ascending=False)


def returns_leakage_by_category(returns, order_lines, products):
    r = returns.merge(products[["product_id", "category"]], on="product_id", how="left")
    g = r.groupby("category").agg(
        credit_note_value_inr=("credit_note_value_inr", "sum"),
        return_lines=("return_id", "count"),
    ).reset_index()
    top_reason = (
        r.groupby(["category", "return_reason_code"]).size().reset_index(name="n")
        .sort_values("n", ascending=False).drop_duplicates("category")
        .set_index("category")["return_reason_code"]
    )
    g["leading_reason_code"] = g["category"].map(top_reason)
    return g.sort_values("credit_note_value_inr", ascending=False)


def returns_pct_of_dispatch(returns, orders, group_cols=None):
    dispatch_value = orders.loc[orders["order_status"].isin(FULFILLED_STATUSES), "order_value_net_inr"].sum()
    returns_value = returns["credit_note_value_inr"].sum()
    overall = round(returns_value / dispatch_value * 100, 2) if dispatch_value else None
    return overall


def freight_cost_per_case(freight, order_lines, warehouses, period_start=None, period_end=None):
    """Freight invoices carry no order-level key -- only warehouse_code/route_code/date
    (see DECISIONS.md). Cost per case is therefore a warehouse-month aggregate,
    not a shipment-level join."""
    f = freight.copy()
    if period_start is not None:
        f = f[f["invoice_date"] >= period_start]
    if period_end is not None:
        f = f[f["invoice_date"] <= period_end]
    f["month"] = f["invoice_date"].dt.to_period("M").astype(str)
    freight_by_wh_month = f.groupby(["warehouse_code", "month"])["amount_inr"].sum().reset_index()

    ol = order_lines.copy()
    if period_start is not None:
        ol = ol[ol["order_date"] >= period_start]
    if period_end is not None:
        ol = ol[ol["order_date"] <= period_end]
    ol = ol[ol["order_status"].isin(FULFILLED_STATUSES)]
    ol["delivered_cases_equiv"] = ol["delivered_eaches"] / ol["case_pack_at_order"]
    ol["month"] = ol["order_date"].dt.to_period("M").astype(str)
    cases_by_wh_month = ol.groupby(["warehouse_code", "month"])["delivered_cases_equiv"].sum().reset_index()

    merged = freight_by_wh_month.merge(cases_by_wh_month, on=["warehouse_code", "month"], how="inner")
    merged["freight_cost_per_case_inr"] = (merged["amount_inr"] / merged["delivered_cases_equiv"]).round(2)
    return merged.sort_values(["warehouse_code", "month"])


def price_position(price_matches, products, city=None):
    pm = price_matches[price_matches["matched_sku_code"].notna()].copy()
    if city:
        pm = pm[pm["city"] == city]
    lowest = pm.groupby(["matched_sku_code", "city"]).agg(
        lowest_competitor_price_inr=("price_inr", "min"),
        kestrel_mrp_inr=("kestrel_mrp_inr", "first"),
    ).reset_index()
    lowest["gap_inr"] = (lowest["kestrel_mrp_inr"] - lowest["lowest_competitor_price_inr"]).round(2)
    lowest["gap_pct"] = (lowest["gap_inr"] / lowest["kestrel_mrp_inr"] * 100).round(1)
    return lowest.sort_values("gap_pct")


def discontinued_orders(order_lines):
    return order_lines[order_lines["ordered_after_discontinuation"]]
