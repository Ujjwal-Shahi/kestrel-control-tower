"""
Reproduces every DECISIONS.md data-quality claim that's derivable from the raw
operational db, straight from that db. Exists so the claims are checkable
rather than assertions -- if a number in DECISIONS.md drifts from the data,
this script fails loudly instead of the doc quietly going stale.

Scope: the DISPUTED-freight-invoice claim (~20% of invoice value, 58-97%
cost/case overstatement) is NOT checked here -- freight invoices live in
freight/cache/invoices.csv, written by freight/ingest.py from the mock
partner API, not in the raw db this script opens. That claim has no
raw-db-only reproduction path.

Run: python etl/verify_data_findings.py
Exit code 0 = every claim checked here holds. Thresholds are intentionally
loose (directional, not exact-match) so harmless rounding in the source data
doesn't cause false failures -- the specific numbers quoted in DECISIONS.md's
prose are printed for a human to compare, not asserted bit-for-bit.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import config

FAILURES = []


def check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}\n        {detail}")
    if not condition:
        FAILURES.append(label)


def parse_actual(row):
    val = row["actual_arrival"]
    if pd.isna(val):
        return pd.NaT
    try:
        if row["telematics_vendor"] == "TELEMATICS_B":
            return pd.to_datetime(val, format="%d-%b-%Y %I:%M %p")
        return pd.to_datetime(val, format="%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return pd.NaT


def main():
    conn = sqlite3.connect(config.DB_PATH)

    # ---- 1. planned_arrival's hour is corrupted; delay_minutes is authoritative ----
    d = pd.read_sql(
        "SELECT planned_arrival, actual_arrival, telematics_vendor, delay_minutes FROM deliveries", conn
    )
    d["act"] = d.apply(parse_actual, axis=1)
    d["plan"] = pd.to_datetime(d["planned_arrival"], errors="coerce")
    d["recalc"] = (d["act"] - d["plan"]).dt.total_seconds() / 60
    disagree = (d["recalc"] - d["delay_minutes"]).abs() > 1
    check(
        "planned_arrival disagrees with delay_minutes on most deliveries",
        disagree.mean() > 0.80,
        f"{disagree.sum():,} of {len(d):,} rows ({disagree.mean() * 100:.1f}%) disagree by >1 min.",
    )

    residual = (d["recalc"] - d["delay_minutes"]).dropna()
    whole_hours = (residual % 60 == 0)
    check(
        "the disagreement is always a whole number of hours",
        whole_hours.mean() > 0.99,
        f"{whole_hours.mean() * 100:.2f}% of residuals are exact multiples of 60 minutes "
        f"(range {residual.min():.0f} to {residual.max():.0f}).",
    )

    # If delay_minutes was computed against the TRUE schedule, then
    # actual - delay_minutes must reconstruct that schedule exactly.
    implied = d["act"] - pd.to_timedelta(d["delay_minutes"], unit="m")
    on_hour = (implied.dt.minute == 0) & (implied.dt.second == 0)
    same_date = implied.dt.date == d["plan"].dt.date
    check(
        "actual_arrival - delay_minutes reconstructs an exact on-the-hour schedule",
        on_hour.mean() > 0.999 and same_date.mean() > 0.999,
        f"{on_hour.mean() * 100:.2f}% land exactly on the hour, {same_date.mean() * 100:.2f}% on the "
        f"stored planned date. So delay_minutes is internally consistent with the real schedule "
        f"and planned_arrival's hour is the corrupted field.",
    )
    ot_delay = (d["delay_minutes"] <= 0).mean() * 100
    ot_recalc = (d["recalc"] <= 0).mean() * 100
    print(f"        -> on-time is {ot_delay:.1f}% using delay_minutes, "
          f"{ot_recalc:.1f}% using the corrupted planned_arrival. We use the former.")

    # ---- 2. delivered_qty never reaches ordered_qty ----
    r = pd.read_sql(
        """SELECT order_id,
             SUM(CASE WHEN qty_uom='CASE' THEN ordered_qty*case_pack_at_order ELSE ordered_qty END) oe,
             SUM(CASE WHEN qty_uom='CASE' THEN delivered_qty*case_pack_at_order ELSE delivered_qty END) de
           FROM order_lines GROUP BY order_id""",
        conn,
    )
    ratio = r["de"] / r["oe"]
    check(
        "no order is ever delivered in full against ordered_qty",
        ratio.max() < 1.0,
        f"max fill ratio {ratio.max():.4f}, median {ratio.median():.4f} across {len(r):,} orders. "
        f"This is why OTIF's 'in full' leg measures against allocated, not ordered.",
    )

    # ---- 3. temperature_excursion_flag is not usable ----
    t = pd.read_sql(
        """SELECT d.temperature_excursion_flag f, d.max_temp_celsius t
           FROM deliveries d
           WHERE EXISTS (SELECT 1 FROM order_lines ol JOIN products p ON p.product_id=ol.product_id
                         WHERE ol.order_id=d.order_id AND p.is_chilled=1)""",
        conn,
    )
    mean_flagged, mean_unflagged = t.loc[t.f == 1, "t"].mean(), t.loc[t.f == 0, "t"].mean()
    check(
        "temperature_excursion_flag does not correlate with max_temp_celsius",
        abs(mean_flagged - mean_unflagged) < 0.5,
        f"mean peak temp is {mean_flagged:.2f}C when flagged vs {mean_unflagged:.2f}C when not. "
        f"Flag fires on {t.f.mean() * 100:.1f}% of chilled deliveries; temp>8C on "
        f"{(t.t > 8).mean() * 100:.1f}%. The flag carries no information, so we derive from the reading.",
    )

    # ---- 4. REJECTED credit notes are a material share of value ----
    cn = pd.read_sql("SELECT status, credit_note_value_inr v FROM returns_credit_notes", conn)
    rej = cn.loc[cn.status == "REJECTED", "v"].sum()
    check(
        "REJECTED credit notes are material and must be excluded from leakage",
        rej / cn.v.sum() > 0.2,
        f"REJECTED is Rs {rej:,.0f} of Rs {cn.v.sum():,.0f} ({rej / cn.v.sum() * 100:.1f}%). "
        f"Including it overstates returns leakage by that much.",
    )

    # ---- 5. KP-2301 (header vs line value mismatch) is not reproducible ----
    # LEFT JOIN + COALESCE, not INNER JOIN: an order with zero order_lines
    # rows would silently vanish from an inner join instead of counting as a
    # (order_value_gross_inr - 0) mismatch. If KP-2301 specifically affected
    # orders missing lines entirely, an inner join would never see them and
    # this check would falsely PASS.
    k = pd.read_sql(
        """SELECT o.source_system, SUM(ABS(o.order_value_gross_inr - COALESCE(l.lt, 0))) diff
           FROM orders o LEFT JOIN (SELECT order_id, SUM(line_value_inr) lt FROM order_lines
                                    GROUP BY order_id) l ON l.order_id = o.order_id
           GROUP BY o.source_system""",
        conn,
    )
    check(
        "KP-2301 header-to-line mismatch does not reproduce",
        k["diff"].max() < 1.0,
        f"largest total absolute variance across any source system is {k['diff'].max():.2e} "
        f"(floating point noise). Treated as a stale entry in the issues log.",
    )

    # ---- 6. Outlet duplication and test outlets ----
    o = pd.read_sql("SELECT outlet_id, outlet_code, outlet_name, city, status, is_deleted FROM outlets", conn)
    canon = {"Bangalore": "Bengaluru", "New Delhi": "Delhi"}
    key = (o.outlet_name.str.strip().str.lower() + "|"
           + o.city.str.strip().map(lambda x: canon.get(x, x)).str.strip().str.lower())
    vc = key.value_counts()
    check(
        "outlet master contains name+city duplicates (KP-2211)",
        (vc > 1).sum() > 100,
        f"{(vc > 1).sum()} groups covering {vc[vc > 1].sum()} outlets. Flagged, not merged -- "
        f"legal_name is empty and GST differs even within a group.",
    )
    tst = o.outlet_code.str.startswith("TST")
    check(
        "test outlets are identifiable by TST prefix and are still ACTIVE",
        tst.sum() > 0 and (o.loc[tst, "status"] == "ACTIVE").all(),
        f"{tst.sum()} test outlets ({', '.join(o.loc[tst, 'outlet_name'])}), all status=ACTIVE with "
        f"is_deleted=0 -- so status filtering alone does not remove them (KP-2377).",
    )

    # ---- 7. Fill rate carries almost no signal above outlet grain ----
    fr = pd.read_sql(
        """SELECT o.region_id, o.warehouse_id, o.channel,
             SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.ordered_qty*ol.case_pack_at_order ELSE ol.ordered_qty END) oe,
             SUM(CASE WHEN ol.qty_uom='CASE' THEN ol.delivered_qty*ol.case_pack_at_order ELSE ol.delivered_qty END) de
           FROM order_lines ol JOIN orders o ON o.order_id = ol.order_id
           WHERE o.order_status IN ('DELIVERED','PARTIAL')
           GROUP BY o.region_id, o.warehouse_id, o.channel""",
        conn,
    )
    spreads = {}
    for dim in ["region_id", "warehouse_id", "channel"]:
        g = fr.groupby(dim)[["oe", "de"]].sum()
        pct = g.de / g.oe * 100
        spreads[dim] = pct.max() - pct.min()
    check(
        "fill rate is near-uniform above outlet grain (worst-performer views rank noise)",
        max(spreads.values()) < 1.0,
        "spread is " + ", ".join(f"{k.replace('_id','')} {v:.2f}pp" for k, v in spreads.items())
        + ". Reported honestly in the UI rather than presented as a performance ranking.",
    )

    # ---- 8. Every route in the network breaches the late-delivery bar ----
    # Mirrors app/metrics.py's late_routes(): >120 min late counts as "very
    # late", a route needs >=10 deliveries to be scored, and it's flagged if
    # >10% of its deliveries are very late. app/nl.py's t_late_routes uses
    # this to decide whether to present the result as a shortlist of problem
    # routes or state that lateness is network-wide -- fully raw-db-derivable
    # and load-bearing for that behavior, so it belongs here.
    lr = pd.read_sql(
        "SELECT rt.route_code, d.delay_minutes FROM deliveries d "
        "JOIN routes rt ON rt.route_id = d.route_id", conn,
    )
    lr["very_late"] = lr["delay_minutes"] > 120
    g = lr.groupby("route_code").agg(deliveries=("delay_minutes", "count"), very_late=("very_late", "sum"))
    g = g[g["deliveries"] >= 10]
    breach = g["very_late"] / g["deliveries"] > 0.10
    check(
        "nearly every scored route breaches the >2h-late->10%-of-deliveries bar",
        breach.mean() > 0.95,
        f"{breach.sum()} of {len(g)} routes with >=10 deliveries breach the bar "
        f"({breach.mean() * 100:.1f}%). Lateness is network-wide, not route-specific.",
    )

    # ---- 9. Returns run a few basis points of dispatch value, not whole percent ----
    # Mirrors app/metrics.py's returns_pct_of_dispatch_bps(): dispatch value is
    # fulfilled-order net value, returns value is SETTLED (APPROVED/PENDING,
    # excluding REJECTED) credit notes. Fully raw-db-derivable and it's the
    # number the Overview KPI tile shows, so it belongs here too.
    disp = pd.read_sql(
        "SELECT order_value_net_inr v FROM orders WHERE order_status IN ('DELIVERED','PARTIAL')", conn,
    )["v"].sum()
    settled = cn.loc[cn.status.isin(["APPROVED", "PENDING"]), "v"].sum()
    bps = settled / disp * 10_000
    check(
        "returns vs dispatch value is a few basis points, not whole percent",
        0.5 < bps < 20,
        f"{bps:.1f} bps ({bps / 100:.3f}%) of dispatch value. Reported in bps because a one-decimal "
        f"percentage would round to '0.0%' and read as a broken metric rather than a small one.",
    )

    conn.close()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} claim(s) no longer hold: {', '.join(FAILURES)}")
        sys.exit(1)
    print("All claims in DECISIONS.md verified against the raw database.")


if __name__ == "__main__":
    main()
