# Cafeteria POS — FY 2024-25 analysis (Kanishka challenge)

Import a 10.3 GB cafeteria POS dump into MySQL 8.0, clean it with logged row counts per rule, explore it, and forecast 7 days of daily orders for one branch with a backtested seasonal-naive baseline.
Deliverables: **[REPORT.md](project/REPORT.md)** (analysis, insights, recommendations), **[ASSUMPTIONS.md](project/ASSUMPTIONS.md)** (A1–A12), and machine-readable evidence in `project/outputs/` (aggregate CSVs + PNG charts).

## Key results

- Cleaned: **5,435,450** paid in-FY orders (of 5,961,005 raw) plus 6,786,676 line items; 14,839 rows dated 2025-04-01 held out for validation.
- Forecast branch: **2 Embassy Tech Village** — 2,244,973 orders in FY 2024-25 (auto-picked: largest volume with full 12-month coverage).
- Backtest (10 rolling folds, 7-day horizon, 365-day series): **seasonal-naive** wins — pooled wMAPE 0.102, MAE 668 orders/day (Holt–Winters 0.117, weekday OLS 0.137, naive 0.498).
- 7-day forecast, Apr 1–7 2025: **38,198 orders** total with an 80% band of −736/+660 — [forecast_7d.csv](project/outputs/forecast_7d.csv).
- Holdout sanity check: day-1 forecast 9,752 vs 5,476 actual (dump truncated 17:11:47 IST); share-adjusted expectation 5,744 → error −4.7% ([holdout_check.csv](project/outputs/holdout_check.csv)).
- Evidence: 26 aggregate files + 13 charts under `project/outputs/` — no PII, no raw rows.

## Repository structure

What is committed matches this tree exactly (59 files); local-only items are annotated:

```
.                          # repo root (H:\kanishka)
├── README.md              # this file
├── .gitignore             # venv/, *.sql, split/, logs/, reset_root_password.cmd, __pycache__/
├── Cafeteria Order Data.sql   raw 10.3 GB dump  — NOT committed (*.sql ignored)
├── users.sql                 raw users (PII)    — NOT committed (*.sql ignored)
├── split/                    per-table split    — NOT committed (gitignored)
└── project/                  everything below IS committed
    ├── REPORT.md  ASSUMPTIONS.md  README.md    report, assumptions, file guide
    ├── run_all.cmd  requirements.txt            pipeline runner + pinned deps
    ├── import_one.cmd  start_service.cmd        import helper, MySQL service helper
    ├── monitor_disk.ps1  split_dump.py  split_log.txt
    ├── src/
    │   ├── config.py  db.py                     paths, constants, MySQL helpers
    │   ├── 01_explore.py  02_clean.py           schema evidence, cleaning rules R1–R6
    │   ├── 03_eda.py  04_forecast.py            EDA + branch pick, backtest + forecast
    │   └── 05_holdout_check.py  06_tz_chart.py  holdout validation, timezone chart
    ├── logs/                run logs            — NOT committed (gitignored)
    ├── venv/                Python 3.11 venv    — NOT committed (gitignored)
    └── outputs/             aggregate CSVs only (no PII)
        ├── 26 files         cleaning_log, backtest_*, forecast_7d, holdout_check, ...
        └── charts/*.png     13 charts (10 EDA/tz + 3 forecast)
```

## Requirements

- **MySQL** 8.0.46 (service `MySQL80`), client
  `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe`, database `cafe`.
- **Python** 3.11.9 (venv at `project\venv`, created with `py -3.11`).
- Packages pinned in [`requirements.txt`](project/requirements.txt)
  (PyMySQL, pandas, numpy, matplotlib, pillow, statsmodels, scipy):
  `venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Database password (never stored here)

```bat
setx MYSQL_PWD <password>     rem run once; open a NEW shell afterwards
```
Every script reads it from the environment (`os.environ["MYSQL_PWD"]`,
`%MYSQL_PWD%`). No file in this repository contains a password or an email.

## Run order

1. **Import (first time only)** — service running, from `project\`, one file per call:
   `import_one.cmd "split\branches.sql" branches` (repeat for `counters`,
   `categories`, `category_has_dishes`, `dishes`, `menus`, `footfalls`, `users`,
   `order_details`, `orders`). `order_has_statuses` is truncated in the dump and
   intentionally not loaded.
2. **Pipeline**: `run_all.cmd` — stages 1–6, each logged to `logs\`:

| Stage | Script | Writes |
|---|---|---|
| 1 explore | `src\01_explore.py` | `logs/schema_*.txt`, coverage CSVs, `tz_comparison.csv`, `distributions.csv` |
| 2 clean | `src\02_clean.py` | `orders_clean`, `order_details_clean`, `orders_holdout`, `outputs/cleaning_log.csv` (raw tables dropped; `split\*.sql` kept as source) |
| 3 EDA | `src\03_eda.py` | `outputs/*.csv`, `outputs/charts/*.png`, `outputs/forecast_branch.txt` |
| 4 forecast | `src\04_forecast.py` | `outputs/backtest_*.csv`, `outputs/forecast_7d.csv`, forecast charts |
| 5 holdout check | `src\05_holdout_check.py` | `outputs/holdout_check.csv`, `outputs/hourly_tuesday_branch.csv` |
| 6 tz chart | `src\06_tz_chart.py` | `outputs/charts/tz_comparison.png` |

## Key conventions (full list in [ASSUMPTIONS.md](project/ASSUMPTIONS.md))

- FY 2024-25 = `2024-04-01 <= day < 2025-04-01` (IST).
- Timestamps in the dump are **local wall-clock** values — no +05:30 shift
  (A1/A4). Analysis sessions use `time_zone='+00:00'`; `ist_date/ist_hour/
  ist_dow` are precomputed in `orders_clean`.
- Forecast = seasonal-naive baseline + 10-fold rolling backtest (pooled wMAPE
  0.102); models limited to these four, no Prophet/ML.
- Outputs are aggregates only — raw rows contain PII and never leave the DB.

## Deliverables

- [Full report](project/REPORT.md)
- [Assumptions](project/ASSUMPTIONS.md)
- [Project README (reproduce / file guide)](project/README.md)
- [7-day forecast, branch 2 Embassy Tech Village (CSV)](project/outputs/forecast_7d.csv)

Raw data (10 GB dump, user table) is not included.
