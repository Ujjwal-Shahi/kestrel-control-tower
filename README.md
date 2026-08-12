# Kestrel Provisions: Supply Chain Control Tower

A working control tower over Kestrel's operational database, the shipped
competitor-price site, and the shipped mock freight API. See
[`DECISIONS.md`](DECISIONS.md) for what was built, what wasn't, and why.

## Cold start (one machine, no accounts)

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

Copy the supplied `kestrel_ops.db` into `data/kestrel_ops.db` (this repo
does not commit it — see submission notes below):

```bash
cp /path/to/kestrel_ops.db data/kestrel_ops.db
```

Then:

```bash
python run.py
```

This builds the cleaned database on first run and opens the dashboard at
`http://localhost:8501`. That's the whole cold start — everything below is
optional enrichment the dashboard works fine without (it shows a banner
telling you what's missing instead of crashing).

## Optional: competitor pricing

```bash
# terminal 1
cd bazaarpulse_site && python -m http.server 8080

# terminal 2
python -m scraper.scrape_and_match
```

Takes a couple of minutes (the site enforces a 1-second crawl delay).
Writes `scraper/cache/price_matches.csv`, which the Price Position tab reads.
Re-run any time to refresh.

## Optional: freight cost

```bash
# terminal 1
python partner_api/server.py

# terminal 2
python -m freight.ingest
```

Walks all ~41,500 invoices with retry/backoff around the API's deliberate
429/503 chaos; takes 1-2 minutes. Writes `freight/cache/invoices.csv`, which
the Money tab reads. If the API is unreachable, the ingester keeps whatever
was cached from a previous run rather than wiping it.

## Verifying the data findings

Every data-quality claim in `DECISIONS.md` is re-derived from the raw db by:

```
python etl/verify_data_findings.py
```

It prints each claim with the numbers behind it and exits non-zero if any of
them stops holding, so the doc cannot quietly go stale against the data.

## Re-running the ETL

If you get a fresh `kestrel_ops.db`, delete `data/kestrel_clean.db` and
re-run `python run.py` (or `python etl/build_clean_db.py` directly).

## Repository layout

```
config.py           central config, every path/URL overridable by env var
run.py               single entry point: build clean db + launch dashboard
etl/                 raw db -> cleaned tables (data-quality fixes, see DECISIONS.md)
scraper/              BazaarPulse crawler + SKU matcher
freight/              partner API ingestion client
app/                  Streamlit dashboard + deterministic NL layer
bazaarpulse_site/     shipped scrape target (as supplied)
partner_api/          shipped mock freight API (as supplied)
data/                 kestrel_ops.db goes here (gitignored)
```

## Ask Anything

The natural-language box answers a fixed set of question shapes
deterministically — no API key needed (see the "What can I ask?" expander
in the app, or `app/nl.py`). Setting `ANTHROPIC_API_KEY` is a documented
extension point for free-form questions but is not wired up to a live model
in this build — see `DECISIONS.md`.

## Design system

Dark theme, one accent hue (`#3987e5`, the same blue in every chart, every
metric-card glow, and the title gradient — never a different color per
element). Deliberately restrained rather than "add more effects":

- **Theme**: `.streamlit/config.toml` `[theme]` block sets the base dark
  palette (`base="dark"`, background `#0d0d0d`, chart surface `#1a1a19`).
  These are the *dark-mode* values from the `dataviz` skill's own validated
  palette, not invented colors — `app/charts.py` uses the matching light/dark
  pair for chart marks, gridlines, and axis ink.
- **Charts** (`app/charts.py`): single sequential hue for every bar/line —
  each chart plots one measure by category or time, so one hue is the
  correct encoding (a different color per bar would encode nothing extra).
  Thin marks, rounded bar caps, hairline gridlines — see
  `references/marks-and-anatomy.md` in the `dataviz` skill for the spec
  these follow.
- **Status signal**: KPI trend badges on Overview (▲/▼/–) always pair an
  icon with a text label ("Improving"/"Worsening"/"Flat"), never color
  alone — color is a reinforcement, not the only channel carrying meaning.
- **Accessibility**: every chart has a "View as table" twin at the same
  grain, so nothing is chart-only.
- **CSS**: `app/app.py`'s `_CUSTOM_CSS` block adds a soft glow-on-hover to
  metric cards and buttons using the one accent color, plus a gradient
  title. No per-element color decisions outside that one constant.

## Submission notes

`data/kestrel_ops.db` is gitignored and not part of this repository, per
the assignment brief. Supply it at `data/kestrel_ops.db` (or point
`KESTREL_DB_PATH` at it) before running.
