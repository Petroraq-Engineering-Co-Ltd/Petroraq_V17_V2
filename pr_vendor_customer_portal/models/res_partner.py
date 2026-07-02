# -*- coding: utf-8 -*-

from collections import OrderedDict

from odoo import fields, models
from odoo.osv import expression
from odoo.tools import format_date


PARTNER_BALANCE_ACCOUNT_TYPES = ("asset_receivable", "liability_payable")
INVOICE_MOVE_TYPES = (
    "out_invoice",
    "out_refund",
    "in_invoice",
    "in_refund",
    "out_receipt",
    "in_receipt",
)
PORTAL_INVOICE_MOVE_TYPES = (
    "out_invoice",
    "out_refund",
    "in_invoice",
    "in_refund",
)


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _pr_portal_statement_partner_ids(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        return self.sudo().search([
            ("commercial_partner_id", "=", commercial_partner.id),
        ]).ids

    def _pr_portal_statement_has_shared_ledger(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        ledger_account = commercial_partner.pr_ledger_account_id
        if not ledger_account:
            return False
        mapped_partners = self.sudo().search([
            ("pr_ledger_account_id", "=", ledger_account.id),
        ]).mapped("commercial_partner_id")
        return bool(mapped_partners - commercial_partner)

    def _pr_portal_statement_mapped_account(self, company):
        """Return the configured ledger usable by the active company.

        The accounting setup allows a child company to use accounts owned by
        its parent company, so the portal must recognize both companies.
        """
        self.ensure_one()
        configured_account = self.commercial_partner_id.pr_ledger_account_id
        if not configured_account:
            return configured_account
        allowed_companies = company | company.parent_id
        return configured_account.filtered(
            lambda account: not account.company_id
            or account.company_id in allowed_companies
        )

    def _pr_portal_statement_domain(
        self, company, date_from=False, date_to=False, opening=False
    ):
        """Posted partner ledger lines authorized for this commercial partner.

        This mirrors the custom Account Ledger behavior:
        - lines posted directly to the mapped legacy ledger account; and
        - receivable/payable lines from invoices, payments, and journal entries
          posted for this partner or one of its contacts.

        If a ledger account is mapped to more than one commercial partner,
        direct account lines are additionally restricted by partner to prevent
        cross-customer disclosure through the portal.
        """
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        partner_ids = commercial_partner._pr_portal_statement_partner_ids()
        mapped_account = commercial_partner._pr_portal_statement_mapped_account(company)

        partner_branch = [
            ("partner_id", "in", partner_ids),
            ("account_id.account_type", "in", PARTNER_BALANCE_ACCOUNT_TYPES),
        ]
        if mapped_account:
            partner_branch.append(("account_id", "!=", mapped_account.id))

        branches = [partner_branch]
        if mapped_account:
            mapped_branch = [("account_id", "=", mapped_account.id)]
            if commercial_partner._pr_portal_statement_has_shared_ledger():
                mapped_branch.append(("partner_id", "in", partner_ids))
            branches.append(mapped_branch)

        domain = [
            ("company_id", "=", company.id),
            ("move_id.state", "=", "posted"),
        ]
        if opening:
            domain.append(("date", "<", date_from))
        else:
            if date_from:
                domain.append(("date", ">=", date_from))
            if date_to:
                domain.append(("date", "<=", date_to))
        return expression.AND([domain, expression.OR(branches)])

    def _pr_portal_statement_count(self, company):
        self.ensure_one()
        domain = self._pr_portal_statement_domain(
            company,
            date_to=fields.Date.context_today(self),
        )
        return self.env["account.move.line"].sudo().search_count(domain)

    @staticmethod
    def _pr_statement_reference(line):
        move = line.move_id
        candidates = (
            move.invoice_origin if move.move_type in INVOICE_MOVE_TYPES else False,
            line.ref,
            move.ref,
            move.payment_reference,
            move.name,
        )
        return next((str(value).strip() for value in candidates if value), "")

    @staticmethod
    def _pr_statement_description(line):
        move = line.move_id
        candidates = (
            line.name,
            move.invoice_origin,
            move.ref,
            move.payment_reference,
            move.name,
        )
        return next((str(value).strip() for value in candidates if value), "")

    @staticmethod
    def _pr_statement_group_key(line):
        """Match Account Ledger's always-on invoice merge behavior.

        Invoice lines are collapsed per invoice and source account. Ordinary
        journal-entry lines remain separate even when they belong to one move.
        """
        if line.move_id.move_type in INVOICE_MOVE_TYPES:
            return ("invoice", line.move_id.id, line.account_id.id)
        return ("line", line.id)

    def _pr_get_portal_statement_data(self, company, date_from, date_to):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        MoveLine = self.env["account.move.line"].sudo()
        mapped_account = commercial_partner._pr_portal_statement_mapped_account(company)

        opening_domain = commercial_partner._pr_portal_statement_domain(
            company, date_from=date_from, opening=True
        )
        period_domain = commercial_partner._pr_portal_statement_domain(
            company, date_from=date_from, date_to=date_to
        )

        opening_groups = MoveLine.read_group(
            opening_domain,
            ["balance:sum"],
            ["account_id"],
            lazy=False,
        )
        opening_by_account = {
            group["account_id"][0]: group.get("balance", 0.0)
            for group in opening_groups
            if group.get("account_id")
        }
        if mapped_account:
            opening_by_account = {
                mapped_account.id: sum(opening_by_account.values())
            }

        move_lines = MoveLine.search(
            period_domain,
            order="date, id" if mapped_account else "account_id, date, id",
        )
        grouped_move_lines = OrderedDict()
        for line in move_lines:
            display_account = mapped_account or line.account_id
            key = commercial_partner._pr_statement_group_key(line)
            if key not in grouped_move_lines:
                grouped_move_lines[key] = {
                    "account": display_account,
                    "move": line.move_id,
                    "line": line,
                    "debit": 0.0,
                    "credit": 0.0,
                }
            grouped_move_lines[key]["debit"] += line.debit
            grouped_move_lines[key]["credit"] += line.credit

        grouped_by_account = OrderedDict()
        for group in grouped_move_lines.values():
            account = group["account"]
            grouped_by_account.setdefault(account.id, {
                "account": account,
                "entries": [],
                "period_debit": 0.0,
                "period_credit": 0.0,
            })
            grouped_by_account[account.id]["entries"].append(group)
            grouped_by_account[account.id]["period_debit"] += group["debit"]
            grouped_by_account[account.id]["period_credit"] += group["credit"]

        account_ids = set(opening_by_account) | set(grouped_by_account)
        if mapped_account:
            account_ids.add(mapped_account.id)
        accounts = self.env["account.account"].sudo().browse(list(account_ids)).exists().sorted(
            lambda account: (account.code or "", account.id)
        )

        account_groups = []
        total_opening = 0.0
        total_debit = 0.0
        total_credit = 0.0
        ledger_total_debit = 0.0
        ledger_total_credit = 0.0
        amount_receivable = 0.0
        amount_payable = 0.0
        for account in accounts:
            grouped_account = grouped_by_account.get(account.id, {})
            opening_balance = opening_by_account.get(account.id, 0.0)
            opening_debit = max(opening_balance, 0.0)
            opening_credit = max(-opening_balance, 0.0)
            period_debit = grouped_account.get("period_debit", 0.0)
            period_credit = grouped_account.get("period_credit", 0.0)
            account_total_debit = opening_debit + period_debit
            account_total_credit = opening_credit + period_credit
            running_balance = opening_balance
            entries = []

            for group in grouped_account.get("entries", []):
                line = group["line"]
                move = group["move"]
                running_balance += group["debit"] - group["credit"]
                entries.append({
                    "date": line.date,
                    "date_display": format_date(self.env, line.date),
                    "move_id": move.id,
                    "move_name": move.name,
                    "move_type": move.move_type,
                    "is_invoice": move.move_type in PORTAL_INVOICE_MOVE_TYPES,
                    "reference": commercial_partner._pr_statement_reference(line),
                    "description": commercial_partner._pr_statement_description(line),
                    "journal": line.journal_id.name,
                    "debit": group["debit"],
                    "credit": group["credit"],
                    "balance": running_balance,
                })

            closing_balance = opening_balance + period_debit - period_credit
            amount_receivable += max(closing_balance, 0.0)
            amount_payable += max(-closing_balance, 0.0)
            total_opening += opening_balance
            total_debit += period_debit
            total_credit += period_credit
            ledger_total_debit += account_total_debit
            ledger_total_credit += account_total_credit
            account_groups.append({
                "id": account.id,
                "code": account.code,
                "name": account.name,
                "account_type": account.account_type,
                "is_mapped": account == mapped_account,
                "opening_balance": opening_balance,
                "opening_debit": opening_debit,
                "opening_credit": opening_credit,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "total_debit": account_total_debit,
                "total_credit": account_total_credit,
                "closing_balance": closing_balance,
                "entries": entries,
            })

        return {
            "partner_id": commercial_partner.id,
            "partner_name": commercial_partner.display_name,
            "company_id": company.id,
            "company_name": company.display_name,
            "currency_id": company.currency_id.id,
            "date_from": date_from,
            "date_to": date_to,
            "date_from_display": format_date(self.env, date_from),
            "date_to_display": format_date(self.env, date_to),
            "mapped_account_id": mapped_account.id if mapped_account else False,
            "mapped_account_name": mapped_account.display_name if mapped_account else False,
            "shared_ledger_account": bool(
                mapped_account
                and commercial_partner._pr_portal_statement_has_shared_ledger()
            ),
            "accounts": account_groups,
            "entry_count": sum(len(group["entries"]) for group in account_groups),
            "opening_balance": total_opening,
            "period_debit": total_debit,
            "period_credit": total_credit,
            "total_debit": ledger_total_debit,
            "total_credit": ledger_total_credit,
            "closing_balance": total_opening + total_debit - total_credit,
            "amount_receivable": amount_receivable,
            "amount_payable": amount_payable,
            "net_balance": amount_receivable - amount_payable,
        }
