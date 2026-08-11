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


# ---- templates ----

def t_lowest_fill_rate(q, ctx):
    if "fill rate" not in q.lower() or "lowest" not in q.lower() and "worst" not in q.lower():
        return None
    n = 5
    m = re.search(r"\b(\d+)\b", q)
    if m:
        n = int(m.group(1))
    g = metrics.fill_rate_eaches(ctx["ol"], ["outlet_name"])
    g = g[g["ordered_eaches"] > 0].head(n)
    text = f"{n} lowest case fill rate outlets (measured in eaches, reportable outlets only):"
    return text, g


def t_otif_by_region(q, ctx):
    ql = q.lower()
    if "otif" not in ql:
        return None
    g = metrics.otif(ctx["dv"], ctx["ol"], ["region_name"])
    text = "OTIF by region, last complete quarter (Apr-Jun 2026):"
    return text, g


def t_returns_category(q, ctx):
    ql = q.lower()
    if "return" not in ql or "categor" not in ql and "reason" not in ql:
        return None
    g = metrics.returns_leakage_by_category(ctx["data"]["returns"], ctx["ol"], ctx["data"]["products"])
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
    text = "Routes more than two hours late on more than 1-in-10 deliveries:"
    return text, g


def t_price_gap(q, ctx):
    ql = q.lower()
    if "mrp" not in ql and "competitor" not in ql and "price" not in ql:
        return None
    city_word = _find_one(CITIES, ql)
    city = city_word.title() if city_word else None
    if city == "Bengaluru":
        city = "Bengaluru"
    g = metrics.price_position(ctx["price_matches"], ctx["data"]["products"], city=city)
    label = city or "all scraped cities"
    text = f"MRP vs lowest observed competitor price ({label}), most competitively exposed first:"
    return text, g.head(20)


def t_freight_cost(q, ctx):
    ql = q.lower()
    if "freight" not in ql or "case" not in ql:
        return None
    g = metrics.freight_cost_per_case(ctx["freight"], ctx["ol"], ctx["data"]["warehouses"])
    text = "Freight cost per delivered case, by warehouse and month:"
    return text, g


def t_discontinued(q, ctx):
    ql = q.lower()
    if "discontinu" not in ql:
        return None
    g = metrics.discontinued_orders(ctx["ol"])[
        ["order_id", "outlet_name", "sku_code", "order_date", "discontinued_date"]
    ]
    text = f"{len(g)} order lines ordered a SKU after its discontinuation date:"
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
- "which outlets had the lowest fill rate" / "worst N outlets by fill rate"
- "what was OTIF by region"
- "which categories drive the most returns" / "leading reason code"
- "temperature excursions per month"
- "which routes are late more than 1 in 10 deliveries"
- "freight cost per case by warehouse"
- "which outlets ordered a discontinued SKU"
- "MRP vs competitor price in <city>"
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
