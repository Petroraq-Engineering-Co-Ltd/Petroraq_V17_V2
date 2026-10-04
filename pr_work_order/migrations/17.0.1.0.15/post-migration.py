import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


def _product_labels(product):
    return {
        (product.name or "").strip(),
        (product.display_name or "").strip(),
        (product.with_context(display_default_code=False).display_name or "").strip(),
    }


def migrate(cr, version):
    """Repair deterministic WO descriptions on existing draft PR lines."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    requisitions = env["purchase.requisition"].sudo().search([
        ("approval", "=", "draft"),
        ("expense_bucket_id", "!=", False),
    ])
    repaired_lines = env["purchase.requisition.line"]

    for requisition in requisitions:
        bucket = requisition.expense_bucket_id
        work_order = (
            bucket.work_order_id.sudo()
            if "work_order_id" in bucket._fields and bucket.work_order_id
            else False
        )
        if not work_order:
            continue

        section_names_by_cost_center = {}
        for cost_center in work_order.cost_center_ids.filtered("analytic_account_id"):
            section_names_by_cost_center.setdefault(
                cost_center.analytic_account_id.id,
                set(),
            ).add(cost_center.section_name)

        for line in requisition.line_ids.filtered(lambda item: item.description):
            current_description = (line.line_description or "").strip()
            if current_description not in _product_labels(line.description):
                # Preserve descriptions already customized directly on the PR.
                continue

            section_names = section_names_by_cost_center.get(line.cost_center_id.id, set())
            candidates = work_order.boq_line_ids.filtered(
                lambda boq: (
                    boq.display_type not in ("line_section", "line_note")
                    and boq.product_id == line.description
                    and boq.section_name in section_names
                    and float_compare(
                        boq.qty or 0.0,
                        line.quantity or 0.0,
                        precision_digits=8,
                    ) == 0
                    and float_compare(
                        boq.unit_cost or boq.product_id.standard_price or 0.0,
                        line.unit_price or 0.0,
                        precision_digits=8,
                    ) == 0
                )
            )
            if len(candidates) != 1:
                continue

            desired_description = candidates._get_purchase_requisition_description()
            if desired_description and desired_description != current_description:
                line.line_description = desired_description
                repaired_lines |= line

    if repaired_lines:
        _logger.info(
            "Restored Work Order descriptions on draft PR lines %s",
            repaired_lines.ids,
        )
