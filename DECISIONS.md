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
  "Design system" section rather than repeating it here. Two passes
  through `design-taste-frontend` (a React/Tailwind landing-page taste
  skill, whose own docs say it's not built for dashboards) still
  surfaced real corrections applicable to any stack: a blue-to-violet
  title gradient and blurred outer-glow hover effect were exactly the
  "AI purple/blue glow" cliche its anti-pattern rules name; decorative
  emoji in every tab/KPI label; and, on a second audit pass, 3
  em-dashes in visible UI strings (its #1 named tell, mechanically
  found by grep). All fixed within Streamlit + CSS. Used the skill's
  taste judgment throughout, not its React/GSAP mechanics, which don't
  apply here.
- **Service tab wraps its grain-dependent tables in `st.spinner()`.**
  Switching "Break down by" is a cache miss; without an explicit
  spinner Streamlit leaves the previous grain's tables on screen
  looking stale/broken until the new ones arrive. Found via real use,
  not a test agent.
- **Charts use a fixed pixel width, not Streamlit's `use_container_width`
  responsive sizing.** That path depends on Vega-Embed's ResizeObserver
  correctly measuring the wrapper element; at a fractional
  `devicePixelRatio` (observed: 1.25, the default under Windows' common
  125% display scaling) the measurement came back 0 and the chart
  canvas never recovered, even after a manual resize event. Confirmed
  by testing: identical chart, `width=600` renders correctly every
  time, `width="container"` does not. Traded true responsiveness for
  charts that reliably render. Chart containers use `overflow-x: auto`
  (not `hidden`) so a fixed width wider than a narrow viewport scrolls
  instead of silently clipping.
- **First-load progress is a real `st.status`, not simulated skeleton
  shimmer** -- decided after running the `llm-council` skill on the
  question. A true skeleton doesn't fit Streamlit's rerun model, and
  every load after the first is already an instant cache hit, so the
  honest fix is staged progress through a native widget for the one
  real wait, not decorative shimmer CSS pretending there's more latency
  than there is. Building it surfaced a real Streamlit trap: `st.status()`
  called inside an `@st.cache_data` function gets *replayed* on every
  cache hit, everywhere that function is called from. `build_ctx()` is
  called from inside ~10 separate cached wrapper functions, so the first
  version of this showed the loading banner about 10 times in a row on
  first load. Fixed by keeping `build_ctx()` free of all `st.*` calls and
  moving the status UI into a separate, non-cached `load_data_with_status()`
  gated by `session_state` to fire once per browser session, wrapped in
  `st.empty()` so the completed banner is removed from the DOM once
  loading finishes rather than sitting there collapsed forever -- `st.tabs`
  renders all six panels in one script pass and switching tabs afterward
  is a client-side show/hide with no rerun, so nothing else would ever
  have cleared it.
- Third `design-taste-frontend` pass, focused on "feel responsive /
  cool / interesting": no new findings. Single accent hue, inner-border
  hover states (not outer glow), the one motivated tab-switch fade
  (feedback that a click registered, per the skill's "motion needs a
  reason" rule), and em-dash-free UI strings all still held.
- **Four parallel UX-tester agents (first-time user, daily power-user,
  accessibility/responsive, edge-case breaker) audited the live app.**
  Real, verified findings fixed:
  - **`cached_near_expiry()` ignored every sidebar filter** -- caught by
    the edge-case agent reading the source directly. It's the only
    Cold Chain element on the page that didn't take `region`/`warehouse`,
    so a regional manager filtering to their region saw *global* near-
    expiry inventory with no indication it wasn't scoped. Fixed by
    joining to warehouses/regions and filtering on both (channel and
    date don't apply -- inventory is a point-in-time snapshot with
    neither dimension on it).
  - **Ask Anything's fallback answer showed literal `**` asterisks.**
    `st.markdown(f"**{text}**")` bolds every answer, but the fallback
    (`nl.CAPABILITIES`, a multi-paragraph bullet list) can't have inline
    emphasis span paragraph/list boundaries under CommonMark, so the
    markers rendered as literal characters -- on what's the *common*
    path for this deterministic matcher (anything outside its fixed
    question set). Fixed by only bolding single-line answers.
  - **Two agents disagreed on whether the Region filter actually works**
    (one saw KPIs change, one saw them stay identical). Verified directly
    in Python, bypassing UI automation entirely: the filter is correct
    -- row counts and raw numerator/denominator sums genuinely differ per
    region -- but this synthetic dataset has near-uniform fulfillment
    rates across regions (all within ~0.05 points of each other), so the
    rounded headline percentage barely moves. That's indistinguishable
    from "the filter is broken" at a glance. Added a caption under the
    Overview KPIs, shown only when a filter is active, stating the
    filtered order-line count -- a number that *does* move visibly even
    when the ratio doesn't, as proof the filter took effect.
  - Raw backend identifiers leaking into UI controls with no glossary
    (`GT`/`MT`/`HORECA`/`ECOM_DARKSTORE` channel codes, `region_name`/
    `warehouse_code`/`route_code`/`outlet_name` as the Service tab's
    "Break down by" options) -- mapped to plain-English labels via
    `format_func`, keeping the underlying codes as the actual filter/
    cache-key values.
  - Only the OTIF tile had a help tooltip; the other three Overview KPIs
    read as unexplained numbers to a first-time viewer. Added tooltips
    to all four.
  - The Price Position category-gap bar chart was the one chart on the
    page without a "View as table" twin (the README's own documented
    design rule). Added one.
  - Empty Ask-Anything submissions did nothing with no feedback. Added
    a warning.
  - Not fixed, and not a bug: `st.dataframe` tables measured stuck at
    52px wide during this audit. Traced to the Browser-pane sandbox not
    compositing frames at all in this session (`screenshot` failed with
    "page is not compositing frames" consistently, independent of any
    app code) -- `devicePixelRatio` was a clean 1.0, ruling out the
    earlier Vega chart bug's cause, and the dataframe grid depends on a
    real paint-driven `ResizeObserver` cycle to size itself the way the
    Vega charts (fixed-width, no ResizeObserver) don't. Switched
    `use_container_width=True` to explicit `width=` values anyway as a
    more deterministic sizing choice, but this needs confirming in a
    real browser, not claimed as fixed.
  - Also surfaced but deliberately not changed: Streamlit's rerun model
    means every sidebar filter change and grain switch costs a
    perceptible round-trip (already the known, accepted tradeoff
    documented above under "Breaks first in production"); the Ask
    Anything "first-match-wins" behavior on compound questions is a
    already-documented, accepted design limit, not a new bug.

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
