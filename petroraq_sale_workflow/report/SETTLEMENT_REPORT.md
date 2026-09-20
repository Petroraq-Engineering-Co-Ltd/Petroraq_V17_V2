# Customer receivable and vendor payable reports

Upgrade `petroraq_sale_workflow` to 17.0.1.0.37. Open **Sales > Reporting > Customer Receivables**
or **Purchase > Reporting > Vendor Payables**. Both are also under **Accounting > Reporting**.
The Sales/Purchase Reporting menus retain their existing manager access requirements;
the new reports require Accounting user access and respect record rules, without sudo.

Select a company, one or more partners (empty means all), an as-of date, and optionally
a posting-date start and balance filter. Export PDF produces an A3 landscape report
following the 16-column customer receivables workbook layout.

## Calculations

- One row per posted invoice/bill, optionally including credit notes as negative rows.
- Amounts and balances are in the selected company's currency, using the posted ledger values.
- Cutoff selection uses accounting posting dates. Invoice/Bill Date is the date used for
  credit and cycle days; it falls back to the posting date when absent.
- Historical balance starts from receivable/payable journal-line balances and applies
  only partial reconciliations whose `max_date` is on or before the cutoff. Later payments
  therefore do not reduce an earlier report. This follows the current ledger and recorded
  reconciliation links; it cannot reconstruct reconciliations subsequently deleted.
- Received/Paid Amount is the net settled amount, including allocated credits, write-offs
  and exchange differences. Unapplied advances/receipts are not invoice settlements.
- Due Date is the earliest outstanding installment, or final due date for a settled invoice.
  Credit Days is the difference from Invoice/Bill Date to that displayed due date.
- Overdue Days is positive after the due date, otherwise zero. On a settled invoice it
  reflects lateness at final settlement. The Overdue filter requires a positive overdue
  installment balance; an outstanding credit does not qualify.
- Received/Paid Date is the last reconciliation date through the cutoff. Cycle Days runs
  from Invoice/Bill Date to final settlement, or to the cutoff while still outstanding.
- Orders and references come from the linked invoice lines; multiple orders appear together.
  Order amounts are converted to company currency at the order date. They are reference
  information, may repeat on several invoices, and are not added to report totals.

## Validation

`test_settlement_report_logic.py` runs without an Odoo database and exercises the production
report method with isolated records. `test_settlement_report.py` adds Odoo integration checks
for actual posted invoices, partial reconciliation, historical cutoffs and partner filters.
The latter must run on the Odoo test build.
