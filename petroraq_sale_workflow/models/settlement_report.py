from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date, formatLang


def settlement_status(amount, balance, due_date, settled_date, as_of, is_zero, purchase=False):
    """Classify signed invoice/credit balances without using today's residual."""
    if amount < 0:
        return "Credit Applied" if is_zero(balance) else "Credit Outstanding"
    if is_zero(balance):
        if not settled_date:
            return "Settled"
        verb = "Paid" if purchase else "Received"
        return ("Early " if settled_date < due_date else "Late " if settled_date > due_date else "") + verb
    if not is_zero(amount - balance):
        return "Partially Paid" if purchase else "Partially Received"
    return "Overdue" if due_date < as_of else "Pending"


class SettlementReportWizard(models.TransientModel):
    _name = "pr.settlement.report.wizard"
    _description = "Customer Receivable / Vendor Payable Report"

    report_type = fields.Selection([("sale", "Customer Receivables"), ("purchase", "Vendor Payables")],
                                   required=True, default="sale")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    partner_ids = fields.Many2many("res.partner", string="Customers / Vendors",
                                  help="Leave empty for all customers/vendors. Includes their child contacts.")
    date_from = fields.Date(string="Posting Date From", help="Leave empty for all dates up to the cutoff.")
    date_as_of = fields.Date(string="As of", required=True, default=fields.Date.context_today)
    balance_filter = fields.Selection([
        ("all", "All"), ("open", "Outstanding"), ("settled", "Settled"), ("overdue", "Overdue"),
    ], required=True, default="all", string="Show")
    include_credit_notes = fields.Boolean(default=True)

    def _check_report_access(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        if not self.env.user.has_group("account.group_account_user"):
            raise AccessError(_("Accounting access is required to export this report."))
        if self.company_id not in self.env.companies:
            raise AccessError(_("Select a company enabled in your current company selection."))
        if self.date_from and self.date_from > self.date_as_of:
            raise ValidationError(_("The start date must be on or before the as-of date."))

    def action_print_pdf(self):
        self._check_report_access()
        return self.env.ref("petroraq_sale_workflow.action_settlement_report_pdf").report_action(self)

    def _get_report_data(self):
        self._check_report_access()
        purchase = self.report_type == "purchase"
        currency = self.company_id.currency_id
        sign = -1 if purchase else 1
        types = ["in_invoice" if purchase else "out_invoice"]
        if self.include_credit_notes:
            types.append("in_refund" if purchase else "out_refund")
        domain = [("company_id", "=", self.company_id.id), ("state", "=", "posted"),
                  ("move_type", "in", types), ("date", "<=", self.date_as_of)]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.partner_ids:
            domain.append(("commercial_partner_id", "child_of", self.partner_ids.commercial_partner_id.ids))
        moves = self.env["account.move"].search(domain, order="invoice_date, name, id")
        account_type = "liability_payable" if purchase else "asset_receivable"
        lines = moves.line_ids.filtered(lambda line: line.account_id.account_type == account_type)
        # Rebuild residuals at the cutoff. Current amount_residual would include
        # later payments and give incorrect historical balances.
        partials = self.env["account.partial.reconcile"].search([
            ("max_date", "<=", self.date_as_of), "|",
            ("debit_move_id", "in", lines.ids), ("credit_move_id", "in", lines.ids),
        ]) if lines else self.env["account.partial.reconcile"]
        adjustments = defaultdict(float)
        payment_dates = defaultdict(list)
        for partial in partials:
            adjustments[partial.debit_move_id.id] -= partial.amount
            adjustments[partial.credit_move_id.id] += partial.amount
            payment_dates[partial.debit_move_id.id].append(partial.max_date)
            payment_dates[partial.credit_move_id.id].append(partial.max_date)
        by_move = defaultdict(list)
        for line in lines:
            by_move[line.move_id.id].append(line)
        rows = []
        for move in moves:
            terms = by_move[move.id]
            if not terms:
                continue
            amount = currency.round(sign * sum(line.balance for line in terms))
            balance = currency.round(sign * sum(line.balance + adjustments[line.id] for line in terms))
            paid = currency.round(amount - balance)
            start = move.invoice_date or move.date
            open_terms = [line for line in terms if not currency.is_zero(line.balance + adjustments[line.id])]
            due_dates = [line.date_maturity or start for line in (open_terms or terms)]
            due = min(due_dates) if open_terms else max(due_dates)
            dates = [day for line in terms for day in payment_dates[line.id]]
            received_date = max(dates) if dates else False
            settled = currency.is_zero(balance)
            overdue = sum(sign * (line.balance + adjustments[line.id]) for line in open_terms
                          if (line.date_maturity or start) < self.date_as_of)
            if self.balance_filter == "open" and settled:
                continue
            if self.balance_filter == "settled" and not settled:
                continue
            if self.balance_filter == "overdue" and currency.compare_amounts(overdue, 0) <= 0:
                continue
            if purchase:
                orders = move.invoice_line_ids.purchase_line_id.order_id
                references = orders.mapped("partner_ref")
            else:
                orders = move.invoice_line_ids.sale_line_ids.order_id
                references = [order.po_number or order.client_order_ref for order in orders]
            order_amount = sum(order.currency_id._convert(
                order.amount_total, currency, self.company_id,
                fields.Date.to_date(order.date_order) or start,
            ) for order in orders)
            status = settlement_status(amount, balance, due, received_date, self.date_as_of,
                                       currency.is_zero, purchase=purchase)
            rows.append({
                "partner": move.commercial_partner_id.display_name,
                "reference": ", ".join(dict.fromkeys(filter(None, references))),
                "order_amount": order_amount if orders else None,
                "order": ", ".join(orders.mapped("name")) or move.invoice_origin or "",
                "credit_days": max((due - start).days, 0), "invoice_date": start,
                "invoice": move.name, "amount": amount, "paid": paid, "balance": balance,
                "due_date": due, "received_date": received_date,
                "overdue_days": max(((received_date if settled and received_date else self.date_as_of) - due).days, 0)
                    if amount > 0 else 0,
                "status": status,
                "cycle_days": max(((received_date if settled and received_date else self.date_as_of) - start).days, 0),
            })
        rows.sort(key=lambda row: (row["partner"].casefold(), row["invoice_date"], row["invoice"]))
        return {
            "title": _("Vendor Payable Report") if purchase else _("Customer Receivable Report"),
            "purchase": purchase, "rows": rows, "currency": currency,
            "partners": ", ".join(self.partner_ids.mapped("display_name")) or _("All"),
            "filter_label": dict(self._fields["balance_filter"].selection)[self.balance_filter],
            "totals": {key: sum(row[key] for row in rows) for key in ("amount", "paid", "balance")},
        }


class SettlementReport(models.AbstractModel):
    _name = "report.petroraq_sale_workflow.settlement_report_pdf"
    _description = "Receivables and Payables PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["pr.settlement.report.wizard"].browse(docids).exists()
        docs.ensure_one()
        report = docs._get_report_data()
        return {
            "doc_ids": docs.ids, "doc_model": docs._name, "docs": docs, "report": report,
            "date_text": lambda day: format_date(self.env, day) if day else "—",
            "money": lambda value: formatLang(self.env, value, digits=report["currency"].decimal_places)
                if value is not None else "—",
        }
