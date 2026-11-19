from odoo import fields, models, _
from odoo.exceptions import UserError


class HrPublicHoliday(models.Model):
    _inherit = "hr.public.holiday"

    approval_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("to_approve", "To Approve"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Approval Status",
        default="draft",
        tracking=True,
    )
    approved_by_id = fields.Many2one("res.users", string="Approved By", readonly=True, tracking=True)
    approved_on = fields.Datetime(string="Approved On", readonly=True, tracking=True)

    def _user_is_holiday_approver(self):
        user = self.env.user
        return user.has_group("hr.group_hr_manager") or user.has_group("pr_hr.group_hr_manager")

    def write(self, vals):
        if "approval_state" in vals and not self.env.su and not self._user_is_holiday_approver():
            # Anyone allowed to write the holiday may submit a draft for approval;
            # every other approval transition is reserved to HR Managers.
            is_submit = vals["approval_state"] == "to_approve" and all(
                rec.approval_state == "draft" for rec in self
            )
            if not is_submit:
                raise UserError(_("Only HR Managers can change holiday approval status."))
        return super().write(vals)

    def action_submit_for_approval(self):
        for rec in self:
            if rec.approval_state != "draft":
                raise UserError(_("Only draft public holidays can be submitted for approval."))
        self.write({"approval_state": "to_approve"})

    def action_hr_manager_approve(self):
        if not self._user_is_holiday_approver():
            raise UserError(_("Only HR Managers can approve public holidays."))
        # Approval rights are checked above; pr_hr HR Managers may lack the
        # hr_holidays write ACL on hr.public.holiday.
        self.sudo().write({
            "approval_state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_on": fields.Datetime.now(),
            "state": "active",
        })

    def action_hr_manager_reject(self):
        if not self._user_is_holiday_approver():
            raise UserError(_("Only HR Managers can reject public holidays."))
        self.sudo().write({
            "approval_state": "rejected",
            "approved_by_id": False,
            "approved_on": False,
            "state": "inactive",
        })
