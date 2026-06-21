# -*- coding: utf-8 -*-

from collections import OrderedDict
from datetime import datetime, date

from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DATE_FORMAT, format_date


PARTNER_LEDGER_ACCOUNT_TYPES = ("asset_receivable", "liability_payable")
INVOICE_MOVE_TYPES = (
    "out_invoice",
    "out_refund",
    "in_invoice",
    "in_refund",
    "out_receipt",
    "in_receipt",
)


def as_date(value):
    """Return a Python date for wizard/report date values."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), DATE_FORMAT).date()


def format_report_date(env, value, empty=" "):
    """Format report dates with the active Odoo language date format."""
    if not value or str(value).strip() == "":
        return empty
    return format_date(env, as_date(value))


def get_mapped_partner_ids(env, account_ids, company_id):
    """Partners whose legacy ledger account is among the selected accounts.

    Include commercial entities and child contacts so invoices/payments posted on
    either the parent company or a contact are reported under the mapped legacy
    account.
    """
    account_ids = [account_id for account_id in account_ids if account_id]
    if not account_ids:
        return []

    partner_domain = [("pr_ledger_account_id", "in", account_ids)]
    if company_id:
        partner_domain = expression.AND([
            partner_domain,
            ["|", ("company_id", "=", False), ("company_id", "=", company_id)],
        ])

    partners = env["res.partner"].sudo().search(partner_domain)
    if not partners:
        return []

    commercial_partners = partners.mapped("commercial_partner_id") | partners
    related_partners = env["res.partner"].sudo().search([
        ("commercial_partner_id", "in", commercial_partners.ids),
    ])
    return (partners | commercial_partners | related_partners).ids


def build_ledger_move_line_domain(
    company_id,
    account_ids,
    partner_ids=None,
    date_start=None,
    date_end=None,
    analytic_ids=None,
    opening=False,
):
    """Build the account ledger domain including partner-mapped move lines.

    Partner-mapped lines intentionally only include receivable/payable
    accounts. Invoice tax, revenue, and COGS lines often also carry the
    partner, but including them would make customer/vendor ledgers show
    invoice detail accounts instead of the partner balance movement.
    """
    account_ids = [account_id for account_id in account_ids if account_id]
    partner_ids = [partner_id for partner_id in (partner_ids or []) if partner_id]
    analytic_ids = [analytic_id for analytic_id in (analytic_ids or []) if analytic_id]

    base_domain = [
        ("company_id", "=", company_id),
        ("move_id.state", "=", "posted"),
    ]

    if opening:
        base_domain.append(("date", "<", as_date(date_start)))
    else:
        base_domain.extend([
            ("date", ">=", as_date(date_start)),
            ("date", "<=", as_date(date_end)),
        ])

    for analytic_id in analytic_ids:
        base_domain.append(("analytic_distribution", "in", [int(analytic_id)]))

    account_domain = [("account_id", "in", account_ids)]
    if partner_ids:
        partner_domain = [
            ("partner_id", "in", partner_ids),
            ("account_id", "not in", account_ids),
            ("account_id.account_type", "in", PARTNER_LEDGER_ACCOUNT_TYPES),
        ]
        ledger_domain = expression.OR([account_domain, partner_domain])
    else:
        ledger_domain = account_domain

    return expression.AND([base_domain, ledger_domain])


def get_ledger_move_lines(env, company_id, account_ids, date_start, date_end, analytic_ids=None):
    partner_ids = get_mapped_partner_ids(env, account_ids, company_id)
    domain = build_ledger_move_line_domain(
        company_id,
        account_ids,
        partner_ids=partner_ids,
        date_start=date_start,
        date_end=date_end,
        analytic_ids=analytic_ids,
    )
    return env["account.move.line"].search(domain, order="date asc, id asc")


def get_opening_balance(env, company_id, account_ids, date_start, analytic_ids=None):
    partner_ids = get_mapped_partner_ids(env, account_ids, company_id)
    domain = build_ledger_move_line_domain(
        company_id,
        account_ids,
        partner_ids=partner_ids,
        date_start=date_start,
        analytic_ids=analytic_ids,
        opening=True,
    )
    result = env["account.move.line"].read_group(domain, ["balance:sum"], [])
    return result[0].get("balance", 0.0) if result else 0.0


def _clean_text(value):
    return str(value or "").strip()


def _get_line_reference(line):
    move = line.move_id
    if move.move_type in INVOICE_MOVE_TYPES:
        candidates = (
            getattr(move, "invoice_origin", False),
            line.ref,
            move.ref,
            getattr(move, "payment_reference", False),
            move.name,
        )
    else:
        candidates = (
            line.ref,
            move.ref,
            getattr(move, "invoice_origin", False),
            getattr(move, "payment_reference", False),
            move.name,
        )
    return next((value for value in (_clean_text(candidate) for candidate in candidates) if value), " ")


def _get_line_description(line):
    move = line.move_id
    candidates = (
        line.name,
        getattr(move, "invoice_origin", False),
        move.ref,
        getattr(move, "payment_reference", False),
        move.name,
    )
    return next((value for value in (_clean_text(candidate) for candidate in candidates) if value), " ")


def get_ledger_report_line_groups(move_lines, merge_invoice_lines=False):
    """Return report rows, optionally collapsing invoice product lines.

    Journal entries remain untouched. Invoice/refund/receipt move lines are
    grouped by invoice and account so a revenue ledger can show one line per
    invoice while preserving account-level debit, credit, and running balance.
    """
    if not merge_invoice_lines:
        return [{
            "transaction_ref": line.move_id.name,
            "date": line.date,
            "description": _get_line_description(line),
            "reference": _get_line_reference(line),
            "journal": line.journal_id.name,
            "debit": line.debit,
            "credit": line.credit,
        } for line in move_lines]

    grouped_lines = OrderedDict()
    for line in move_lines:
        move = line.move_id
        if move.move_type in INVOICE_MOVE_TYPES:
            group_key = ("invoice", move.id, line.account_id.id)
        else:
            group_key = ("line", line.id)

        if group_key not in grouped_lines:
            grouped_lines[group_key] = {
                "first_line": line,
                "debit": 0.0,
                "credit": 0.0,
                "line_count": 0,
            }

        grouped_lines[group_key]["debit"] += line.debit
        grouped_lines[group_key]["credit"] += line.credit
        grouped_lines[group_key]["line_count"] += 1

    report_lines = []
    for group in grouped_lines.values():
        first_line = group["first_line"]
        report_lines.append({
            "transaction_ref": first_line.move_id.name,
            "date": first_line.date,
            "description": _get_line_description(first_line),
            "reference": _get_line_reference(first_line),
            "journal": first_line.journal_id.name,
            "debit": group["debit"],
            "credit": group["credit"],
        })
    return report_lines
