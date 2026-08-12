# Decisions

## Built

Streamlit control tower over the three shipped sources: ETL cleans the
operational SQLite db, a BazaarPulse scraper/matcher, a freight API
ingestion client, and six views (Overview with Q1 headline metrics,
Service, Cold Chain, Money, Price Position, Ask Anything). Ask Anything is
a deterministic NL-to-query mapper covering the brief's illustrative
questions plus "why did fill rate drop in region X last week" — no LLM key
needed anywhere. `python run.py` from a clean checkout is the one command.

## Not built, on purpose

- **Outlet entity resolution.** 161 groups (364 outlets) share a
  (name, city) key — consistent with the ownership-transfer duplication
  KP-2211 flags — but `legal_name`/GST aren't reliable disambiguators.
  Flagged (`possible_duplicate`), not merged: wrong merges are worse than
  visible duplicates.
- **General text-to-SQL / LLM-agentic layer.** `ANTHROPIC_API_KEY` is a
  wired extension point, not implemented — a non-deterministic layer that's
  also the *only* path to an answer was the wrong trade for something
  graded on a cold, unassisted checkout.
- **Row-level freight-to-delivery join.** The mock API exposes no
  `order_id`, only `warehouse_code`/`route_code`/date. Freight cost per
  case is a warehouse-month aggregate of two independently summed series.
- Auth, live refresh, Postgres migration, product-detail-page scraping
  (adds only price history, unused by the price-gap ask).

## Assumptions where the brief was unclear or self-contradicted

- **Fill rate in eaches**, per Rakesh's override of Divya's "cases" — more
  specific, more recent.
- **"Last complete quarter" is derived from the data's own max date**
  (`last_complete_fy_quarter()`), not hardcoded — currently resolves to
  Apr-Jun 2026, which happens to be Q1, since the data ends 2026-06-30.
- **Freight cost excludes DISPUTED invoices** (~20% of invoice value).
  A contested charge isn't a settled cost; including it at face value
  overstated cost/case by 58-97% per warehouse-month. PENDING is kept —
  unpaid but undisputed is still a real, owed liability.
- **OTIF "in full" = delivered vs allocated, not vs ordered.**
  `delivered_qty` never once reaches `ordered_qty` for any of 83,671
  orders (max ratio 99.4%, median ~86%) — an ordered-basis definition
  reads ~0% everywhere and double-counts the same gap fill-rate already
  reports. Even on allocated basis OTIF reads low (~2%); ranking across
  warehouses/routes is usable now, the absolute number needs validating
  with Ops.
- **Cold-chain excursion derived from `max_temp_celsius > 8°C`**, not the
  raw flag — the flag doesn't correlate with the reading (21% breach rate
  flagged or not).
- Test outlets excluded by `outlet_code` prefix `TST`; only two real city
  spelling variants found (Bangalore/Bengaluru, New Delhi/Delhi).
- **KP-2301 value mismatch not reproducible** — reconciles to zero across
  all orders; treated as a stale doc entry, not built around.
- **Price matching uses literal `(pack_value, pack_uom)` equality**, not
  unit correction — Kestrel's own catalog has the same "400kg snack"
  anomalies and BazaarPulse reproduces them faithfully, so literal
  matching is more correct than "fixing" units would be. Fuzzy scoring
  uses `WRatio`, not `token_sort_ratio` — the latter once ranked a
  wrong-brand, same-pack product above the true match ("AmritValley" vs
  catalog "Amrit Valley" spacing); `WRatio` resolves it correctly. 100%
  matched (75 exact-pack / 90 fuzzy-fallback thresholds), zero category
  mismatches on spot-check.
- **The NL layer answers one capability per question**, by design — a
  two-part question ("why did OTIF and fill rate both drop") silently
  answers only the first match. Fixing this needs an LLM or a
  multi-intent router, which reintroduces the complexity the
  deterministic layer exists to avoid. Accepted, not fixed.
- `/internal/margin-sheet.html` found, deliberately not scraped —
  `robots.txt` disallows it and it's irrelevant to the task.
- **Visual design** (dark theme, single accent hue, chart conventions)
  follows the `dataviz` skill's palette and mark specs — see README's
  "Design system" section rather than repeating it here. A later pass
  through `design-taste-frontend` (a React/Tailwind landing-page taste
  skill, whose own docs say it's not built for dashboards) still
  surfaced a real correction applicable to any stack: the blue-to-violet
  title gradient and blurred outer-glow hover effect were exactly the
  "AI purple/blue glow" cliche its anti-pattern rules name, and the
  emoji in every tab/KPI label were decorative rather than functional.
  Removed the second accent color and outer glow (inner border/tint
  only now), removed the emoji. Used the skill's taste judgment, not
  its React/GSAP mechanics, which don't apply to a Streamlit app.
- **Charts use a fixed pixel width, not Streamlit's `use_container_width`
  responsive sizing.** That path depends on Vega-Embed's ResizeObserver
  correctly measuring the wrapper element; at a fractional
  `devicePixelRatio` (observed: 1.25, the default under Windows' common
  125% display scaling) the measurement came back 0 and the chart
  canvas never recovered, even after a manual resize event. Confirmed
  by testing: identical chart, `width=600` renders correctly every
  time, `width="container"` does not. Traded true responsiveness for
  charts that reliably render.

## Next, with two more weeks

Real outlet disambiguation (GPS/phone, not name/city); an order-level
freight join if the API ever exposes one; regional-manager auth instead of
an open filter; a real LLM upgrade with safe execution and citations.
Also considered and rejected: orchestrating ETL/scraper/freight as an n8n
workflow instead of plain scripts — needs its own server/account, breaking
the cold-start bar this is graded on. Worth it once the pipeline runs on
a schedule against live systems, not as a reviewer-run local script.

## Breaks first in production

SQLite's single-writer lock and the in-memory pandas joins — fine at
820k rows, not 82M. `st.tabs` also renders every tab's Python on every
rerun regardless of which one is active, so any interaction anywhere
recomputed every metric for every tab; fixed by caching on the cheap
filter values (region/warehouse/channel/date), not on the dataframes,
so an unchanged-filter rerun is a cache hit rather than a recompute.
That holds at this scale; at 82M rows even the first hit per filter
combination needs Postgres and scheduled materialized aggregates
instead of per-page pandas recompute.
