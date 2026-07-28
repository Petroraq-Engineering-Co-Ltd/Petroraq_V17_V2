# Project Feasibility Calculator

Standalone Odoo 17 application for testing whether a proposed investor profit
split meets a fixed monthly return target.

## Calculation

- Required profit = Investment × Expected monthly return × Duration
- Investor projected profit = Total project profit × Investor share
- Minimum feasible investor share = Required profit ÷ Total project profit
- Required total project profit = Required profit ÷ Current investor share

The OWL calculator supports forward and reverse analysis, persistent scenarios,
backend list/form views, and a formatted XLSX export.
