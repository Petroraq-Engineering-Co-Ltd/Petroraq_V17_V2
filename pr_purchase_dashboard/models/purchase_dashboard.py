# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


PO_STATES = ["pending", "purchase", "done"]
RFQ_STATES = ["draft", "sent", "cancel"]
PR_APPROVALS = [
    ("pending", "Pending"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]
PR_TYPES = [
    ("pr", "Regular PR"),
    ("cash", "Cash PR"),
]
EXPENSE_TYPES = [
    ("opex", "Opex"),
    ("capex", "Capex"),
]
EXPENSE_SCOPES = [
    ("department", "Department"),
    ("project", "Project"),
    ("trading", "Trading"),
]
BUDGET_STATES = [
    ("draft", "Draft"),
    ("pm_approval", "Project Manager"),
    ("accounts_approval", "Accounts"),
    ("md_approval", "Managing Director"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]
APPROVAL_STAGE_DOMAINS = {
    "pe": [("state", "=", "pending"), ("pe_approved", "=", False)],
    "pm": [
        ("state", "=", "pending"),
        ("subtotal", ">", 10000),
        ("pe_approved", "=", True),
        ("pm_approved", "=", False),
    ],
    "od": [
        ("state", "=", "pending"),
        ("subtotal", ">", 100000),
        ("pe_approved", "=", True),
        ("pm_approved", "=", True),
        ("od_approved", "=", False),
    ],
    "md": [
        ("state", "=", "pending"),
        ("subtotal", ">", 500000),
        ("pe_approved", "=", True),
        ("pm_approved", "=", True),
        ("od_approved", "=", True),
        ("md_approved", "=", False),
    ],
}


class PrPurchaseDashboard(models.AbstractModel):
    _name = "pr.purchase.dashboard"
    _description = "Petroraq Purchase Dashboard Service"

    @api.model
    def get_dashboard_data(self):
        po_domain = [("state", "in", PO_STATES)]
        rfq_domain = [("state", "in", RFQ_STATES)]
        requisition_domain = []
        po_line_domain = [
            ("order_id.state", "in", PO_STATES),
            ("display_type", "=", False),
            ("product_id", "!=", False),
        ]
        requisition_line_domain = [("requisition_id.approval", "!=", "rejected")]

        product_data = self._get_product_data(po_line_domain)

        return {
            "summary": self._get_summary(po_domain, requisition_domain, rfq_domain),
            "monthly": self._get_monthly_spend(po_domain),
            "pr_types": self._get_selection_breakdown(
                "purchase.requisition",
                requisition_domain,
                "pr_type",
                "total_incl_vat",
                PR_TYPES,
            ),
            "pr_approvals": self._get_selection_breakdown(
                "purchase.requisition",
                requisition_domain,
                "approval",
                "total_incl_vat",
                PR_APPROVALS,
            ),
            "expense_types": self._get_selection_breakdown(
                "purchase.requisition",
                requisition_domain,
                "expense_type",
                "total_incl_vat",
                EXPENSE_TYPES,
            ),
            "expense_scopes": self._get_selection_breakdown(
                "purchase.requisition",
                requisition_domain,
                "expense_scope",
                "total_incl_vat",
                EXPENSE_SCOPES,
            ),
            "po_approval": self._get_po_approval(po_domain),
            "approval_stages": self._get_approval_stages(),
            "rfq_pipeline": self._get_rfq_pipeline(rfq_domain),
            "top_vendors": self._get_top_vendors(po_domain),
            "buyers": self._get_buyers(po_domain),
            "vendor_countries": self._get_vendor_countries(po_domain),
            "product_categories": product_data["categories"],
            "top_products_value": product_data["top_value"],
            "top_products_volume": product_data["top_volume"],
            "cost_centers": self._get_cost_centers(requisition_line_domain),
            "budget_watch": self._get_budget_watch(),
            "currency": self._currency_data(),
        }

    def _currency_data(self):
        currency = self.env.company.currency_id
        return {
            "symbol": currency.symbol or "",
            "position": currency.position or "before",
            "digits": currency.decimal_places,
        }

    def _get_summary(self, po_domain, requisition_domain, rfq_domain):
        Order = self.env["purchase.order"]
        Requisition = self.env["purchase.requisition"]

        po_total = self._read_group_total(Order, po_domain, "amount_total")
        pr_total = self._read_group_total(Requisition, requisition_domain, "total_incl_vat")
        pending_po_count = Order.search_count([("state", "=", "pending")])

        return {
            "total_po_value": po_total,
            "total_po_count": Order.search_count(po_domain),
            "total_pr_value": pr_total,
            "total_pr_count": Requisition.search_count(requisition_domain),
            "total_rfq_count": Order.search_count(rfq_domain),
            "pending_po_count": pending_po_count,
            "po_domain": self._domain_to_json(po_domain),
            "pr_domain": self._domain_to_json(requisition_domain),
            "rfq_domain": self._domain_to_json(rfq_domain),
            "pending_po_domain": [["state", "=", "pending"]],
        }

    def _get_monthly_spend(self, domain):
        Order = self.env["purchase.order"]
        today = fields.Date.context_today(self)
        start_month = today.replace(day=1) - relativedelta(months=5)
        month_keys = []
        month_values = {}

        for index in range(6):
            month_date = start_month + relativedelta(months=index)
            key = month_date.strftime("%Y-%m")
            month_keys.append((key, month_date.strftime("%b %Y")))
            month_values[key] = {"amount": 0.0, "orders": 0}

        start_dt = datetime.combine(start_month, time.min)
        orders = Order.search(domain + [("date_order", ">=", fields.Datetime.to_string(start_dt))])
        for order in orders:
            if not order.date_order:
                continue
            key = fields.Datetime.to_datetime(order.date_order).strftime("%Y-%m")
            if key in month_values:
                month_values[key]["amount"] += order.amount_total
                month_values[key]["orders"] += 1

        max_amount = max([month_values[key]["amount"] for key, label in month_keys] or [0.0])
        return [
            {
                "label": label,
                "amount": month_values[key]["amount"],
                "orders": month_values[key]["orders"],
                "percent": self._percent(month_values[key]["amount"], max_amount),
                "domain": self._domain_to_json(
                    domain
                    + [
                        ("date_order", ">=", fields.Datetime.to_string(datetime.combine((start_month + relativedelta(months=index)), time.min))),
                        ("date_order", "<", fields.Datetime.to_string(datetime.combine((start_month + relativedelta(months=index + 1)), time.min))),
                    ]
                ),
            }
            for index, (key, label) in enumerate(month_keys)
        ]

    def _get_selection_breakdown(self, model_name, base_domain, field_name, amount_field, labels):
        Model = self.env[model_name]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9", "#4dd4d0"]
        group_fields = [f"{amount_field}:sum"] if amount_field in Model._fields else []
        groups = Model.read_group(base_domain, group_fields, [field_name], lazy=False)
        grouped = {group.get(field_name): group for group in groups}
        total_count = sum(group.get("__count", 0) for group in groups)
        total_amount = sum(group.get(amount_field, 0.0) for group in groups)

        rows = []
        for index, (value, label) in enumerate(labels):
            group = grouped.get(value, {})
            count = group.get("__count", 0)
            amount = group.get(amount_field, 0.0)
            rows.append({
                "value": value,
                "label": label,
                "count": count,
                "amount": amount,
                "count_percent": self._percent(count, total_count),
                "amount_percent": self._percent(amount, total_amount),
                "color": colors[index % len(colors)],
                "domain": self._domain_to_json(base_domain + [(field_name, "=", value)]),
            })
        return rows

    def _get_po_approval(self, po_domain):
        Order = self.env["purchase.order"]
        approved_domain = [("state", "in", ["purchase", "done"])]
        rejected_domain = [("state", "=", "cancel"), ("rejection_reason", "!=", False)]
        pending_domain = [("state", "=", "pending")]
        total_orders = Order.search_count(po_domain + [("state", "!=", "cancel")])
        approved = Order.search_count(approved_domain)
        pending = Order.search_count(pending_domain)
        rejected = Order.search_count(rejected_domain)

        return {
            "approved": approved,
            "pending": pending,
            "rejected": rejected,
            "approved_percent": self._percent(approved, total_orders),
            "pending_percent": self._percent(pending, total_orders),
            "rejected_percent": self._percent(rejected, total_orders + rejected),
            "approved_domain": self._domain_to_json(approved_domain),
            "pending_domain": self._domain_to_json(pending_domain),
            "rejected_domain": self._domain_to_json(rejected_domain),
        }

    def _get_approval_stages(self):
        Order = self.env["purchase.order"]
        stages = [
            ("pe", "Procurement Manager", "#2f95ed"),
            ("pm", "Project Manager", "#18cf93"),
            ("od", "Operations Director", "#ffbd45"),
            ("md", "Managing Director", "#ff5a66"),
        ]
        rows = []
        for key, label, color in stages:
            domain = APPROVAL_STAGE_DOMAINS[key]
            rows.append({
                "key": key,
                "label": label,
                "count": Order.search_count(domain),
                "amount": self._read_group_total(Order, domain, "amount_total"),
                "color": color,
                "domain": self._domain_to_json(domain),
            })

        max_amount = max([row["amount"] for row in rows] or [0.0])
        max_count = max([row["count"] for row in rows] or [0])
        for row in rows:
            row["amount_percent"] = self._percent(row["amount"], max_amount)
            row["count_percent"] = self._percent(row["count"], max_count)
        return rows

    def _get_rfq_pipeline(self, domain):
        Order = self.env["purchase.order"]
        labels = [
            ("draft", "Draft RFQs", "#2f95ed"),
            ("sent", "Sent RFQs", "#18cf93"),
            ("cancel", "Cancelled", "#ff5a66"),
        ]
        groups = Order.read_group(domain, ["amount_total:sum"], ["state"], lazy=False)
        grouped = {group.get("state"): group for group in groups}
        total_count = sum(group.get("__count", 0) for group in groups)
        total_amount = sum(group.get("amount_total", 0.0) for group in groups)
        return [
            {
                "state": value,
                "label": label,
                "count": grouped.get(value, {}).get("__count", 0),
                "amount": grouped.get(value, {}).get("amount_total", 0.0),
                "count_percent": self._percent(grouped.get(value, {}).get("__count", 0), total_count),
                "amount_percent": self._percent(grouped.get(value, {}).get("amount_total", 0.0), total_amount),
                "color": color,
                "domain": [["state", "=", value]],
            }
            for value, label, color in labels
        ]

    def _get_top_vendors(self, domain):
        Order = self.env["purchase.order"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        groups = [group for group in groups if group.get("partner_id")]
        groups = sorted(groups, key=lambda item: item.get("amount_total", 0.0), reverse=True)[:5]
        max_amount = max([group.get("amount_total", 0.0) for group in groups] or [0.0])
        return [
            {
                "id": group["partner_id"][0],
                "name": group["partner_id"][1],
                "amount": group.get("amount_total", 0.0),
                "orders": group.get("__count", 0),
                "percent": self._percent(group.get("amount_total", 0.0), max_amount),
                "domain": [["partner_id", "=", group["partner_id"][0]], ["state", "in", PO_STATES]],
            }
            for group in groups
        ]

    def _get_buyers(self, domain):
        Order = self.env["purchase.order"]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9"]
        groups = Order.read_group(domain, ["amount_total:sum"], ["user_id"], lazy=False)
        groups = sorted(groups, key=lambda item: item.get("amount_total", 0.0), reverse=True)[:5]
        total = sum(group.get("amount_total", 0.0) for group in groups)
        return [
            {
                "id": group["user_id"][0] if group.get("user_id") else False,
                "name": group["user_id"][1] if group.get("user_id") else "Unassigned",
                "amount": group.get("amount_total", 0.0),
                "orders": group.get("__count", 0),
                "percent": self._percent(group.get("amount_total", 0.0), total),
                "color": colors[index % len(colors)],
                "domain": [["user_id", "=", group["user_id"][0]], ["state", "in", PO_STATES]] if group.get("user_id") else [["user_id", "=", False], ["state", "in", PO_STATES]],
            }
            for index, group in enumerate(groups)
        ]

    def _get_vendor_countries(self, domain):
        Order = self.env["purchase.order"]
        Partner = self.env["res.partner"]
        country_totals = defaultdict(float)
        groups = Order.read_group(domain, ["amount_total:sum"], ["partner_id"], lazy=False)
        for group in groups:
            partner_tuple = group.get("partner_id")
            if not partner_tuple:
                country_totals[0] += group.get("amount_total", 0.0)
                continue
            partner = Partner.browse(partner_tuple[0])
            country = partner.country_id
            country_totals[country.id or 0] += group.get("amount_total", 0.0)

        rows = sorted(country_totals.items(), key=lambda item: item[1], reverse=True)[:5]
        max_amount = max([amount for country_id, amount in rows] or [0.0])
        return [
            {
                "id": country_id,
                "name": self.env["res.country"].browse(country_id).name if country_id else "Unspecified",
                "amount": amount,
                "percent": self._percent(amount, max_amount),
                "domain": [["partner_id.country_id", "=", country_id], ["state", "in", PO_STATES]] if country_id else [["partner_id.country_id", "=", False], ["state", "in", PO_STATES]],
            }
            for country_id, amount in rows
        ]

    def _get_product_data(self, domain):
        Line = self.env["purchase.order.line"]
        Product = self.env["product.product"]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9", "#4dd4d0"]
        groups = Line.read_group(
            domain,
            ["price_total:sum", "product_qty:sum"],
            ["product_id"],
            lazy=False,
        )

        category_totals = defaultdict(float)
        products = []
        for group in groups:
            product_tuple = group.get("product_id")
            if not product_tuple:
                continue
            product = Product.browse(product_tuple[0])
            amount = group.get("price_total", 0.0)
            quantity = group.get("product_qty", 0.0)
            category = product.categ_id
            category_totals[category.id or 0] += amount
            products.append({
                "id": product.id,
                "name": product.display_name,
                "amount": amount,
                "quantity": quantity,
                "category": category.display_name or "Uncategorized",
                "domain": [["product_id", "=", product.id], ["order_id.state", "in", PO_STATES]],
            })

        category_total = sum(category_totals.values())
        categories = []
        for index, (category_id, amount) in enumerate(sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]):
            category = self.env["product.category"].browse(category_id)
            categories.append({
                "id": category_id,
                "name": category.display_name if category_id else "Uncategorized",
                "amount": amount,
                "percent": self._percent(amount, category_total),
                "color": colors[index % len(colors)],
                "domain": [["product_id.categ_id", "=", category_id], ["order_id.state", "in", PO_STATES]] if category_id else [["product_id.categ_id", "=", False], ["order_id.state", "in", PO_STATES]],
            })

        top_value = sorted(products, key=lambda item: item["amount"], reverse=True)[:5]
        max_amount = max([item["amount"] for item in top_value] or [0.0])
        for index, item in enumerate(top_value):
            item["percent"] = self._percent(item["amount"], max_amount)
            item["color"] = colors[index % len(colors)]

        top_volume = sorted(products, key=lambda item: item["quantity"], reverse=True)[:5]
        total_volume = sum(item["quantity"] for item in top_volume)
        for index, item in enumerate(top_volume):
            item["percent"] = self._percent(item["quantity"], total_volume)
            item["color"] = colors[index % len(colors)]

        return {
            "categories": categories,
            "top_value": top_value,
            "top_volume": top_volume,
        }

    def _get_cost_centers(self, domain):
        Line = self.env["purchase.requisition.line"]
        colors = ["#2f95ed", "#18cf93", "#ffbd45", "#ff5a66", "#8b6bd9"]
        groups = Line.read_group(domain, ["total_price:sum", "quantity:sum"], ["cost_center_id"], lazy=False)
        groups = [group for group in groups if group.get("cost_center_id")]
        groups = sorted(groups, key=lambda item: item.get("total_price", 0.0), reverse=True)[:5]
        max_amount = max([group.get("total_price", 0.0) for group in groups] or [0.0])
        return [
            {
                "id": group["cost_center_id"][0],
                "name": group["cost_center_id"][1],
                "amount": group.get("total_price", 0.0),
                "quantity": group.get("quantity", 0.0),
                "percent": self._percent(group.get("total_price", 0.0), max_amount),
                "color": colors[index % len(colors)],
                "domain": [["cost_center_id", "=", group["cost_center_id"][0]], ["requisition_id.approval", "!=", "rejected"]],
            }
            for index, group in enumerate(groups)
        ]

    def _get_budget_watch(self):
        Requisition = self.env["purchase.requisition"]
        today = fields.Date.context_today(self)
        today_string = fields.Date.to_string(today)
        overdue_domain = [
            ("required_date", "<", today_string),
            ("approval", "!=", "rejected"),
            ("status", "!=", "completed"),
        ]
        active_requisitions = Requisition.search([("approval", "!=", "rejected")])
        variance_requisitions = active_requisitions.filtered("wo_variance_requires_approval")
        variance_domain = [("id", "in", variance_requisitions.ids or [0])]

        budget_requests = []
        pending_budget_count = 0
        pending_budget_amount = 0.0
        if "budget.increase.request" in self.env:
            Request = self.env["budget.increase.request"]
            request_groups = Request.read_group([], [], ["state"], lazy=False)
            grouped = {group.get("state"): group for group in request_groups}
            for value, label in BUDGET_STATES:
                count = grouped.get(value, {}).get("__count", 0)
                domain = [["state", "=", value]]
                budget_requests.append({
                    "value": value,
                    "label": label,
                    "count": count,
                    "domain": domain,
                })
            pending_states = ["pm_approval", "accounts_approval", "md_approval"]
            pending_budget_domain = [("state", "in", pending_states)]
            pending_budget_count = Request.search_count(pending_budget_domain)
            if "budget.increase.request.line" in self.env:
                pending_requests = Request.search(pending_budget_domain)
                pending_budget_amount = sum(pending_requests.mapped("line_ids.requested_increase"))

        return {
            "wo_variance_count": len(variance_requisitions),
            "wo_variance_amount": sum(variance_requisitions.mapped("total_incl_vat")),
            "wo_variance_domain": self._domain_to_json(variance_domain),
            "overdue_count": Requisition.search_count(overdue_domain),
            "overdue_amount": self._read_group_total(Requisition, overdue_domain, "total_incl_vat"),
            "overdue_domain": self._domain_to_json(overdue_domain),
            "pending_budget_count": pending_budget_count,
            "pending_budget_amount": pending_budget_amount,
            "pending_budget_domain": [["state", "in", ["pm_approval", "accounts_approval", "md_approval"]]],
            "budget_requests": budget_requests,
        }

    def _read_group_total(self, model, domain, field_name):
        if field_name not in model._fields:
            return 0.0
        groups = model.read_group(domain, [f"{field_name}:sum"], [])
        return groups[0].get(field_name, 0.0) if groups else 0.0

    def _domain_to_json(self, domain):
        return [[item[0], item[1], item[2]] for item in domain]

    def _percent(self, value, total):
        if not total:
            return 0
        return round((float(value or 0.0) / float(total)) * 100, 2)
