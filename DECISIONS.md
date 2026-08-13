# Decisions

## Built

Streamlit control tower. ETL cleans the operational SQLite db into a second file
(raw never mutated). Six tabs: Overview (Q1 headline), Service, Cold Chain, Money,
Price Position, Ask Anything. BazaarPulse scraper, freight API client (full
41,500-invoice walk), deterministic NL layer covering all eight illustrative
questions -- no API key needed. `python run.py` is the one command.

`etl/verify_data_findings.py` re-derives every data claim below from the raw db
and exits non-zero if any stops holding.

## Data findings that changed a metric

- **`planned_arrival`'s hour is corrupted; `delay_minutes` is authoritative.**
  actual - planned disagrees with delay_minutes on 87% of deliveries; the residual
  is always a whole multiple of 60 minutes. Reconstructing actual - delay_minutes
  lands exactly on the hour, same date, for 100.00% of 76,889 rows while the stored
  hour is independent of it. On-time is 34.9% on the correct field, 38.0% on the
  corrupted one. Not in the known-issues log.
- **temperature_excursion_flag is noise.** Mean peak temp 5.53 C flagged vs 5.54 C
  unflagged. Derived from max_temp_celsius > 8 C instead.
- **OTIF "in full" = delivered vs allocated, not ordered.** delivered_qty never
  reaches ordered_qty across 83,671 orders (max 99.4%, median 86%). Ordered basis
  reads ~0% everywhere and double-counts the availability gap fill rate already
  reports.
- **Contested amounts excluded on both sides, three-for-three.** DISPUTED freight
  (contested, not settled), REJECTED credit notes (refused, not leaked), and
  UNAVAILABLE competitor listings (out-of-stock price is not a shelf price) all
  excluded on the same principle. PENDING stays on all three: unpaid but unrefused
  is owed. 147 of 1,137 listings are unavailable; 6.3% of SKU-city pairs had one
  setting the floor, understating the shelf price by Rs 29 avg. Headline gap moves
  +15.95% to +15.28% (Mumbai +16.88% to +15.63%).
- **Fill rate carries no signal above outlet grain.** 0.04pp spread across regions,
  0.15pp warehouses -- all ~85.6%. Worst-performer views print a live note when
  spread is under 1pp. All 140 of 140 routes breach the >2h-late-on->1-in-10 bar;
  NL reports network-wide lateness, not a 140-row shortlist.
- **Returns vs dispatch in basis points (~3.4 bps settled).** As one-decimal percent
  it renders as "0.0%" on a tile Divya named. KP-2301 not reproducible.

## Assumptions

- Eaches, per Rakesh's override. Cases derivable; one-line change if overruled.
- Last complete quarter from data's max date, not hardcoded. Currently Apr-Jun 2026.
- Price gap uses current products.mrp_inr (correct for a "today" question).
- /internal/margin-sheet.html found; not scraped (robots.txt disallows it).
- No FROZEN storage band exists; 8 C threshold safe here by luck, noted.
- WRatio over token_sort_ratio: latter ranked wrong-brand same-pack SKU above the
  true match on a real case ("AmritValley" vs "Amrit Valley" spacing).

## Not built, on purpose

- Outlet entity resolution: 161 groups/364 outlets share (name, city) but legal_name
  is empty and GST differs within groups. Flagged, not merged -- wrong merge silently
  corrupts every per-outlet metric.
- General LLM layer: non-deterministic path as the *only* path to an answer was wrong
  for a cold, unassisted checkout. Extension point wired, not live.
- Row-level freight join: API exposes no order_id; cost is a warehouse-month aggregate.
  Ranking holds; a single route's number does not.
- Returns leakage by carrier: carrier exists only in the freight API, never on a
  delivery or credit note. Freight spend by carrier is shown instead.
- salespeople and promotions tables read by ETL, not exposed. Promotions are the
  obvious "why did fill rate drop" candidate but joining to shortfalls without a
  coverage denominator produces noise.
- /v1/fuel_surcharge and /v1/shipment_events not ingested. fuel_surcharge is the
  next join to explain the Rs 198-429 freight cost spread by warehouse-month.
- Weather/holiday APIs: no defensible causal link in the time available.
- Auth, live refresh, Postgres migration, product-detail-page scraping.

## Breaks first in production

SKU matcher (heuristic on titles, degrades silently on retailer renames) then
SQLite single-writer lock at volume then freight API schema drift then outlet
deduplication (re-breaks on ownership transfers).

## Next with two more weeks

Outlet disambiguation on GPS/phone; order-level freight join if API exposes a
shipment reference; role-scoped auth for regional managers; LLM layer over the
deterministic floor with read-only execution and query citations.
