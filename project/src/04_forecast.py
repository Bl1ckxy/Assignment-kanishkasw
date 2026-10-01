"""Stage 4 — 7-day daily-order forecast for ONE branch (picked in stage 3).

Models: naive, seasonal-naive (lag 7), Holt-Winters (additive
trend + additive weekly seasonality), weekday OLS (linear trend + weekday
dummies). Baseline to beat: seasonal-naive. Rolling-origin backtest,
7-day horizon, 10 folds. No Prophet, no deep learning.

Outputs:
  outputs/backtest_predictions.csv  model/fold/date/actual/pred
  outputs/backtest_metrics.csv      per-fold MAE, RMSE, wMAPE, sMAPE
  outputs/backtest_summary.csv      pooled + mean-fold metrics, model pick
  outputs/forecast_7d.csv           final 7-day forecast (+80% band)
  outputs/forecast_pick.txt         chosen model and why
  outputs/charts/forecast_*.png

Run: venv\\Scripts\\python.exe src\\04_forecast.py
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import config
import db

warnings.filterwarnings("ignore", category=FutureWarning)

MODELS = ["naive", "seasonal_naive", "holt_winters", "weekday_ols"]
FOLDS = 10          # rolling-origin folds, each 7 days
HORIZON = 7
PARSIMONY_TOL = 0.02  # within 2% of seasonal-naive -> prefer the simpler model


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_branch() -> tuple[int, str]:
    lines = (config.OUTPUTS / "forecast_branch.txt").read_text(encoding="utf-8").strip().splitlines()
    parts = lines[1].split("\t")
    return int(parts[0]), parts[1]


def load_series(conn, bid: int) -> pd.Series:
    """FY daily order counts, complete calendar, missing days -> 0."""
    df = db.fetch_df(conn, """
        SELECT ist_date, COUNT(*) AS orders FROM orders_clean
        WHERE branch_id = %s GROUP BY ist_date
    """, (bid,))
    idx = pd.date_range(config.FY_START, config.FY_END, freq="D", inclusive="left")
    s = pd.Series(df["orders"].values, index=pd.to_datetime(df["ist_date"])).reindex(idx, fill_value=0)
    s.index.name = "date"
    assert len(s) == 365, f"FY series should be 365 days, got {len(s)}"
    zero_days = int((s == 0).sum())
    print(f"[fc] series: {len(s)} days, {int(s.sum()):,} orders, {zero_days} zero-order days")
    return s.astype(float)


def holdout_actual(conn, bid: int) -> int | None:
    row = db.fetch_df(conn, """
        SELECT COUNT(*) n FROM orders_holdout WHERE branch_id = %s
    """, (bid,)).iloc[0]
    return int(row["n"])


# ---------------------------------------------------------------------------
# models (each: train array -> horizon forecast)
# ---------------------------------------------------------------------------
def m_naive(train: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(train[-1], h)


def m_seasonal_naive(train: np.ndarray, h: int) -> np.ndarray:
    return np.array([train[-7 + (i % 7)] for i in range(h)])


def m_holt_winters(train: np.ndarray, h: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    model = ExponentialSmoothing(train, trend="add", seasonal="add",
                                 seasonal_periods=7, initialization_method="estimated")
    fitted = model.fit(optimized=True)
    return np.asarray(fitted.forecast(h), dtype=float)


def m_weekday_ols(train: np.ndarray, h: int, dates: pd.DatetimeIndex | None = None,
                  start_t: int = 0) -> np.ndarray:
    """Linear trend + weekday dummies (dow dummies from positions in train)."""
    n = len(train)
    t = np.arange(n, dtype=float)
    # weekday of each train position: caller supplies via `dates` for accuracy
    if dates is None:
        dates = pd.date_range("2024-04-01", periods=n, freq="D")
    dow = dates.dayofweek.to_numpy()  # 0=Mon..6=Sun
    X = np.column_stack([np.ones(n), t] + [(dow == k).astype(float) for k in range(1, 7)])
    beta, *_ = np.linalg.lstsq(X, train, rcond=None)
    # forecast positions
    t_new = np.arange(n, n + h, dtype=float)
    dow_new = dates[-1] + pd.to_timedelta(np.arange(1, h + 1), unit="D")
    down = dow_new.dayofweek.to_numpy()
    Xn = np.column_stack([np.ones(h), t_new] + [(down == k).astype(float) for k in range(1, 7)])
    return Xn @ beta


PREDICTORS = {
    "naive": lambda train, h, dates, start_t: m_naive(train, h),
    "seasonal_naive": lambda train, h, dates, start_t: m_seasonal_naive(train, h),
    "holt_winters": lambda train, h, dates, start_t: m_holt_winters(train, h),
    "weekday_ols": lambda train, h, dates, start_t: m_weekday_ols(train, h, dates),
}


def clip(pred: np.ndarray) -> np.ndarray:
    """Counts cannot be negative."""
    return np.maximum(pred, 0.0)


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------
def backtest(y: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rolling origin: fold k trains on y[:-7k], tests next 7 days."""
    n = len(y)
    rows = []
    for k in range(1, FOLDS + 1):
        cut = n - HORIZON * k
        train, test = y.iloc[:cut], y.iloc[cut:cut + HORIZON]
        dates_train, dates_test = y.index[:cut], y.index[cut:cut + HORIZON]
        for model in MODELS:
            try:
                pred = clip(PREDICTORS[model](train.to_numpy(), HORIZON, dates_train, cut))
            except Exception as exc:  # model failure -> NaN, counted as worst
                print(f"[fc] WARN {model} fold {k}: {exc}")
                pred = np.full(HORIZON, np.nan)
            for i in range(HORIZON):
                rows.append((model, k, dates_test[i].date(), float(test.iloc[i]), float(pred[i])))
    bt = pd.DataFrame(rows, columns=["model", "fold", "date", "actual", "pred"])
    bt.to_csv(config.OUTPUTS / "backtest_predictions.csv", index=False)

    mrows = []
    for (model, fold), g in bt.groupby(["model", "fold"]):
        a, p = g["actual"].to_numpy(), g["pred"].to_numpy()
        ok = ~np.isnan(p)
        a, p = a[ok], p[ok]
        err = a - p
        mrows.append({
            "model": model, "fold": fold,
            "mae": np.mean(np.abs(err)) if len(err) else np.nan,
            "rmse": np.sqrt(np.mean(err ** 2)) if len(err) else np.nan,
            "wmape": np.sum(np.abs(err)) / np.sum(np.abs(a)) if np.sum(np.abs(a)) else np.nan,
            "smape": np.mean(2 * np.abs(err) / (np.abs(a) + np.abs(p) + 1e-9)),
        })
    metrics = pd.DataFrame(mrows)
    metrics.to_csv(config.OUTPUTS / "backtest_metrics.csv", index=False)
    return bt, metrics


def summarize(metrics: pd.DataFrame, bt: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model, g in metrics.groupby("model"):
        sub = bt[bt["model"] == model]
        a, p = sub["actual"].to_numpy(), sub["pred"].to_numpy()
        ok = ~np.isnan(p)
        a, p = a[ok], p[ok]
        err = a - p
        rows.append({
            "model": model,
            "mean_fold_wmape": g["wmape"].mean(),
            "pooled_wmape": np.sum(np.abs(err)) / np.sum(np.abs(a)),
            "pooled_mae": np.mean(np.abs(err)),
            "pooled_rmse": np.sqrt(np.mean(err ** 2)),
            "mean_fold_smape": g["smape"].mean(),
        })
    s = pd.DataFrame(rows).sort_values("pooled_wmape")
    s.to_csv(config.OUTPUTS / "backtest_summary.csv", index=False)
    return s


def pick_model(summary: pd.DataFrame) -> tuple[str, str]:
    """Best pooled wMAPE; within 2% of seasonal-naive -> keep the simpler SN."""
    best = summary.iloc[0]["model"]
    sn = summary[summary["model"] == "seasonal_naive"].iloc[0]["pooled_wmape"]
    best_w = summary.iloc[0]["pooled_wmape"]
    if best != "seasonal_naive" and best_w > sn * (1 - PARSIMONY_TOL):
        reason = (f"pooled wMAPE {best_w:.3f} vs seasonal-naive {sn:.3f} within "
                  f"{PARSIMONY_TOL:.0%} -> parsimony favors seasonal_naive")
        pick = "seasonal_naive"
    else:
        reason = f"lowest pooled wMAPE {best_w:.3f} (seasonal-naive {sn:.3f})"
        pick = best
    (config.OUTPUTS / "forecast_pick.txt").write_text(
        f"model={pick}\nreason={reason}\n", encoding="utf-8")
    print(f"[fc] model pick -> {pick}: {reason}")
    return pick, reason


# ---------------------------------------------------------------------------
# final fit + interval + outputs
# ---------------------------------------------------------------------------
def final_forecast(y: pd.Series, model: str) -> np.ndarray:
    return clip(PREDICTORS[model](y.to_numpy(), HORIZON, y.index, len(y)))


def prediction_band(bt: pd.DataFrame, model: str) -> tuple[float, float]:
    """80% band from pooled backtest residuals (actual - pred), pooled leads."""
    sub = bt[bt["model"] == model]
    res = (sub["actual"] - sub["pred"]).dropna().to_numpy()
    return float(np.quantile(res, 0.10)), float(np.quantile(res, 0.90))


def write_forecast(y: pd.Series, model: str, pred: np.ndarray,
                   lo_err: float, hi_err: float, holdout: int | None) -> pd.DataFrame:
    dates = pd.date_range(config.FY_END, periods=HORIZON, freq="D")
    rows = []
    for i, d in enumerate(dates):
        lo = max(0.0, pred[i] + lo_err)
        hi = max(0.0, pred[i] + hi_err)
        rows.append({
            "date": d.date(),
            "dow": d.day_name()[:3],
            "model": model,
            "forecast_orders": round(float(pred[i]), 1),
            "lo80": round(lo, 1),
            "hi80": round(hi, 1),
            "actual": holdout if (i == 0 and holdout is not None) else "",
        })
    df = pd.DataFrame(rows)
    df.to_csv(config.OUTPUTS / "forecast_7d.csv", index=False)
    print(f"[fc] forecast written: total {df['forecast_orders'].sum():.0f} orders over 7 days")
    if holdout is not None:
        err = pred[0] - holdout
        print(f"[fc] holdout 2025-04-01 actual={holdout}, "
              f"pred day1={pred[0]:.1f}, err={err:+.1f} (actual is a partial day: data ends 17:11 IST)")
    return df


def charts(y: pd.Series, bt: pd.DataFrame, model: str, pred: np.ndarray,
           lo_err: float, hi_err: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dates_f = pd.date_range(config.FY_END, periods=HORIZON, freq="D")
    lo = np.maximum(0, pred + lo_err)
    hi = np.maximum(0, pred + hi_err)

    # full year + forecast
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(y.index, y.values, lw=0.7, color="tab:blue", label="actual daily orders")
    ax.plot(dates_f, pred, "o-", color="tab:red", label=f"forecast ({model})")
    ax.fill_between(dates_f, lo, hi, color="tab:red", alpha=0.15, label="80% band")
    ax.set_title(f"Daily orders — FY 2024-25 actual + 7-day forecast (branch {load_branch()[0]})")
    ax.legend(); ax.grid(alpha=0.3)
    fig.savefig(config.OUTPUTS / "charts" / "forecast_full.png", dpi=120, bbox_inches="tight")
    plt.close(fig)

    # zoom last 6 weeks + backtest preds of chosen model
    tail = y.iloc[-42:]
    sub = bt[(bt["model"] == model) & (pd.to_datetime(bt["date"]) >= tail.index[0])]
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(tail.index, tail.values, "o-", ms=3, color="tab:blue", label="actual")
    if len(sub):
        ax.plot(pd.to_datetime(sub["date"]), sub["pred"], "s--", ms=3, color="tab:orange",
                label=f"backtest preds ({model})")
    ax.plot(dates_f, pred, "o-", color="tab:red", label="forecast")
    ax.fill_between(dates_f, lo, hi, color="tab:red", alpha=0.15)
    ax.set_title("Zoom: last 6 weeks, backtest fit, and 7-day forecast")
    ax.legend(); ax.grid(alpha=0.3)
    fig.savefig(config.OUTPUTS / "charts" / "forecast_zoom.png", dpi=120, bbox_inches="tight")
    plt.close(fig)

    # metrics bar
    summ = pd.read_csv(config.OUTPUTS / "backtest_summary.csv")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(summ["model"], summ["pooled_wmape"], color="tab:green")
    ax.set_title("Backtest pooled wMAPE (lower is better)")
    ax.grid(axis="y", alpha=0.3)
    fig.savefig(config.OUTPUTS / "charts" / "backtest_wmape.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("[fc] charts written (forecast_full, forecast_zoom, backtest_wmape)")


def main() -> None:
    (config.OUTPUTS / "charts").mkdir(parents=True, exist_ok=True)
    conn = db.connect(time_zone=config.IST_OFFSET)
    try:
        bid, bname = load_branch()
        print(f"[fc] branch {bid} ({bname})")
        y = load_series(conn, bid)
        holdout = holdout_actual(conn, bid)
        bt, metrics = backtest(y)
        summary = summarize(metrics, bt)
        print("[fc] backtest summary (pooled_wmape asc):")
        print(summary.to_string(index=False))
        model, _ = pick_model(summary)
        pred = final_forecast(y, model)
        lo_err, hi_err = prediction_band(bt, model)
        print(f"[fc] 80% residual band: {lo_err:+.1f} .. {hi_err:+.1f} orders")
        write_forecast(y, model, pred, lo_err, hi_err, holdout)
        charts(y, bt, model, pred, lo_err, hi_err)
        print("[fc] done")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
