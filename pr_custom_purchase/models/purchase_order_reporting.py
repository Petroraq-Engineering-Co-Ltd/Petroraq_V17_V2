from odoo import api, fields, models
from odoo.tools import SQL, float_compare


LIVE_REPORT_FIELDS = frozenset({
    "budget_remaining_amount", "approval_status",
    "workflow_billing_status", "workflow_payment_status", "workflow_delivery_status",
})


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    workflow_delivery_status = fields.Selection([
        ("not_ordered", "Not Ordered"), ("pending", "Not Received"),
        ("partial", "Partially Received"), ("done", "Fully Received"),
        ("cancel", "Cancelled"),
    ], string="Delivery Status", compute="_compute_workflow_delivery_status",
        search="_search_po_delivery_status", compute_sudo=True)

    @api.depends("state", "order_line.product_qty", "order_line.qty_received",
                 "order_line.display_type", "order_line.product_uom")
    def _compute_workflow_delivery_status(self):
        for order in self:
            lines = order.order_line.filtered(
                lambda line: not line.display_type and line.product_qty > 0
                and not getattr(line, "is_downpayment", False)
            )
            if order.state == "cancel":
                status = "cancel"
            elif order.state not in ("purchase", "done"):
                status = "not_ordered"
            elif lines and all(float_compare(line.qty_received, line.product_qty,
                                            precision_rounding=line.product_uom.rounding) >= 0 for line in lines):
                status = "done"
            elif any(float_compare(line.qty_received, 0,
                                   precision_rounding=line.product_uom.rounding) > 0 for line in lines):
                status = "partial"
            else:
                status = "pending"
            order.workflow_delivery_status = status

    @api.model
    def _search_po_delivery_status(self, operator, value):
        return self._search_live_po_report_field("workflow_delivery_status", operator, value)

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        if attributes is None or "sortable" in attributes:
            for name in LIVE_REPORT_FIELDS.intersection(result):
                result[name]["sortable"] = True
        return result

    @api.model
    def _search_live_po_report_field(self, field_name, operator, value):
        # Read with the caller's access rules. The computations retain their
        # existing sudo policy; searching never grants access to another PO.
        # A stored snapshot would miss shared budget, GRN/SES and payment changes.
        candidates = self.search([], order="id")
        matches = candidates.filtered_domain([(field_name, operator, value)])
        return [("id", "in", matches.ids)]

    @api.model
    def _search_po_budget_remaining(self, operator, value):
        return self._search_live_po_report_field("budget_remaining_amount", operator, value)

    @api.model
    def _search_po_approval_status(self, operator, value):
        return self._search_live_po_report_field("approval_status", operator, value)

    @api.model
    def _search_po_billing_status(self, operator, value):
        return self._search_live_po_report_field("workflow_billing_status", operator, value)

    @api.model
    def _search_po_payment_status(self, operator, value):
        return self._search_live_po_report_field("workflow_payment_status", operator, value)

    def _order_field_to_sql(self, alias, field_name, direction, nulls, query):
        if field_name not in LIVE_REPORT_FIELDS:
            return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

        # Odoo builds ORDER BY before applying LIMIT/OFFSET. Evaluate the live
        # values for this query's full result, then let PostgreSQL do sorting,
        # tie-breaking with other order terms, and pagination as usual.
        self.env.cr.execute(query.select(SQL("DISTINCT %s", SQL.identifier(alias, "id"))))
        ids = [row[0] for row in self.env.cr.fetchall() if row[0]]
        records = self.search([("id", "in", ids)], order="id") if ids else self.browse()
        cases = []
        for record in records:
            value = record[field_name]
            cases.append(SQL("WHEN %s THEN %s", record.id, None if value is False else value))
        if not cases:
            return SQL()
        return SQL(
            "CASE %s %s ELSE NULL END %s %s",
            SQL.identifier(alias, "id"), SQL(" ").join(cases), direction, nulls,
        )
