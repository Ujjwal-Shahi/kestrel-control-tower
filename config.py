"""Central config. Everything overridable by env var, everything has a working default
so a clean checkout runs with zero setup."""
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get("KESTREL_DB_PATH", os.path.join(REPO_ROOT, "data", "kestrel_ops.db"))
CLEAN_DB_PATH = os.environ.get("KESTREL_CLEAN_DB_PATH", os.path.join(REPO_ROOT, "data", "kestrel_clean.db"))

FREIGHT_API_BASE = os.environ.get("FREIGHT_API_BASE", "http://localhost:8088")
FREIGHT_API_KEY = os.environ.get("FREIGHT_API_KEY", "kp_live_7f3a9c21")  # shipped in assignment docs, not a secret
FREIGHT_CACHE_PATH = os.environ.get("FREIGHT_CACHE_PATH", os.path.join(REPO_ROOT, "freight", "cache", "invoices.csv"))

BAZAARPULSE_BASE = os.environ.get("BAZAARPULSE_BASE", "http://localhost:8080")
PRICE_MATCH_CACHE_PATH = os.environ.get("PRICE_MATCH_CACHE_PATH", os.path.join(REPO_ROOT, "scraper", "cache", "price_matches.csv"))
RAW_LISTINGS_CACHE_PATH = os.environ.get("RAW_LISTINGS_CACHE_PATH", os.path.join(REPO_ROOT, "scraper", "cache", "raw_listings.csv"))

# Optional NL upgrade. Absent -> deterministic mapper only, no degraded UX.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

FY_START_MONTH = 4  # April. FY Q1 = Apr-Jun.
