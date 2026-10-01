"""Stage 6 — timezone evidence chart.

Reads outputs/tz_comparison.csv (written by 01_explore.py) and renders
outputs/charts/tz_comparison.png: the raw hourly histogram of the dump's
timestamp columns under both candidate interpretations —

  +00:00 session (value as stored)  -> peak 13:00 = local lunch  -> CHOSEN (A1/A4)
  +05:30 session (value + 5h30m)    -> peak 22:00                -> rejected

All three compared columns (order_date, IST_timezone, created_at) are
identical, so only order_date is drawn.

Run: venv\\Scripts\\python.exe src\\06_tz_chart.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

import config

CHARTS = config.OUTPUTS / "charts"


def main() -> None:
    CHARTS.mkdir(parents=True, exist_ok=True)
    tz = pd.read_csv(config.OUTPUTS / "tz_comparison.csv")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.5))
    styles = {
        "+00:00": dict(color="tab:blue", lw=2.2,
                       label="as stored, session +00:00 — CHOSEN (A1/A4): peak 13:00 = IST lunch"),
        "+05:30": dict(color="tab:red", lw=1.6, ls="--",
                       label="value + 5h30m, session +05:30 — rejected: peak 22:00"),
    }
    for tz_name, g in tz[tz["column"] == "order_date"].groupby("display_tz"):
        g = g.sort_values("hour_of_day")
        st = styles.get(tz_name, dict(label=tz_name))
        ax.plot(g["hour_of_day"], g["n"], **st)

    ax.set_title("Raw dump timestamps by hour of day — order_date "
                 "(order_date / IST_timezone / created_at are identical, "
                 "5,961,005 rows)")
    ax.set_xlabel("hour of day (24h) as rendered by the MySQL session named in the legend")
    ax.set_ylabel("orders")
    ax.set_xticks(range(0, 24))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = CHARTS / "tz_comparison.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[tz] written {out}")


if __name__ == "__main__":
    main()
