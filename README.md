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

## Submission notes

`data/kestrel_ops.db` is gitignored and not part of this repository, per
the assignment brief. Supply it at `data/kestrel_ops.db` (or point
`KESTREL_DB_PATH` at it) before running.
