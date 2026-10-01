# Cafeteria POS — FY 2024-25 analysis (Kanishka challenge)

Import a 10.3 GB cafeteria POS dump into MySQL 8.0, clean it (row counts logged
per rule), explore it, and forecast 7 days of daily orders for one branch with
a backtested seasonal-naive baseline. Deliverables: **[REPORT.md](REPORT.md)**
(analysis, insights, recommendations), **[ASSUMPTIONS.md](ASSUMPTIONS.md)**
(A1–A12), and machine-readable evidence in [`outputs/`](outputs/) (aggregate
CSVs + PNG charts).

## Repository structure

```
.                          # repo root (H:\kanishka)
├── Cafeteria Order Data.sql   raw 10.3 GB dump  — NOT committed (*.sql ignored)
├── users.sql                  raw users (PII)   — NOT committed (*.sql ignored)
├── split/                     per-table split    — NOT committed (gitignored)
├── .gitignore                 venv/, *.sql, split/, logs/, reset_root_password.cmd, __pycache__/
└── project/                   everything below is committed
    ├── REPORT.md  ASSUMPTIONS.md  README.md
    ├── run_all.cmd  requirements.txt
    ├── import_one.cmd  start_service.cmd
    ├── monitor_disk.ps1  split_dump.py
    ├── src/
    │   ├── config.py  db.py
    │   ├── 01_explore.py  02_clean.py  03_eda.py  04_forecast.py
    │   ├── 05_holdout_check.py  06_tz_chart.py
    ├── outputs/               aggregate CSVs only (no PII)
    │   └── charts/*.png       13 charts (10 EDA/tz + 3 forecast)
    ├── logs/                  run logs        — NOT committed (gitignored)
    └── venv/                  Python 3.11 venv — NOT committed (gitignored)
```

## Requirements

- **MySQL** 8.0.46 (service `MySQL80`), client
  `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe`, database `cafe`.
- **Python** 3.11.9 (venv at `project\venv`, created with `py -3.11`).
- Packages pinned in [`requirements.txt`](requirements.txt)
  (PyMySQL, pandas, numpy, matplotlib, pillow, statsmodels, scipy):
  `venv\Scripts\python.exe -m pip install -r requirements.txt`.
- **Raw data is NOT in this repo** (10.3 GB dump + `split\*.sql` are excluded
  by `.gitignore`). Place `Cafeteria Order Data.sql` at the repo root and split
  it with `project\split_dump.py` only if you need to re-import.

## Database password (never stored here)

```bat
setx MYSQL_PWD <password>     rem run once; open a NEW shell afterwards
```
Every script reads it from the environment (`os.environ["MYSQL_PWD"]`,
`%MYSQL_PWD%`). No file in this repository contains a password or an email.

## Run order

1. **Import (first time only)** — service running, from `project\`:
   `import_one.cmd branches` → `counters` → `categories` → `category_has_dishes`
   → `dishes` → `menus` → `footfalls` → `users` → `order_details` → `orders`.
   (`order_has_statuses` is truncated in the dump and intentionally not loaded.)
2. **Pipeline**: `run_all.cmd` — stages 1–6, each logged to `logs\`:

| Stage | Script | Writes |
|---|---|---|
| 1 explore | `src\01_explore.py` | `logs/schema_*.txt`, coverage CSVs, `tz_comparison.csv`, `distributions.csv` |
| 2 clean | `src\02_clean.py` | `orders_clean`, `order_details_clean`, `orders_holdout`, `outputs/cleaning_log.csv` (raw tables dropped; `split\*.sql` kept as source) |
| 3 EDA | `src\03_eda.py` | `outputs/*.csv`, `outputs/charts/*.png`, `outputs/forecast_branch.txt` |
| 4 forecast | `src\04_forecast.py` | `outputs/backtest_*.csv`, `outputs/forecast_7d.csv`, forecast charts |
| 5 holdout check | `src\05_holdout_check.py` | `outputs/holdout_check.csv`, `outputs/hourly_tuesday_branch.csv` |
| 6 tz chart | `src\06_tz_chart.py` | `outputs/charts/tz_comparison.png` |

## Key conventions (full list in [ASSUMPTIONS.md](ASSUMPTIONS.md))

- FY 2024-25 = `2024-04-01 <= day < 2025-04-01` (IST).
- Timestamps in the dump are **local wall-clock** values — no +05:30 shift
  (A1/A4). Analysis sessions use `time_zone='+00:00'`; `ist_date/ist_hour/
  ist_dow` are precomputed in `orders_clean`.
- Forecast = seasonal-naive baseline + 10-fold rolling backtest (pooled wMAPE
  0.102); models limited to these four, no Prophet/ML.
- Outputs are aggregates only — raw rows contain PII and never leave the DB.
