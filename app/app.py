import os
import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def _embed_html(html, height=0):
    """st.components.v1.html is deprecated for removal after 2026-06-01; st.iframe
    is its replacement but only exists on newer Streamlit. Prefer the new API when
    present so a reviewer on a current release doesn't hit a removed function, and
    fall back on older ones. This is a purely cosmetic accessibility patch, so if
    neither path exists the app must still run -- hence the bare except."""
    try:
        if hasattr(st, "iframe"):
            st.iframe(html, height=height)
        else:
            components.html(html, height=height)
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import data
import metrics
import nl
import charts
import tables

st.set_page_config(page_title="Kestrel Control Tower", layout="wide", page_icon="\U0001F4E6")

# ONE accent hue, no second gradient color, no outer glow -- per taste-skill's
# LILA RULE (no default "AI purple/blue glow") and Section 9.A ("no neon /
# outer glows -- use inner borders or subtle tinted shadows instead"). The
# first pass here used a blue-to-violet gradient title and a blurred outer
# glow on hover -- both are the exact patterns that rule exists to catch.
_CUSTOM_CSS = """
<style>
:root {
    --kt-accent: #3987e5;
    --kt-accent-tint: rgba(57, 135, 229, 0.14);
}

h1 {
    color: var(--kt-accent);
    letter-spacing: -0.02em;
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}

/* Section subheaders ("Cold chain", "Money", the Overview quarter line, ...)
   get a left accent bar instead of relying on size/weight alone to mark
   "a new section starts here" -- the same accent used everywhere else,
   not a second color, per the color-consistency lock. */
h3 {
    border-left: 3px solid var(--kt-accent);
    padding-left: 12px;
    letter-spacing: -0.01em;
}

/* KPI cards: a top accent stripe (the "dashboard tile" convention BI tools
   use -- Grafana, Looker, Datadog) plus tabular-nums on the headline number
   so 85.6% and 100.0% occupy the same visual width. Shape-lock exception,
   documented: cards are 14px, this stripe follows the card's own radius at
   the two top corners only, not a second radius scale. */
div[data-testid="stMetric"] {
    position: relative;
    background: var(--kt-accent-tint);
    border: 1px solid rgba(57,135,229,0.20);
    border-radius: 14px;
    padding: 18px 16px 10px 16px;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    overflow: hidden;
}
div[data-testid="stMetric"]::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--kt-accent);
    opacity: 0.55;
}
div[data-testid="stMetric"]:hover {
    border-color: rgba(57,135,229,0.55);
    box-shadow: inset 0 1px 0 rgba(57,135,229,0.25);
    transform: translateY(-1px);
}
div[data-testid="stMetricValue"] {
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
}

button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primaryFormSubmit"],
button[data-testid="stBaseButton-primary"] {
    border-radius: 10px !important;
    transition: border-color 0.2s ease, background 0.2s ease, transform 0.1s ease;
}
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    border-color: var(--kt-accent) !important;
    background: var(--kt-accent-tint);
}
/* Tactile feedback on click (skill's Section 4.5) -- a real physical-press
   cue, not decoration, so it's gated to :active only. */
button[data-testid="stBaseButton-secondary"]:active,
button[data-testid="stBaseButton-primaryFormSubmit"]:active,
button[data-testid="stBaseButton-primary"]:active {
    transform: translateY(1px) scale(0.98);
}
/* Pagination page-number buttons (app/tables.py) -- the current page uses
   Streamlit's own type="primary" (solid accent fill), everything else is
   the default secondary style above. Tight padding keeps a 32-page row
   (Price Position's matched-SKU list) from forcing horizontal scroll on
   the whole page. */
div[data-testid="stHorizontalBlock"] button[data-testid^="stBaseButton"] {
    min-width: 0;
    padding-left: 8px;
    padding-right: 8px;
}

/* Status badges (Overview KPI trend chips) -- was plain colored text via
   Streamlit's :green[]/:red[] markdown shortcode, upgraded to a tinted pill
   to match the rest of the app's chip/card language instead of being the
   one plain-text element on the page. Pill radius is the shape-lock's
   documented interactive-chip exception (see DECISIONS.md). */
.kt-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.01em;
}
.kt-badge-good { background: rgba(63,185,80,0.16); color: #3fb950; }
.kt-badge-bad { background: rgba(248,81,73,0.16); color: #f85149; }
.kt-badge-flat { background: rgba(154,154,154,0.16); color: #9a9a9a; }

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 16px !important;
}

/* overflow-x: auto, not hidden -- charts use a fixed pixel width (see
   charts.py for why: Streamlit's use_container_width sizing silently
   returns 0-width canvases at fractional devicePixelRatio). A fixed width
   can be wider than a narrow viewport; auto-scroll keeps the chart fully
   visible and scrollable there instead of silently clipping it. */
div[data-testid="stVegaLiteChart"] {
    border-radius: 12px;
    overflow-x: auto;
}

/* Every table in the app is now app/tables.py's paginated st.table (see
   DECISIONS.md) instead of the interactive stDataFrame widget, which has
   zero built-in styling of its own -- this is the difference between an
   enterprise data table and a bare unstyled browser <table>. */
div[data-testid="stTable"] {
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.08);
    overflow: hidden;
}
div[data-testid="stTable"] table {
    width: 100%;
}
div[data-testid="stTable"] thead th {
    background: var(--kt-accent-tint);
    color: var(--kt-accent);
    font-weight: 600;
    text-transform: none;
    border-bottom: 1px solid rgba(57,135,229,0.35) !important;
    padding: 10px 14px !important;
}
div[data-testid="stTable"] tbody td {
    padding: 8px 14px !important;
    border-bottom: 1px solid rgba(255,255,255,0.06) !important;
}
div[data-testid="stTable"] tbody tr:last-child td {
    border-bottom: none !important;
}
div[data-testid="stTable"] tbody tr:hover td {
    background: rgba(57,135,229,0.08);
}
/* pandas always renders the DataFrame index as a row-header column; after
   paginated_table()'s reset_index(drop=True) that's just a meaningless
   per-page 0/1/2.. counter, not real data. No Styler-based hide() available
   (this env's jinja2 is too old for pandas' Styler), so hidden via CSS. */
div[data-testid="stTable"] th.blank,
div[data-testid="stTable"] th.row_heading {
    display: none;
}
div[data-testid="stTable"] td {
    font-variant-numeric: tabular-nums;
}

section[data-testid="stSidebar"] {
    border-right: 1px solid rgba(57,135,229,0.15);
    background: rgba(255,255,255,0.015);
}
section[data-testid="stSidebar"] h2 {
    border-left: 3px solid var(--kt-accent);
    padding-left: 10px;
    font-size: 1.05rem;
}

/* Tab switch feedback -- motivated by Section 5's own rule (motion needs a
   reason: hierarchy / storytelling / feedback / state transition). This is
   feedback: confirms the click registered and new content is in, fast
   enough (200ms) to read as responsive rather than decorative. */
[role="tabpanel"] {
    animation: kt-fade-in 0.2s ease;
}
@keyframes kt-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
}
button[data-testid="stTab"] {
    transition: color 0.15s ease;
}
/* KNOWN, NOT FIXED: Streamlit's own tab component colors the active tab
   with a hardcoded #ff4b4b (Streamlit's stock brand red) via an
   emotion-generated class, not the theme's primaryColor -- confirmed live,
   present even before any custom CSS, breaking the color-consistency lock
   in a small way. Tried overriding with an !important attribute selector;
   live-testing showed the override interacting unpredictably with
   Streamlit's own focus/selection-state classes (the color shown after a
   tab switch didn't reliably match either the override or Streamlit's
   default, across repeated tests). Reverted rather than ship a change that
   couldn't be verified correct -- this environment's Browser pane isn't
   compositing frames this session, so no visual screenshot to confirm
   against. Cosmetic only (one tab's text color); not worth shipping
   unverified over. Revisit with real screenshot capability available. */
</style>
"""

# The sidebar's reopen control (only visible once the sidebar auto-collapses
# on narrow viewports -- the sole path to Region/Warehouse/Channel/Date on
# mobile) ships with an explicit empty aria-label and an aria-hidden icon, so
# a screen-reader user gets an unnamed button. It's Streamlit chrome, not app
# markup, so there's no Python-level prop for it; a components.html iframe
# reaching into the parent DOM is the only way to patch it. Re-applied via
# MutationObserver since Streamlit re-renders this control on every rerun.
_SIDEBAR_LABEL_FIX = """
<script>
function ktLabelSidebarToggle() {
    const btn = window.parent.document.querySelector(
        '[data-testid="stSidebarCollapsedControl"] button');
    if (btn) btn.setAttribute('aria-label', 'Open filters sidebar');
}
ktLabelSidebarToggle();
new MutationObserver(ktLabelSidebarToggle)
    .observe(window.parent.document.body, {childList: true, subtree: true});
</script>
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


@st.cache_data(show_spinner=False)
def build_ctx():
    # No st.* calls in here on purpose -- this is called from inside every
    # cached_* wrapper below, and Streamlit *replays* any UI element a
    # cached function produced, on every cache hit, everywhere it's called
    # from. Putting the status widget in here made it repeat once per
    # wrapper (~10 times) instead of once. All loading UI lives in main()
    # instead, gated to fire once per browser session.
    d = data.load_clean_tables()
    ol = metrics.enrich_order_lines(d)
    dv = metrics.enrich_deliveries(d)
    od = metrics.enrich_orders(d)
    rt = metrics.enrich_returns(d)
    freight = data.load_freight()
    price_matches = data.load_price_matches()
    return {"data": d, "freight": freight, "price_matches": price_matches, "ol": ol, "dv": dv, "od": od, "rt": rt}


def load_data_with_status():
    """Shows real staged progress on the true first load of a session; every
    later call (including the ~10 cached_* wrappers calling build_ctx()
    internally) is an instant cache hit with no UI, since build_ctx() itself
    carries none. Per the LLM council's verdict on skeleton loading: a true
    skeleton doesn't fit Streamlit's rerun model and this is a once-per-
    session wait anyway, so the honest fix is real progress through real
    stages (a native widget), not simulated shimmer CSS.

    st.tabs renders every panel in one script pass and switching tabs is a
    client-side show/hide with no rerun, so this placeholder is the only
    thing standing between "collapsed status widget" and "status widget
    wedged under the tab bar forever" -- .empty() drops it from the DOM
    once loading is done instead of leaving a permanent completed banner."""
    if "kt_data_loaded" in st.session_state:
        return build_ctx()
    placeholder = st.empty()
    with placeholder.container():
        with st.status("Loading Kestrel data (first run only)...", expanded=True) as status:
            status.write("Reading cleaned operational tables, joining facts, loading freight and price data...")
            ctx = build_ctx()
            status.update(label="Kestrel data loaded", state="complete", expanded=False)
    placeholder.empty()
    st.session_state["kt_data_loaded"] = True
    return ctx


# Raw trade-channel codes from the source system, kept as the underlying
# filter value (matches column values, cache keys, and CSV exports) but
# shown with a plain-English label -- a first-time-user audit found "GT",
# "MT", "HORECA", "ECOM_DARKSTORE" meant nothing without FMCG domain context.
CHANNEL_LABELS = {
    "All": "All",
    "GT": "GT (General Trade)",
    "MT": "MT (Modern Trade)",
    "HORECA": "HORECA (Hotel/Restaurant/Cafe)",
    "ECOM_DARKSTORE": "E-commerce dark store",
}

GRAIN_LABELS = {
    "region_name": "Region",
    "warehouse_code": "Warehouse",
    "route_code": "Route",
    "outlet_name": "Outlet",
}


def sidebar_filters(ctx):
    st.sidebar.header("Filters")
    regions = ["All"] + sorted(ctx["data"]["regions"]["region_name"].dropna().unique().tolist())
    region = st.sidebar.selectbox("Region", regions)

    wh_options = ctx["data"]["warehouses"]
    if region != "All":
        region_id = ctx["data"]["regions"].loc[ctx["data"]["regions"]["region_name"] == region, "region_id"].iloc[0]
        wh_options = wh_options[wh_options["region_id"] == region_id]
    warehouse = st.sidebar.selectbox("Warehouse", ["All"] + sorted(wh_options["warehouse_code"].tolist()))

    channel = st.sidebar.selectbox("Channel", ["All", "GT", "MT", "HORECA", "ECOM_DARKSTORE"],
                                    format_func=lambda c: CHANNEL_LABELS[c])

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
    return metrics.returns_pct_of_dispatch_bps(rt, od)


@st.cache_data(show_spinner=False)
def cached_freight_cost(region, warehouse, channel, date_range):
    ctx = build_ctx()
    if ctx["freight"].empty:
        return pd.DataFrame()
    ol = _filtered(ctx, "ol", region, warehouse, channel, date_range)
    # The date_range sidebar filter narrowed `ol` (the cases/denominator) but
    # was never passed to the freight side (the amount/numerator) -- found
    # live while auditing this metric. Region/Warehouse happened to work by
    # accident (freight has no channel dimension, but warehouse_code does,
    # and the inner join in freight_cost_per_case naturally drops any
    # warehouse absent from the filtered cases side); the date window did
    # not, silently dividing a date-filtered numerator by an unfiltered
    # denominator. Channel still can't be applied -- freight invoices carry
    # no channel field at all (see freight_cost_per_case's own docstring on
    # why this is a warehouse-month aggregate, not an order-level join).
    period_start = period_end = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        period_start, period_end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    return metrics.freight_cost_per_case(ctx["freight"], ol, ctx["data"]["warehouses"],
                                          period_start=period_start, period_end=period_end)


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
    st_rt = metrics.settled_returns(rt)
    return st_rt.loc[st_rt["return_reason_code"] == "RT06_COLD_CHAIN_BREACH", "credit_note_value_inr"].sum()


@st.cache_data(show_spinner=False)
def cached_near_expiry(region, warehouse):
    # Inventory is a point-in-time snapshot with no order date or channel on
    # it, so date_range/channel don't apply -- only region and warehouse do,
    # via a join to the warehouses/regions dims. Found and fixed after a UX
    # audit caught this table silently showing global inventory while every
    # other Cold Chain element on the page was correctly scoped to the
    # sidebar's region/warehouse filter.
    ctx = build_ctx()
    inv = ctx["data"]["inventory"]
    wh = ctx["data"]["warehouses"].merge(ctx["data"]["regions"][["region_id", "region_name"]], on="region_id")
    near_expiry = inv[inv["ageing_bucket"].isin(["61-90", "90+"])]
    near_expiry = near_expiry.merge(wh[["warehouse_id", "warehouse_code", "region_name"]], on="warehouse_id")
    if region != "All":
        near_expiry = near_expiry[near_expiry["region_name"] == region]
    if warehouse != "All":
        near_expiry = near_expiry[near_expiry["warehouse_code"] == warehouse]
    by_wh = near_expiry.groupby("warehouse_code")["on_hand_cases"].sum().reset_index()
    return by_wh


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
    """Icon + label, never colour alone (dataviz skill's status-colour rule).
    Renders as a tinted pill (see .kt-badge* in _CUSTOM_CSS) instead of
    Streamlit's plain-text :green[]/:red[] markdown shortcode."""
    if delta_value is None:
        return ""
    good = (delta_value > 0) if higher_is_better else (delta_value < 0)
    if abs(delta_value) < 0.3:
        return '<span class="kt-badge kt-badge-flat">– Flat</span>'
    if good:
        return '<span class="kt-badge kt-badge-good">▲ Improving</span>'
    return '<span class="kt-badge kt-badge-bad">▼ Worsening</span>'


def overview_tab(region, warehouse, channel, date_range):
    q_start, q_end = metrics.last_complete_fy_quarter(build_ctx()["ol"]["order_date"].max())
    prior_start, prior_end = metrics.last_complete_fy_quarter(q_start - pd.Timedelta(days=1))
    quarter_num = ((q_start.month - 4) % 12) // 3 + 1
    st.subheader(f"Q{quarter_num} FY: {q_start:%b %Y} to {q_end:%b %Y} (the board asks about Q1 first)")

    # These KPIs are pinned to the last complete quarter by design (Rakesh's
    # brief: "Q1 is on the front page, the board asks about Q1 first, every
    # time") -- the sidebar date range narrows WITHIN that quarter, it
    # doesn't replace it. A range entirely outside the quarter (e.g. Feb
    # 2026 when the quarter is Apr-Jun 2026) correctly intersects to nothing
    # and every tile below reads "n/a" -- found via a UX audit that this
    # degrades gracefully but with zero on-screen explanation, reading as
    # "the dashboard is broken" rather than as the intentional, quarter-
    # pinned behavior it is. Other tabs aren't pinned to a quarter and
    # reflect the date range directly, so this note is Overview-only.
    if isinstance(date_range, tuple) and len(date_range) == 2:
        sel_start, sel_end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        if sel_end < q_start or sel_start > q_end:
            st.info(
                f"The sidebar date range ({sel_start:%d %b %Y} to {sel_end:%d %b %Y}) falls "
                f"outside this quarter, so the KPIs below have nothing to show. This section "
                f"is pinned to the last complete quarter; the date filter narrows within it "
                f"rather than replacing it. Other tabs aren't quarter-pinned and reflect the "
                f"date range directly."
            )

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

    # All 4 tiles now carry a help tooltip -- a first-time-user audit found
    # only OTIF had one, so the other three read as unexplained numbers with
    # no way to tell if e.g. a 21.5 excursion rate is good or catastrophic.
    kpis = [
        ("Case fill rate (eaches)", fr_val, fr_prior, True, "%",
         "Delivered eaches / ordered eaches, for orders that reached fulfillment "
         "(delivered or partially delivered). Cancelled and still-open orders are "
         "excluded from both sides of the ratio."),
        ("OTIF", otif_val, otif_prior, True, "%",
         "Strict definition: any delay at all counts as late (no grace window), and "
         "'in full' compares delivered to allocated stock, not to what was originally "
         "ordered -- so this reads much lower than fill rate on the same orders. "
         "That's expected under this definition, not a data error -- see DECISIONS.md."),
        ("Cold-chain excursions / 100 chilled", exc_val, exc_prior, False, "",
         "Chilled deliveries with a recorded max temperature above 8 degrees C, per "
         "100 chilled deliveries that month. Lower is better."),
        ("Returns vs dispatch value", ret_val, ret_prior, False, " bps",
         "Settled credit-note value as a share of dispatched order value in the same "
         "period, in basis points (100 bps = 1%). Shown in bps because the true figure "
         "is ~3.4 bps -- as a one-decimal percentage it renders as '0.0%', which reads "
         "as a broken metric rather than a small one. REJECTED credit notes are excluded: "
         "a refused claim was defended, not leaked -- see DECISIONS.md."),
    ]
    cols = st.columns(4)
    for col, (label, val, prior, higher_better, unit, help_text) in zip(cols, kpis):
        d, dc = _delta(val, prior, higher_better)
        col.metric(label, f"{val}{unit}" if val is not None else "n/a", delta=d, delta_color=dc, help=help_text)
        delta_raw = None if (val is None or prior is None) else round(val - prior, 1)
        col.markdown(_status_badge(delta_raw, higher_better), unsafe_allow_html=True)
    st.caption(f"vs prior quarter ({prior_start:%b %Y} to {prior_end:%b %Y}). "
               "Status reflects direction of travel, not an absolute target.")

    # This dataset's fulfillment rates happen to be near-uniform across
    # regions/warehouses, so narrowing the sidebar filters barely moves the
    # rounded KPI percentages -- which reads exactly like "the filter didn't
    # apply." It did; the underlying order-line count below is the proof,
    # since that always changes with the filter even when the ratio doesn't.
    active_filters = [f"{k}: {v}" for k, v in
                       [("Region", region), ("Warehouse", warehouse), ("Channel", channel)] if v != "All"]
    if active_filters:
        st.caption(f"Filtered to {', '.join(active_filters)} -- "
                   f"{int(fr['ordered_eaches'].sum()):,} eaches ordered this quarter under this filter.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Worst 5 outlets by fill rate, Q1**")
        tables.paginated_table(fr_by_outlet[fr_by_outlet["ordered_eaches"] > 0].head(5),
                                formats={"fill_rate_pct": (None, "%.1f%%")}, key="overview_worst_outlets")
    with right:
        st.markdown("**Fill rate by region, Q1**")
        st.altair_chart(charts.bar(fr, "region_name", "fill_rate_pct", "Region", "Fill rate %", height=260, width=500))
    with st.expander("View region chart as table"):
        tables.paginated_table(fr, formats={"fill_rate_pct": (None, "%.1f%%")}, key="overview_region_table")
    _spread_note(fr, "fill_rate_pct", "region")


def _spread_note(df, col, grain_label):
    """States plainly when a 'worst performers' ranking has no material spread.

    Fill rate in this dataset sits at ~85.6% across every region, warehouse and
    channel -- total spread under 0.2pp. Sorting that ascending and calling the
    top row a worst performer presents rounding noise as a finding, which is
    the opposite of what a control tower is for. Computed live rather than
    hardcoded, so it disappears on its own if real dispersion ever appears.
    """
    if df.empty or col not in df.columns or df[col].notna().sum() < 2:
        return
    spread = float(df[col].max() - df[col].min())
    if spread < 1.0:
        st.caption(
            f"Note: spread across {grain_label} is only {spread:.2f} percentage points "
            f"({df[col].min():.1f}%-{df[col].max():.1f}%). This ranking is ordering noise, not "
            f"performance -- no {grain_label} is materially worse than another. The finding is "
            f"the uniform level itself, not the order."
        )


def service_tab(region, warehouse, channel, date_range):
    st.subheader("Service: fill rate & OTIF (eaches)")
    grain = st.radio("Break down by", ["region_name", "warehouse_code", "route_code", "outlet_name"],
                      horizontal=True, key="service_grain", format_func=lambda g: GRAIN_LABELS[g])

    # Switching grain is a cache miss (new key) -- without an explicit spinner
    # here, Streamlit keeps the PREVIOUS grain's tables on screen until the
    # new ones are ready, which reads as "the switch didn't work" or "this is
    # showing stale data" rather than "this is loading." Computing both
    # tables inside one spinner block means they replace each other atomically.
    with st.spinner(f"Computing by {grain.replace('_', ' ')}..."):
        fr = cached_fill_rate(region, warehouse, channel, date_range, grain)
        fr = fr[fr["ordered_eaches"] > 0]
        ot = cached_otif(region, warehouse, channel, date_range, grain)

    st.markdown("Worst performers first (case fill rate, eaches)")
    tables.paginated_table(fr, formats={"fill_rate_pct": (None, "%.1f%%")}, key=f"service_fill_rate_{grain}")
    _spread_note(fr, "fill_rate_pct", GRAIN_LABELS[grain].lower())

    st.markdown("OTIF, worst performers first")
    tables.paginated_table(ot, formats={"otif_pct": (None, "%.1f%%")}, key=f"service_otif_{grain}")


def cold_chain_tab(region, warehouse, channel, date_range):
    st.subheader("Cold chain")
    exc = cached_excursions(region, warehouse, channel, date_range)
    st.markdown("Temperature excursions per hundred chilled deliveries, by month")
    st.altair_chart(charts.line(exc, "month", "excursions_per_100", "Month", "Excursions / 100", width=900))
    with st.expander("View as table"):
        tables.paginated_table(exc, formats={"excursions_per_100": (None, "%.1f")}, key="coldchain_excursions")

    st.markdown("Near-expiry inventory (ageing bucket 61-90 or 90+ days)")
    tables.paginated_table(cached_near_expiry(region, warehouse), key="coldchain_near_expiry")

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
        tables.paginated_table(
            fc[["warehouse_code", "month", "freight_amount_cr", "delivered_cases_equiv", "freight_cost_per_case_inr"]],
            formats={
                "warehouse_code": ("Warehouse", None),
                "month": ("Month", None),
                "freight_amount_cr": ("Freight amount (₹ Cr)", "%.2f"),
                "delivered_cases_equiv": ("Delivered cases", "%.0f"),
                "freight_cost_per_case_inr": ("Cost / case (₹)", "%.2f"),
            },
            key="money_freight_cost",
        )
        st.caption("Excludes DISPUTED invoices (contested, unsettled) -- see DECISIONS.md.")

        st.markdown("Freight spend by carrier")
        by_carrier = cached_carrier_spend(region, warehouse, channel, date_range).copy()
        by_carrier["spend_cr"] = charts.to_crore(by_carrier["amount_inr"])
        st.altair_chart(charts.bar(by_carrier, "carrier_name", "spend_cr", "Carrier", "Spend (₹ Cr)", width=900))
        with st.expander("View as table"):
            tables.paginated_table(by_carrier[["carrier_name", "spend_cr"]],
                                    formats={"spend_cr": ("Spend (₹ Cr)", "%.2f")}, key="money_carrier_spend")

    st.markdown("Returns leakage by category (value and leading reason)")
    leak = cached_returns_leakage(region, warehouse, channel, date_range).copy()
    leak["credit_note_lakh"] = charts.to_lakh(leak["credit_note_value_inr"])
    tables.paginated_table(
        leak[["category", "credit_note_lakh", "return_lines", "leading_reason_code"]],
        formats={
            "credit_note_lakh": ("Credit notes (₹ L)", "%.2f"),
            "return_lines": ("Return lines", None),
            "leading_reason_code": ("Leading reason", None),
        },
        key="money_returns_leakage",
    )
    st.caption("Excludes REJECTED credit notes (26% of raw credit-note value) -- a refused "
               "claim was defended, not leaked. Same treatment as DISPUTED freight above.")


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
            with st.expander("View as table"):
                tables.paginated_table(by_cat, formats={"gap_pct": ("Avg gap %", "%.1f%%")},
                                        key="price_category_gap")

    st.markdown("All matched SKUs (₹ = INR). Positive gap = priced above the lowest competitor; negative = below.")
    tables.paginated_table(
        pp[["matched_sku_code", "city", "category", "kestrel_mrp_inr", "lowest_competitor_price_inr",
            "gap_inr", "gap_pct"]],
        formats={
            "matched_sku_code": ("SKU", None),
            "kestrel_mrp_inr": ("Kestrel MRP (₹)", "%.2f"),
            "lowest_competitor_price_inr": ("Lowest competitor price (₹)", "%.2f"),
            "gap_inr": ("Gap (₹)", "%.2f"),
            "gap_pct": ("Gap %", "%.1f%%"),
        },
        page_size=20,
        key=f"price_matched_skus_{city}",
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
        st.caption("No LLM key needed. Try one of these, or type your own:")
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
            submitted = st.form_submit_button("Ask", use_container_width=True, type="primary")
        if submitted:
            st.session_state["ask_question"] = q_input.strip()
            if not st.session_state["ask_question"]:
                st.warning("Type a question first, or click one of the suggestions above.")

    with st.expander("Full list of what I can answer"):
        st.text(nl.CAPABILITIES)

    q = st.session_state["ask_question"]
    if q:
        text, df = cached_nl_answer(q)
        # Bolding a multi-line answer (the "I don't understand this" fallback,
        # which is the fixed multi-paragraph CAPABILITIES list) breaks
        # CommonMark's inline-emphasis parsing across paragraph/list
        # boundaries -- the leading/trailing ** render as literal asterisks
        # instead of applying bold. Only single-line answers get bolded.
        st.markdown(f"**{text}**" if "\n" not in text else text)
        if df is not None:
            tables.paginated_table(df, key=f"ask_answer_{hash(q)}")


def main():
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    _embed_html(_SIDEBAR_LABEL_FIX, height=0)
    st.title("Kestrel Provisions: Supply Chain Control Tower")
    # Tab bar built before the data load -- it's static chrome with no data
    # dependency, so it can render immediately instead of waiting behind
    # build_ctx(). Streamlit streams each st.xxx() call to the browser as it
    # runs, so this genuinely shows up first, not just in source order.
    tabs = st.tabs(["Overview", "Service", "Cold Chain", "Money", "Price Position", "Ask Anything"])

    status = data.data_status()
    degrade_banner(status)

    ctx = load_data_with_status()
    region, warehouse, channel, date_range = sidebar_filters(ctx)

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
