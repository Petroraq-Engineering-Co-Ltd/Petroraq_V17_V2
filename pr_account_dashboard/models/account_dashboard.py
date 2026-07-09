# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


CUSTOM_VOUCHERS = [
    ("pr.account.bank.payment", "BPV", "Payments", "#3b82f6", "accounting_date"),
    ("pr.account.cash.payment", "CPV", "Payments", "#8b5cf6", "accounting_date"),
    ("pr.account.bank.receipt", "BRV", "Receipts", "#14b8a6", "accounting_date"),
    ("pr.account.cash.receipt", "CRV", "Receipts", "#22c55e", "accounting_date"),
]
CUSTOM_VOUCHER_LINES = {
    "pr.account.bank.payment": "bank_payment_line_ids",
    "pr.account.cash.payment": "cash_payment_line_ids",
    "pr.account.bank.receipt": "bank_receipt_line_ids",
    "pr.account.cash.receipt": "cash_receipt_line_ids",
}
PAYMENT_EXCLUDED_STATES = ["draft", "cancel", "canceled", "reject", "rejected"]


class PrAccountDashboard(models.AbstractModel):
    _name = "pr.account.dashboard"
    _description = "Petroraq Accounting Dashboard Service"

    @api.model
    def get_dashboard_data(self, options=None):
        self._check_dashboard_access()
        options = self._normalize_options(options or {})
        company = options["company"]
        date_from = options["date_from"]
        date_to = options["date_to"]

        invoice_data = self._get_invoice_summary(company, date_from, date_to)
        payment_data = self._get_payment_summary(company, date_from, date_to)
        voucher_data = self._get_voucher_summary(company, date_from, date_to)
        journal_data = self._get_journal_balances(company, date_to)
        analytics_data = self._get_analytic_analysis(company, date_from, date_to)
        vat_data = self._get_vat_position(company, date_from, date_to)
        data_quality = self._get_data_quality(company, date_from, date_to)

        cash_in = payment_data["cash_in"] + voucher_data["receipt_total"]
        cash_out = payment_data["cash_out"] + voucher_data["payment_total"]

        return {
            "filters": {
                "date_from": fields.Date.to_string(date_from),
                "date_to": fields.Date.to_string(date_to),
                "company_id": company.id,
                "company_name": company.display_name,
                "scope_company_ids": self._scope_companies(company).ids,
                "scope_company_names": self._scope_companies(company).mapped("display_name"),
                "is_consolidated": len(self._scope_companies(company)) > 1,
                "companies": [
                    {"id": allowed_company.id, "name": allowed_company.display_name}
                    for allowed_company in self.env.companies.sorted(
                        key=lambda item: item.name or ""
                    )
                ],
            },
            "currency": self._currency_data(company),
            "summary": {
                **invoice_data,
                **payment_data,
                "cash_in": cash_in,
                "cash_out": cash_out,
                "net_cash": cash_in - cash_out,
            },
            "monthly": self._get_monthly_trends(company, date_from, date_to),
            "aging": self._get_aging(company, date_to),
            "vouchers": voucher_data["rows"],
            "approval_queue": self._get_approval_queue(company, date_from, date_to),
            "journals": journal_data,
            "gl": self._get_gl_overview(company, date_from, date_to),
            "main_heads": self._get_main_head_analysis(company, date_from, date_to),
            "analytics": analytics_data,
            "vat": vat_data,
            "top_customers": self._get_top_open_partners(company, date_to, "out_invoice"),
            "top_vendors": self._get_top_open_partners(company, date_to, "in_invoice"),
            "data_quality": data_quality,
            "close_checklist": self._get_close_checklist(company, date_from, date_to),
            "exceptions": self._get_exception_monitor(company, date_from, date_to),
            "cash_forecast": self._get_cash_forecast(company, date_to, journal_data),
            "voucher_sla": self._get_voucher_sla(company, date_from, date_to),
            "vat_audit": self._get_vat_audit(company, date_from, date_to, vat_data),
            "bank_health": self._get_bank_health(company, date_to, journal_data),
            "profitability": self._get_project_profitability(company, date_from, date_to, analytics_data),
            "recent_activity": self._get_recent_activity(company, date_from, date_to),
        }

    def _check_dashboard_access(self):
        groups = [
            "account.group_account_invoice",
            "account.group_account_user",
            "account.group_account_manager",
            "pr_account.custom_group_accounting_manager",
        ]
        if not any(self.env.user.has_group(group) for group in groups):
            raise AccessError(_("You are not allowed to access the Accounting Dashboard."))

    def _normalize_options(self, options):
        allowed_companies = self.env.companies
        company_id = int(options.get("company_id") or self.env.company.id)
        company = allowed_companies.filtered(lambda item: item.id == company_id)
        if not company:
            raise AccessError(_("The selected company is not available in your allowed companies."))
        company = company[:1]

        today = fields.Date.context_today(self)
        date_from = fields.Date.to_date(options.get("date_from")) if options.get("date_from") else today.replace(month=1, day=1)
        date_to = fields.Date.to_date(options.get("date_to")) if options.get("date_to") else today
        if date_from > date_to:
            raise ValidationError(_("Start Date cannot be later than End Date."))
        return {
            "company": company,
            "date_from": date_from,
            "date_to": date_to,
        }

    def _currency_data(self, company):
        currency = company.currency_id
        return {
            "id": currency.id,
            "symbol": currency.symbol or "",
            "position": currency.position or "before",
            "digits": currency.decimal_places,
        }

    def _scope_companies(self, company):
        """Companies whose accounting entries belong to the selected scope.

        Selecting a branch returns only that branch. Selecting a parent returns
        its allowed descendants as a consolidated scope. Companies with a
        different currency are excluded because adding raw company-currency
        balances would be mathematically incorrect.
        """
        company.ensure_one()

        def is_descendant(candidate):
            current = candidate
            while current:
                if current == company:
                    return True
                current = current.parent_id
            return False

        return self.env.companies.filtered(
            lambda candidate: (
                is_descendant(candidate)
                and candidate.currency_id == company.currency_id
            )
        )

    def _journal_companies(self, company):
        """Return entry-scope companies plus ancestors owning shared journals."""
        scope = self._scope_companies(company)
        company_ids = set(scope.ids)
        for scoped_company in scope:
            current = scoped_company.parent_id
            while current:
                company_ids.add(current.id)
                current = current.parent_id
        return self.env["res.company"].sudo().browse(sorted(company_ids)).exists()

    def _company_domain(self, company):
        return [("company_id", "in", self._scope_companies(company).ids)]

    def _date_domain(self, field_name, date_from, date_to):
        return [
            (field_name, ">=", fields.Date.to_string(date_from)),
            (field_name, "<=", fields.Date.to_string(date_to)),
        ]

    def _json_domain(self, domain):
        return [list(item) if isinstance(item, tuple) else item for item in domain]

    def _dashboard_issue(
        self,
        label,
        description,
        model,
        domain,
        count,
        amount=0.0,
        color="#f59e0b",
        icon="fa-exclamation-circle",
        severity="warning",
    ):
        return {
            "label": label,
            "description": description,
            "model": model,
            "count": count,
            "amount": amount,
            "color": color,
            "icon": icon,
            "severity": severity,
            "domain": self._json_domain(domain),
        }

    def _record_amount(self, record):
        for field_name in (
            "amount_total_signed",
            "amount_total",
            "total_amount",
            "approved_amount",
            "amount",
            "balance",
        ):
            if field_name in record._fields:
                return abs(record[field_name] or 0.0)
        return 0.0

    def _pending_voucher_states(self, model):
        state_field = model._fields.get("state")
        if not state_field:
            return []
        selection = state_field.selection
        if callable(selection):
            selection = selection(model)
        values = dict(selection or {})
        return [state for state in ("submit", "finance_approve") if state in values]

    def _custom_voucher_line_model(self, parent_model_name):
        parent_model = self.env[parent_model_name]
        line_field_name = CUSTOM_VOUCHER_LINES.get(parent_model_name)
        line_field = parent_model._fields.get(line_field_name) if line_field_name else False
        if not line_field:
            return False, False
        return self.env[line_field.comodel_name].sudo(), line_field.inverse_name

    def _signed_company_amount(self, record, signed_field, fallback_field):
        if signed_field in record._fields:
            return abs(record[signed_field] or 0.0)
        amount = abs(record[fallback_field] or 0.0)
        currency = getattr(record, "currency_id", False)
        company = getattr(record, "company_id", False)
        if currency and company and currency != company.currency_id:
            amount = currency._convert(
                amount,
                company.currency_id,
                company,
                getattr(record, "date", False) or fields.Date.context_today(record),
            )
        return amount

    def _invoice_amount(self, move, residual=False):
        if residual:
            return self._signed_company_amount(
                move,
                "amount_residual_signed",
                "amount_residual",
            )
        return self._signed_company_amount(move, "amount_total_signed", "amount_total")

    def _payment_amount(self, payment):
        for field_name in ("amount_company_currency_signed", "amount_company_currency"):
            if field_name in payment._fields:
                return abs(payment[field_name] or 0.0)
        return self._signed_company_amount(payment, "amount_signed", "amount")

    def _voucher_amount(self, voucher):
        """Amount represented by the posted journal entry for custom vouchers."""
        if (
            voucher._name in ("pr.account.bank.payment", "pr.account.cash.payment")
            and voucher.state == "posted"
            and "approved_amount" in voucher._fields
        ):
            return voucher.approved_amount or 0.0
        return voucher.total_amount or 0.0

    def _sum_records(self, records, getter):
        return sum(getter(record) for record in records)

    def _get_invoice_summary(self, company, date_from, date_to):
        Move = self.env["account.move"].sudo()
        base = self._company_domain(company) + self._date_domain("invoice_date", date_from, date_to)
        posted = base + [("state", "=", "posted")]

        customer_invoices = Move.search(posted + [("move_type", "=", "out_invoice")])
        customer_refunds = Move.search(posted + [("move_type", "=", "out_refund")])
        vendor_bills = Move.search(posted + [("move_type", "=", "in_invoice")])
        vendor_refunds = Move.search(posted + [("move_type", "=", "in_refund")])

        open_customer_items = self._open_invoice_items(
            company,
            date_to,
            "out_invoice",
        )
        open_vendor_items = self._open_invoice_items(
            company,
            date_to,
            "in_invoice",
        )
        open_customer = Move.browse([item["move"].id for item in open_customer_items])
        open_vendor = Move.browse([item["move"].id for item in open_vendor_items])
        open_customer_domain = [("id", "in", open_customer.ids)]
        open_vendor_domain = [("id", "in", open_vendor.ids)]

        invoice_domain = posted + [("move_type", "=", "out_invoice")]
        bill_domain = posted + [("move_type", "=", "in_invoice")]
        return {
            "customer_invoice_total": self._sum_records(customer_invoices, self._invoice_amount),
            "customer_invoice_count": len(customer_invoices),
            "customer_credit_total": self._sum_records(customer_refunds, self._invoice_amount),
            "vendor_bill_total": self._sum_records(vendor_bills, self._invoice_amount),
            "vendor_bill_count": len(vendor_bills),
            "vendor_credit_total": self._sum_records(vendor_refunds, self._invoice_amount),
            "receivable_total": sum(item["residual"] for item in open_customer_items),
            "receivable_count": len(open_customer),
            "payable_total": sum(item["residual"] for item in open_vendor_items),
            "payable_count": len(open_vendor),
            "invoice_domain": self._json_domain(invoice_domain),
            "bill_domain": self._json_domain(bill_domain),
            "receivable_domain": self._json_domain(open_customer_domain),
            "payable_domain": self._json_domain(open_vendor_domain),
        }

    def _get_payment_summary(self, company, date_from, date_to):
        Payment = self.env["account.payment"].sudo()
        base = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [("state", "not in", PAYMENT_EXCLUDED_STATES)]
        )
        inbound_domain = base + [("payment_type", "=", "inbound")]
        outbound_domain = base + [("payment_type", "=", "outbound")]
        inbound = Payment.search(inbound_domain)
        outbound = Payment.search(outbound_domain)
        return {
            "registered_receipt_total": self._sum_records(inbound, self._payment_amount),
            "registered_receipt_count": len(inbound),
            "registered_payment_total": self._sum_records(outbound, self._payment_amount),
            "registered_payment_count": len(outbound),
            "cash_in": self._sum_records(inbound, self._payment_amount),
            "cash_out": self._sum_records(outbound, self._payment_amount),
            "receipt_domain": self._json_domain(inbound_domain),
            "payment_domain": self._json_domain(outbound_domain),
        }

    def _get_voucher_summary(self, company, date_from, date_to):
        rows = []
        payment_total = 0.0
        receipt_total = 0.0
        state_colors = {
            "draft": "#94a3b8",
            "submit": "#f59e0b",
            "finance_approve": "#8b5cf6",
            "posted": "#16a34a",
            "cancel": "#ef4444",
        }
        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            Model = self.env[model_name].sudo()
            base = self._company_domain(company) + self._date_domain(
                date_field,
                date_from,
                date_to,
            )
            active_domain = base + [("state", "!=", "cancel")]
            records = Model.search(active_domain)
            posted_records = records.filtered(lambda record: record.state == "posted")
            total = self._sum_records(posted_records, self._voucher_amount)
            if category == "Payments":
                payment_total += total
            else:
                receipt_total += total

            state_rows = []
            selection = dict(Model._fields["state"].selection)
            for state_value in ("draft", "submit", "finance_approve", "posted", "cancel"):
                if state_value not in selection:
                    continue
                state_domain = base + [("state", "=", state_value)]
                state_records = Model.search(state_domain)
                state_rows.append({
                    "state": state_value,
                    "label": selection[state_value],
                    "count": len(state_records),
                    "amount": self._sum_records(state_records, self._voucher_amount),
                    "color": state_colors.get(state_value, color),
                    "domain": self._json_domain(state_domain),
                })

            rows.append({
                "code": code,
                "label": "%s - %s" % (code, category[:-1]),
                "model": model_name,
                "color": color,
                "count": len(records),
                "posted_count": len(posted_records),
                "posted_total": total,
                "pending_count": len(records.filtered(
                    lambda record: record.state in ("submit", "finance_approve")
                )),
                "domain": self._json_domain(active_domain),
                "states": state_rows,
            })
        return {
            "rows": rows,
            "payment_total": payment_total,
            "receipt_total": receipt_total,
        }

    def _month_range(self, date_from, date_to):
        first = date_from.replace(day=1)
        last = date_to.replace(day=1)
        if first < last - relativedelta(months=11):
            first = last - relativedelta(months=11)
        months = []
        cursor = first
        while cursor <= last:
            months.append(cursor)
            cursor += relativedelta(months=1)
        return months

    def _get_monthly_trends(self, company, date_from, date_to):
        months = self._month_range(date_from, date_to)
        values = {
            month.strftime("%Y-%m"): {
                "label": month.strftime("%b %Y"),
                "invoices": 0.0,
                "bills": 0.0,
                "cash_in": 0.0,
                "cash_out": 0.0,
            }
            for month in months
        }
        if not months:
            return []
        actual_from = max(date_from, months[0])

        Move = self.env["account.move"].sudo()
        move_domain = (
            self._company_domain(company)
            + self._date_domain("invoice_date", actual_from, date_to)
            + [
                ("state", "=", "posted"),
                ("move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]),
            ]
        )
        for move in Move.search(move_domain):
            if not move.invoice_date:
                continue
            row = values.get(move.invoice_date.strftime("%Y-%m"))
            if not row:
                continue
            amount = self._invoice_amount(move)
            if move.move_type == "out_invoice":
                row["invoices"] += amount
            elif move.move_type == "out_refund":
                row["invoices"] -= amount
            elif move.move_type == "in_invoice":
                row["bills"] += amount
            else:
                row["bills"] -= amount

        Payment = self.env["account.payment"].sudo()
        payment_domain = (
            self._company_domain(company)
            + self._date_domain("date", actual_from, date_to)
            + [("state", "not in", PAYMENT_EXCLUDED_STATES)]
        )
        for payment in Payment.search(payment_domain):
            row = values.get(payment.date.strftime("%Y-%m")) if payment.date else False
            if not row:
                continue
            if payment.payment_type == "inbound":
                row["cash_in"] += self._payment_amount(payment)
            elif payment.payment_type == "outbound":
                row["cash_out"] += self._payment_amount(payment)

        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            records = self.env[model_name].sudo().search(
                self._company_domain(company)
                + self._date_domain(date_field, actual_from, date_to)
                + [("state", "=", "posted")]
            )
            for record in records:
                record_date = record[date_field]
                row = values.get(record_date.strftime("%Y-%m")) if record_date else False
                if not row:
                    continue
                if category == "Payments":
                    row["cash_out"] += self._voucher_amount(record)
                else:
                    row["cash_in"] += self._voucher_amount(record)

        rows = [values[month.strftime("%Y-%m")] for month in months]
        max_value = max(
            [max(row["invoices"], row["bills"], row["cash_in"], row["cash_out"]) for row in rows]
            or [0.0]
        )
        for row in rows:
            row["invoice_percent"] = self._percent(row["invoices"], max_value)
            row["bill_percent"] = self._percent(row["bills"], max_value)
            row["cash_in_percent"] = self._percent(row["cash_in"], max_value)
            row["cash_out_percent"] = self._percent(row["cash_out"], max_value)
        return rows

    def _open_invoice_base_domain(self, company, date_to, move_type):
        return (
            self._company_domain(company)
            + [
                ("state", "=", "posted"),
                ("move_type", "=", move_type),
                ("invoice_date", "<=", fields.Date.to_string(date_to)),
            ]
        )

    def _partial_reconcile_date(self, partial):
        if "max_date" in partial._fields and partial.max_date:
            return partial.max_date
        debit_date = partial.debit_move_id.date
        credit_date = partial.credit_move_id.date
        return max(filter(None, [debit_date, credit_date]), default=False)

    def _residual_as_of(self, move, date_to):
        """Company-currency invoice residual reconstructed at ``date_to``."""
        receivable_payable_lines = move.line_ids.filtered(
            lambda line: (
                line.date <= date_to
                and line.account_id.account_type in (
                    "asset_receivable",
                    "liability_payable",
                )
            )
        )
        residual = 0.0
        for line in receivable_payable_lines:
            line_residual = line.balance
            for partial in line.matched_debit_ids:
                partial_date = self._partial_reconcile_date(partial)
                if partial_date and partial_date <= date_to:
                    line_residual += partial.amount
            for partial in line.matched_credit_ids:
                partial_date = self._partial_reconcile_date(partial)
                if partial_date and partial_date <= date_to:
                    line_residual -= partial.amount
            residual += line_residual
        return abs(residual)

    def _open_invoice_items(self, company, date_to, move_type):
        moves = self.env["account.move"].sudo().search(
            self._open_invoice_base_domain(company, date_to, move_type)
        )
        items = []
        currency = company.currency_id
        for move in moves:
            residual = self._residual_as_of(move, date_to)
            if currency.is_zero(residual):
                continue
            items.append({"move": move, "residual": residual})
        return items

    def _get_aging(self, company, date_to):
        return {
            "receivable": self._aging_side(company, date_to, "out_invoice"),
            "payable": self._aging_side(company, date_to, "in_invoice"),
        }

    def _aging_side(self, company, date_to, move_type):
        Move = self.env["account.move"].sudo()
        items = self._open_invoice_items(company, date_to, move_type)
        records = Move.browse([item["move"].id for item in items])
        base = [("id", "in", records.ids)]
        buckets = [
            {"key": "current", "label": "Current", "min": None, "max": 0, "amount": 0.0, "count": 0},
            {"key": "1_30", "label": "1–30 Days", "min": 1, "max": 30, "amount": 0.0, "count": 0},
            {"key": "31_60", "label": "31–60 Days", "min": 31, "max": 60, "amount": 0.0, "count": 0},
            {"key": "61_90", "label": "61–90 Days", "min": 61, "max": 90, "amount": 0.0, "count": 0},
            {"key": "over_90", "label": "Over 90 Days", "min": 91, "max": None, "amount": 0.0, "count": 0},
        ]
        for item in items:
            move = item["move"]
            due_date = move.invoice_date_due or move.invoice_date or date_to
            days = (date_to - due_date).days
            if days <= 0:
                bucket = buckets[0]
            elif days <= 30:
                bucket = buckets[1]
            elif days <= 60:
                bucket = buckets[2]
            elif days <= 90:
                bucket = buckets[3]
            else:
                bucket = buckets[4]
            bucket["amount"] += item["residual"]
            bucket["count"] += 1

        total = sum(bucket["amount"] for bucket in buckets)
        colors = ["#22c55e", "#84cc16", "#f59e0b", "#f97316", "#ef4444"]
        for index, bucket in enumerate(buckets):
            bucket["percent"] = self._percent(bucket["amount"], total)
            bucket["color"] = colors[index]
            domain = list(base)
            if bucket["key"] == "current":
                domain += [
                    "|",
                    ("invoice_date_due", "=", False),
                    ("invoice_date_due", ">=", fields.Date.to_string(date_to)),
                ]
            elif bucket["key"] == "over_90":
                domain.append((
                    "invoice_date_due",
                    "<=",
                    fields.Date.to_string(date_to - relativedelta(days=91)),
                ))
            else:
                domain += [
                    (
                        "invoice_date_due",
                        "<=",
                        fields.Date.to_string(date_to - relativedelta(days=bucket["min"])),
                    ),
                    (
                        "invoice_date_due",
                        ">=",
                        fields.Date.to_string(date_to - relativedelta(days=bucket["max"])),
                    ),
                ]
            bucket["domain"] = self._json_domain(domain)
        return {
            "total": total,
            "count": len(records),
            "buckets": buckets,
            "domain": self._json_domain(base),
        }

    def _get_approval_queue(self, company, date_from, date_to):
        rows = []

        def add_row(label, model_name, domain, amount_getter, color, icon):
            records = self.env[model_name].sudo().search(domain)
            rows.append({
                "label": label,
                "model": model_name,
                "count": len(records),
                "amount": sum(amount_getter(record) for record in records),
                "domain": self._json_domain(domain),
                "color": color,
                "icon": icon,
            })

        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            state_selection = dict(self.env[model_name]._fields["state"].selection)
            pending_states = [
                state
                for state in ("submit", "finance_approve")
                if state in state_selection
            ]
            if not pending_states:
                continue
            add_row(
                "%s Pending Approval" % code,
                model_name,
                self._company_domain(company) + self._date_domain(
                    date_field,
                    date_from,
                    date_to,
                ) + [
                    ("state", "in", pending_states),
                ],
                lambda record: record.total_amount,
                color,
                "fa-credit-card" if category == "Payments" else "fa-download",
            )

        payment_base = self._company_domain(company) + self._date_domain("date", date_from, date_to) + [
            ("state", "=", "draft"),
            ("pr_requires_vendor_payment_approval", "=", True),
        ]
        add_row(
            "Vendor Payments — Accounts",
            "account.payment",
            payment_base + [("pr_payment_approval_state", "=", "submit")],
            self._payment_amount,
            "#f59e0b",
            "fa-check-square-o",
        )
        add_row(
            "Vendor Payments — Final",
            "account.payment",
            payment_base + [("pr_payment_approval_state", "=", "finance_approve")],
            self._payment_amount,
            "#ef4444",
            "fa-shield",
        )
        add_row(
            "Draft Customer Invoices",
            "account.move",
            self._company_domain(company)
            + self._date_domain("invoice_date", date_from, date_to)
            + [("state", "=", "draft"), ("move_type", "=", "out_invoice")],
            self._invoice_amount,
            "#0ea5e9",
            "fa-file-text-o",
        )
        add_row(
            "Draft Vendor Bills",
            "account.move",
            self._company_domain(company)
            + self._date_domain("invoice_date", date_from, date_to)
            + [("state", "=", "draft"), ("move_type", "=", "in_invoice")],
            self._invoice_amount,
            "#8b5cf6",
            "fa-file-o",
        )
        return rows

    def _get_journal_balances(self, company, date_to):
        Journal = self.env["account.journal"].sudo()
        MoveLine = self.env["account.move.line"].sudo()
        scope_companies = self._scope_companies(company)
        journal_companies = self._journal_companies(company)
        journals = Journal.search([
            ("company_id", "in", journal_companies.ids),
            ("type", "in", ["bank", "cash"]),
            ("active", "=", True),
        ], order="type, sequence, name")
        account_ids = journals.mapped("default_account_id").ids
        balance_by_account = defaultdict(float)
        if account_ids:
            groups = MoveLine.read_group(
                [
                    ("company_id", "in", scope_companies.ids),
                    ("parent_state", "=", "posted"),
                    ("date", "<=", fields.Date.to_string(date_to)),
                    ("account_id", "in", account_ids),
                ],
                ["balance:sum"],
                ["account_id"],
                lazy=False,
            )
            for group in groups:
                if group.get("account_id"):
                    balance_by_account[group["account_id"][0]] = group.get("balance", 0.0)

        rows = []
        for journal in journals:
            account = journal.default_account_id
            domain = [
                ("company_id", "in", scope_companies.ids),
                ("parent_state", "=", "posted"),
                ("date", "<=", fields.Date.to_string(date_to)),
                ("account_id", "=", account.id),
            ]
            rows.append({
                "id": journal.id,
                "name": journal.display_name,
                "code": journal.code,
                "type": journal.type,
                "owner_company": journal.company_id.display_name,
                "shared": journal.company_id not in scope_companies,
                "account_id": account.id,
                "account": account.display_name,
                "balance": balance_by_account.get(account.id, 0.0),
                "domain": self._json_domain(domain),
            })
        max_balance = max([abs(row["balance"]) for row in rows] or [0.0])
        for row in rows:
            row["percent"] = self._percent(abs(row["balance"]), max_balance)
        return rows

    def _get_gl_overview(self, company, date_from, date_to):
        categories = [
            ("revenue", "Revenue", ["income", "income_other"], True, False, "#0f766e"),
            (
                "expenses",
                "Expenses",
                ["expense", "expense_depreciation", "expense_direct_cost"],
                False,
                False,
                "#ea580c",
            ),
            (
                "assets",
                "Assets",
                ["asset_receivable", "asset_cash", "asset_current", "asset_non_current", "asset_fixed", "asset_prepayments"],
                False,
                True,
                "#2563eb",
            ),
            (
                "liabilities",
                "Liabilities",
                ["liability_payable", "liability_credit_card", "liability_current", "liability_non_current"],
                True,
                True,
                "#7c3aed",
            ),
            (
                "equity",
                "Equity",
                ["equity", "equity_unaffected"],
                True,
                True,
                "#475569",
            ),
        ]
        MoveLine = self.env["account.move.line"].sudo()
        rows = []
        values = {}
        for key, label, account_types, invert, as_of, color in categories:
            domain = (
                self._company_domain(company)
                + [
                ("parent_state", "=", "posted"),
                ("account_id.account_type", "in", account_types),
                ("date", "<=", fields.Date.to_string(date_to)),
                ]
            )
            if not as_of:
                domain.append(("date", ">=", fields.Date.to_string(date_from)))
            grouped = MoveLine.read_group(domain, ["balance:sum"], [], lazy=False)
            balance = grouped[0].get("balance", 0.0) if grouped else 0.0
            amount = -balance if invert else balance
            values[key] = amount
            rows.append({
                "key": key,
                "label": label,
                "amount": amount,
                "color": color,
                "domain": self._json_domain(domain),
            })
        values["net_profit"] = values.get("revenue", 0.0) - values.get("expenses", 0.0)
        return {
            "rows": rows,
            "net_profit": values["net_profit"],
            "profit_margin": self._percent(values["net_profit"], values.get("revenue", 0.0)),
        }

    def _get_main_head_analysis(self, company, date_from, date_to):
        MoveLine = self.env["account.move.line"].sudo()
        Account = self.env["account.account"]
        heads = [
            ("assets", "Assets", "assets_main_head", False, True, "#2563eb", "fa-building"),
            ("liabilities", "Liabilities", "liability_main_head", True, True, "#7c3aed", "fa-balance-scale"),
            ("equity", "Equity", "equity_category", True, True, "#475569", "fa-pie-chart"),
            ("revenue", "Revenue", "revenue_category", True, False, "#0f766e", "fa-line-chart"),
            ("expense", "Expense", "expense_category", False, False, "#ea580c", "fa-shopping-basket"),
        ]
        rows = []
        category_rows = []
        for key, label, category_field, invert, as_of, color, icon in heads:
            domain = [
                ("company_id", "in", self._scope_companies(company).ids),
                ("parent_state", "=", "posted"),
                ("account_id.main_head", "=", key),
                ("date", "<=", fields.Date.to_string(date_to)),
            ]
            if not as_of:
                domain.append(("date", ">=", fields.Date.to_string(date_from)))
            lines = MoveLine.search(domain)
            raw_balance = sum(lines.mapped("balance"))
            amount = -raw_balance if invert else raw_balance
            rows.append({
                "key": key,
                "label": label,
                "amount": amount,
                "debit": sum(lines.mapped("debit")),
                "credit": sum(lines.mapped("credit")),
                "accounts": len(lines.mapped("account_id")),
                "entries": len(lines),
                "color": color,
                "icon": icon,
                "domain": self._json_domain(domain),
            })

            field = Account._fields.get(category_field)
            selection = field.selection if field else []
            if callable(selection):
                selection = selection(Account)
            labels = dict(selection or [])
            category_totals = defaultdict(float)
            category_accounts = defaultdict(set)
            for line in lines:
                value = line.account_id[category_field] or False
                category_totals[value] += line.balance
                category_accounts[value].add(line.account_id.id)
            for value, raw_category_amount in category_totals.items():
                category_amount = -raw_category_amount if invert else raw_category_amount
                category_domain = list(domain) + [
                    ("account_id.%s" % category_field, "=", value),
                ]
                category_rows.append({
                    "key": "%s:%s" % (key, value or "unclassified"),
                    "main_head": key,
                    "main_head_label": label,
                    "label": labels.get(value, _("Unclassified")),
                    "amount": category_amount,
                    "accounts": len(category_accounts[value]),
                    "color": color,
                    "domain": self._json_domain(category_domain),
                })

        max_amount = max([abs(row["amount"]) for row in rows] or [0.0])
        for row in rows:
            row["percent"] = self._percent(abs(row["amount"]), max_amount)
        category_rows.sort(key=lambda row: abs(row["amount"]), reverse=True)
        category_max = max([abs(row["amount"]) for row in category_rows] or [0.0])
        for row in category_rows:
            row["percent"] = self._percent(abs(row["amount"]), category_max)
        return {
            "rows": rows,
            "categories": category_rows[:10],
        }

    def _analytic_distribution_ids(self, distribution):
        ids = set()
        for analytic_key in (distribution or {}):
            for key_part in str(analytic_key).split(","):
                if key_part.strip().isdigit():
                    ids.add(int(key_part))
        return ids

    def _get_analytic_analysis(self, company, date_from, date_to):
        MoveLine = self.env["account.move.line"].sudo()
        domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [
                ("parent_state", "=", "posted"),
            ]
        )
        lines = MoveLine.search(domain)
        analytic_ids = set()
        for line in lines:
            analytic_ids.update(self._analytic_distribution_ids(line.analytic_distribution))
            if "cs_project_id" in line._fields and line.cs_project_id:
                analytic_ids.add(line.cs_project_id.id)
        analytics = self.env["account.analytic.account"].sudo().browse(
            sorted(analytic_ids)
        ).exists()
        analytic_by_id = {analytic.id: analytic for analytic in analytics}
        totals = defaultdict(lambda: {
            "debit": 0.0,
            "credit": 0.0,
            "balance": 0.0,
            "revenue": 0.0,
            "expense": 0.0,
            "entries": 0,
        })

        for line in lines:
            allocated_on_line = set()
            for analytic_key, percentage in (line.analytic_distribution or {}).items():
                try:
                    ratio = float(percentage or 0.0) / 100.0
                except (TypeError, ValueError):
                    ratio = 0.0
                if not ratio:
                    continue
                for key_part in str(analytic_key).split(","):
                    key_part = key_part.strip()
                    if not key_part.isdigit():
                        continue
                    analytic_id = int(key_part)
                    analytic = analytic_by_id.get(analytic_id)
                    if not analytic:
                        continue
                    row = totals[analytic_id]
                    row["debit"] += line.debit * ratio
                    row["credit"] += line.credit * ratio
                    row["balance"] += line.balance * ratio
                    if line.account_id.main_head == "expense":
                        row["expense"] += line.balance * ratio
                    elif line.account_id.main_head == "revenue":
                        row["revenue"] += -line.balance * ratio
                    if analytic_id not in allocated_on_line:
                        row["entries"] += 1
                        allocated_on_line.add(analytic_id)
            if (
                "cs_project_id" in line._fields
                and line.cs_project_id
                and line.cs_project_id.id in analytic_by_id
                and line.cs_project_id.id not in allocated_on_line
            ):
                row = totals[line.cs_project_id.id]
                row["debit"] += line.debit
                row["credit"] += line.credit
                row["balance"] += line.balance
                if line.account_id.main_head == "expense":
                    row["expense"] += line.balance
                elif line.account_id.main_head == "revenue":
                    row["revenue"] += -line.balance
                row["entries"] += 1

        dimension_meta = [
            ("project", "Projects", "#2563eb", "fa-briefcase"),
            ("department", "Departments", "#0f766e", "fa-sitemap"),
            ("section", "Sections", "#8b5cf6", "fa-object-group"),
            ("employee", "Employees", "#ea580c", "fa-users"),
            ("asset", "Assets", "#64748b", "fa-cubes"),
        ]
        dimensions = []
        project_rows = []
        for plan_type, label, color, icon in dimension_meta:
            type_analytics = analytics.filtered(
                lambda analytic: analytic.analytic_plan_type == plan_type
            )
            type_rows = []
            for analytic in type_analytics:
                values = totals[analytic.id]
                movement = values["debit"] + values["credit"]
                analytic_domain = list(domain) + [
                    ("analytic_distribution", "in", [analytic.id]),
                ]
                if plan_type == "project" and "cs_project_id" in MoveLine._fields:
                    analytic_domain = list(domain) + [
                        "|",
                        ("analytic_distribution", "in", [analytic.id]),
                        ("cs_project_id", "=", analytic.id),
                    ]
                row = {
                    "id": analytic.id,
                    "name": analytic.with_context(show_analytic_name=True).display_name,
                    "debit": values["debit"],
                    "credit": values["credit"],
                    "balance": values["balance"],
                    "movement": movement,
                    "revenue": values["revenue"],
                    "expense": values["expense"],
                    "net": values["revenue"] - values["expense"],
                    "entries": values["entries"],
                    "domain": self._json_domain(analytic_domain),
                }
                type_rows.append(row)
                if plan_type == "project":
                    project_rows.append(row)
            type_rows.sort(key=lambda row: row["movement"], reverse=True)
            total_movement = sum(row["movement"] for row in type_rows)
            top_rows = type_rows[:5]
            max_movement = max([row["movement"] for row in top_rows] or [0.0])
            for row in top_rows:
                row["percent"] = self._percent(row["movement"], max_movement)
            dimensions.append({
                "key": plan_type,
                "label": label,
                "color": color,
                "icon": icon,
                "count": len(type_rows),
                "entries": sum(row["entries"] for row in type_rows),
                "movement": total_movement,
                "top": top_rows,
            })

        project_rows.sort(
            key=lambda row: abs(row["revenue"]) + abs(row["expense"]),
            reverse=True,
        )
        project_rows = project_rows[:8]
        project_max = max([
            max(abs(row["revenue"]), abs(row["expense"]))
            for row in project_rows
        ] or [0.0])
        for row in project_rows:
            row["revenue_percent"] = self._percent(abs(row["revenue"]), project_max)
            row["expense_percent"] = self._percent(abs(row["expense"]), project_max)
        return {
            "dimensions": dimensions,
            "projects": project_rows,
        }

    def _get_data_quality(self, company, date_from, date_to):
        MoveLine = self.env["account.move.line"].sudo()
        Move = self.env["account.move"].sudo()
        period_domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
        )
        unclassified_domain = period_domain + [
            ("parent_state", "=", "posted"),
            ("account_id.main_head", "=", False),
        ]
        missing_analytic_domain = period_domain + [
            ("parent_state", "=", "posted"),
            ("account_id.main_head", "in", ["revenue", "expense"]),
            ("analytic_distribution", "=", False),
        ]
        draft_entry_domain = period_domain + [
            ("state", "=", "draft"),
            ("move_type", "=", "entry"),
        ]
        unclassified = MoveLine.search(unclassified_domain)
        missing_analytic = MoveLine.search(missing_analytic_domain)
        draft_entries = Move.search(draft_entry_domain)
        return [
            {
                "label": "Missing Main Head",
                "description": "Posted journal items on unclassified accounts",
                "model": "account.move.line",
                "count": len(unclassified),
                "amount": abs(sum(unclassified.mapped("balance"))),
                "color": "#ef4444",
                "icon": "fa-exclamation-triangle",
                "domain": self._json_domain(unclassified_domain),
            },
            {
                "label": "Missing Analytic Distribution",
                "description": "Revenue/expense lines without cost-center dimensions",
                "model": "account.move.line",
                "count": len(missing_analytic),
                "amount": sum(missing_analytic.mapped("debit")) + sum(missing_analytic.mapped("credit")),
                "color": "#f59e0b",
                "icon": "fa-tags",
                "domain": self._json_domain(missing_analytic_domain),
            },
            {
                "label": "Draft Journal Entries",
                "description": "Unposted general journal entries in this period",
                "model": "account.move",
                "count": len(draft_entries),
                "amount": sum(abs(move.amount_total_signed or 0.0) for move in draft_entries),
                "color": "#64748b",
                "icon": "fa-pencil-square-o",
                "domain": self._json_domain(draft_entry_domain),
            },
        ]

    def _get_close_checklist(self, company, date_from, date_to):
        Move = self.env["account.move"].sudo()
        Payment = self.env["account.payment"].sudo()
        MoveLine = self.env["account.move.line"].sudo()

        rows = []

        def add_row(label, description, model_name, domain, amount_getter=None, color="#f59e0b", icon="fa-check-square-o", severity="warning"):
            records = self.env[model_name].sudo().search(domain)
            amount = sum((amount_getter or self._record_amount)(record) for record in records)
            rows.append(self._dashboard_issue(
                label,
                description,
                model_name,
                domain,
                len(records),
                amount,
                color,
                icon,
                severity if records else "success",
            ))

        period_move_domain = self._company_domain(company) + self._date_domain("date", date_from, date_to)
        period_invoice_domain = self._company_domain(company) + self._date_domain("invoice_date", date_from, date_to)
        add_row(
            "Draft Journal Entries",
            "General journal entries still not posted for this period",
            "account.move",
            period_move_domain + [("state", "=", "draft"), ("move_type", "=", "entry")],
            lambda move: abs(move.amount_total_signed or 0.0),
            "#64748b",
            "fa-pencil-square-o",
        )
        add_row(
            "Draft Customer Invoices",
            "Customer invoices created but not posted",
            "account.move",
            period_invoice_domain + [("state", "=", "draft"), ("move_type", "=", "out_invoice")],
            self._invoice_amount,
            "#0ea5e9",
            "fa-file-text-o",
        )
        add_row(
            "Draft Vendor Bills",
            "Vendor bills created but not posted",
            "account.move",
            period_invoice_domain + [("state", "=", "draft"), ("move_type", "=", "in_invoice")],
            self._invoice_amount,
            "#8b5cf6",
            "fa-file-o",
        )
        add_row(
            "Draft Payments",
            "Registered payments still in draft",
            "account.payment",
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [("state", "=", "draft")],
            self._payment_amount,
            "#f97316",
            "fa-money",
        )

        account_ids = self.env["account.journal"].sudo().search([
            ("company_id", "in", self._journal_companies(company).ids),
            ("type", "in", ["bank", "cash"]),
            ("active", "=", True),
        ]).mapped("default_account_id").ids
        if account_ids:
            unreconciled_domain = (
                self._company_domain(company)
                + [
                    ("parent_state", "=", "posted"),
                    ("date", "<=", fields.Date.to_string(date_to)),
                    ("account_id", "in", account_ids),
                    ("balance", "!=", 0),
                    ("full_reconcile_id", "=", False),
                ]
            )
            unreconciled = MoveLine.search(unreconciled_domain)
            rows.append(self._dashboard_issue(
                "Unreconciled Bank/Cash Lines",
                "Posted bank or cash ledger lines still open",
                "account.move.line",
                unreconciled_domain,
                len(unreconciled),
                sum(abs(line.balance) for line in unreconciled),
                "#ef4444",
                "fa-university",
                "danger" if unreconciled else "success",
            ))

        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            Model = self.env[model_name].sudo()
            pending_states = self._pending_voucher_states(Model)
            if not pending_states:
                continue
            domain = (
                self._company_domain(company)
                + self._date_domain(date_field, date_from, date_to)
                + [("state", "in", pending_states)]
            )
            records = Model.search(domain)
            rows.append(self._dashboard_issue(
                "%s Pending Vouchers" % code,
                "%s waiting for approval or posting" % category,
                model_name,
                domain,
                len(records),
                self._sum_records(records, self._voucher_amount),
                color,
                "fa-credit-card",
                "warning" if records else "success",
            ))
        return rows

    def _get_exception_monitor(self, company, date_from, date_to):
        Move = self.env["account.move"].sudo()
        MoveLine = self.env["account.move.line"].sudo()
        rows = []

        move_domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [("state", "=", "posted")]
        )
        moves = Move.search(move_domain)
        shared_journal_moves = moves.filtered(
            lambda move: move.journal_id.company_id
            and move.company_id
            and move.journal_id.company_id != move.company_id
        )
        shared_domain = [("id", "in", shared_journal_moves.ids)]
        rows.append(self._dashboard_issue(
            "Shared Journal Entries",
            "Entries posted in branch scope using a parent/shared journal",
            "account.move",
            shared_domain,
            len(shared_journal_moves),
            sum(abs(move.amount_total_signed or 0.0) for move in shared_journal_moves),
            "#0ea5e9",
            "fa-random",
            "neutral" if shared_journal_moves else "success",
        ))

        line_domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [("parent_state", "=", "posted")]
        )
        lines = MoveLine.search(line_domain)
        account_mismatch = lines.filtered(
            lambda line: line.account_id.company_id
            and line.company_id
            and line.account_id.company_id != line.company_id
        )
        account_mismatch_domain = [("id", "in", account_mismatch.ids)]
        rows.append(self._dashboard_issue(
            "Account Company Mismatch",
            "Journal items using an account owned by a different company",
            "account.move.line",
            account_mismatch_domain,
            len(account_mismatch),
            sum(abs(line.balance) for line in account_mismatch),
            "#ef4444",
            "fa-warning",
            "danger" if account_mismatch else "success",
        ))

        partner_missing_domain = line_domain + [
            ("account_id.account_type", "in", ["asset_receivable", "liability_payable"]),
            ("partner_id", "=", False),
        ]
        partner_missing = MoveLine.search(partner_missing_domain)
        rows.append(self._dashboard_issue(
            "Partner Missing on AR/AP",
            "Receivable or payable lines without customer/vendor",
            "account.move.line",
            partner_missing_domain,
            len(partner_missing),
            sum(abs(line.balance) for line in partner_missing),
            "#f97316",
            "fa-user-times",
            "warning" if partner_missing else "success",
        ))

        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            Model = self.env[model_name].sudo()
            posted_domain = (
                self._company_domain(company)
                + self._date_domain(date_field, date_from, date_to)
                + [("state", "=", "posted"), ("journal_entry_id", "=", False)]
            )
            records = Model.search(posted_domain)
            rows.append(self._dashboard_issue(
                "%s Posted Without JE" % code,
                "Posted custom voucher missing linked journal entry",
                model_name,
                posted_domain,
                len(records),
                self._sum_records(records, self._voucher_amount),
                color,
                "fa-chain-broken",
                "danger" if records else "success",
            ))

            LineModel, parent_field = self._custom_voucher_line_model(model_name)
            if not LineModel or "analytic_distribution" not in LineModel._fields:
                continue
            line_base = (
                self._company_domain(company)
                + [
                    ("%s.%s" % (parent_field, date_field), ">=", fields.Date.to_string(date_from)),
                    ("%s.%s" % (parent_field, date_field), "<=", fields.Date.to_string(date_to)),
                    ("%s.state" % parent_field, "!=", "cancel"),
                    ("analytic_distribution", "=", False),
                ]
            )
            if "cs_project_id" in LineModel._fields:
                line_base.append(("cs_project_id", "=", False))
            voucher_lines = LineModel.search(line_base)
            rows.append(self._dashboard_issue(
                "%s Lines Missing Cost Center" % code,
                "Voucher lines without analytic/project distribution",
                LineModel._name,
                line_base,
                len(voucher_lines),
                sum(getattr(line, "total_amount", 0.0) or 0.0 for line in voucher_lines),
                "#f59e0b",
                "fa-tags",
                "warning" if voucher_lines else "success",
            ))
        return rows

    def _get_cash_forecast(self, company, date_to, journal_rows):
        current_cash = sum(row.get("balance", 0.0) for row in journal_rows)
        receivable_items = self._open_invoice_items(company, date_to + relativedelta(days=30), "out_invoice")
        payable_items = self._open_invoice_items(company, date_to + relativedelta(days=30), "in_invoice")

        def empty_buckets():
            return {
                "overdue": 0.0,
                "next_7": 0.0,
                "next_15": 0.0,
                "next_30": 0.0,
            }

        def fill_buckets(items):
            buckets = empty_buckets()
            for item in items:
                move = item["move"]
                due_date = move.invoice_date_due or move.invoice_date or date_to
                days = (due_date - date_to).days
                if days < 0:
                    buckets["overdue"] += item["residual"]
                elif days <= 7:
                    buckets["next_7"] += item["residual"]
                elif days <= 15:
                    buckets["next_15"] += item["residual"]
                elif days <= 30:
                    buckets["next_30"] += item["residual"]
            return buckets

        receivable = fill_buckets(receivable_items)
        payable = fill_buckets(payable_items)
        pending_receipts = []
        pending_payments = []
        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            Model = self.env[model_name].sudo()
            pending_states = self._pending_voucher_states(Model)
            if not pending_states:
                continue
            domain = (
                self._company_domain(company)
                + [
                    (date_field, "<=", fields.Date.to_string(date_to + relativedelta(days=30))),
                    ("state", "in", pending_states),
                ]
            )
            records = Model.search(domain)
            row = {
                "code": code,
                "model": model_name,
                "count": len(records),
                "amount": self._sum_records(records, self._voucher_amount),
                "color": color,
                "domain": self._json_domain(domain),
            }
            if category == "Receipts":
                pending_receipts.append(row)
            else:
                pending_payments.append(row)

        expected_receipts = sum(receivable.values()) + sum(row["amount"] for row in pending_receipts)
        expected_payments = sum(payable.values()) + sum(row["amount"] for row in pending_payments)
        receivable_moves = self.env["account.move"].browse([item["move"].id for item in receivable_items])
        payable_moves = self.env["account.move"].browse([item["move"].id for item in payable_items])
        return {
            "current_cash": current_cash,
            "receivable": receivable,
            "payable": payable,
            "expected_receipts_30": expected_receipts,
            "expected_payments_30": expected_payments,
            "projected_30": current_cash + expected_receipts - expected_payments,
            "pending_receipts": pending_receipts,
            "pending_payments": pending_payments,
            "receivable_domain": self._json_domain([("id", "in", receivable_moves.ids)]),
            "payable_domain": self._json_domain([("id", "in", payable_moves.ids)]),
        }

    def _get_voucher_sla(self, company, date_from, date_to):
        today = fields.Date.context_today(self)
        rows = []
        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            Model = self.env[model_name].sudo()
            pending_states = self._pending_voucher_states(Model)
            if not pending_states:
                continue
            domain = (
                self._company_domain(company)
                + self._date_domain(date_field, date_from, date_to)
                + [("state", "in", pending_states)]
            )
            records = Model.search(domain)
            ages = []
            for record in records:
                start_date = record.create_date.date() if record.create_date else record[date_field]
                if start_date:
                    ages.append(max((today - start_date).days, 0))
            oldest_age = max(ages or [0])
            rows.append({
                "code": code,
                "label": "%s Approval SLA" % code,
                "model": model_name,
                "count": len(records),
                "amount": self._sum_records(records, self._voucher_amount),
                "avg_age": round(sum(ages) / len(ages), 1) if ages else 0.0,
                "oldest_age": oldest_age,
                "overdue_count": len([age for age in ages if age > 7]),
                "color": color,
                "severity": "danger" if oldest_age > 14 else "warning" if oldest_age > 7 else "success",
                "domain": self._json_domain(domain),
            })
        return rows

    def _get_vat_audit(self, company, date_from, date_to, vat_data):
        Move = self.env["account.move"].sudo()
        MoveLine = self.env["account.move.line"].sudo()
        rows = []

        def add_moves(label, description, domain, color, icon, severity="warning"):
            moves = Move.search(domain)
            rows.append(self._dashboard_issue(
                label,
                description,
                "account.move",
                domain,
                len(moves),
                self._sum_records(moves, self._invoice_amount),
                color,
                icon,
                severity if moves else "success",
            ))
            return moves

        invoice_base = self._company_domain(company) + self._date_domain("invoice_date", date_from, date_to) + [("state", "=", "posted")]
        add_moves(
            "Customer VAT Missing",
            "Posted sales invoices where customer VAT number is empty",
            invoice_base + [("move_type", "=", "out_invoice"), ("partner_id.vat", "=", False)],
            "#ef4444",
            "fa-id-card-o",
        )
        add_moves(
            "Vendor VAT Missing",
            "Posted vendor bills where supplier VAT number is empty",
            invoice_base + [("move_type", "=", "in_invoice"), ("partner_id.vat", "=", False)],
            "#f97316",
            "fa-id-card-o",
        )

        customer_moves = Move.search(invoice_base + [("move_type", "=", "out_invoice")])
        vendor_moves = Move.search(invoice_base + [("move_type", "=", "in_invoice")])
        customer_no_tax = customer_moves.filtered(
            lambda move: any(not line.tax_ids for line in move.invoice_line_ids.filtered(lambda line: not line.display_type))
        )
        vendor_no_tax = vendor_moves.filtered(
            lambda move: any(not line.tax_ids for line in move.invoice_line_ids.filtered(lambda line: not line.display_type))
        )
        rows.append(self._dashboard_issue(
            "Sales Lines Without Tax",
            "Posted sales invoices with at least one invoice line missing tax",
            "account.move",
            [("id", "in", customer_no_tax.ids)],
            len(customer_no_tax),
            self._sum_records(customer_no_tax, self._invoice_amount),
            "#0ea5e9",
            "fa-percent",
            "warning" if customer_no_tax else "success",
        ))
        rows.append(self._dashboard_issue(
            "Purchase Lines Without Tax",
            "Posted vendor bills with at least one bill line missing tax",
            "account.move",
            [("id", "in", vendor_no_tax.ids)],
            len(vendor_no_tax),
            self._sum_records(vendor_no_tax, self._invoice_amount),
            "#8b5cf6",
            "fa-percent",
            "warning" if vendor_no_tax else "success",
        ))

        manual_tax_domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [
                ("parent_state", "=", "posted"),
                ("tax_line_id", "!=", False),
                ("tax_line_id.type_tax_use", "not in", ["sale", "purchase"]),
            ]
        )
        manual_tax_lines = MoveLine.search(manual_tax_domain)
        rows.append(self._dashboard_issue(
            "Untyped Tax Lines",
            "Tax lines not classified as sales or purchases",
            "account.move.line",
            manual_tax_domain,
            len(manual_tax_lines),
            sum(abs(line.balance) for line in manual_tax_lines),
            "#64748b",
            "fa-question-circle",
            "warning" if manual_tax_lines else "success",
        ))
        return {
            "checks": rows,
            "output_vat": vat_data.get("output_vat", 0.0),
            "input_vat": vat_data.get("input_vat", 0.0),
            "net_vat": vat_data.get("net_vat", 0.0),
        }

    def _get_bank_health(self, company, date_to, journal_rows):
        MoveLine = self.env["account.move.line"].sudo()
        rows = []
        for journal in journal_rows:
            account_id = journal.get("account_id")
            if not account_id:
                continue
            base_domain = (
                self._company_domain(company)
                + [
                    ("parent_state", "=", "posted"),
                    ("date", "<=", fields.Date.to_string(date_to)),
                    ("account_id", "=", account_id),
                ]
            )
            unreconciled_domain = base_domain + [
                ("balance", "!=", 0),
                ("full_reconcile_id", "=", False),
            ]
            old_unreconciled_domain = unreconciled_domain + [
                ("date", "<=", fields.Date.to_string(date_to - relativedelta(days=30))),
            ]
            unreconciled = MoveLine.search(unreconciled_domain)
            old_unreconciled = MoveLine.search(old_unreconciled_domain)
            last_line = MoveLine.search(base_domain, order="date desc, id desc", limit=1)
            severity = "danger" if journal.get("balance", 0.0) < 0 or old_unreconciled else "warning" if unreconciled or journal.get("shared") else "success"
            rows.append({
                **journal,
                "unreconciled_count": len(unreconciled),
                "unreconciled_amount": sum(abs(line.balance) for line in unreconciled),
                "old_unreconciled_count": len(old_unreconciled),
                "old_unreconciled_amount": sum(abs(line.balance) for line in old_unreconciled),
                "last_entry_date": fields.Date.to_string(last_line.date) if last_line else False,
                "severity": severity,
                "unreconciled_domain": self._json_domain(unreconciled_domain),
                "old_unreconciled_domain": self._json_domain(old_unreconciled_domain),
            })
        return rows

    def _get_project_profitability(self, company, date_from, date_to, analytics_data):
        MoveLine = self.env["account.move.line"].sudo()
        domain = (
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [
                ("parent_state", "=", "posted"),
                ("account_id.main_head", "in", ["revenue", "expense"]),
            ]
        )
        lines = MoveLine.search(domain)
        analytic_ids = set()
        for line in lines:
            analytic_ids.update(self._analytic_distribution_ids(line.analytic_distribution))
            if "cs_project_id" in line._fields and line.cs_project_id:
                analytic_ids.add(line.cs_project_id.id)
        analytics = self.env["account.analytic.account"].sudo().browse(sorted(analytic_ids)).exists()
        project_analytics = analytics.filtered(lambda analytic: analytic.analytic_plan_type == "project")
        project_by_id = {project.id: project for project in project_analytics}
        totals = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0, "line_ids": set()})
        missing_lines = self.env["account.move.line"].sudo()

        for line in lines:
            project_allocations = {}
            if "cs_project_id" in line._fields and line.cs_project_id:
                project_allocations[line.cs_project_id.id] = 1.0
            for analytic_key, percentage in (line.analytic_distribution or {}).items():
                try:
                    ratio = float(percentage or 0.0) / 100.0
                except (TypeError, ValueError):
                    ratio = 0.0
                if not ratio:
                    continue
                for key_part in str(analytic_key).split(","):
                    key_part = key_part.strip()
                    if not key_part.isdigit():
                        continue
                    analytic_id = int(key_part)
                    if analytic_id not in project_by_id:
                        continue
                    project_allocations.setdefault(analytic_id, ratio)
            project_allocations = {
                project_id: ratio
                for project_id, ratio in project_allocations.items()
                if project_id in project_by_id
            }
            if not project_allocations:
                missing_lines |= line
                continue
            for project_id, ratio in project_allocations.items():
                row = totals[project_id]
                if line.account_id.main_head == "revenue":
                    row["revenue"] += -line.balance * ratio
                else:
                    row["expense"] += line.balance * ratio
                row["line_ids"].add(line.id)

        rows = []
        for project_id, values in totals.items():
            project = project_by_id.get(project_id)
            if not project:
                continue
            revenue = values["revenue"]
            expense = values["expense"]
            net = revenue - expense
            rows.append({
                "id": project.id,
                "name": project.with_context(show_analytic_name=True).display_name,
                "revenue": revenue,
                "expense": expense,
                "net": net,
                "margin": self._percent(net, revenue),
                "entries": len(values["line_ids"]),
                "domain": self._json_domain([("id", "in", list(values["line_ids"]))]),
            })

        rows.sort(key=lambda row: abs(row["revenue"]) + abs(row["expense"]), reverse=True)
        total_revenue = sum(row["revenue"] for row in rows)
        total_expense = sum(row["expense"] for row in rows)
        return {
            "revenue": total_revenue,
            "expense": total_expense,
            "net": total_revenue - total_expense,
            "margin": self._percent(total_revenue - total_expense, total_revenue),
            "top_profit": sorted(rows, key=lambda row: row["net"], reverse=True)[:5],
            "losses": [row for row in sorted(rows, key=lambda row: row["net"]) if row["net"] < 0][:5],
            "missing_project_count": len(missing_lines),
            "missing_project_amount": sum(abs(line.balance) for line in missing_lines),
            "missing_project_domain": self._json_domain([("id", "in", missing_lines.ids)]),
            "source_projects": analytics_data.get("projects", []),
        }

    def _get_vat_position(self, company, date_from, date_to):
        MoveLine = self.env["account.move.line"].sudo()
        base = (
            self._company_domain(company)
            + [
                ("parent_state", "=", "posted"),
                ("tax_line_id", "!=", False),
            ]
            + self._date_domain("date", date_from, date_to)
        )
        output_domain = base + [("tax_line_id.type_tax_use", "=", "sale")]
        input_domain = base + [("tax_line_id.type_tax_use", "=", "purchase")]
        output_balance = sum(MoveLine.search(output_domain).mapped("balance"))
        input_balance = sum(MoveLine.search(input_domain).mapped("balance"))
        output_vat = -output_balance
        input_vat = input_balance
        return {
            "output_vat": output_vat,
            "input_vat": input_vat,
            "net_vat": output_vat - input_vat,
            "output_domain": self._json_domain(output_domain),
            "input_domain": self._json_domain(input_domain),
        }

    def _get_top_open_partners(self, company, date_to, move_type):
        items = self._open_invoice_items(company, date_to, move_type)
        records = self.env["account.move"].browse([
            item["move"].id for item in items
        ])
        totals = defaultdict(lambda: {"amount": 0.0, "count": 0, "partner": False})
        for item in items:
            move = item["move"]
            partner = move.commercial_partner_id or move.partner_id
            key = partner.id or 0
            totals[key]["partner"] = partner
            totals[key]["amount"] += item["residual"]
            totals[key]["count"] += 1
        rows = sorted(totals.values(), key=lambda item: item["amount"], reverse=True)[:7]
        max_amount = max([row["amount"] for row in rows] or [0.0])
        base = [("id", "in", records.ids)]
        result = []
        for row in rows:
            partner = row["partner"]
            partner_domain = base + [
                ("commercial_partner_id", "=", partner.id if partner else False),
            ]
            result.append({
                "id": partner.id if partner else False,
                "name": partner.display_name if partner else _("Unassigned"),
                "amount": row["amount"],
                "count": row["count"],
                "percent": self._percent(row["amount"], max_amount),
                "domain": self._json_domain(partner_domain),
            })
        return result

    def _selection_label(self, record, field_name):
        selection = record._fields[field_name].selection
        if callable(selection):
            selection = selection(record)
        return dict(selection).get(record[field_name], record[field_name] or "")

    def _get_recent_activity(self, company, date_from, date_to):
        activity = []
        moves = self.env["account.move"].sudo().search(
            self._company_domain(company)
            + self._date_domain("date", date_from, date_to)
            + [("move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund", "entry"])],
            order="date desc, id desc",
            limit=8,
        )
        move_labels = {
            "out_invoice": "Customer Invoice",
            "out_refund": "Customer Credit Note",
            "in_invoice": "Vendor Bill",
            "in_refund": "Vendor Credit Note",
            "entry": "Journal Entry",
        }
        for move in moves:
            activity.append({
                "model": "account.move",
                "id": move.id,
                "name": move.display_name,
                "type": move_labels.get(move.move_type, "Journal Entry"),
                "date": fields.Date.to_string(move.date),
                "partner": move.partner_id.display_name or "",
                "amount": self._invoice_amount(move) if move.move_type != "entry" else abs(move.amount_total_signed or 0.0),
                "state": self._selection_label(move, "state"),
                "timestamp": move.date,
            })

        for model_name, code, category, color, date_field in CUSTOM_VOUCHERS:
            records = self.env[model_name].sudo().search(
                self._company_domain(company)
                + self._date_domain(date_field, date_from, date_to),
                order="%s desc, id desc" % date_field,
                limit=4,
            )
            for record in records:
                record_date = record[date_field]
                activity.append({
                    "model": model_name,
                    "id": record.id,
                    "name": record.display_name,
                    "type": code,
                    "date": fields.Date.to_string(record_date),
                    "partner": "",
                "amount": self._voucher_amount(record),
                    "state": self._selection_label(record, "state"),
                    "timestamp": record_date,
                })

        activity.sort(
            key=lambda item: (item["timestamp"] or date.min, item["id"]),
            reverse=True,
        )
        for item in activity:
            item.pop("timestamp", None)
        return activity[:10]

    def _percent(self, value, total):
        if not total:
            return 0.0
        return round((float(value or 0.0) / abs(float(total))) * 100.0, 2)
