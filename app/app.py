import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import data
import metrics
import nl
import charts

st.set_page_config(page_title="Kestrel Control Tower", layout="wide")


def degrade_banner(status):
    if not status["clean_db"]:
        st.error(
            "No cleaned database found. Run `python etl/build_clean_db.py` first "
            "(needs `data/kestrel_ops.db` supplied separately -- see README)."
        )
        st.stop()
    missing = []
    if not status["freight"]:
        missing.append("freight cost data (`python -m freight.ingest`, needs the partner API running)")
    if not status["price_matches"]:
        missing.append("competitor price data (`python -m scraper.scrape_and_match`, needs BazaarPulse served)")
    if missing:
        st.warning("Not loaded yet, those sections will show as empty: " + "; ".join(missing))


@st.cache_data
def build_ctx():
    d = data.load_clean_tables()
    freight = data.load_freight()
    price_matches = data.load_price_matches()
    ol = metrics.enrich_order_lines(d)
    dv = metrics.enrich_deliveries(d)
    od = metrics.enrich_orders(d)
    rt = metrics.enrich_returns(d)
    return {"data": d, "freight": freight, "price_matches": price_matches, "ol": ol, "dv": dv, "od": od, "rt": rt}


def sidebar_filters(ctx):
    st.sidebar.header("Filters")
    regions = ["All"] + sorted(ctx["data"]["regions"]["region_name"].dropna().unique().tolist())
    region = st.sidebar.selectbox("Region", regions)

    wh_options = ctx["data"]["warehouses"]
    if region != "All":
        region_id = ctx["data"]["regions"].loc[ctx["data"]["regions"]["region_name"] == region, "region_id"].iloc[0]
        wh_options = wh_options[wh_options["region_id"] == region_id]
    warehouse = st.sidebar.selectbox("Warehouse", ["All"] + sorted(wh_options["warehouse_code"].tolist()))

    channel = st.sidebar.selectbox("Channel", ["All", "GT", "MT", "HORECA", "ECOM_DARKSTORE"])

    # Bounds span order_date AND return_date -- a return can be filed weeks
    # after its order (return_date max is 2026-07-29 vs order_date max
    # 2026-06-30 in this data), so bounding on order_date alone silently
    # clipped the returns-based KPIs even at the "full range" default.
    date_min = min(ctx["ol"]["order_date"].min(), ctx["rt"]["return_date"].min()).date()
    date_max = max(ctx["ol"]["order_date"].max(), ctx["rt"]["return_date"].max()).date()
    date_range = st.sidebar.date_input("Date range", value=(date_min, date_max),
                                        min_value=date_min, max_value=date_max)
    if region != "All":
        st.sidebar.caption(f"Regional manager view: {region}")
    return region, warehouse, channel, date_range


def apply_filters(df, region, warehouse, channel, date_range, date_col="order_date"):
    out = df
    if region != "All":
        out = out[out["region_name"] == region]
    if warehouse != "All":
        out = out[out["warehouse_code"] == warehouse]
    if channel != "All":
        out = out[out["channel"] == channel]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        out = out[(out[date_col] >= start) & (out[date_col] <= end)]
    return out


def _quarter_headline(ol, dv, od, rt, q_start, q_end):
    """The 4 Overview KPIs for one quarter window, given already-filtered frames."""
    q_ol = ol[(ol["order_date"] >= q_start) & (ol["order_date"] <= q_end)]
    q_dv = dv[(dv["order_date"] >= q_start) & (dv["order_date"] <= q_end)]
    q_od = od[(od["order_date"] >= q_start) & (od["order_date"] <= q_end)]
    q_rt = rt[(rt["return_date"] >= q_start) & (rt["return_date"] <= q_end)]

    overall_fr = (q_ol[q_ol["order_status"].isin(metrics.FULFILLED_STATUSES) & q_ol["is_reportable"]]
                  [["delivered_eaches", "ordered_eaches"]].sum())
    fr_pct = round(overall_fr["delivered_eaches"] / overall_fr["ordered_eaches"] * 100, 1) \
        if overall_fr["ordered_eaches"] else None

    ot = metrics.otif(q_dv, q_ol, ["region_name"])
    otif_pct = round(ot["otif_count"].sum() / ot["deliveries"].sum() * 100, 1) if ot["deliveries"].sum() else None

    exc = metrics.cold_chain_excursions_by_month(q_dv)
    exc_rate = round(exc["excursions"].sum() / exc["chilled_deliveries"].sum() * 100, 1) \
        if len(exc) and exc["chilled_deliveries"].sum() else None

    ret_pct = metrics.returns_pct_of_dispatch(q_rt, q_od)
    return q_ol, fr_pct, otif_pct, exc_rate, ret_pct


def _delta(current, prior, higher_is_better=True):
    """(delta_string, delta_color) for st.metric -- None if either side is n/a."""
    if current is None or prior is None:
        return None, "off"
    d = round(current - prior, 1)
    return f"{d:+.1f} pts vs prior qtr", ("normal" if higher_is_better else "inverse")


def overview_tab(ctx, ol, dv, od, rt):
    # Quarter boundary derived from the data's own max date (unfiltered), not
    # hardcoded -- stays correct if the db is later refreshed with more months.
    q_start, q_end = metrics.last_complete_fy_quarter(ctx["ol"]["order_date"].max())
    prior_start, prior_end = metrics.last_complete_fy_quarter(q_start - pd.Timedelta(days=1))
    st.subheader(f"Q{((q_start.month - 4) % 12) // 3 + 1} FY -- {q_start:%b %Y} to {q_end:%b %Y} "
                 f"(the board asks about Q1 first)")

    q1_ol, fr_pct, otif_pct, exc_rate, ret_pct = _quarter_headline(ol, dv, od, rt, q_start, q_end)
    _, prior_fr, prior_otif, prior_exc, prior_ret = _quarter_headline(ol, dv, od, rt, prior_start, prior_end)

    c1, c2, c3, c4 = st.columns(4)
    d, dc = _delta(fr_pct, prior_fr, higher_is_better=True)
    c1.metric("Case fill rate (eaches)", f"{fr_pct}%" if fr_pct is not None else "n/a", delta=d, delta_color=dc)
    d, dc = _delta(otif_pct, prior_otif, higher_is_better=True)
    c2.metric("OTIF", f"{otif_pct}%" if otif_pct is not None else "n/a", delta=d, delta_color=dc)
    d, dc = _delta(exc_rate, prior_exc, higher_is_better=False)
    c3.metric("Cold-chain excursions / 100 chilled deliveries", f"{exc_rate}" if exc_rate is not None else "n/a",
              delta=d, delta_color=dc)
    d, dc = _delta(ret_pct, prior_ret, higher_is_better=False)
    c4.metric("Returns as % of dispatch value", f"{ret_pct}%" if ret_pct is not None else "n/a",
              delta=d, delta_color=dc)
    st.caption(f"Delta vs prior quarter ({prior_start:%b %Y} to {prior_end:%b %Y}). "
               "Colour follows whether the direction is good or bad for that metric, not just up/down.")

    st.markdown("**Worst 5 outlets by fill rate, Q1**")
    worst = metrics.fill_rate_eaches(q1_ol, ["outlet_name"])
    st.dataframe(worst[worst["ordered_eaches"] > 0].head(5), use_container_width=True,
                 column_config={"fill_rate_pct": st.column_config.NumberColumn(format="%.1f%%")})

    st.markdown("**Fill rate by region, Q1**")
    fr = metrics.fill_rate_eaches(q1_ol, ["region_name"])
    st.altair_chart(charts.bar(fr, "region_name", "fill_rate_pct", "Region", "Fill rate %"),
                     use_container_width=True)
    with st.expander("View as table"):
        st.dataframe(fr, use_container_width=True,
                     column_config={"fill_rate_pct": st.column_config.NumberColumn(format="%.1f%%")})


def service_tab(ol, dv):
    st.subheader("Service: fill rate & OTIF (eaches)")
    grain = st.radio("Break down by", ["region_name", "warehouse_code", "route_code", "outlet_name"],
                      horizontal=True, key="service_grain")
    fr = metrics.fill_rate_eaches(ol, [grain])
    fr = fr[fr["ordered_eaches"] > 0]
    st.markdown("Worst performers first (case fill rate, eaches)")
    st.dataframe(fr, use_container_width=True)

    ot = metrics.otif(dv, ol, [grain])
    st.markdown("OTIF, worst performers first")
    st.dataframe(ot, use_container_width=True)


def cold_chain_tab(ctx, dv, rt):
    st.subheader("Cold chain")
    exc = metrics.cold_chain_excursions_by_month(dv)
    st.markdown("Temperature excursions per hundred chilled deliveries, by month")
    st.altair_chart(charts.line(exc, "month", "excursions_per_100", "Month", "Excursions / 100"),
                     use_container_width=True)
    with st.expander("View as table"):
        st.dataframe(exc, use_container_width=True,
                     column_config={"excursions_per_100": st.column_config.NumberColumn(format="%.1f")})

    st.markdown("Near-expiry inventory (ageing bucket 61-90 or 90+ days)")
    inv = ctx["data"]["inventory"]
    near_expiry = inv[inv["ageing_bucket"].isin(["61-90", "90+"])]
    near_expiry_by_wh = near_expiry.groupby("warehouse_id")["on_hand_cases"].sum().reset_index()
    near_expiry_by_wh = near_expiry_by_wh.merge(
        ctx["data"]["warehouses"][["warehouse_id", "warehouse_code"]], on="warehouse_id"
    )
    st.dataframe(near_expiry_by_wh[["warehouse_code", "on_hand_cases"]], use_container_width=True)

    st.markdown("Returns attributed to cold-chain breach (reason RT06_COLD_CHAIN_BREACH)")
    cold_returns = rt[rt["return_reason_code"] == "RT06_COLD_CHAIN_BREACH"]
    st.metric("Cold-chain-breach credit note value (INR)", f"{cold_returns['credit_note_value_inr'].sum():,.0f}")


def money_tab(ctx, ol, rt):
    st.subheader("Money")
    st.markdown("Freight cost per delivered case, by warehouse and month")
    if ctx["freight"].empty:
        st.info("No freight data loaded. Run `python -m freight.ingest`.")
    else:
        fc = metrics.freight_cost_per_case(ctx["freight"], ol, ctx["data"]["warehouses"])
        st.dataframe(fc, use_container_width=True, column_config={
            "amount_inr": st.column_config.NumberColumn("Freight amount (INR)", format="%,.0f"),
            "freight_cost_per_case_inr": st.column_config.NumberColumn("Cost / case (INR)", format="%,.2f"),
        })
        st.caption("Excludes DISPUTED invoices (contested, unsettled) -- see DECISIONS.md.")

        st.markdown("Freight spend by carrier")
        by_carrier = ctx["freight"].groupby("carrier_name")["amount_inr"].sum() \
            .sort_values(ascending=False).reset_index()
        st.altair_chart(charts.bar(by_carrier, "carrier_name", "amount_inr", "Carrier", "Spend (INR)"),
                         use_container_width=True)
        with st.expander("View as table"):
            st.dataframe(by_carrier, use_container_width=True, column_config={
                "amount_inr": st.column_config.NumberColumn("Spend (INR)", format="%,.0f"),
            })

    st.markdown("Returns leakage by category (value and leading reason)")
    leak = metrics.returns_leakage_by_category(rt, ctx["data"]["products"])
    st.dataframe(leak, use_container_width=True, column_config={
        "credit_note_value_inr": st.column_config.NumberColumn("Credit note value (INR)", format="%,.0f"),
    })


def price_tab(ctx):
    st.subheader("Price position: our MRP vs lowest observed competitor price")
    if ctx["price_matches"].empty:
        st.info("No competitor price data loaded. Run `python -m scraper.scrape_and_match`.")
        return
    city = st.selectbox("City", ["All"] + sorted(ctx["price_matches"]["city"].dropna().unique().tolist()))
    pp = metrics.price_position(ctx["price_matches"], ctx["data"]["products"], city=None if city == "All" else city)
    st.markdown("Positive gap = we are priced above the lowest competitor; negative = below")
    st.dataframe(pp, use_container_width=True, column_config={
        "lowest_competitor_price_inr": st.column_config.NumberColumn("Lowest competitor price (INR)", format="%,.2f"),
        "kestrel_mrp_inr": st.column_config.NumberColumn("Kestrel MRP (INR)", format="%,.2f"),
        "gap_inr": st.column_config.NumberColumn("Gap (INR)", format="%,.2f"),
        "gap_pct": st.column_config.NumberColumn("Gap %", format="%.1f%%"),
    })
    match_rate = ctx["price_matches"]["matched_sku_code"].notna().mean() * 100
    st.caption(f"{match_rate:.0f}% of scraped listings matched to a Kestrel SKU "
               f"(see DECISIONS.md on matching method and confidence thresholds).")


SUGGESTED_QUESTIONS = [
    "which outlets had the lowest fill rate",
    "what was OTIF by region",
    "why did fill rate drop in the West last week",
    "MRP vs competitor price in Mumbai",
]


def ask_tab(ctx):
    st.subheader("Ask anything")
    if "ask_question" not in st.session_state:
        st.session_state["ask_question"] = ""

    st.caption("Try one of these, or type your own below -- no LLM key needed for any of it:")
    cols = st.columns(len(SUGGESTED_QUESTIONS))
    for i, sq in enumerate(SUGGESTED_QUESTIONS):
        if cols[i].button(sq, use_container_width=True, key=f"chip_{i}"):
            st.session_state["ask_question"] = sq

    with st.expander("Full list of what I can answer"):
        st.text(nl.CAPABILITIES)

    # A plain st.text_input + "if q:" re-showed the PREVIOUS question's answer
    # for one rerun after pressing Enter on a new one -- the widget's committed
    # value and the script's read of it weren't guaranteed to land in the same
    # rerun. st.form makes the text_input's value and the submit action land
    # together, atomically, so what's answered is always what was just typed.
    with st.form("ask_form"):
        q_input = st.text_input("Question", value=st.session_state["ask_question"],
                                 placeholder="e.g. why did fill rate drop in the West last week")
        submitted = st.form_submit_button("Ask")
    if submitted:
        st.session_state["ask_question"] = q_input

    q = st.session_state["ask_question"]
    if q:
        text, df = nl.answer(q, ctx)
        st.markdown(text)
        if df is not None:
            st.dataframe(df, use_container_width=True)


def main():
    st.title("Kestrel Provisions: Supply Chain Control Tower")
    status = data.data_status()
    degrade_banner(status)

    ctx = build_ctx()
    region, warehouse, channel, date_range = sidebar_filters(ctx)
    ol = apply_filters(ctx["ol"], region, warehouse, channel, date_range, "order_date")
    dv = apply_filters(ctx["dv"], region, warehouse, channel, date_range, "order_date")
    od = apply_filters(ctx["od"], region, warehouse, channel, date_range, "order_date")
    rt = apply_filters(ctx["rt"], region, warehouse, channel, date_range, "return_date")

    tabs = st.tabs(["Overview", "Service", "Cold Chain", "Money", "Price Position", "Ask Anything"])
    with tabs[0]:
        overview_tab(ctx, ol, dv, od, rt)
    with tabs[1]:
        service_tab(ol, dv)
    with tabs[2]:
        cold_chain_tab(ctx, dv, rt)
    with tabs[3]:
        money_tab(ctx, ol, rt)
    with tabs[4]:
        price_tab(ctx)
    with tabs[5]:
        ask_tab(ctx)  # unfiltered ctx -- NL questions parse their own scope from the question text


if __name__ == "__main__":
    main()
