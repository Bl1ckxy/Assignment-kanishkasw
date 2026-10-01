"""Stage 2 — clean raw tables into analysis-ready tables.

Builds:
  orders_stage        narrow projection of raw orders + dedup rank + rule flags
  orders_clean        final rows (one per id, FY-window, business-valid)
  order_details_clean line items joined to orders_clean (orphans dropped)
Then: DROP raw `orders` and `order_details`.

Every rule logs rows before/removed/after -> outputs/cleaning_log.csv.

DECISIONS block below is filled from 01_explore.py output.

Run: venv\\Scripts\\python.exe src\\02_clean.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import db

# ---------------------------------------------------------------------------
# DECISIONS — filled after 01_explore.py (see ASSUMPTIONS.md A4/A6/A7)
# ---------------------------------------------------------------------------
DECISIONS = {
    # A4: raw stored values ARE local (IST) wall clock.
    # Evidence: (a) hourly peak of raw values sits at 13h = lunch 12-14;
    # (b) shifting +5:30 moves mass to implausible 21:30-03:30 peaks;
    # (c) json_data terminal tag "Transaction Time 171128" == raw 17:11:44
    #     (terminal stamps local time). => NO shift, use values as-is.
    "time_column": "order_date",
    "time_interpretation": "wall_clock",
    # A7: test/toy branch ids (data: branches 6/7/8 have ZERO orders; kept
    # explicit so the rule is visible in the log; removes 0 rows).
    "test_branches": (6, 7, 8),
    # R6: business-real orders = paid and not refunded (from crosstab:
    # paid=5,450,311 incl. 22 refunded; cancel=402,133; pending=108,422;
    # rejected=138; NULL=1). Unqualified columns (used on orders + stage).
    "status_predicate": "paid_or_cancel = 'paid' AND is_refunded = 0",
}

RULES_LOG = []  # (rule_id, description, rows_before, rows_removed, note)


def log_rule(rule_id: str, description: str, before: int, removed: int, note: str = "") -> None:
    RULES_LOG.append((rule_id, description, before, removed, before - removed, note))
    print(f"  [{rule_id}] {description}: before={before:,} removed={removed:,} "
          f"after={before - removed:,} {note}")


def assert_decisions() -> None:
    missing = [k for k, v in DECISIONS.items() if v is None or v == ()]
    if DECISIONS["status_predicate"] is None:
        missing.append("status_predicate")
    if missing:
        raise RuntimeError(f"DECISIONS not filled yet: {missing} (run 01_explore.py first)")


def time_expr_parts(col: str) -> tuple[str, str]:
    """Return (session_for_derivation, SQL expressions) for IST date/hour/dow.

    utc_instant : derive in IST session  -> DATE(col), HOUR(col), DAYOFWEEK(col)
    wall_clock  : value IS local time    -> derive in UTC session (value used as-is)
    """
    if DECISIONS["time_interpretation"] == "utc_instant":
        return config.IST_OFFSET, (f"DATE(`{col}`)", f"HOUR(`{col}`)", f"DAYOFWEEK(`{col}`)")
    if DECISIONS["time_interpretation"] == "wall_clock":
        return config.UTC_OFFSET, (f"DATE(`{col}`)", f"HOUR(`{col}`)", f"DAYOFWEEK(`{col}`)")
    raise ValueError(f"bad interpretation {DECISIONS['time_interpretation']!r}")


def raw_counts(conn) -> tuple[int, int]:
    n_orders = db.scalar(conn, "SELECT COUNT(*) FROM orders")
    n_details = db.scalar(conn, "SELECT COUNT(*) FROM order_details")
    print(f"  [R0] raw rows: orders={n_orders:,} order_details={n_details:,}")
    return n_orders, n_details


def build_stage(conn) -> None:
    """Narrow projection + dedup rank + cumulative rule flags (single pass).

    Cumulative flags: f_k = f_{k-1} AND predicate_k, so per-rule removals are
    SUM(f_{k-1}) - SUM(f_k) among rn=1 rows.
    """
    tc = DECISIONS["time_column"]
    tz, (d_expr, h_expr, w_expr) = time_expr_parts(tc)
    db.execute(conn, f"SET SESSION time_zone = '{tz}'")

    tb = DECISIONS["test_branches"]
    tb_sql = f"branch_id NOT IN ({','.join(str(int(b)) for b in tb)})" if tb else "1=1"
    status_sql = DECISIONS["status_predicate"]  # UNQUALIFIED columns (orders o / stage)

    db.execute(conn, "DROP TABLE IF EXISTS orders_stage")
    db.execute(conn, """
        CREATE TABLE orders_stage (
          id BIGINT UNSIGNED NOT NULL,
          order_number VARCHAR(255),
          user_id INT,
          branch_id INT,
          order_status INT,
          paid_or_cancel VARCHAR(255),
          is_refunded TINYINT NOT NULL DEFAULT 0,
          grand_total DOUBLE(9,2),
          sub_total DOUBLE(9,2),
          tax_amount DOUBLE(9,2),
          discount_amount DOUBLE(9,2),
          mode_of_transaction VARCHAR(255),
          order_through VARCHAR(255),
          order_date TIMESTAMP NULL,
          payment_timestamp TIMESTAMP NULL,
          created_at TIMESTAMP NULL,
          updated_at TIMESTAMP NULL,
          rn BIGINT NOT NULL,
          ist_date DATE,
          ist_hour TINYINT,
          ist_dow TINYINT,
          f_valid_date TINYINT,
          f_fy TINYINT,
          f_branch TINYINT,
          f_status TINYINT,
          f_amount TINYINT,
          KEY ix_rn (rn), KEY ix_ist (ist_date)
        ) ENGINE=InnoDB
    """)
    n = db.execute(conn, f"""
        INSERT INTO orders_stage
        SELECT id, order_number, user_id, branch_id, order_status,
               paid_or_cancel, is_refunded, grand_total, sub_total,
               tax_amount, discount_amount, mode_of_transaction, order_through,
               order_date, payment_timestamp, created_at, updated_at,
               ROW_NUMBER() OVER (PARTITION BY id ORDER BY updated_at DESC, id DESC) rn,
               {d_expr} ist_date, {h_expr} ist_hour, {w_expr} ist_dow,
               -- R2 valid date (non-null, sane)
               CASE WHEN o.order_date IS NOT NULL AND o.order_date >= '1971-01-02' THEN 1 ELSE 0 END,
               -- R3 in FY window (cumulative; window part folded into R3)
               CASE WHEN o.order_date IS NOT NULL AND o.order_date >= '1971-01-02'
                         AND {d_expr} >= '{config.FY_START}' AND {d_expr} < '{config.FY_END}'
                    THEN 1 ELSE 0 END,
               -- R4 non-test branch (cumulative)
               CASE WHEN o.order_date IS NOT NULL AND o.order_date >= '1971-01-02'
                         AND {d_expr} >= '{config.FY_START}' AND {d_expr} < '{config.FY_END}'
                         AND {tb_sql}
                    THEN 1 ELSE 0 END,
               -- R5 status rule (cumulative) — unqualified predicate, also used in holdout
               CASE WHEN o.order_date IS NOT NULL AND o.order_date >= '1971-01-02'
                         AND {d_expr} >= '{config.FY_START}' AND {d_expr} < '{config.FY_END}'
                         AND {tb_sql} AND ({status_sql})
                    THEN 1 ELSE 0 END,
               -- R6 amount sanity (cumulative): grand_total >= 0
               CASE WHEN o.order_date IS NOT NULL AND o.order_date >= '1971-01-02'
                         AND {d_expr} >= '{config.FY_START}' AND {d_expr} < '{config.FY_END}'
                         AND {tb_sql} AND ({status_sql}) AND o.grand_total >= 0
                    THEN 1 ELSE 0 END
        FROM orders o
    """)
    print(f"  [stage] inserted {n:,} rows into orders_stage (session tz={tz})")


def log_stage_rules(conn) -> int:
    """R0-R7 row counts from stage flags (rn=1 basis)."""
    row = db.fetch_df(conn, """
        SELECT COUNT(*) stage_rows,
               SUM(rn = 1) dedup_rows,
               SUM(rn = 1 AND f_valid_date = 1) r2,
               SUM(rn = 1 AND f_fy = 1)         r3,
               SUM(rn = 1 AND f_branch = 1)     r4,
               SUM(rn = 1 AND f_status = 1)     r5,
               SUM(rn = 1 AND f_amount = 1)     r6
        FROM orders_stage
    """).iloc[0]
    raw = int(db.scalar(conn, "SELECT COUNT(*) FROM orders"))
    stage = int(row["stage_rows"])
    dedup = int(row["dedup_rows"])
    log_rule("R0", "raw orders rows", raw, 0, "baseline")
    log_rule("R1", "dedupe on id (keep max updated_at)", raw, raw - dedup, "dup ids possible: no PK in dump")
    b = dedup
    for rid, name, cnt in [
        ("R2", "valid order_date (non-null, >= 1971-01-02)", int(row["r2"])),
        ("R3", f"in FY window (ist_date in [{config.FY_START}, {config.FY_END}))", int(row["r3"])),
        ("R4", "non-test branch", int(row["r4"])),
        ("R5", "status rule (paid/completed)", int(row["r5"])),
        ("R6", "grand_total >= 0", int(row["r6"])),
    ]:
        log_rule(rid, name, b, b - cnt)
        b = cnt
    return b  # expected orders_clean rows


def create_orders_clean(conn, expected: int) -> None:
    tc = DECISIONS["time_column"]
    tz, (d_expr, h_expr, w_expr) = time_expr_parts(tc)
    db.execute(conn, f"SET SESSION time_zone = '{tz}'")
    db.execute(conn, "DROP TABLE IF EXISTS orders_clean")
    db.execute(conn, f"""
        CREATE TABLE orders_clean (
          id BIGINT UNSIGNED NOT NULL,
          order_number VARCHAR(255),
          user_id INT,
          branch_id INT,
          order_status INT,
          paid_or_cancel VARCHAR(255),
          is_refunded TINYINT NOT NULL DEFAULT 0,
          grand_total DOUBLE(9,2) NOT NULL DEFAULT 0,
          sub_total DOUBLE(9,2) NOT NULL DEFAULT 0,
          tax_amount DOUBLE(9,2) NOT NULL DEFAULT 0,
          discount_amount DOUBLE(9,2) DEFAULT NULL,
          mode_of_transaction VARCHAR(255),
          order_through VARCHAR(255),
          order_date TIMESTAMP NULL,
          ist_date DATE,
          ist_hour TINYINT,
          ist_dow TINYINT,
          payment_timestamp TIMESTAMP NULL,
          PRIMARY KEY (id)
        ) ENGINE=InnoDB
    """)
    n = db.execute(conn, """
        INSERT INTO orders_clean
        SELECT id, order_number, user_id, branch_id, order_status,
               paid_or_cancel, is_refunded, grand_total, sub_total, tax_amount,
               discount_amount, mode_of_transaction, order_through,
               order_date, ist_date, ist_hour, ist_dow, payment_timestamp
        FROM orders_stage
        WHERE rn = 1 AND f_amount = 1
    """)
    if n != expected:
        raise RuntimeError(f"orders_clean rows {n} != expected {expected} (flags miscounted)")
    print(f"  [orders_clean] inserted {n:,} rows (matches flag count)")


def add_orders_indexes(conn) -> None:
    print("  [index] orders_clean (branch_id, ist_date) ...")
    db.execute(conn, "ALTER TABLE orders_clean ADD KEY ix_branch_day (branch_id, ist_date)")
    db.execute(conn, "ALTER TABLE orders_clean ADD KEY ix_user (user_id)")
    db.execute(conn, "ALTER TABLE orders_clean ADD KEY ix_day (ist_date)")


def build_order_details_clean(conn) -> None:
    n_raw = int(db.scalar(conn, "SELECT COUNT(*) FROM order_details"))
    # true orphans: order_id never present in RAW orders
    n_orphan = int(db.scalar(conn, """
        SELECT COUNT(*) FROM order_details d
        LEFT JOIN orders o ON o.id = d.order_id
        WHERE o.id IS NULL
    """))
    db.execute(conn, "DROP TABLE IF EXISTS order_details_clean")
    db.execute(conn, """
        CREATE TABLE order_details_clean (
          id BIGINT UNSIGNED NOT NULL,
          order_id INT NOT NULL,
          dish_id INT NOT NULL,
          dish_name VARCHAR(255) NOT NULL,
          order_quantity INT NOT NULL,
          order_status INT,
          dish_price DOUBLE(9,2) NOT NULL DEFAULT 0,
          dish_cal_price DOUBLE(9,2) DEFAULT NULL,
          dish_discount_amount DOUBLE(9,2) DEFAULT NULL,
          created_at TIMESTAMP NULL,
          PRIMARY KEY (id),
          KEY ix_order (order_id),
          KEY ix_dish (dish_id)
        ) ENGINE=InnoDB
    """)
    # dedup + join to clean orders in one statement
    n = db.execute(conn, """
        INSERT INTO order_details_clean
        SELECT d.id, d.order_id, d.dish_id, d.dish_name, d.order_quantity,
               d.order_status, d.dish_price, d.dish_cal_price,
               d.dish_discount_amount, d.created_at
        FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY updated_at DESC, id DESC) rn
          FROM order_details
        ) d
        JOIN orders_clean oc ON oc.id = d.order_id
        WHERE d.rn = 1
    """)
    n_distinct_detail_ids = int(db.scalar(conn, "SELECT COUNT(DISTINCT id) FROM order_details"))
    log_rule("R0d", "raw order_details rows", n_raw, 0, "baseline")
    log_rule("R1d", "dedupe details on id", n_raw, n_raw - n_distinct_detail_ids, "dup ids possible")
    log_rule("R7d", "orphan detail rows (order_id not in raw orders)", n_distinct_detail_ids, n_orphan,
             "left join to raw orders")
    log_rule("R8d", "detail rows outside clean scope (order not in orders_clean)",
             n_distinct_detail_ids - n_orphan, (n_distinct_detail_ids - n_orphan) - n,
             "FY/test/status filtered orders")
    print(f"  [order_details_clean] inserted {n:,} rows")


def build_holdout(conn) -> None:
    """Keep 2025-04-01 rows (out of FY) for the holdout check.

    Raw orders is dropped afterwards, so capture the holdout day first.
    Data coverage note: raw orders end 2025-04-01 17:11 IST (partial day).
    """
    tz, (d_expr, _, _) = time_expr_parts(DECISIONS["time_column"])
    db.execute(conn, f"SET SESSION time_zone = '{tz}'")
    tb = DECISIONS["test_branches"]
    tb_sql = f"branch_id NOT IN ({','.join(str(int(b)) for b in tb)})" if tb else "1=1"
    status_sql = DECISIONS["status_predicate"]  # unqualified: works on stage too
    db.execute(conn, "DROP TABLE IF EXISTS orders_holdout")
    db.execute(conn, f"""
        CREATE TABLE orders_holdout ENGINE=InnoDB AS
        SELECT id, branch_id, user_id, grand_total, order_date, ist_date, rn
        FROM orders_stage
        WHERE ist_date = '2025-04-01' AND rn = 1
          AND {tb_sql} AND ({status_sql}) AND grand_total >= 0
    """)
    n = int(db.scalar(conn, "SELECT COUNT(*) FROM orders_holdout"))
    print(f"  [holdout] orders_holdout rows (all branches, 2025-04-01) = {n:,}")


def drop_raw_tables(conn) -> None:
    """A9: raw dropped after clean tables verified; source .sql remains."""
    for t in ("orders_stage", "orders", "order_details"):
        db.execute(conn, f"DROP TABLE IF EXISTS `{t}`")
        print(f"  [drop] {t} dropped (source of truth: split/*.sql)")


def write_log() -> None:
    path = config.OUTPUTS / "cleaning_log.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rule", "description", "rows_before", "rows_removed", "rows_after", "note"])
        w.writerows(RULES_LOG)
    print(f"  [log] {path}")


def main() -> None:
    assert_decisions()
    config.OUTPUTS.mkdir(exist_ok=True)
    conn = db.connect(time_zone=config.IST_OFFSET)
    try:
        print("[clean] raw counts")
        raw_counts(conn)
        print("[clean] stage build (narrow + dedup + flags)")
        build_stage(conn)
        print("[clean] rule counts")
        expected = log_stage_rules(conn)
        print("[clean] orders_clean")
        create_orders_clean(conn, expected)
        add_orders_indexes(conn)
        print("[clean] order_details_clean")
        build_order_details_clean(conn)
        print("[clean] final verification counts")
        v = db.scalar(conn, "SELECT COUNT(*) FROM orders_clean")
        d = db.scalar(conn, "SELECT COUNT(*) FROM order_details_clean")
        print(f"  orders_clean={int(v):,} order_details_clean={int(d):,}")
        print("[clean] holdout capture (2025-04-01, before raw drop)")
        build_holdout(conn)
        print("[clean] dropping raw tables (A9)")
        drop_raw_tables(conn)
        write_log()
        print("[clean] done")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
