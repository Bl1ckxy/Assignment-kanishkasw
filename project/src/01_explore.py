"""Stage 1 — explore the loaded raw tables BEFORE cleaning.

Outputs (all aggregates / DDL, no raw rows):
  logs/schema_<table>.txt        SHOW CREATE TABLE evidence (schema read before queries)
  outputs/distributions.csv      value counts for key categorical columns
  outputs/tz_comparison.csv      hourly histograms for 3 candidate time columns
                                 under UTC vs IST display
Also prints a compact summary to stdout.

Run: venv\\Scripts\\python.exe src\\01_explore.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import db

CAT_COLS = [
    ("orders", "order_status"),
    ("orders", "cd_status"),
    ("orders", "paid_or_cancel"),
    ("orders", "order_through"),
    ("orders", "mode_of_transaction"),
    ("orders", "is_refunded"),
    ("orders", "branch_id"),
    ("order_details", "order_status"),
]


def dump_schema(conn, table: str) -> str:
    """SHOW CREATE TABLE -> logs/schema_<table>.txt (evidence of real columns)."""
    with conn.cursor() as cur:
        cur.execute(f"SHOW CREATE TABLE `{table}`")
        ddl = cur.fetchone()[1]
    path = config.LOGS / f"schema_{table}.txt"
    path.write_text(ddl + "\n", encoding="utf-8")
    print(f"[schema] {table} -> {path.name} ({len(ddl)} chars)")
    return ddl


def coverage(conn) -> None:
    """Row counts and time ranges of every timestamp-ish column on orders."""
    cols = ["order_date", "IST_timezone", "order_create_time",
            "created_at", "payment_timestamp", "order_closed_time"]
    parts = ", ".join(
        f"MIN(`{c}`) AS mn_{c}, MAX(`{c}`) AS mx_{c}, "
        f"SUM(`{c}` IS NULL) AS nulls_{c}" for c in cols
    )
    sql = f"SELECT COUNT(*) AS n, {parts} FROM orders"
    db.execute(conn, "SET SESSION time_zone = '+05:30'")  # display IST
    rows = db.fetch_df(conn, sql)
    r = rows.iloc[0]
    print(f"[coverage] orders rows = {int(r['n']):,} (display tz = IST)")
    for c in cols:
        print(f"    {c:22s} {r['mn_' + c]} .. {r['mx_' + c]}  nulls={int(r['nulls_' + c]):,}")
    rows.to_csv(config.OUTPUTS / "orders_time_coverage_ist.csv", index=False)

    # Same columns displayed as UTC for comparison
    db.execute(conn, "SET SESSION time_zone = '+00:00'")
    rows_u = db.fetch_df(conn, sql)
    rows_u.to_csv(config.OUTPUTS / "orders_time_coverage_utc.csv", index=False)
    r = rows_u.iloc[0]
    print(f"[coverage] (display tz = UTC) order_date {r['mn_order_date']} .. {r['mx_order_date']}")


def distributions(conn) -> None:
    """Value counts for categorical columns -> outputs/distributions.csv."""
    out = []
    for table, col in CAT_COLS:
        rows = db.fetch_df(
            conn,
            f"SELECT `{col}` AS value, COUNT(*) AS n FROM `{table}` "
            f"GROUP BY `{col}` ORDER BY n DESC LIMIT 50",
        )
        top = ", ".join(f"{v}={int(n):,}" for v, n in rows.head(6).values)
        rows.insert(0, "column", f"{table}.{col}")
        out.append(rows)
        print(f"[dist] {table}.{col}: {top}")
    import pandas as pd
    pd.concat(out, ignore_index=True).to_csv(
        config.OUTPUTS / "distributions.csv", index=False
    )


def tz_comparison(conn) -> None:
    """Hourly histograms of candidate columns under UTC vs IST display.

    The (column, display) pair whose histogram peaks at lunch (12-14h IST)
    tells us which column already holds local wall-clock time and which is a
    true UTC instant. Written to outputs/tz_comparison.csv; decision recorded
    in ASSUMPTIONS.md.
    """
    cols = config.TZ_COMPARE_COLUMNS
    frames = []
    for display in ("+00:00", "+05:30"):
        db.execute(conn, f"SET SESSION time_zone = '{display}'")
        for c in cols:
            df = db.fetch_df(
                conn,
                f"SELECT HOUR(`{c}`) AS hour_of_day, COUNT(*) AS n FROM orders "
                f"WHERE `{c}` IS NOT NULL GROUP BY HOUR(`{c}`)",
            )
            df.insert(0, "display_tz", display)
            df.insert(0, "column", c)
            frames.append(df)
    import pandas as pd
    all_df = pd.concat(frames, ignore_index=True)
    all_df.to_csv(config.OUTPUTS / "tz_comparison.csv", index=False)

    print("[tz] peak hour and 12-14h share (of FY-window rows):")
    for (col, disp), g in all_df.groupby(["column", "display_tz"]):
        total = g["n"].sum()
        g = g.sort_values("hour_of_day")
        peak = int(g.loc[g["n"].idxmax(), "hour_of_day"])
        lunch = int(g[g["hour_of_day"].isin([12, 13, 14])]["n"].sum())
        print(f"    {col:16s} display={disp}  peak={peak:02d}h  "
              f"share(12-14h)={lunch / total:.1%}")


def duplicate_checks(conn) -> None:
    """Primary-key sanity: dup ids and repeated order numbers."""
    df = db.fetch_df(
        conn,
        "SELECT COUNT(*) AS rows_, COUNT(DISTINCT id) AS distinct_ids, "
        "       COUNT(DISTINCT order_number) AS distinct_order_numbers "
        "FROM orders",
    )
    r = df.iloc[0]
    dup_ids = int(r["rows_"]) - int(r["distinct_ids"])
    print(f"[dup] orders rows={int(r['rows_']):,} distinct_ids={int(r['distinct_ids']):,} "
          f"duplicate_id_rows={dup_ids:,} distinct_order_numbers={int(r['distinct_order_numbers']):,}")
    df.to_csv(config.OUTPUTS / "duplicate_summary.csv", index=False)


def main() -> None:
    config.LOGS.mkdir(exist_ok=True)
    config.OUTPUTS.mkdir(exist_ok=True)
    conn = db.connect(time_zone=config.IST_OFFSET)
    try:
        for t in ("orders", "order_details"):
            dump_schema(conn, t)
        coverage(conn)
        distributions(conn)
        tz_comparison(conn)
        duplicate_checks(conn)
        print("[explore] done -> outputs/")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
