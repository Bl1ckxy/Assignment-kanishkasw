"""Stage 5 — holdout (2025-04-01) partial-day check for the 7-day forecast.

The dump stops mid-day on 2025-04-01, so the holdout actual must NOT be
compared with a full-day forecast. This stage:

  1. reads the exact data cutoff (last order_date in orders_holdout),
  2. computes the share of a *Tuesday* (same weekday) that occurs at or
     before that cutoff from the IST hourly profile of the forecast branch,
  3. compares actual vs forecast x share,
  4. asserts the training window ends 2025-03-31 (no partial-day leakage).

Writes:
  outputs/hourly_tuesday_branch.csv  IST hourly profile, forecast branch, Tuesdays
  outputs/holdout_check.csv          the comparison (metrics, value)

Run: venv\\Scripts\\python.exe src\\05_holdout_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

import config
import db

DOW_TUE = 3  # DAYOFWEEK: 1=Sun .. 3=Tue (see 03_eda.py)


def load_branch() -> tuple[int, str]:
    lines = (config.OUTPUTS / "forecast_branch.txt").read_text(
        encoding="utf-8").strip().splitlines()
    parts = lines[1].split("\t")
    return int(parts[0]), parts[1]


def cutoff_and_holdout(conn, bid: int) -> tuple[str, str, int]:
    """Data cutoff (all branches), branch-2 last timestamp, branch-2 actual."""
    row = db.fetch_df(conn, """
        SELECT DATE_FORMAT(MAX(order_date), '%%Y-%%m-%%d %%H:%%i:%%s') AS cutoff_all,
               SUM(branch_id = %s) AS b2_actual
        FROM orders_holdout
    """, (bid,)).iloc[0]
    b2_last = db.scalar(conn, """
        SELECT DATE_FORMAT(MAX(order_date), '%%Y-%%m-%%d %%H:%%i:%%s')
        FROM orders_holdout WHERE branch_id = %s
    """, (bid,))
    return str(row["cutoff_all"]), str(b2_last), int(row["b2_actual"])


def tuesday_profile(conn, bid: int) -> pd.DataFrame:
    """IST hourly counts for the branch, Tuesdays only (FY 2024-25)."""
    df = db.fetch_df(conn, """
        SELECT ist_hour, COUNT(*) AS orders FROM orders_clean
        WHERE branch_id = %s AND ist_dow = %s
        GROUP BY ist_hour ORDER BY ist_hour
    """, (bid, DOW_TUE))
    df.to_csv(config.OUTPUTS / "hourly_tuesday_branch.csv", index=False)
    return df


def tuesday_share_to_cutoff(conn, bid: int, cutoff: str) -> tuple[int, int, float]:
    """(Tuesday orders <= cutoff time-of-day, all Tuesday orders, share)."""
    time_of_day = cutoff.split(" ")[1]
    to_cut = int(db.scalar(conn, """
        SELECT COUNT(*) FROM orders_clean
        WHERE branch_id = %s AND ist_dow = %s AND TIME(order_date) <= %s
    """, (bid, DOW_TUE, time_of_day)))
    total = int(db.scalar(conn, """
        SELECT COUNT(*) FROM orders_clean WHERE branch_id = %s AND ist_dow = %s
    """, (bid, DOW_TUE)))
    return to_cut, total, to_cut / total if total else float("nan")


def training_window(conn, bid: int) -> tuple[str, int]:
    """(max ist_date in the training series, rows on 2025-04-01) — leakage check."""
    max_day = str(db.scalar(conn, "SELECT MAX(ist_date) FROM orders_clean"))
    apr1 = int(db.scalar(conn, """
        SELECT COUNT(*) FROM orders_clean WHERE ist_date = '2025-04-01'
    """))
    return max_day, apr1


def main() -> None:
    bid, bname = load_branch()
    fc = pd.read_csv(config.OUTPUTS / "forecast_7d.csv")
    day1 = fc.iloc[0]
    forecast = float(day1["forecast_orders"])
    actual = float(day1["actual"])

    conn = db.connect(time_zone=config.UTC_OFFSET)  # wall-clock values as stored
    try:
        cutoff, b2_last, b2_actual = cutoff_and_holdout(conn, bid)
        tue_profile = tuesday_profile(conn, bid)
        to_cut, tue_total, share = tuesday_share_to_cutoff(conn, bid, cutoff)
        max_day, apr1_rows = training_window(conn, bid)
    finally:
        conn.close()

    assert b2_actual == actual, f"holdout {b2_actual} != forecast_7d actual {actual}"
    expected = forecast * share
    error = actual - expected
    error_pct = 100.0 * error / expected

    print(f"[holdout] branch {bid} ({bname})")
    print(f"[holdout] data cutoff (as stored / IST wall clock): {cutoff}")
    print(f"[holdout] branch-2 last order that day:            {b2_last}")
    print(f"[holdout] training window ends {max_day}; "
          f"rows on 2025-04-01 in orders_clean = {apr1_rows}")
    print(f"[holdout] Tuesday profile: {len(tue_profile)} hourly bins "
          f"(outputs/hourly_tuesday_branch.csv), total {tue_total:,}")
    print(f"[holdout] Tuesday orders <= {cutoff.split(' ')[1]}: {to_cut:,} "
          f"-> expected share {share:.4f} ({share * 100:.1f}%)")
    print(f"[holdout] forecast full day {forecast:,.0f} -> expected to cutoff "
          f"{expected:,.0f}; actual {actual:,.0f} "
          f"= {error:+,.0f} ({error_pct:+.1f}%)")

    rows = [
        ("branch_id", bid),
        ("branch_name", bname),
        ("data_cutoff_as_stored_ist", cutoff),
        ("branch2_last_order_ist", b2_last),
        ("holdout_outside_fy", "yes (2025-04-01, after FY end 2025-03-31)"),
        ("holdout_partial_day", "yes (dump stops mid-day)"),
        ("forecast_day1_full", round(forecast, 1)),
        ("actual_partial_day", round(actual, 1)),
        ("tuesday_dow", DOW_TUE),
        ("tuesday_orders_fy", tue_total),
        ("tuesday_orders_to_cutoff", to_cut),
        ("expected_share_before_cutoff", round(share, 6)),
        ("expected_full_forecast_x_share", round(expected, 1)),
        ("error_actual_minus_expected", round(error, 1)),
        ("error_pct", round(error_pct, 2)),
        ("training_max_ist_date", max_day),
        ("rows_on_2025_04_01_in_orders_clean", apr1_rows),
    ]
    out = config.OUTPUTS / "holdout_check.csv"
    pd.DataFrame(rows, columns=["metric", "value"]).to_csv(out, index=False)
    print(f"[holdout] written {out}")


if __name__ == "__main__":
    main()
