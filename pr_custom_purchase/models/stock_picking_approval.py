from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    receipt_approval_state_ui = fields.Selection(
        [
            ("pending", "Pending QC Approval"),
            ("qc_approved", "QC Approved"),
            ("approved", "Admin Approved"),
            ("rejected", "Rejected"),
        ],
        string="Receipt Approval",
        compute="_compute_receipt_approval_state_ui",
        store=False,
    )
    is_current_user_approver = fields.Boolean(
        string="Pending My Approval",
        compute="_compute_is_current_user_approver",
        search="_search_is_current_user_approver",
    )

    def _get_receipt_approval_state(self):
        """Schema-free approval state based on chatter markers."""
        self.ensure_one()
        if self.picking_type_code != "incoming":
            return "pending"
        last_msg = self.env["mail.message"].sudo().search([
            ("model", "=", "stock.picking"),
            ("res_id", "=", self.id),
            ("body", "ilike", "[RECEIPT_APPROVAL_STATE:"),
        ], order="id desc", limit=1)
        body = (last_msg.body or "") if last_msg else ""
        if "[RECEIPT_APPROVAL_STATE:APPROVED]" in body:
            return "approved"
        if "[RECEIPT_APPROVAL_STATE:REJECTED]" in body:
            return "rejected"
        if "[RECEIPT_APPROVAL_STATE:QC_APPROVED]" in body:
            return "qc_approved"
        return "pending"

    def _compute_receipt_approval_state_ui(self):
        for picking in self:
            picking.receipt_approval_state_ui = picking._get_receipt_approval_state()

    @api.depends_context("uid")
    def _compute_is_current_user_approver(self):
        user = self.env.user
        is_qc = user.has_group("pr_custom_purchase.inventory_qc")
        is_admin = user.has_group("pr_custom_purchase.inventory_admin")
        for picking in self:
            is_approver = False
            if picking.picking_type_code == "incoming" and picking.state not in ("done", "cancel"):
                app_state = picking._get_receipt_approval_state()
                if is_qc and app_state == "pending":
                    is_approver = True
                elif is_admin and app_state in ("qc_approved", "approved"):
                    is_approver = True
            picking.is_current_user_approver = is_approver

    def _search_is_current_user_approver(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search operation for current approver filter."))

        is_approver_requested = (operator == "=" and value) or (operator == "!=") and not value

        user = self.env.user
        is_qc = user.has_group("pr_custom_purchase.inventory_qc")
        is_admin = user.has_group("pr_custom_purchase.inventory_admin")

        if not is_qc and not is_admin:
            return [("id", "=", False)] if is_approver_requested else []

        active_pickings = self.sudo().search([
            ("picking_type_code", "=", "incoming"),
            ("state", "not in", ["done", "cancel"]),
        ])

        matching_ids = []
        for p in active_pickings:
            st = p._get_receipt_approval_state()
            if is_qc and st == "pending":
                matching_ids.append(p.id)
            elif is_admin and st in ("qc_approved", "approved"):
                matching_ids.append(p.id)

        if is_approver_requested:
            return [("id", "in", matching_ids)] if matching_ids else [("id", "=", False)]
        return [("id", "not in", matching_ids)] if matching_ids else []

    def button_validate(self):
        for picking in self:
            if picking.picking_type_code != "incoming":
                continue
            group = self.env.ref("pr_custom_purchase.inventory_admin", raise_if_not_found=False)
            if group and self.env.user not in group.users and not self.env.is_admin():
                raise UserError(_("Only Inventory Administration can validate receipts."))
            if picking._get_receipt_approval_state() != "approved":
                raise UserError(_("This receipt must be approved by Inventory QC and Inventory Administration before validation."))
        return super().button_validate()

    def action_qc_approve_receipt(self):
        group = self.env.ref("pr_custom_purchase.inventory_qc", raise_if_not_found=False)
        if group and self.env.user not in group.users and not self.env.is_admin():
            raise UserError(_("Only Inventory QC can approve receipts at QC stage."))
        for rec in self.filtered(lambda p: p.picking_type_code == "incoming"):
            if rec.state in ("done", "cancel"):
                raise UserError(_("Cannot approve a cancelled or completed receipt."))
            curr_state = rec._get_receipt_approval_state()
            if curr_state != "pending":
                raise UserError(_("This receipt is not pending QC approval."))
            rec.message_post(
                body=_(
                    "[RECEIPT_APPROVAL_STATE:QC_APPROVED] Receipt approved by Inventory QC."
                )
            )
        return True

    def action_approve_receipt(self):
        group = self.env.ref("pr_custom_purchase.inventory_admin", raise_if_not_found=False)
        if group and self.env.user not in group.users and not self.env.is_admin():
            raise UserError(_("Only Inventory Administration can approve receipts."))
        for rec in self.filtered(lambda p: p.picking_type_code == "incoming"):
            if rec.state in ("done", "cancel"):
                raise UserError(_("Cannot approve a cancelled or completed receipt."))
            curr_state = rec._get_receipt_approval_state()
            if curr_state == "approved":
                continue
            if curr_state != "qc_approved":
                raise UserError(_("The receipt must be approved by Inventory QC before Inventory Administration approval."))
            rec.message_post(
                body=_(
                    "[RECEIPT_APPROVAL_STATE:APPROVED] Receipt approved by Inventory Administration."
                )
            )
        return True

    def action_open_receipt_reject_wizard(self):
        self.ensure_one()
        if self.picking_type_code != "incoming":
            raise UserError(_("Rejection is only available for incoming receipts."))
        is_qc = self.env.user.has_group("pr_custom_purchase.inventory_qc")
        is_admin = self.env.user.has_group("pr_custom_purchase.inventory_admin")
        if not is_qc and not is_admin and not self.env.is_admin():
            raise UserError(_("Only Inventory QC or Inventory Administration can reject receipts."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Receipt"),
            "res_model": "stock.picking.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }


class StockPickingRejectWizard(models.TransientModel):
    _name = "stock.picking.reject.wizard"
    _description = "Stock Picking Rejection Wizard"

    picking_id = fields.Many2one("stock.picking", required=True)
    rejection_reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        is_qc = self.env.user.has_group("pr_custom_purchase.inventory_qc")
        is_admin = self.env.user.has_group("pr_custom_purchase.inventory_admin")
        if not is_qc and not is_admin and not self.env.is_admin():
            raise UserError(_("Only Inventory QC or Inventory Administration can reject receipts."))
        if self.picking_id.picking_type_code != "incoming":
            raise UserError(_("Rejection is only available for incoming receipts."))
        role_label = "Inventory QC" if is_qc and not is_admin else "Inventory Administration"
        self.picking_id.message_post(
            body=_(
                "[RECEIPT_APPROVAL_STATE:REJECTED] Receipt rejected by %s. Reason: %s"
            ) % (role_label, self.rejection_reason)
        )
        self.picking_id.action_cancel()
        return {"type": "ir.actions.act_window_close"}
