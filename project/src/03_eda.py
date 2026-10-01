"""Stage 3 — EDA on cleaned tables. Aggregates only (no raw rows).

Writes tables to outputs/*.csv and charts to outputs/charts/*.png.
Auto-picks the forecast branch (largest FY volume among branches covering all
12 FY months; test branches already excluded in cleaning) and records it in
outputs/forecast_branch.txt for stage 4.

Run: venv\\Scripts\\python.exe src\\03_eda.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

import config
import db

CHARTS = config.OUTPUTS / "charts"
BRANCH_FILE = config.OUTPUTS / "forecast_branch.txt"

DOW_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]  # DAYOFWEEK: 1=Sun


def ensure_dirs() -> None:
    config.OUTPUTS.mkdir(exist_ok=True)
    CHARTS.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def daily_series(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """FY daily orders/revenue: all branches + per branch (small: <=18x365)."""
    all_df = db.fetch_df(conn, """
        SELECT ist_date, COUNT(*) orders, ROUND(SUM(grand_total), 2) revenue,
               COUNT(DISTINCT user_id) customers
        FROM orders_clean
        GROUP BY ist_date ORDER BY ist_date
    """)
    all_df.to_csv(config.OUTPUTS / "daily_orders_all.csv", index=False)

    br_df = db.fetch_df(conn, """
        SELECT branch_id, ist_date, COUNT(*) orders, ROUND(SUM(grand_total), 2) revenue
        FROM orders_clean GROUP BY branch_id, ist_date
    """)
    br_df.to_csv(config.OUTPUTS / "daily_orders_by_branch.csv", index=False)
    print(f"[eda] daily series: all={len(all_df)} rows, by_branch={len(br_df)} rows")
    return all_df, br_df


def branch_summary(conn) -> pd.DataFrame:
    df = db.fetch_df(conn, """
        SELECT o.branch_id, b.name, COUNT(*) orders,
               ROUND(SUM(o.grand_total), 2) revenue,
               ROUND(AVG(o.grand_total), 2) aov,
               COUNT(DISTINCT o.ist_date) active_days,
               MIN(o.ist_date) first_day, MAX(o.ist_date) last_day,
               COUNT(DISTINCT DATE_FORMAT(o.ist_date, '%Y-%m')) months_covered
        FROM orders_clean o LEFT JOIN branches b ON b.id = o.branch_id
        GROUP BY o.branch_id, b.name ORDER BY orders DESC
    """)
    df.to_csv(config.OUTPUTS / "branch_summary.csv", index=False)
    for r in df.itertuples():
        print(f"[eda] branch {r.branch_id:>2} {str(r.name)[:28]:28s} orders={r.orders:>8,} "
              f"rev={r.revenue:>12,.0f} days={r.active_days:>3} months={r.months_covered:>2}")
    return df


def pick_forecast_branch(df: pd.DataFrame) -> tuple[int, str]:
    """Largest FY orders among branches covering all 12 FY months."""
    eligible = df[df["months_covered"] == 12]
    pool = eligible if len(eligible) else df
    top = pool.iloc[0]
    note = "" if len(eligible) else " (no branch covered 12/12 months; picked by volume)"
    text = (f"{int(top.branch_id)}\t{top['name']}\t{int(top.orders)}{note}\n")
    BRANCH_FILE.write_text(
        "branch_id\tname\torders\tnote\n" + text, encoding="utf-8")
    print(f"[pick] forecast branch -> id={int(top.branch_id)} name={top['name']} "
          f"orders={int(top.orders):,}{note}")
    return int(top.branch_id), str(top["name"])


def hourly_profile(conn, bid: int) -> pd.DataFrame:
    df = db.fetch_df(conn, """
        SELECT ist_hour, COUNT(*) orders FROM orders_clean
        WHERE branch_id = %s GROUP BY ist_hour ORDER BY ist_hour
    """, (bid,))
    df.to_csv(config.OUTPUTS / "hourly_profile_branch.csv", index=False)
    peak = int(df.loc[df["orders"].idxmax(), "ist_hour"])
    print(f"[eda] hourly peak for branch {bid}: {peak:02d}h IST")
    return df


def dow_profile(conn, bid: int) -> pd.DataFrame:
    """DAYOFWEEK: 1=Sun..7=Sat. Avg per occurrence to expose closures."""
    df = db.fetch_df(conn, """
        SELECT ist_dow, SUM(day_orders) orders,
               ROUND(AVG(day_orders), 1) avg_per_active_day
        FROM (
          SELECT ist_dow, ist_date, COUNT(*) day_orders
          FROM orders_clean WHERE branch_id = %s GROUP BY ist_dow, ist_date
        ) t GROUP BY ist_dow ORDER BY ist_dow
    """, (bid,))
    df["dow"] = df["ist_dow"].map(lambda x: DOW_LABELS[int(x) - 1])
    df.to_csv(config.OUTPUTS / "dow_profile_branch.csv", index=False)
    print("[eda] dow: " + ", ".join(f"{r.dow}={r.orders:,}" for r in df.itertuples()))
    return df


def monthly_trend(conn) -> pd.DataFrame:
    df = db.fetch_df(conn, """
        SELECT DATE_FORMAT(ist_date, '%Y-%m') month, COUNT(*) orders,
               ROUND(SUM(grand_total), 2) revenue,
               COUNT(DISTINCT ist_date) days
        FROM orders_clean GROUP BY month ORDER BY month
    """)
    df["orders_per_day"] = (df["orders"] / df["days"]).round(1)
    df.to_csv(config.OUTPUTS / "monthly_trend.csv", index=False)
    print(f"[eda] monthly trend rows={len(df)}")
    return df


def product_mix(conn, bid: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    top = db.fetch_df(conn, """
        SELECT d.dish_id, d.dish_name, SUM(d.order_quantity) qty,
               COUNT(DISTINCT d.order_id) orders_having,
               ROUND(SUM(COALESCE(d.dish_cal_price, 0) - COALESCE(d.dish_discount_amount, 0)), 2) revenue
        FROM order_details_clean d JOIN orders_clean o ON o.id = d.order_id
        WHERE o.branch_id = %s
        GROUP BY d.dish_id, d.dish_name ORDER BY qty DESC LIMIT 30
    """, (bid,))
    top.to_csv(config.OUTPUTS / "top_dishes_branch.csv", index=False)

    # Fractional attribution: 469 dishes are mapped to >1 category, so plain
    # joins would double-count (4.84M vs true 3.23M qty). Each detail row
    # contributes qty / n_categories(dish); unmapped dishes keep full qty
    # under NULL category. Column sums then equal the true branch total.
    cat = db.fetch_df(conn, """
        SELECT c.category_name AS category,
               ROUND(SUM(d.order_quantity / COALESCE(chn.n_cat, 1)), 1) qty,
               ROUND(SUM((COALESCE(d.dish_cal_price,0) - COALESCE(d.dish_discount_amount,0))
                         / COALESCE(chn.n_cat, 1)), 2) revenue
        FROM order_details_clean d
        JOIN orders_clean o ON o.id = d.order_id
        LEFT JOIN (SELECT dish_id, COUNT(*) n_cat
                   FROM category_has_dishes GROUP BY dish_id) chn
          ON chn.dish_id = d.dish_id
        LEFT JOIN category_has_dishes ch ON ch.dish_id = d.dish_id
        LEFT JOIN categories c ON c.id = ch.category_id
        WHERE o.branch_id = %s
        GROUP BY c.category_name ORDER BY qty DESC
    """, (bid,))
    cat.to_csv(config.OUTPUTS / "category_mix_branch.csv", index=False)
    print(f"[eda] top dish: {top.iloc[0]['dish_name']} qty={int(top.iloc[0]['qty']):,}; "
          f"categories={len(cat)}")
    return top, cat


def channel_payment_mix(conn, bid: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ch = db.fetch_df(conn, """
        SELECT COALESCE(NULLIF(order_through, ''), '(null)') channel,
               COUNT(*) orders, ROUND(SUM(grand_total), 2) revenue
        FROM orders_clean WHERE branch_id = %s GROUP BY channel ORDER BY orders DESC
    """, (bid,))
    ch.to_csv(config.OUTPUTS / "channel_mix_branch.csv", index=False)
    pm = db.fetch_df(conn, """
        SELECT COALESCE(NULLIF(mode_of_transaction, ''), '(null)') mode,
               COUNT(*) orders, ROUND(SUM(grand_total), 2) revenue
        FROM orders_clean WHERE branch_id = %s GROUP BY mode ORDER BY orders DESC
    """, (bid,))
    pm.to_csv(config.OUTPUTS / "payment_mix_branch.csv", index=False)
    print("[eda] channels: " + ", ".join(f"{r.channel}={r.orders:,}" for r in ch.itertuples()))
    print("[eda] payments: " + ", ".join(f"{r.mode}={r.orders:,}" for r in pm.itertuples()))
    return ch, pm


def customer_stats(conn, bid: int) -> pd.DataFrame:
    rows = {}
    for label, where in (("all_branches", ""), (f"branch_{bid}", f"WHERE branch_id = {int(bid)}")):
        r = db.fetch_df(conn, f"""
            SELECT COUNT(DISTINCT user_id) users, SUM(user_orders) orders,
              SUM(user_orders >= 2) repeat_users, SUM(user_orders >= 5) loyal_users
            FROM (SELECT user_id, COUNT(*) user_orders FROM orders_clean {where}
                  GROUP BY user_id) t
        """).iloc[0]
        rows[label] = r
    df = pd.DataFrame(rows).T
    df["orders_per_user"] = (df["orders"] / df["users"]).round(2)
    df["repeat_share_pct"] = (100 * df["repeat_users"] / df["users"]).round(1)
    df.to_csv(config.OUTPUTS / "customer_stats.csv")
    print(f"[eda] customers: {rows}")
    return df


def footfalls_crosscheck(conn, bid: int) -> pd.DataFrame | None:
    """Optional: daily covers vs orders correlation for chosen branch."""
    n = int(db.scalar(conn, "SELECT COUNT(*) FROM footfalls WHERE branch_id = %s", (bid,)))
    if n == 0:
        print(f"[eda] footfalls: no rows for branch {bid} (skipped)")
        return None
    df = db.fetch_df(conn, """
        SELECT f.od_date, SUM(CAST(f.covers AS UNSIGNED)) covers, o.orders
        FROM (SELECT od_date, SUM(CAST(covers AS UNSIGNED)) covers FROM footfalls
              WHERE branch_id = %s GROUP BY od_date) f
        JOIN (SELECT ist_date, COUNT(*) orders FROM orders_clean
              WHERE branch_id = %s GROUP BY ist_date) o
          ON o.ist_date = f.od_date
        GROUP BY f.od_date, o.orders ORDER BY f.od_date
    """, (bid, bid))
    df.to_csv(config.OUTPUTS / "footfalls_vs_orders.csv", index=False)
    if len(df) > 10:
        corr = df["covers"].corr(df["orders"])
        print(f"[eda] footfalls crosscheck: {len(df)} days, corr(covers, orders)={corr:.2f}")
    return df


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------
def _save(fig, name: str) -> None:
    p = CHARTS / name
    fig.savefig(p, dpi=120, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"[chart] {p.name}")


def _month_axis(ax) -> None:
    """Readable x-axis for daily series: one tick per month, no 365-label smear."""
    import matplotlib.dates as mdates

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_xlim(ax.get_xlim())  # keep limits after locator change


def charts_daily(all_df: pd.DataFrame, branch_daily: pd.DataFrame, bid: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # charts-only mode reads CSV strings; MonthLocator needs datetimes
    all_df = all_df.copy()
    branch_daily = branch_daily.copy()
    all_df["ist_date"] = pd.to_datetime(all_df["ist_date"])
    branch_daily["ist_date"] = pd.to_datetime(branch_daily["ist_date"])

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(all_df["ist_date"], all_df["orders"], lw=0.8, label="all branches")
    ax.plot(branch_daily["ist_date"], branch_daily["orders"], lw=1.0,
            label=f"branch {bid}")
    ax.set_title("Daily orders FY 2024-25 (IST dates)")
    ax.set_ylabel("orders / day"); ax.legend(); ax.grid(alpha=0.3)
    _month_axis(ax)
    _save(fig, "daily_orders.png")

    fig, ax = plt.subplots(figsize=(14, 4))
    s = all_df.set_index("ist_date")["orders"].rolling(7).mean()
    ax.plot(s.index, s.values, lw=1.5, color="tab:orange", label="7-day MA (all)")
    sb = branch_daily.set_index("ist_date")["orders"].rolling(7).mean()
    ax.plot(sb.index, sb.values, lw=1.5, color="tab:blue", label=f"7-day MA (branch {bid})")
    ax.set_title("7-day moving average of daily orders (IST dates)")
    ax.legend(); ax.grid(alpha=0.3)
    _month_axis(ax)
    _save(fig, "daily_orders_ma7.png")


def charts_profile(hourly: pd.DataFrame, dow: pd.DataFrame, bid: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(hourly["ist_hour"], hourly["orders"], color="tab:blue")
    ax.axvspan(11.5, 14.5, color="tab:red", alpha=0.12, label="lunch 12-14")
    ax.set_xticks(range(0, 24))
    ax.set_title(f"Hourly order profile, IST (branch {bid})")
    ax.set_xlabel("hour (IST)"); ax.legend(); ax.grid(axis="y", alpha=0.3)
    _save(fig, "hourly_profile.png")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(dow["dow"], dow["orders"], color="tab:green")
    ax.set_title(f"Orders by weekday, IST dates (branch {bid})")
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "dow_profile.png")


def charts_branches(bs: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    lbl = bs["name"].astype(str).str.slice(0, 24)
    ax.barh(lbl[::-1], bs["orders"][::-1], color="tab:purple")
    ax.set_title("FY 2024-25 orders by branch")
    ax.grid(axis="x", alpha=0.3)
    _save(fig, "branch_orders.png")


def charts_products(top: pd.DataFrame, cat: pd.DataFrame, bname: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = top.sort_values("qty", ascending=False).head(15).copy()
    t = t[::-1]  # largest at the top of the barh
    fig, ax = plt.subplots(figsize=(9, 6))
    # numeric y positions: duplicate dish names would collide on a categorical axis
    y = range(len(t))
    ax.barh(list(y), t["qty"], color="tab:cyan")
    ax.set_yticks(list(y), t["dish_name"].astype(str).str.slice(0, 38))
    ax.set_title(f"Top 15 dishes by quantity — {bname}")
    ax.grid(axis="x", alpha=0.3)
    _save(fig, "top_dishes.png")

    if len(cat):
        c = cat.sort_values("qty", ascending=False).head(10).copy()[::-1]
        c["category"] = c["category"].fillna("(no category)").astype(str)
        fig, ax = plt.subplots(figsize=(9, 5))
        y = range(len(c))
        ax.barh(list(y), c["qty"], color="tab:olive")
        ax.set_yticks(list(y), c["category"].str.slice(0, 38))
        ax.set_title(f"Quantity by category — {bname} (fractional attribution)")
        ax.grid(axis="x", alpha=0.3)
        _save(fig, "category_mix.png")


def charts_mix(ch: pd.DataFrame, pm: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    axes[0].bar(ch["channel"].astype(str), ch["orders"], color="tab:blue")
    axes[0].set_title("Orders by channel")
    axes[1].bar(pm["mode"].astype(str), pm["orders"], color="tab:orange")
    axes[1].set_title("Orders by payment mode")
    for ax in axes:
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=30)
    _save(fig, "channel_payment_mix.png")


def charts_monthly(mt: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(mt["month"], mt["orders_per_day"], color="tab:red")
    ax.set_title("Orders per day by month (all branches)")
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "monthly_orders_per_day.png")


def charts_only() -> None:
    """Re-render all charts from saved CSVs (no SQL; for crash recovery)."""
    all_df = pd.read_csv(config.OUTPUTS / "daily_orders_all.csv")
    br_df = pd.read_csv(config.OUTPUTS / "daily_orders_by_branch.csv")
    bs = pd.read_csv(config.OUTPUTS / "branch_summary.csv")
    parts = BRANCH_FILE.read_text(encoding="utf-8").strip().splitlines()[1].split("\t")
    bid, bname = int(parts[0]), parts[1]
    bd = br_df[br_df["branch_id"] == bid].copy()
    hourly = pd.read_csv(config.OUTPUTS / "hourly_profile_branch.csv")
    dow = pd.read_csv(config.OUTPUTS / "dow_profile_branch.csv")
    mt = pd.read_csv(config.OUTPUTS / "monthly_trend.csv")
    top = pd.read_csv(config.OUTPUTS / "top_dishes_branch.csv")
    cat = pd.read_csv(config.OUTPUTS / "category_mix_branch.csv")
    ch = pd.read_csv(config.OUTPUTS / "channel_mix_branch.csv")
    pm = pd.read_csv(config.OUTPUTS / "payment_mix_branch.csv")
    charts_daily(all_df, bd, bid)
    charts_profile(hourly, dow, bid)
    charts_branches(bs)
    charts_products(top, cat, bname)
    charts_mix(ch, pm)
    charts_monthly(mt)
    print(f"[eda] charts-only done — forecast branch {bid} ({bname})")


def main() -> None:
    ensure_dirs()
    if "--charts-only" in sys.argv:
        charts_only()
        return
    conn = db.connect(time_zone=config.IST_OFFSET)  # ist_* are precomputed anyway
    try:
        all_df, br_df = daily_series(conn)
        bs = branch_summary(conn)
        bid, bname = pick_forecast_branch(bs)
        bd = br_df[br_df["branch_id"] == bid].copy()
        hourly = hourly_profile(conn, bid)
        dow = dow_profile(conn, bid)
        mt = monthly_trend(conn)
        top, cat = product_mix(conn, bid)
        ch, pm = channel_payment_mix(conn, bid)
        customer_stats(conn, bid)
        footfalls_crosscheck(conn, bid)
        # charts
        charts_daily(all_df, bd, bid)
        charts_profile(hourly, dow, bid)
        charts_branches(bs)
        charts_products(top, cat, bname)
        charts_mix(ch, pm)
        charts_monthly(mt)
        print(f"[eda] done — forecast branch {bid} ({bname})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
