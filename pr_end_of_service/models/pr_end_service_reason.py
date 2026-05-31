from odoo import fields, models


class PrEndServiceReason(models.Model):
    _name = "pr.end.service.reason"
    _description = "End of Service Reason"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Reason", required=True)
    active = fields.Boolean(default=True)
    deserved_after = fields.Float(
        string="Deserved After Years",
        default=0.0,
        help="Minimum service years required before this reason gives any EOS benefit.",
    )
    zero_message = fields.Char(
        string="Zero Message",
        default="Employee has not completed the minimum service period.",
    )
    is_partial = fields.Boolean(string="Partial Settlement")
    line_ids = fields.One2many(
        "pr.end.service.reason.line",
        "reason_id",
        string="Benefit Rules",
        copy=True,
    )


class PrEndServiceReasonLine(models.Model):
    _name = "pr.end.service.reason.line"
    _description = "End of Service Reason Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    reason_id = fields.Many2one(
        "pr.end.service.reason",
        string="Reason",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(string="Description", required=True)
    deserved_for_first = fields.Float(
        string="Service Years",
        required=True,
        help="Number of service years this rule covers before moving to the next rule.",
    )
    deserved_month_for_year = fields.Float(
        string="Months per Year",
        required=True,
        help="Benefit months granted for each year covered by this rule.",
    )
