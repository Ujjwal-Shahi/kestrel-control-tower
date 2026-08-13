"""
Deterministic NL-to-query mapper. This is the core "ask anything" layer and
works with zero setup, zero keys, zero network calls -- see DECISIONS.md for
why this is the primary layer and the LLM path is an optional upgrade, not
the other way round.

Each template: (matcher(question) -> bool, handler(question, ctx) -> (text, df|None))
First matching template wins. ctx carries the enriched dataframes the caller
already built, so handlers don't touch raw tables.
"""
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import metrics

REGIONS = ["west", "south", "north", "east", "central"]
CITIES = ["mumbai", "delhi", "bengaluru", "chennai"]


def _find_one(words, text):
    text = text.lower()
    for w in words:
        if w in text:
            return w
    return None


def _region_filter(df, region_word, col="region_name"):
    if not region_word:
        return df
    return df[df[col].str.lower() == region_word]


MISSING_PRICE_DATA = (
    "Competitor price data hasn't been loaded yet, so I can't answer price questions. "
    "Serve the site (`cd bazaarpulse_site && python -m http.server 8080`) then run "
    "`python -m scraper.scrape_and_match`, and ask again. See the README."
)
MISSING_FREIGHT_DATA = (
    "Freight invoice data hasn't been loaded yet, so I can't answer freight-cost questions. "
    "Start the API (`python partner_api/server.py`) then run `python -m freight.ingest`, "
    "and ask again. See the README."
)


def _has_price(ctx):
    pm = ctx.get("price_matches")
    return pm is not None and not pm.empty and "matched_sku_code" in pm.columns


def _has_freight(ctx):
    f = ctx.get("freight")
    return f is not None and not f.empty and "status" in f.columns


def _window(q, ctx):
    """Resolves a date scope the question actually asked for.

    The brief's own questions say "last month" (Q1) and "for the last quarter"
    (Q7). Answering those over all 18 months and labelling it as if scoped
    would be quietly wrong, so the scope is parsed and stated back in the
    answer text. Anchored on the data's max date, not today's, since the db is
    a fixed 18-month extract.
    """
    ql = q.lower()
    max_date = ctx["ol"]["order_date"].max()
    if "last month" in ql or "past month" in ql:
        end = (max_date.replace(day=1) - pd.Timedelta(days=1))
        start = end.replace(day=1)
        return start.normalize(), end.normalize(), f"{start:%b %Y}"
    if "quarter" in ql:
        start, end = metrics.last_complete_fy_quarter(max_date)
        return start, end, f"{start:%b %Y} to {end:%b %Y}"
    return None, None, None


def _scope(df, start, end, col="order_date"):
    if start is None or df is None or df.empty:
        return df
    return df[(df[col] >= start) & (df[col] <= end)]


# ---- templates ----

def t_lowest_fill_rate(q, ctx):
    if "fill rate" not in q.lower() or "lowest" not in q.lower() and "worst" not in q.lower():
        return None
    n = 5
    m = re.search(r"\b(\d+)\b", q)
    if m:
        n = int(m.group(1))
    start, end, label = _window(q, ctx)
    g = metrics.fill_rate_eaches(_scope(ctx["ol"], start, end), ["outlet_name"])
    g = g[g["ordered_eaches"] > 0]
    # Asking for more outlets than exist (e.g. "9999 lowest fill rate
    # outlets") used to echo the requested n verbatim in the header even
    # though head(n) could only ever return len(g) rows -- found via a
    # correctness audit ("9999 lowest ... outlets" over a 70-row table).
    # Report what's actually shown, not what was asked for.
    shown = min(n, len(g))
    g = g.head(n)
    scope_txt = f" in {label}" if label else " across all 18 months of data"
    text = (f"{shown} lowest case fill rate outlets{scope_txt} (measured in eaches; closed, "
            f"deleted and test outlets excluded):")
    return text, g


def t_otif_by_region(q, ctx):
    ql = q.lower()
    if "otif" not in ql and "on time in full" not in ql:
        return None
    # Answer text claims "last complete quarter" -- actually filter to it,
    # rather than computing over the full history and mislabeling the result.
    q_start, q_end = metrics.last_complete_fy_quarter(ctx["ol"]["order_date"].max())
    dv_q = ctx["dv"][(ctx["dv"]["order_date"] >= q_start) & (ctx["dv"]["order_date"] <= q_end)]
    ol_q = ctx["ol"][(ctx["ol"]["order_date"] >= q_start) & (ctx["ol"]["order_date"] <= q_end)]
    g = metrics.otif(dv_q, ol_q, ["region_name"])
    text = f"OTIF by region, last complete quarter ({q_start:%b %Y} to {q_end:%b %Y}):"
    return text, g


def t_returns_category(q, ctx):
    ql = q.lower()
    if "return" not in ql or "categor" not in ql and "reason" not in ql:
        return None
    g = metrics.returns_leakage_by_category(ctx["data"]["returns"], ctx["data"]["products"])
    text = "Return value by category, with leading reason code:"
    return text, g


def t_excursions(q, ctx):
    ql = q.lower()
    if "excursion" not in ql and "temperature" not in ql:
        return None
    g = metrics.cold_chain_excursions_by_month(ctx["dv"])
    text = "Temperature excursions per hundred chilled deliveries, by month:"
    return text, g


def t_late_routes(q, ctx):
    ql = q.lower()
    if "late" not in ql or "route" not in ql:
        return None
    g = metrics.late_routes(ctx["dv"])
    total_routes = ctx["dv"]["route_code"].nunique()
    text = "Routes more than two hours late on more than 1-in-10 deliveries:"
    if total_routes and len(g) >= total_routes:
        # Every route in the network clears this bar, so the list is not a
        # shortlist -- saying so is the actual answer. Reporting 140 rows as
        # "the problem routes" would imply the other routes are fine.
        text = (f"All {len(g)} of {total_routes} routes breach this bar -- lateness is "
                f"network-wide, not route-specific, so this is not a shortlist to action. "
                f"Worst rates first:")
    return text, g


def t_price_gap(q, ctx):
    ql = q.lower()
    if "mrp" not in ql and "competitor" not in ql and "price" not in ql:
        return None
    # city_word ("delhi") deliberately not .title()-cased into a display name here --
    # the scraped data's actual city string is "Delhi NCR" (from the site's own link
    # text), not "Delhi". price_position() matches by substring, case-insensitive,
    # so the raw keyword is the right thing to pass through.
    if not _has_price(ctx):
        return MISSING_PRICE_DATA, None
    city_word = _find_one(CITIES, ql)
    g = metrics.price_position(ctx["price_matches"], ctx["data"]["products"], city=city_word)
    label = city_word.title() if city_word else "all scraped cities"

    # "our top twenty SKUs by value" (brief Q6) is a SALES-VALUE ranking, not
    # the most price-exposed SKUs. Answering the latter and calling it the
    # former would be a different question with a plausible-looking answer, so
    # the value ranking is applied when the question asks for it, and coverage
    # is reported because not every top-value SKU is sold by a scraped retailer.
    m = re.search(r"top\s+(\d+|twenty|ten|five)", ql)
    if m and ("value" in ql or "sku" in ql):
        words = {"twenty": 20, "ten": 10, "five": 5}
        n = words.get(m.group(1), None) or int(m.group(1))
        top = metrics.top_skus_by_value(ctx["ol"], n)
        g = g[g["matched_sku_code"].isin(top["sku_code"])]
        g = g.merge(top, left_on="matched_sku_code", right_on="sku_code",
                    how="left").drop(columns="sku_code")
        g = g.sort_values("shipped_value_inr", ascending=False)
        # g has one row per (SKU, city) match, not one row per SKU -- a SKU
        # observed in 4 cities contributes 4 rows. len(g) as a "how many of
        # the top N SKUs matched" count over-reports (can exceed N entirely,
        # as it did here: 37 rows from as few as 6 distinct SKUs). Count
        # unique SKUs instead.
        matched_skus = g["matched_sku_code"].nunique()
        text = (f"Top {n} SKUs by shipped value vs the lowest observed competitor price "
                f"({label}). {matched_skus} of the top {n} are stocked by a scraped retailer "
                f"there; the rest have no competitor observation to compare against:")
        return text, g

    text = f"MRP vs lowest observed competitor price ({label}), most competitively exposed first:"
    return text, g.head(20)


def t_freight_cost(q, ctx):
    ql = q.lower()
    if "case" not in ql or ("freight" not in ql and "cost per delivered" not in ql and "cost per case" not in ql):
        return None
    if not _has_freight(ctx):
        return MISSING_FREIGHT_DATA, None
    start, end, label = _window(q, ctx)
    g = metrics.freight_cost_per_case(ctx["freight"], ctx["ol"], ctx["data"]["warehouses"],
                                      period_start=start, period_end=end)
    scope_txt = f", {label}" if label else ""
    text = f"Freight cost per delivered case, by warehouse and month{scope_txt}:"
    return text, g


def t_discontinued(q, ctx):
    ql = q.lower()
    if "discontinu" not in ql:
        return None
    g = metrics.discontinued_orders(ctx["ol"])[
        ["order_id", "outlet_name", "sku_code", "order_date", "discontinued_date"]
    ]
    # The stated total and the table's page-count footer are both true but
    # were unreconciled -- a reader saw "14370 order lines" next to a table
    # footer saying "50 rows total" with nothing explaining the gap.
    shown_note = " (showing the first 50; download the CSV for all)" if len(g) > 50 else ""
    text = f"{len(g)} order lines ordered a SKU after its discontinuation date{shown_note}:"
    return text, g.head(50)


def t_why_fill_rate_drop(q, ctx):
    ql = q.lower()
    if "why" not in ql or "fill rate" not in ql:
        return None
    ol = ctx["ol"]
    region_word = _find_one(REGIONS, ql)
    max_date = ol["order_date"].max()
    last7_start = max_date - pd.Timedelta(days=6)
    prev7_start = max_date - pd.Timedelta(days=13)
    prev7_end = max_date - pd.Timedelta(days=7)

    scope = ol if not region_word else ol[ol["region_name"].str.lower() == region_word]

    def window_rate(df, start, end, group):
        w = df[(df["order_date"] >= start) & (df["order_date"] <= end)]
        return metrics.fill_rate_eaches(w, [group])

    group_col = "warehouse_code" if region_word else "region_name"
    last7 = window_rate(scope, last7_start, max_date, group_col).set_index(group_col)["fill_rate_pct"]
    prev7 = window_rate(scope, prev7_start, prev7_end, group_col).set_index(group_col)["fill_rate_pct"]
    comp = pd.DataFrame({"prior_week_pct": prev7, "last_week_pct": last7}).reset_index()
    comp["delta_pct_pts"] = (comp["last_week_pct"] - comp["prior_week_pct"]).round(1)
    comp = comp.sort_values("delta_pct_pts")

    scope_label = f"the {region_word.title()} region" if region_word else "all regions"
    text = (f"Fill-rate change, last 7 days vs prior 7 days (data through {max_date.date()}), "
            f"{scope_label}, broken down by {group_col.replace('_', ' ')}:")
    return text, comp


TEMPLATES = [
    t_why_fill_rate_drop,  # before the generic fill-rate template, "why...drop" is more specific
    t_lowest_fill_rate,
    t_otif_by_region,
    t_returns_category,
    t_excursions,
    t_late_routes,
    t_freight_cost,
    t_discontinued,
    t_price_gap,
]

CAPABILITIES = """I answer from a fixed set of question shapes (no LLM key needed):
- "which outlets had the lowest fill rate" / "worst N outlets by fill rate" (add "last month" to scope it)
- "what was OTIF by region"
- "which categories drive the most returns" / "leading reason code"
- "temperature excursions per month"
- "which routes are late more than 1 in 10 deliveries"
- "freight cost per case by warehouse" (add "last quarter" to scope it)
- "which outlets ordered a discontinued SKU"
- "MRP vs competitor price in <city>" / "top 20 SKUs by value vs competitors in <city>"
- "why did fill rate drop in <region> last week"

Set ANTHROPIC_API_KEY to unlock free-form questions beyond this list."""


def llm_fallback(question):
    import config
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        return "ANTHROPIC_API_KEY is set but the `anthropic` package isn't installed (`pip install anthropic`)."
    return ("LLM upgrade path is wired for this key but not implemented in this build -- "
            "see DECISIONS.md for scope. Falling back to the fixed question list below.")


def answer(question, ctx):
    for template in TEMPLATES:
        result = template(question, ctx)
        if result:
            return result
    llm_note = llm_fallback(question)
    text = CAPABILITIES if not llm_note else f"{llm_note}\n\n{CAPABILITIES}"
    return text, None
