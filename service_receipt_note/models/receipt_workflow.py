from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class ServiceReceiptNote(models.Model):
    _inherit = "service.receipt.note"

    requested_user_id = fields.Many2one(
        "res.users", related="purchase_id.requisition_id.requested_user_id", store=True,
        string="Requested By", readonly=True,
    )
    department_manager_id = fields.Many2one(
        "res.users", compute="_compute_department_manager", store=True,
        string="Department Manager", compute_sudo=True,
    )
    payment_requested = fields.Boolean(readonly=True, copy=False, tracking=True)
    payment_requested_by = fields.Many2one("res.users", readonly=True, copy=False)
    payment_requested_on = fields.Datetime(readonly=True, copy=False)
    can_approve_service = fields.Boolean(compute="_compute_workflow_permissions")
    can_request_payment = fields.Boolean(compute="_compute_workflow_permissions")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                order = self.env["purchase.order"].browse(vals.get("purchase_id")).exists()
                order.check_access_rights("read")
                order.check_access_rule("read")
                backorder = self.browse(vals.get("backorder_id")).exists()
                is_backorder = backorder and backorder.purchase_id == order and backorder.state == "done"
                if not is_backorder and order.requisition_id.requested_user_id != self.env.user:
                    raise AccessError(_("Only the requesting end user can initiate an SRN."))
                if is_backorder:
                    backorder._require_service_manager()
                if vals.get("state", "ready") not in ("draft", "ready") or vals.get("approval_state", "pending") != "pending" or vals.get("payment_requested"):
                    raise AccessError(_("New SRNs must start open and pending approval."))
        receipts = super().create(vals_list)
        for receipt in receipts.filtered("department_manager_id"):
            receipt.activity_schedule(
                "mail.mail_activity_data_todo", user_id=receipt.department_manager_id.id,
                summary=_("Service Receipt Awaiting Review"),
                note=_("Review the service quantities and supporting documents before approval and validation."),
            )
        return receipts

    @api.depends("requested_user_id", "company_id",
                 "requested_user_id.employee_ids.company_id",
                 "requested_user_id.employee_ids.department_id.manager_id.user_id")
    def _compute_department_manager(self):
        for receipt in self:
            employee = receipt.requested_user_id.employee_ids.filtered(
                lambda emp: emp.company_id == receipt.company_id
            )[:1]
            receipt.department_manager_id = employee.department_id.manager_id.user_id

    @api.depends_context("uid")
    @api.depends("department_manager_id", "requested_user_id", "state", "payment_requested")
    def _compute_workflow_permissions(self):
        for receipt in self:
            receipt.can_approve_service = receipt.department_manager_id == self.env.user
            receipt.can_request_payment = (
                receipt.requested_user_id == self.env.user
                and receipt.state == "done" and not receipt.payment_requested
            )

    def _require_service_manager(self):
        for receipt in self:
            if not receipt.department_manager_id:
                raise UserError(_("Configure the requester's employee department and department manager first."))
            if not self.env.su and receipt.department_manager_id != self.env.user:
                raise AccessError(_("Only the requester's department manager can approve or validate this SRN."))

    def action_approve(self):
        self._require_service_manager()
        for receipt in self:
            if receipt.state not in ("draft", "ready"):
                raise UserError(_("Only open SRNs can be approved."))
            receipt._validate_lines()
            receipt.write({"approval_state": "approved", "rejection_reason": False})
        return True

    def action_validate(self):
        self._require_service_manager()
        for receipt in self.sorted("id"):
            self.env.cr.execute("SELECT id FROM purchase_order WHERE id = %s FOR UPDATE", [receipt.purchase_id.id])
            receipt.invalidate_recordset(["state", "approval_state"])
            receipt.line_ids.invalidate_recordset(["already_received_qty", "remaining_qty_before", "balance_qty"])
        return super().action_validate()

    def action_request_payment(self):
        for receipt in self:
            if receipt.requested_user_id != self.env.user and not self.env.su:
                raise AccessError(_("Only the requesting end user can initiate the payment request."))
            if receipt.state != "done":
                raise UserError(_("The department manager must validate the SRN before payment is requested."))
            self.env.cr.execute("SELECT id FROM service_receipt_note WHERE id = %s FOR UPDATE", [receipt.id])
            receipt.invalidate_recordset(["payment_requested"])
            if receipt.payment_requested:
                continue
            receipt.write({"payment_requested": True,
                           "payment_requested_by": self.env.uid,
                           "payment_requested_on": fields.Datetime.now()})
            accountants = self.env.ref("account.group_account_invoice").users.filtered(
                lambda user: user.active and receipt.company_id in user.company_ids
            )
            for user in accountants:
                receipt.activity_schedule("mail.mail_activity_data_todo", user_id=user.id,
                                          summary=_("SRN Payment Request"),
                                          note=_("Review the validated receipt and supporting documents, then create the vendor bill."))
        return True

    def unlink(self):
        if any(receipt.state == "done" or receipt.payment_requested for receipt in self):
            raise UserError(_("Validated or payment-requested SRNs cannot be deleted."))
        if not self.env.su and any(receipt.requested_user_id != self.env.user for receipt in self):
            raise AccessError(_("Only the requester can delete an unvalidated SRN."))
        return super().unlink()

    def write(self, vals):
        if not self.env.su:
            if "purchase_id" in vals and any(r.purchase_id.id != vals["purchase_id"] for r in self):
                raise AccessError(_("The purchase order of an existing SRN cannot be changed."))
            if vals.get("approval_state") in ("approved", "rejected") or vals.get("state") == "done":
                self._require_service_manager()
            if vals.get("state") == "done":
                if any(r.approval_state != "approved" or r.purchase_id.state not in ("purchase", "done") for r in self):
                    raise UserError(_("Approval and a confirmed purchase order are required before validation."))
                self._validate_lines()
            if {"payment_requested", "payment_requested_by", "payment_requested_on"} & vals.keys():
                if any(r.requested_user_id != self.env.user or r.state != "done" for r in self):
                    raise AccessError(_("Only the requester can request payment on a validated SRN."))
                if not vals.get("payment_requested") or vals.get("payment_requested_by") != self.env.uid:
                    raise AccessError(_("Payment requests cannot be reset or assigned to another user."))
            if any(r.requested_user_id != self.env.user and r.department_manager_id != self.env.user for r in self):
                raise AccessError(_("Only the requester or department manager can edit a service receipt."))
        return super().write(vals)


class ServiceReceiptLine(models.Model):
    _inherit = "service.receipt.note.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_editable_receipt()
        return lines

    @api.constrains("purchase_line_id", "receipt_id")
    def _check_purchase_line_receipt(self):
        for line in self:
            if line.purchase_line_id.order_id != line.receipt_id.purchase_id:
                raise UserError(_("The service line must belong to the receipt's purchase order."))

    def _check_editable_receipt(self):
        for receipt in self.mapped("receipt_id"):
            if receipt.state in ("done", "cancel"):
                raise UserError(_("Lines of a completed or cancelled SRN cannot be changed."))
            if not self.env.su and self.env.user not in (receipt.requested_user_id | receipt.department_manager_id):
                raise AccessError(_("Only the requester or department manager can edit SRN lines."))

    def write(self, vals):
        self._check_editable_receipt()
        if "receipt_id" in vals:
            raise AccessError(_("SRN lines cannot be moved to another receipt."))
        return super().write(vals)

    def unlink(self):
        self._check_editable_receipt()
        return super().unlink()


class ServiceRejectWizard(models.TransientModel):
    _inherit = "service.receipt.reject.wizard"

    def action_confirm_reject(self):
        self.ensure_one()
        self.receipt_id._require_service_manager()
        if self.receipt_id.state in ("done", "cancel"):
            raise UserError(_("A completed or cancelled SRN cannot be rejected."))
        self.receipt_id.write({"approval_state": "rejected", "rejection_reason": self.rejection_reason})
        return {"type": "ir.actions.act_window_close"}
