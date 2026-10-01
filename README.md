# Cafeteria POS — EDA & 7-Day Order Forecast

Kanishka Software internship challenge: load a 10.3 GB phpMyAdmin dump of a cafeteria POS into MySQL (8.0), clean and explore it, then forecast 7 days of daily orders for the highest-volume branch.
Method: seasonal-naive baseline with a 365-day backtest (pooled wMAPE 0.102) plus naive, Holt-Winters, and weekday-OLS comparators; every figure in the report is reproduced from `project/outputs/`.

## Deliverables

- [Full report](project/REPORT.md)
- [Assumptions](project/ASSUMPTIONS.md)
- [Project README (reproduce / file guide)](project/README.md)
- [7-day forecast, branch 2 Embassy Tech Village (CSV)](project/outputs/forecast_7d.csv)

Raw data (10 GB dump, user table) is not included.
