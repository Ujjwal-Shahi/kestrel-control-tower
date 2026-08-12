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

st.set_page_config(page_title="Kestrel Control Tower", layout="wide", page_icon="\U0001F4E6")

# One accent hue (the dataviz skill's own dark-mode blue, same one the charts
# use) applied as a soft glow on hover -- restrained on purpose. "Futuristic"
# here means dark surface + one consistent accent, not five competing effects.
_CUSTOM_CSS = """
<style>
:root {
    --kt-accent: #3987e5;
    --kt-accent-2: #7c5cff;
    --kt-glow: rgba(57, 135, 229, 0.35);
}

h1 {
    background: linear-gradient(90deg, var(--kt-accent), var(--kt-accent-2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.02em;
}

div[data-testid="stMetric"] {
    background: linear-gradient(160deg, rgba(57,135,229,0.10), rgba(124,92,255,0.03));
    border: 1px solid rgba(57,135,229,0.20);
    border-radius: 14px;
    padding: 14px 16px 10px 16px;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
div[data-testid="stMetric"]:hover {
    border-color: rgba(57,135,229,0.55);
    box-shadow: 0 0 22px var(--kt-glow);
    transform: translateY(-2px);
}

button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primaryFormSubmit"] {
    border-radius: 10px !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    box-shadow: 0 0 16px var(--kt-glow);
    border-color: var(--kt-accent) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 16px !important;
}

div[data-testid="stVegaLiteChart"] {
    border-radius: 12px;
    overflow: hidden;
}

section[data-testid="stSidebar"] {
    border-right: 1px solid rgba(57,135,229,0.15);
}
</style>
"""


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


@st.cache_data(show_spinner="Loading Kestrel data (first run only -- every tab is cached after this)...")
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


def _filtered(ctx, key, region, warehouse, channel, date_range):
    date_col = "return_date" if key == "rt" else "order_date"
    return apply_filters(ctx[key], region, warehouse, channel, date_range, date_col)


# ---- Cached per-tab computations, keyed by cheap primitives (not dataframes). ----
# st.tabs renders every tab's Python code on every rerun regardless of which tab
# is visually active (confirmed by inspecting the live DOM -- all six tabpanels
# exist at once, only CSS hides the inactive ones). Without this, clicking
# anything anywhere -- a filter, a chip, the Ask button -- recomputes every
# groupby for every tab, which is what made the app feel slow. Caching on
# (region, warehouse, channel, date_range, ...) means a rerun that didn't
# change those values is a cache hit, not a recompute.

@st.cache_data(show_spinner=False)
def cached_fill_rate(region, warehouse, channel, date_range, grain, q_start=None, q_end=None):
    ctx = build_ctx()
    ol = _filtered(ctx, "ol", region, warehouse, channel, date_range)
    if q_start is not None:
        ol = ol[(ol["order_date"] >= q_start) & (ol["order_date"] <= q_end)]
    return metrics.fill_rate_eaches(ol, [grain])


@st.cache_data(show_spinner=False)
def cached_otif(region, warehouse, channel, date_range, grain, q_start=None, q_end=None):
    ctx = build_ctx()
    ol = _filtered(ctx, "ol", region, warehouse, channel, date_range)
    dv = _filtered(ctx, "dv", region, warehouse, channel, date_range)
    if q_start is not None:
        ol = ol[(ol["order_date"] >= q_start) & (ol["order_date"] <= q_end)]
        dv = dv[(dv["order_date"] >= q_start) & (dv["order_date"] <= q_end)]
    return metrics.otif(dv, ol, [grain])


@st.cache_data(show_spinner=False)
def cached_excursions(region, warehouse, channel, date_range, q_start=None, q_end=None):
    ctx = build_ctx()
    dv = _filtered(ctx, "dv", region, warehouse, channel, date_range)
    if q_start is not None:
        dv = dv[(dv["order_date"] >= q_start) & (dv["order_date"] <= q_end)]
    return metrics.cold_chain_excursions_by_month(dv)


@st.cache_data(show_spinner=False)
def cached_returns_pct(region, warehouse, channel, date_range, q_start=None, q_end=None):
    ctx = build_ctx()
    rt = _filtered(ctx, "rt", region, warehouse, channel, date_range)
    od = _filtered(ctx, "od", region, warehouse, channel, date_range)
    if q_start is not None:
        rt = rt[(rt["return_date"] >= q_start) & (rt["return_date"] <= q_end)]
        od = od[(od["order_date"] >= q_start) & (od["order_date"] <= q_end)]
    return metrics.returns_pct_of_dispatch(rt, od)


@st.cache_data(show_spinner=False)
def cached_freight_cost(region, warehouse, channel, date_range):
    ctx = build_ctx()
    if ctx["freight"].empty:
        return pd.DataFrame()
    ol = _filtered(ctx, "ol", region, warehouse, channel, date_range)
    return metrics.freight_cost_per_case(ctx["freight"], ol, ctx["data"]["warehouses"])


@st.cache_data(show_spinner=False)
def cached_carrier_spend(region, warehouse, channel, date_range):
    ctx = build_ctx()
    if ctx["freight"].empty:
        return pd.DataFrame()
    return ctx["freight"].groupby("carrier_name")["amount_inr"].sum().sort_values(ascending=False).reset_index()


@st.cache_data(show_spinner=False)
def cached_returns_leakage(region, warehouse, channel, date_range):
    ctx = build_ctx()
    rt = _filtered(ctx, "rt", region, warehouse, channel, date_range)
    return metrics.returns_leakage_by_category(rt, ctx["data"]["products"])


@st.cache_data(show_spinner=False)
def cached_cold_chain_breach_value(region, warehouse, channel, date_range):
    ctx = build_ctx()
    rt = _filtered(ctx, "rt", region, warehouse, channel, date_range)
    return rt.loc[rt["return_reason_code"] == "RT06_COLD_CHAIN_BREACH", "credit_note_value_inr"].sum()


@st.cache_data(show_spinner=False)
def cached_near_expiry():
    ctx = build_ctx()
    inv = ctx["data"]["inventory"]
    near_expiry = inv[inv["ageing_bucket"].isin(["61-90", "90+"])]
    by_wh = near_expiry.groupby("warehouse_id")["on_hand_cases"].sum().reset_index()
    by_wh = by_wh.merge(ctx["data"]["warehouses"][["warehouse_id", "warehouse_code"]], on="warehouse_id")
    return by_wh[["warehouse_code", "on_hand_cases"]]


@st.cache_data(show_spinner=False)
def cached_price_position(city):
    ctx = build_ctx()
    return metrics.price_position(ctx["price_matches"], ctx["data"]["products"], city=city)


@st.cache_data(show_spinner=False)
def cached_nl_answer(question):
    ctx = build_ctx()
    return nl.answer(question, ctx)


# ---- Overview helpers ----

def _delta(current, prior, higher_is_better=True):
    """(delta_string, delta_color) for st.metric -- None if either side is n/a."""
    if current is None or prior is None:
        return None, "off"
    d = round(current - prior, 1)
    return f"{d:+.1f} pts vs prior qtr", ("normal" if higher_is_better else "inverse")


def _status_badge(delta_value, higher_is_better):
    """Icon + label, never colour alone (dataviz skill's status-colour rule)."""
    if delta_value is None:
        return ""
    good = (delta_value > 0) if higher_is_better else (delta_value < 0)
    if abs(delta_value) < 0.3:
        return ":gray[– Flat]"
    return ":green[▲ Improving]" if good else ":red[▼ Worsening]"


def overview_tab(region, warehouse, channel, date_range):
    q_start, q_end = metrics.last_complete_fy_quarter(build_ctx()["ol"]["order_date"].max())
    prior_start, prior_end = metrics.last_complete_fy_quarter(q_start - pd.Timedelta(days=1))
    quarter_num = ((q_start.month - 4) % 12) // 3 + 1
    st.subheader(f"Q{quarter_num} FY — {q_start:%b %Y} to {q_end:%b %Y} (the board asks about Q1 first)")

    fr = cached_fill_rate(region, warehouse, channel, date_range, "region_name", q_start, q_end)
    fr_by_outlet = cached_fill_rate(region, warehouse, channel, date_range, "outlet_name", q_start, q_end)
    fr_val = round(fr["delivered_eaches"].sum() / fr["ordered_eaches"].sum() * 100, 1) \
        if fr["ordered_eaches"].sum() else None

    ot = cached_otif(region, warehouse, channel, date_range, "region_name", q_start, q_end)
    otif_val = round(ot["otif_count"].sum() / ot["deliveries"].sum() * 100, 1) if ot["deliveries"].sum() else None

    exc = cached_excursions(region, warehouse, channel, date_range, q_start, q_end)
    exc_val = round(exc["excursions"].sum() / exc["chilled_deliveries"].sum() * 100, 1) \
        if len(exc) and exc["chilled_deliveries"].sum() else None

    ret_val = cached_returns_pct(region, warehouse, channel, date_range, q_start, q_end)

    fr_p = cached_fill_rate(region, warehouse, channel, date_range, "region_name", prior_start, prior_end)
    fr_prior = round(fr_p["delivered_eaches"].sum() / fr_p["ordered_eaches"].sum() * 100, 1) \
        if fr_p["ordered_eaches"].sum() else None
    ot_p = cached_otif(region, warehouse, channel, date_range, "region_name", prior_start, prior_end)
    otif_prior = round(ot_p["otif_count"].sum() / ot_p["deliveries"].sum() * 100, 1) if ot_p["deliveries"].sum() else None
    exc_p = cached_excursions(region, warehouse, channel, date_range, prior_start, prior_end)
    exc_prior = round(exc_p["excursions"].sum() / exc_p["chilled_deliveries"].sum() * 100, 1) \
        if len(exc_p) and exc_p["chilled_deliveries"].sum() else None
    ret_prior = cached_returns_pct(region, warehouse, channel, date_range, prior_start, prior_end)

    kpis = [
        ("\U0001F4E6 Case fill rate (eaches)", fr_val, fr_prior, True, "%", None),
        ("\U0001F69A OTIF", otif_val, otif_prior, True, "%",
         "Strict definition: any delay at all counts as late (no grace window), and "
         "'in full' compares delivered to allocated stock, not to what was originally "
         "ordered -- so this reads much lower than fill rate on the same orders. "
         "That's expected under this definition, not a data error -- see DECISIONS.md."),
        ("❄️ Cold-chain excursions / 100 chilled", exc_val, exc_prior, False, "", None),
        ("\U0001F4B8 Returns as % of dispatch value", ret_val, ret_prior, False, "%", None),
    ]
    cols = st.columns(4)
    for col, (label, val, prior, higher_better, unit, help_text) in zip(cols, kpis):
        d, dc = _delta(val, prior, higher_better)
        col.metric(label, f"{val}{unit}" if val is not None else "n/a", delta=d, delta_color=dc, help=help_text)
        delta_raw = None if (val is None or prior is None) else round(val - prior, 1)
        col.markdown(_status_badge(delta_raw, higher_better))
    st.caption(f"vs prior quarter ({prior_start:%b %Y} to {prior_end:%b %Y}) — "
               "status reflects direction of travel, not an absolute target.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Worst 5 outlets by fill rate, Q1**")
        st.dataframe(fr_by_outlet[fr_by_outlet["ordered_eaches"] > 0].head(5), use_container_width=True,
                     column_config={"fill_rate_pct": st.column_config.NumberColumn(format="%.1f%%")})
    with right:
        st.markdown("**Fill rate by region, Q1**")
        st.altair_chart(charts.bar(fr, "region_name", "fill_rate_pct", "Region", "Fill rate %", height=260, width=500))
    with st.expander("View region chart as table"):
        st.dataframe(fr, use_container_width=True,
                     column_config={"fill_rate_pct": st.column_config.NumberColumn(format="%.1f%%")})


def service_tab(region, warehouse, channel, date_range):
    st.subheader("Service: fill rate & OTIF (eaches)")
    grain = st.radio("Break down by", ["region_name", "warehouse_code", "route_code", "outlet_name"],
                      horizontal=True, key="service_grain")
    fr = cached_fill_rate(region, warehouse, channel, date_range, grain)
    fr = fr[fr["ordered_eaches"] > 0]
    st.markdown("Worst performers first (case fill rate, eaches)")
    st.dataframe(fr, use_container_width=True,
                 column_config={"fill_rate_pct": st.column_config.NumberColumn(format="%.1f%%")})

    ot = cached_otif(region, warehouse, channel, date_range, grain)
    st.markdown("OTIF, worst performers first")
    st.dataframe(ot, use_container_width=True,
                 column_config={"otif_pct": st.column_config.NumberColumn(format="%.1f%%")})


def cold_chain_tab(region, warehouse, channel, date_range):
    st.subheader("Cold chain")
    exc = cached_excursions(region, warehouse, channel, date_range)
    st.markdown("Temperature excursions per hundred chilled deliveries, by month")
    st.altair_chart(charts.line(exc, "month", "excursions_per_100", "Month", "Excursions / 100", width=900))
    with st.expander("View as table"):
        st.dataframe(exc, use_container_width=True,
                     column_config={"excursions_per_100": st.column_config.NumberColumn(format="%.1f")})

    st.markdown("Near-expiry inventory (ageing bucket 61-90 or 90+ days)")
    st.dataframe(cached_near_expiry(), use_container_width=True)

    st.markdown("Returns attributed to cold-chain breach (reason RT06_COLD_CHAIN_BREACH)")
    breach_value = cached_cold_chain_breach_value(region, warehouse, channel, date_range)
    st.metric("Cold-chain-breach credit note value", charts.fmt_inr_compact(breach_value))


def money_tab(region, warehouse, channel, date_range):
    ctx = build_ctx()
    st.subheader("Money")
    st.markdown("Freight cost per delivered case, by warehouse and month")
    if ctx["freight"].empty:
        st.info("No freight data loaded. Run `python -m freight.ingest`.")
    else:
        fc = cached_freight_cost(region, warehouse, channel, date_range).copy()
        fc["freight_amount_cr"] = charts.to_crore(fc["amount_inr"])
        st.dataframe(
            fc[["warehouse_code", "month", "freight_amount_cr", "delivered_cases_equiv", "freight_cost_per_case_inr"]],
            use_container_width=True,
            column_config={
                "warehouse_code": "Warehouse",
                "month": "Month",
                "freight_amount_cr": st.column_config.NumberColumn("Freight amount (₹ Cr)", format="%.2f"),
                "delivered_cases_equiv": st.column_config.NumberColumn("Delivered cases", format="%.0f"),
                "freight_cost_per_case_inr": st.column_config.NumberColumn("Cost / case (₹)", format="%.2f"),
            },
        )
        st.caption("Excludes DISPUTED invoices (contested, unsettled) -- see DECISIONS.md.")

        st.markdown("Freight spend by carrier")
        by_carrier = cached_carrier_spend(region, warehouse, channel, date_range).copy()
        by_carrier["spend_cr"] = charts.to_crore(by_carrier["amount_inr"])
        st.altair_chart(charts.bar(by_carrier, "carrier_name", "spend_cr", "Carrier", "Spend (₹ Cr)", width=900))
        with st.expander("View as table"):
            st.dataframe(by_carrier[["carrier_name", "spend_cr"]], use_container_width=True,
                         column_config={"spend_cr": st.column_config.NumberColumn("Spend (₹ Cr)", format="%.2f")})

    st.markdown("Returns leakage by category (value and leading reason)")
    leak = cached_returns_leakage(region, warehouse, channel, date_range).copy()
    leak["credit_note_lakh"] = charts.to_lakh(leak["credit_note_value_inr"])
    st.dataframe(leak[["category", "credit_note_lakh", "return_lines", "leading_reason_code"]],
                 use_container_width=True,
                 column_config={
                     "credit_note_lakh": st.column_config.NumberColumn("Credit notes (₹ L)", format="%.2f"),
                     "return_lines": "Return lines",
                     "leading_reason_code": "Leading reason",
                 })


def price_tab(ctx):
    st.subheader("Price position: our MRP vs lowest observed competitor price")
    if ctx["price_matches"].empty:
        st.info("No competitor price data loaded. Run `python -m scraper.scrape_and_match`.")
        return
    city = st.selectbox("City", ["All"] + sorted(ctx["price_matches"]["city"].dropna().unique().tolist()))
    pp = cached_price_position(None if city == "All" else city)

    avg_gap = pp["gap_pct"].mean() if len(pp) else None
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("Average price gap", f"{avg_gap:+.1f}%" if avg_gap is not None else "n/a",
                   help="Positive = we're priced above competitors on average; negative = below")
        if avg_gap is not None:
            direction = "above" if avg_gap >= 0 else "below"
            st.caption(f"Our MRP sits {abs(avg_gap):.1f}% {direction} the lowest observed competitor price "
                       f"in {city if city != 'All' else 'all scraped cities'}, on average across matched SKUs.")
    with c2:
        if len(pp):
            by_cat = pp.groupby("category")["gap_pct"].mean().reset_index().sort_values("gap_pct", ascending=False)
            st.altair_chart(charts.bar(by_cat, "category", "gap_pct", "Category", "Avg gap %", height=220, width=580))

    st.markdown("All matched SKUs (₹ = INR). Positive gap = priced above the lowest competitor; negative = below.")
    st.dataframe(
        pp[["matched_sku_code", "city", "category", "kestrel_mrp_inr", "lowest_competitor_price_inr",
            "gap_inr", "gap_pct"]],
        use_container_width=True,
        column_config={
            "matched_sku_code": "SKU",
            "kestrel_mrp_inr": st.column_config.NumberColumn("Kestrel MRP (₹)", format="%.2f"),
            "lowest_competitor_price_inr": st.column_config.NumberColumn("Lowest competitor price (₹)", format="%.2f"),
            "gap_inr": st.column_config.NumberColumn("Gap (₹)", format="%.2f"),
            "gap_pct": st.column_config.NumberColumn("Gap %", format="%.1f%%"),
        },
    )
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

    with st.container(border=True):
        st.caption("No LLM key needed — try one of these, or type your own:")
        cols = st.columns(len(SUGGESTED_QUESTIONS))
        for i, sq in enumerate(SUGGESTED_QUESTIONS):
            if cols[i].button(sq, use_container_width=True, key=f"chip_{i}"):
                st.session_state["ask_question"] = sq

        # st.form makes the text_input's value and the submit action land in the
        # same rerun -- a plain text_input + "if q:" showed the PREVIOUS
        # question's answer for one rerun after pressing Enter on a new one.
        with st.form("ask_form", border=False):
            q_input = st.text_input("Search or ask a question", value=st.session_state["ask_question"],
                                     placeholder="e.g. why did fill rate drop in the West last week",
                                     label_visibility="collapsed")
            submitted = st.form_submit_button("\U0001F50D Ask", use_container_width=True, type="primary")
        if submitted:
            st.session_state["ask_question"] = q_input

    with st.expander("Full list of what I can answer"):
        st.text(nl.CAPABILITIES)

    q = st.session_state["ask_question"]
    if q:
        text, df = cached_nl_answer(q)
        st.markdown(f"**{text}**")
        if df is not None:
            st.dataframe(df, use_container_width=True)


def main():
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    st.title("Kestrel Provisions: Supply Chain Control Tower")
    status = data.data_status()
    degrade_banner(status)

    ctx = build_ctx()
    region, warehouse, channel, date_range = sidebar_filters(ctx)

    tabs = st.tabs(["\U0001F4CA Overview", "\U0001F69A Service", "❄️ Cold Chain",
                     "\U0001F4B0 Money", "\U0001F3F7️ Price Position", "\U0001F50D Ask Anything"])
    with tabs[0]:
        overview_tab(region, warehouse, channel, date_range)
    with tabs[1]:
        service_tab(region, warehouse, channel, date_range)
    with tabs[2]:
        cold_chain_tab(region, warehouse, channel, date_range)
    with tabs[3]:
        money_tab(region, warehouse, channel, date_range)
    with tabs[4]:
        price_tab(ctx)
    with tabs[5]:
        ask_tab(ctx)  # unfiltered ctx -- NL questions parse their own scope from the question text


if __name__ == "__main__":
    main()
