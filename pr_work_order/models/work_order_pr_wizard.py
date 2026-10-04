from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class WorkOrderCreatePRWizard(models.TransientModel):
    _name = "pr.work.order.create.pr.wizard"
    _description = "Create PR from Work Order"

    work_order_id = fields.Many2one("pr.work.order", required=True, readonly=True)
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")],
        string="Priority",
        required=True,
        default="medium",
    )
    notes = fields.Text(string="Notes")
    line_ids = fields.One2many(
        "pr.work.order.create.pr.wizard.line",
        "wizard_id",
        string="Products",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)

        work_order_id = self.env.context.get("default_work_order_id")
        if not work_order_id:
            return values

        # Use sudo for BOQ preload so readonly wizard lines are fully populated
        # even when the opener has limited read rights on related models.
        work_order = self.env["pr.work.order"].sudo().browse(work_order_id)
        if not work_order.expense_bucket_id:
            work_order._ensure_project_expense_bucket(sync_budget=True)
            work_order.invalidate_recordset(["expense_bucket_id"])

        source_lines = []
        if work_order.expense_bucket_id:
            scratch_pr = self.env["purchase.requisition"].new({
                "expense_bucket_id": work_order.expense_bucket_id.id,
            })
            source_lines = scratch_pr._prepare_source_product_line_values()

        if source_lines:
            cost_centers_by_section = {
                cc.section_name: cc.analytic_account_id
                for cc in work_order.cost_center_ids.filtered("analytic_account_id")
            }

            def _source_key(product_id, cost_center_id, unit_name, unit_price, description):
                return (
                    product_id,
                    cost_center_id,
                    unit_name or "",
                    round(unit_price or 0.0, 8),
                    (description or "").strip(),
                )

            boq_lines_by_source = {}
            for boq_line in work_order.boq_line_ids.sorted(key=lambda item: (item.sequence, item.id)):
                if boq_line.display_type in ("line_section", "line_note") or not boq_line.product_id:
                    continue
                cost_center = cost_centers_by_section.get(boq_line.section_name)
                unit = boq_line.uom_id or boq_line.product_id.uom_id
                key = _source_key(
                    boq_line.product_id.id,
                    cost_center.id if cost_center else False,
                    unit.name if unit else "",
                    boq_line.unit_cost or boq_line.product_id.standard_price,
                    boq_line._get_purchase_requisition_description(),
                )
                boq_lines_by_source.setdefault(key, []).append(boq_line)

            def _source_boq_line(source_line):
                product = self.env["product.product"].browse(source_line["description"])
                unit = self._get_source_line_uom(source_line)
                key = _source_key(
                    product.id,
                    source_line.get("cost_center_id"),
                    unit.name if unit else "",
                    source_line.get("unit_price"),
                    source_line.get("line_description"),
                )
                candidates = boq_lines_by_source.get(key, [])
                return candidates.pop(0) if candidates else self.env["pr.work.order.boq"]

            values["line_ids"] = [
                (
                    0,
                    0,
                    {
                        "selected": False,
                        "product_name": self.env["product.product"].browse(line["description"]).display_name,
                        "line_description": line.get("line_description"),
                        "boq_line_db_id": source_boq_line.id,
                        "boq_line_id": source_boq_line.id,
                        "product_id": line["description"],
                        "cost_center_id": line["cost_center_id"],
                        "quantity": line["quantity"],
                        "unit_id": self._get_source_line_uom(line).id,
                        "unit_price": line["unit_price"],
                    },
                )
                for line in source_lines
                for source_boq_line in [_source_boq_line(line)]
            ]
            return values

        lines = []
        current_section = False
        cost_centers_by_section = {
            cc.section_name: cc
            for cc in work_order.cost_center_ids.filtered("analytic_account_id")
        }
        for boq_line in work_order.boq_line_ids.sorted(key=lambda l: (l.sequence, l.id)):
            if boq_line.display_type == "line_section":
                current_section = boq_line.name or boq_line.section_name
                continue
            if boq_line.display_type == "line_note" or not boq_line.product_id:
                continue
            section_name = boq_line.section_name or current_section
            cc = cost_centers_by_section.get(section_name)
            lines.append(
                (
                    0,
                    0,
                    {
                        "selected": False,
                        "product_name": boq_line.product_id.display_name,
                        "line_description": boq_line._get_purchase_requisition_description(),
                        "boq_line_db_id": boq_line.id,
                        "product_id": boq_line.product_id.id,
                        "cost_center_id": cc.analytic_account_id.id if cc and cc.analytic_account_id else False,
                        "quantity": boq_line.qty,
                        "unit_id": (boq_line.uom_id or boq_line.product_id.uom_id).id,
                        "unit_price": boq_line.unit_cost or boq_line.product_id.standard_price,
                        "boq_line_id": boq_line.id,
                    },
                )
            )

        values["line_ids"] = lines
        return values

    def action_select_all_products(self):
        self.ensure_one()
        self.line_ids.write({"selected": True})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_clear_all_products(self):
        self.ensure_one()
        self.line_ids.write({"selected": False})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _get_source_line_uom(self, source_line):
        product = self.env["product.product"].browse(source_line["description"])
        unit_value = source_line.get("unit")
        if isinstance(unit_value, int):
            unit = self.env["uom.uom"].browse(unit_value)
            if unit.exists():
                return unit
        if unit_value:
            unit = self.env["uom.uom"].search([("name", "=", unit_value)], limit=1)
            if unit:
                return unit
        return product.uom_id

    def action_create_pr(self):
        self.ensure_one()

        if not self.env.user.has_group("pr_custom_purchase.group_custom_pr_end_user"):
            raise UserError(_("Only End Users can create PR from Work Order."))

        if self.work_order_id.state not in ["acc_approval", "final_approval", "approved", "in_progress", "done"]:
            raise UserError(_("PR can be created only after Operations approval."))

        self.line_ids._ensure_product_link()

        selected_lines = self.line_ids.filtered("selected")
        if not selected_lines:
            raise ValidationError(_("Please select at least one product to create PR."))

        commands = []
        for line in selected_lines:
            product = line.product_id
            boq_line = line.boq_line_id.sudo().exists()
            if not boq_line and line.boq_line_db_id:
                boq_line = self.env["pr.work.order.boq"].sudo().browse(line.boq_line_db_id).exists()
            if not product and line.boq_line_db_id:
                product = boq_line.product_id
            if not product and boq_line:
                product = boq_line.product_id
            if not product:
                raise ValidationError(
                    _("Selected line has no product. Please refresh and try again.")
                )
            if not line.cost_center_id:
                raise ValidationError(
                    _("Please set a Cost Center for product '%s'.") % product.display_name
                )
            line_description = line.line_description or product.display_name
            if (
                boq_line
                and boq_line.work_order_id == self.work_order_id
                and boq_line.product_id == product
            ):
                # Re-read the live BOQ value so edits made after opening the
                # wizard are also reflected in the newly created PR.
                line_description = boq_line._get_purchase_requisition_description()
            commands.append(
                (
                    0,
                    0,
                    {
                        "description": product.id,
                        "line_description": line_description,
                        "cost_center_id": line.cost_center_id.id,
                        "quantity": line.quantity,
                        "type": "service" if product.detailed_type == "service" else "material",
                        "unit": line.unit_id.name,
                        "unit_price": line.unit_price,
                    },
                )
            )
            work_order = self.work_order_id
            if not work_order.expense_bucket_id:
                work_order._ensure_project_expense_bucket(sync_budget=True)
                work_order.invalidate_recordset(["expense_bucket_id"])

            if not work_order.expense_bucket_id:
                raise ValidationError(
                    _("Missing expense bucket on Work Order. Please submit/approve the Work Order budget setup first.")
                )

        requisition = self.env["purchase.requisition"].create(
            {
                "pr_type": "pr",
                "priority": self.priority,
                "expense_type": work_order.expense_bucket_id.expense_type or "capex",
                "expense_bucket_id": work_order.expense_bucket_id.id,
                "expense_scope": work_order.expense_bucket_id.scope,
                "notes": self.notes,
                "line_ids": commands,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Requisition"),
            "res_model": "purchase.requisition",
            "res_id": requisition.id,
            "view_mode": "form",
            "target": "current",
        }


class WorkOrderCreatePRWizardLine(models.TransientModel):
    _name = "pr.work.order.create.pr.wizard.line"
    _description = "Create PR from Work Order Line"

    wizard_id = fields.Many2one("pr.work.order.create.pr.wizard", required=True, ondelete="cascade")
    selected = fields.Boolean(string="Select")
    boq_line_db_id = fields.Integer(string="BOQ Line ID", readonly=True)
    boq_line_id = fields.Many2one("pr.work.order.boq", string="BOQ Line", readonly=True)
    product_name = fields.Char(string="Product", readonly=True)
    line_description = fields.Text(string="Description", readonly=True)
    product_id = fields.Many2one("product.product", string="Product")
    cost_center_id = fields.Many2one("account.analytic.account", string="Cost Center", required=True)
    quantity = fields.Float(string="Quantity", required=True, digits="Product Unit of Measure")
    unit_id = fields.Many2one("uom.uom", string="Unit", required=True)
    unit_price = fields.Float(string="Unit Cost", required=True, digits="Product Price")

    def _ensure_product_link(self):
        """Keep product_id populated even if the editable grid drops readonly values."""
        for line in self:
            if line.product_id:
                continue
            if line.boq_line_db_id:
                product = self.env["pr.work.order.boq"].sudo().browse(line.boq_line_db_id).product_id
                if product:
                    line.product_id = product.id
                    if not line.product_name:
                        line.product_name = product.display_name
                    continue
            if line.boq_line_id and line.boq_line_id.sudo().product_id:
                line.product_id = line.boq_line_id.sudo().product_id.id
                if not line.product_name:
                    line.product_name = line.boq_line_id.sudo().product_id.display_name
