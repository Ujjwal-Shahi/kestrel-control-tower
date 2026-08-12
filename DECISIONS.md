# Decisions

## Built

Streamlit control tower over the three shipped sources: an ETL that cleans the
operational SQLite db, a BazaarPulse scraper/matcher, a freight API ingestion
client, and six views (Overview with Q1 headline metrics, Service, Cold Chain,
Money, Price Position, Ask Anything). Ask Anything is a deterministic
NL-to-query mapper covering the brief's illustrative questions plus "why did
fill rate drop in region X last week" -- no LLM key needed anywhere.
`python run.py` from a clean checkout is the one command.

Every data-quality claim below is reproducible: `python etl/verify_data_findings.py`
re-derives all of them from the raw db and exits non-zero if any stops holding.

## Data findings that changed a metric

- **`planned_arrival`'s hour is corrupted; `delay_minutes` is authoritative.**
  Recomputing delay as `actual_arrival - planned_arrival` disagrees with
  `delay_minutes` on 87% of deliveries, and the residual is *always* an exact
  multiple of 60 minutes. Reconstructing `actual_arrival - delay_minutes` yields
  an exactly on-the-hour timestamp on the stored planned date for 100% of 76,889
  rows, while the stored hour is statistically independent of it (uniform 8x8
  crosstab across the 06:00-13:00 window). So `delay_minutes` was computed
  against the real schedule and `planned_arrival` had its hour shuffled. On-time
  therefore reads from `delay_minutes` (34.9% on time); the timestamp route would
  have reported 38.0% and been wrong. The ETL still parses both vendors'
  `actual_arrival` formats because arrival time itself is real -- only the
  *planned* side is untrusted. Not in the known-issues log.
- **`temperature_excursion_flag` is unusable, so excursions derive from
  `max_temp_celsius > 8C`.** Mean peak temp is 5.53C when flagged vs 5.54C when
  not; the flag fires on 3.1% of chilled deliveries while the reading breaches on
  21.8%. The flag carries no information.
- **OTIF "in full" = delivered vs *allocated*, not vs ordered.** `delivered_qty`
  never once reaches `ordered_qty` across 83,671 orders (max ratio 99.4%, median
  86%). An ordered basis reads ~0% everywhere and double-counts the availability
  gap fill rate already reports. Allocated-to-delivered is the pick/pack/dispatch
  question OTIF exists to answer. Even so OTIF reads low (~2%); cross-warehouse
  ranking is usable now, the absolute number needs validating with Ops.
- **Contested amounts excluded on both sides of the ledger.** DISPUTED freight
  invoices (~20% of invoice value) are out: a contested charge isn't a settled
  cost, and including it overstated cost/case by 58-97% per warehouse-month.
  REJECTED credit notes (26% of credit-note value) are out for the same reason --
  a refused claim was defended, not leaked. PENDING is kept on both: unpaid but
  unrefused is a real owed liability.
- **Fill rate carries almost no signal above outlet grain.** Spread is 0.04pp
  across regions, 0.15pp across warehouses, 0.12pp across channels -- every cut
  sits at ~85.6%. The "worst performers" views therefore print a live warning
  that the ranking is ordering noise and the uniform level is the actual finding.
  Same for Q5: all 140 of 140 routes breach the ">2h late on >1-in-10" bar, so
  the NL answer says lateness is network-wide rather than handing over a 140-row
  "shortlist".
- **Returns vs dispatch is reported in basis points (~3.4 bps settled), not percent.** As
  a one-decimal percentage it renders as "0.0%" -- a metric Divya explicitly
  asked for, reading as broken rather than small.
- **Returns leakage by carrier is not derivable and is not shown.** Divya asked
  for leakage "by category and by carrier". Category is there; carrier is not,
  because carrier identity exists only in the freight API and never on a
  delivery or a credit note. The only bridge is route/warehouse plus date,
  which would attribute returns to a carrier by coincidence of geography.
  Freight *spend* by carrier is shown, since that is a real join.
- **KP-2301 not reproducible** -- header reconciles to line values to within
  floating-point noise across all three source systems. Treated as a stale doc
  entry rather than designed around.
- Test outlets are `outlet_code` prefix `TST` (3 of them) and are all still
  `status = ACTIVE, is_deleted = 0`, so status filtering alone does not remove
  them. Only two genuine city spelling variants exist (Bangalore/Bengaluru, New
  Delhi/Delhi). Credit-note quantities are signed inconsistently, so quantity is
  taken as absolute; all returns *value* metrics are unaffected.

## Assumptions where the brief was unclear or self-contradicted

- **Fill rate in eaches**, per Rakesh's override of Divya's "cases" -- more
  specific and more recent. Cases-equivalent is retained for freight cost/case.
- **"Last complete quarter" is derived from the data's own max date**
  (`last_complete_fy_quarter()`), not hardcoded. Currently resolves to Apr-Jun
  2026, which happens to be FY Q1, since the data ends 2026-06-30.
- **Price gap uses current `products.mrp_inr`, not `product_price_history`.**
  Divya asked for *today's* gap, so today's MRP is the correct operand;
  order-line economics use `unit_price_inr` captured at order time, so the
  history table is not needed for either.
- **Price matching uses literal `(pack_value, pack_uom)` equality**, not unit
  correction -- Kestrel's own catalog contains the same "400kg snack" anomalies
  and BazaarPulse reproduces them faithfully, so literal matching is more correct
  than "fixing" units. Fuzzy scoring uses `WRatio`, not `token_sort_ratio`: the
  latter ranked a wrong-brand same-pack product above the true match
  ("AmritValley" vs catalog "Amrit Valley" spacing). 100% matched (75 exact-pack
  / 90 fuzzy-fallback thresholds), zero category mismatches on spot-check.
- **The NL layer answers one capability per question**, by design -- a two-part
  question silently answers only the first match. Fixing that needs an LLM or a
  multi-intent router, reintroducing the complexity the deterministic layer
  exists to avoid. Accepted, not fixed.
- `/internal/margin-sheet.html` found, deliberately not scraped: `robots.txt`
  disallows it and it is irrelevant to the task.
- The brief describes ambient, chilled *and frozen*; `storage_temp_band` only
  ever holds `AMBIENT` or `CHILLED`, so the single 8C threshold is safe here. A
  real frozen band would need its own.
- Visual design (dark theme, single accent hue, chart conventions) follows the
  `dataviz` palette and mark specs -- see README's "Design system". Charts use a
  fixed pixel width because `use_container_width` measured 0 at fractional
  `devicePixelRatio` (1.25, i.e. Windows 125% scaling) and never recovered;
  reliable rendering beat true responsiveness.

## Not built, on purpose

- **Outlet entity resolution.** 161 groups (364 outlets) share a (name, city)
  key, consistent with the KP-2211 ownership-transfer duplication, but
  `legal_name` is empty and GST differs even within a group. Flagged
  (`possible_duplicate`), not merged -- wrong merges are worse than visible ones.
- **General text-to-SQL / LLM layer.** `ANTHROPIC_API_KEY` is a wired extension
  point, not an implementation. A non-deterministic layer that is also the *only*
  path to an answer was the wrong trade for something graded on a cold,
  unassisted checkout.
- **Row-level freight-to-delivery join.** The mock API exposes no `order_id`,
  only `warehouse_code`/`route_code`/date, so freight cost per case is a
  warehouse-month aggregate of two independently summed series. Cost is smeared
  evenly across routes sharing a warehouse-month; the ranking holds, a single
  route's number does not.
- Auth, live refresh, Postgres migration, product-detail-page scraping (adds only
  price history, unused by the price-gap ask), and the weather/holiday APIs -- no
  analytical link I could defend beyond "it was available".

## Next, with two more weeks

Real outlet disambiguation (GPS/phone, not name/city); an order-level freight
join if the API ever exposes one; regional-manager auth instead of an open
filter; a real LLM upgrade with safe execution and citations. Considered and
rejected: orchestrating ETL/scraper/freight as an n8n workflow -- needs its own
server and account, breaking the cold-start bar this is graded on. Worth it once
the pipeline runs on a schedule against live systems.

## Breaks first in production

SQLite's single-writer lock and the in-memory pandas joins -- fine at 820k rows,
not 82M. `st.tabs` also renders every tab's Python on every rerun regardless of
which tab is active, so any interaction recomputed every metric; fixed by caching
on the cheap filter values (region/warehouse/channel/date) rather than on
dataframes, so an unchanged-filter rerun is a cache hit. That holds at this
scale; at 82M rows even the first hit per filter combination needs Postgres and
scheduled materialised aggregates. After that, the BazaarPulse SKU matcher:
titles are matched heuristically, so a retailer renaming products degrades match
quality silently rather than erroring.
