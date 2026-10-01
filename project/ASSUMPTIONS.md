# ASSUMPTIONS.md — recorded as they are made

Scope: analysis of dump `foodiisoftv3-fy-24-25` (FY 2024-25) for the Kanishka
internship challenge. Every assumption here is stated before/in the step that
relies on it.

## A1. Timestamps: dump session was UTC, but VALUES are local (IST) wall clock
The dump header sets `SET time_zone = "+00:00"`, so MySQL interpreted every
timestamp literal as UTC on import — but inspection shows the application wrote
**local wall-clock values** into those literals (Laravel with app timezone
Asia/Kolkata writing to a UTC-session DB). Consequence: the raw stored numbers
ARE the local times; any +05:30 shift would double-shift them.
- Import sessions used `time_zone='+00:00'` (stored exactly as dumped).
- Analysis sessions therefore also use `time_zone='+00:00'`, so
  `DATE()`/`HOUR()` on raw values yield local (IST) parts directly.
- Server `system_time_zone` = `India Standard Time`; any default `SYSTEM`
  session displays values +05:30 — do NOT use SYSTEM sessions for time parts.
- Verification evidence is in A4.

## A2. Financial year window
FY 2024-25 = `2024-04-01 00:00:00` ≤ t < `2025-04-01 00:00:00` (local/IST
values as stored). Raw `order_date` spans 2024-04-01 00:00:34 ..
2025-04-01 17:11:47 — starts exactly on the FY boundary (no pre-FY rows) and
ends mid-day 2025-04-01 (partial last day; see A12 holdout).

## A3. SQL mode emulated from the dump header
The dump header sets `SQL_MODE = "NO_AUTO_VALUE_ON_ZERO"` (non-strict).
Import sessions therefore run with `sql_mode='NO_AUTO_VALUE_ON_ZERO'`.
Observed need: `dishes` failed on `0000-00-00 00:00:00` under default strict
mode. Analysis/cleaning sessions use the default (strict) mode — by then all
zero-date decisions are made explicitly.

## A4. Canonical time column — DECIDED: `order_date`, interpreted as wall clock
Timebase comparison (`outputs/tz_comparison.csv`): `order_date`, `IST_timezone`
and `created_at` have near-identical hourly histograms (all three within
seconds of each other). Viewed **as stored (no shift)** the histogram peaks at
hour 13 (722k orders; 12–14h share 24.5%) = local lunch. Shifting +05:30 would
move mass to peaks at 19/21:30–23h/02:30 (late-evening/night) — implausible
for a cafeteria. Independent confirmation: a UPI terminal entry inside
`orders.json_data` has `"Transaction Date":"01042025","Transaction Time":
"171128"` on a row whose `order_date` = `2025-04-01 17:11:44` (seconds apart,
terminal stamps local time).
=> Use `order_date` values AS-IS (no +5:30). Analysis sessions run with
`time_zone='+00:00'` so `DATE()`/`HOUR()` = local IST directly.
No other column is ever shifted (no double-shift).
Note: `order_date` (placement) chosen over `created_at` (DB write time,
min+27s lag) and `IST_timezone` (within ±2s; name is misleading).

## A5. `order_has_statuses` is not used
The split file is truncated mid-INSERT and stops at 2024-04-25 (~24 days of
status history only) — biased sample. Status analysis uses
`orders.order_status`, `orders.paid_or_cancel`, `order_details.order_status`
(all rows complete for FY). Tables alphabetically after `order_has_statuses`
(payments, etc.) are absent from the dump entirely.

## A6. Payment analysis via `orders.mode_of_transaction`
No `payments` table in the dump; payment-mode insights come from
`orders.mode_of_transaction` + `payment_timestamp` (NULLs reported).

## A7. Test / toy branches excluded from business metrics — DECIDED: (6, 7, 8)
Branch names `tstbranch` (7), `testobranch` (8) are obviously non-production,
`AK Branch` (6) is toy-sized. Data check (`01_explore.py`): branches 6/7/8
have **zero** orders in the dump (also branch 11: 8 orders, 0 paid; branch -1:
1 order, unpaid — both removed by the status rule anyway). The explicit
`branch_id NOT IN (6,7,8)` predicate is kept so the exclusion is visible in
`outputs/cleaning_log.csv` (it removes 0 rows).

## A8. Duplicate ids are possible (no PKs in dump)
The dump tail (indexes/PK) is missing, so `orders.id` may repeat.
Cleaning dedupes on `id` keeping the row with max `updated_at`
(tie-break: max id) and reports removed counts. Repeated
`(branch_id, order_number)` pairs are counted and reported; they are removed
only when they are actual duplicate ids (same id) — same number on different
ids may be legitimate reprints, so they are flagged, not silently dropped.

## A9. Raw tables dropped after cleaning
Plan: build narrow `orders_clean`, then `DROP TABLE orders`
(6.1 GB reclaimed: `orders.ibd` 6,139 MB). Same treatment for `order_details`
(1.3 GB: `order_details.ibd` 1,333 MB) after `order_details_clean` is verified
(source of truth remains `H:\kanishka\split\*.sql`; re-importable via
`import_one.cmd`).

## A10. Aggregate-only outputs
Raw rows contain PII (users.name/email/contact, UPI VPA in transaction_data).
All files under `outputs/` and the report contain aggregates only; no
passwords in any file (read via `os.environ["MYSQL_PWD"]`).

## A11. Operational tuning during import (not data assumptions)
`SET PERSIST max_allowed_packet=1G`, `innodb_buffer_pool_size=4G`,
`innodb_redo_log_capacity=1G`, `innodb_flush_log_at_trx_commit=2`
(crash-safety relaxed during bulk load; restored to 1 after import).
Import init-command (single statement):
`SET time_zone='+00:00', foreign_key_checks=0, unique_checks=0, sql_log_bin=0, sql_mode='NO_AUTO_VALUE_ON_ZERO'`
(added `sql_mode` to the statement — see A3).

## A12. Forecast scope
- One branch = largest FY 2024-25 paid-order volume with stable coverage,
  test branches excluded (auto-pick). **Picked: branch 2,
  Embassy Tech Village** (2,244,973 paid orders, 365/365 days, 12/12 months).
- Series: daily order counts (IST day) over FY 2024-25 (365 days, 0 gaps).
- Models: naive, seasonal-naive (lag-7), Holt–Winters, weekday OLS.
  Baseline to beat: seasonal-naive. Rolling-origin backtest, 7-day horizon,
  10 folds. **Result: seasonal-naive wins (pooled wMAPE 0.102).**
- Extra holdout: 2025-04-01 — **outside FY and a partial day** (dump stops
  **17:11:47 IST**; branch 2's last order that day 17:11:27). Training/backtest
  use `ist_date` ≤ 2025-03-31 only (verified: 0 rows on 2025-04-01 in
  `orders_clean`), so the partial day never leaks into training. Because a
  full-day forecast cannot be compared with a truncated actual, the comparison
  is share-adjusted: 58.9% of a typical Tuesday's FY volume (280,317 of
  475,937 orders) occurs at/before the cutoff, so expected partial-day actual
  = 9,752 × 58.9% = 5,744 vs observed 5,476 ⇒ **−4.7% (−268 orders)**, inside
  the backtest MAE of 668/day. Numbers: `outputs/holdout_check.csv`,
  `outputs/hourly_tuesday_branch.csv` (`src/05_holdout_check.py`).
