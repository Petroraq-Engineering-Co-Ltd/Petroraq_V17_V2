from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class PaymentTerm(models.Model):
    _inherit = "account.payment.term"

    purchase_milestone_schedule = fields.Boolean(string="Purchase Milestone Breakdown")
    advance_percent = fields.Float(string="Advance (%)")
    progressive_percent = fields.Float(string="Progressive (%)")
    completion_percent = fields.Float(string="At Completion (%)")
    purchase_credit_days = fields.Integer(string="Credit (Days)")
    purchase_schedule_summary = fields.Char(compute="_compute_purchase_schedule_summary")

    @api.constrains("purchase_milestone_schedule", "advance_percent", "progressive_percent",
                    "completion_percent", "purchase_credit_days")
    def _check_purchase_schedule(self):
        for term in self.filtered("purchase_milestone_schedule"):
            percentages = [term.advance_percent, term.progressive_percent, term.completion_percent]
            if any(value < 0 or value > 100 for value in percentages) or float_compare(sum(percentages), 100, precision_digits=2):
                raise ValidationError(_("Advance, Progressive and Completion percentages must total 100%."))
            if term.purchase_credit_days < 0:
                raise ValidationError(_("Credit days cannot be negative."))

    @api.depends("purchase_milestone_schedule", "advance_percent", "progressive_percent",
                 "completion_percent", "purchase_credit_days")
    def _compute_purchase_schedule_summary(self):
        for term in self:
            term.purchase_schedule_summary = (
                _("Advance: %(advance)s%% | Progressive: %(progressive)s%% | At Completion: %(completion)s%% | Credit: %(days)s days")
                % {"advance": term.advance_percent, "progressive": term.progressive_percent,
                   "completion": term.completion_percent, "days": term.purchase_credit_days}
                if term.purchase_milestone_schedule else ""
            )


class AccountPayment(models.Model):
    _inherit = "account.payment"

    purchase_payment_stage = fields.Selection([
        ("advance", "Advance"), ("progressive", "Progressive"),
        ("completion", "At Completion"), ("credit", "Credit"),
    ], string="PO Payment Stage", tracking=True)
    purchase_payment_term_id = fields.Many2one(
        "account.payment.term", related="purchase_order_id.payment_term_id", store=True,
        string="PO Payment Terms",
    )
