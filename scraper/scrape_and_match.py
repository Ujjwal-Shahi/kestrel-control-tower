"""
Scrapes BazaarPulse (the shipped competitor price site), matches listings to
Kestrel SKUs, writes scraper/cache/price_matches.csv for the dashboard.

Respects robots.txt (skips /internal/, /admin/), honours Crawl-delay: 1.
Only scrapes listing pages -- product detail pages add observed price
history, which nothing in the brief's price-gap ask needs, so they are
deliberately not fetched (see DECISIONS.md).

Run: python -m scraper.scrape_and_match
Requires: bazaarpulse_site served locally, e.g.
  cd bazaarpulse_site && python -m http.server 8080
"""
import os
import re
import sys
import time
import sqlite3
from urllib import robotparser

import requests
from bs4 import BeautifulSoup
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

CRAWL_DELAY = 1.0
NOISE_PATTERNS = [
    re.compile(r"^Combo\s+", re.I),
    re.compile(r"^Pack of \d+\s+", re.I),
    re.compile(r"\s*\(New\)\s*$", re.I),
    re.compile(r"\s*\|.*$"),
    re.compile(r"\s*-\s*Family Pack\s*$", re.I),
]


def clean_title(title):
    t = title
    for pat in NOISE_PATTERNS:
        t = pat.sub("", t)
    return " ".join(t.split()).strip()


def get_robots(session):
    rp = robotparser.RobotFileParser()
    rp.set_url(f"{config.BAZAARPULSE_BASE}/robots.txt")
    r = session.get(f"{config.BAZAARPULSE_BASE}/robots.txt", timeout=10)
    rp.parse(r.text.splitlines())
    return rp


def fetch(session, rp, path):
    if not rp.can_fetch("*", f"{config.BAZAARPULSE_BASE}{path}"):
        print(f"  skip (robots.txt disallows): {path}")
        return None
    time.sleep(CRAWL_DELAY)
    r = session.get(f"{config.BAZAARPULSE_BASE}{path}", timeout=10)
    if r.status_code != 200:
        print(f"  skip ({r.status_code}): {path}")
        return None
    return r.text


def discover_cities(session, rp):
    html = fetch(session, rp, "/index.html")
    soup = BeautifulSoup(html, "html.parser")
    cities = {}
    for a in soup.select("ul li a"):
        href = a.get("href", "")
        m = re.match(r"/city/([a-z]+)/(page/1\.html|index\.html)", href)
        if not m:
            continue
        slug, kind = m.groups()
        style = "path" if kind.startswith("page") else "index"
        cities[slug] = {"style": style, "name": a.get_text(strip=True)}
    return cities


def page_path(slug, style, n):
    if style == "path":
        return f"/city/{slug}/page/{n}.html"
    return f"/city/{slug}/index.html" if n == 1 else f"/city/{slug}/index_p{n}.html"


def extract_price(card):
    el = card.select_one("span.price")
    if el:
        return float(re.sub(r"[^\d.]", "", el.get_text()) or 0) or None
    el = card.select_one("div.amt")
    if el:
        m = re.search(r"[\d.]+", el.get_text(" ", strip=True).replace("Rs.", ""))
        return float(m.group()) if m else None
    el = card.select_one("span.pricing-block")
    if el and el.has_attr("data-price-paise"):
        return float(el["data-price-paise"]) / 100.0
    el = card.select_one("b.sellingPrice")
    if el:
        m = re.search(r"[\d.]+", el.get_text().replace("INR", ""))
        return float(m.group()) if m else None
    return None


def parse_card(card, city_name):
    listing_id = card.get("data-listing-id")
    a = card.select_one("a")
    if not a or not a.get("href"):
        return None
    pm = re.search(r"/product/(\d+)\.html", a["href"])
    site_product_id = pm.group(1) if pm else None
    title = a.get_text(strip=True)

    muted = card.select("div.muted")
    retailer = pack_raw = category = None
    if muted:
        parts = [p.strip() for p in muted[0].get_text("·").split("·")]
        if len(parts) >= 3:
            retailer, pack_raw, category = parts[0], parts[1], parts[2]

    mrp = stock_status = rating = None
    if len(muted) > 1:
        line2 = muted[1].get_text(" ", strip=True)
        mm = re.search(r"MRP\s*₹\s*([\d.]+)", line2)
        mrp = float(mm.group(1)) if mm else None
        if "unavailable" in line2.lower():
            stock_status = "UNAVAILABLE"
        elif "out of stock" in line2.lower():
            stock_status = "OUT_OF_STOCK"
        elif "in stock" in line2.lower():
            stock_status = "IN_STOCK"

    last_seen = None
    if len(muted) > 2:
        lm = re.search(r"Last seen:\s*([\d-]+)", muted[2].get_text(strip=True))
        last_seen = lm.group(1) if lm else None

    pack_value = pack_uom = None
    if pack_raw:
        pm2 = re.match(r"([\d.]+)\s*([a-zA-Z]+)", pack_raw)
        if pm2:
            pack_value = float(pm2.group(1))
            pack_uom = pm2.group(2).upper()

    return {
        "listing_id": listing_id,
        "site_product_id": site_product_id,
        "city": city_name,
        "retailer": retailer,
        "category": category,
        "title_raw": title,
        "title_clean": clean_title(title),
        "pack_value": pack_value,
        "pack_uom": pack_uom,
        "price_inr": extract_price(card),
        "mrp_scraped_inr": mrp,
        "stock_status": stock_status,
        "last_seen": last_seen,
    }


def crawl():
    session = requests.Session()
    rp = get_robots(session)
    cities = discover_cities(session, rp)
    print(f"Cities discovered: {cities}")

    rows = []
    for slug, meta in cities.items():
        html = fetch(session, rp, page_path(slug, meta["style"], 1))
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        m = re.search(r"page (\d+) of (\d+)", soup.get_text())
        total_pages = int(m.group(2)) if m else 1
        print(f"{meta['name']}: {total_pages} pages ({meta['style']} style)")

        for n in range(1, total_pages + 1):
            if n == 1:
                page_html = html
            else:
                page_html = fetch(session, rp, page_path(slug, meta["style"], n))
                if page_html is None:
                    continue
            page_soup = BeautifulSoup(page_html, "html.parser")
            for card in page_soup.select("div.product-item"):
                row = parse_card(card, meta["name"])
                if row:
                    rows.append(row)

    df = pd.DataFrame(rows)
    # The site's last page of a city occasionally repeats items from page 1
    # (observed on Mumbai and Chennai) -- dedupe by listing_id, which is unique
    # per listing regardless of which page it was crawled from.
    before = len(df)
    df = df.drop_duplicates(subset="listing_id", keep="first")
    if before != len(df):
        print(f"  dropped {before - len(df)} duplicate listing(s)")

    os.makedirs(os.path.dirname(config.RAW_LISTINGS_CACHE_PATH), exist_ok=True)
    df.to_csv(config.RAW_LISTINGS_CACHE_PATH, index=False)
    print(f"Scraped {len(df)} listings -> {config.RAW_LISTINGS_CACHE_PATH}")
    return df


def load_products():
    conn = sqlite3.connect(config.DB_PATH)
    df = pd.read_sql("SELECT sku_code, brand, product_name, category, pack_size_value, "
                      "pack_size_uom, mrp_inr, status FROM products", conn)
    conn.close()
    # product_name already starts with brand in this catalog (e.g. "Hillfare
    # Instant Noodles 1000g") -- prefixing brand again doubled the brand
    # token and let brand-sharing false positives (e.g. two 1000g noodle
    # SKUs from different brands) out-score the genuinely correct match.
    df["match_target"] = df["product_name"].fillna("").str.strip()
    return df


def match_listings(listings, products):
    exact_pack = {}
    for _, p in products.iterrows():
        key = (p["pack_size_value"], p["pack_size_uom"])
        exact_pack.setdefault(key, []).append(p)

    results = []
    for _, row in listings.iterrows():
        candidates = exact_pack.get((row["pack_value"], row["pack_uom"]), [])
        method = "exact_pack"
        if not candidates:
            candidates = [p for _, p in products.iterrows()]
            method = "fallback_fuzzy"

        # .lower() both sides -- rapidfuzz's token_sort_ratio is case-sensitive,
        # and ~12% of scraped titles are ALL CAPS (e.g. "KESTREL SEL. JUICE
        # 200ML"), which without this scores ~50 against the catalog's normal
        # casing and silently fails every threshold.
        # WRatio, not token_sort_ratio -- token_sort_ratio scored a same-pack,
        # different-brand product HIGHER than the true match on a real listing
        # ("AmritValley Inst. Noodles 1000g" matched to Hillfare's 1000g
        # noodle SKU, not Amrit's, 71.4 vs 70.4) because it has no tolerance
        # for the "AmritValley" vs "Amrit Valley" spacing difference between
        # the site's titles and the catalog's names. WRatio blends several
        # rapidfuzz algorithms (including partial-ratio) and separates the
        # same pair correctly (92.3 vs 75.4 on this example).
        title_norm = row["title_clean"].lower()
        best_sku, best_score, best_row = None, -1, None
        for p in candidates:
            score = fuzz.WRatio(title_norm, p["match_target"].lower())
            if score > best_score:
                best_score, best_sku, best_row = score, p["sku_code"], p

        # Different acceptance bar per method, not a blanket score multiplier --
        # a multiplier (best_score * 0.6) caps fallback confidence at 60, which
        # is mathematically unreachable against any single "confidence >= 70"
        # cutoff. fallback_fuzzy has no pack-size corroboration, so it earns a
        # stricter raw-score bar (90) instead of a scaled-down one.
        # Thresholds re-tuned for WRatio's distribution (observed floor on
        # genuine exact_pack matches in this data: 87.9; median 100).
        confidence = best_score
        if method == "exact_pack":
            matched = confidence >= 75
        else:
            matched = confidence >= 90
        results.append({
            **row.to_dict(),
            "matched_sku_code": best_sku if matched else None,
            "kestrel_mrp_inr": float(best_row["mrp_inr"]) if matched else None,
            "match_confidence": round(confidence, 1),
            "match_method": method if matched else "none",
        })
    return pd.DataFrame(results)


def main():
    listings = crawl()
    products = load_products()
    matched = match_listings(listings, products)
    os.makedirs(os.path.dirname(config.PRICE_MATCH_CACHE_PATH), exist_ok=True)
    matched.to_csv(config.PRICE_MATCH_CACHE_PATH, index=False)
    n_matched = matched["matched_sku_code"].notna().sum()
    print(f"Matched {n_matched}/{len(matched)} listings -> {config.PRICE_MATCH_CACHE_PATH}")


if __name__ == "__main__":
    main()
