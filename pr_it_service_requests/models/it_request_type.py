from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PrItRequestType(models.Model):
    _name = "pr.it.request.type"
    _description = "IT Request Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    default_approver_line_ids = fields.One2many(
        "pr.it.request.type.approver", "request_type_id", string="Default Approvers", copy=True
    )

    _sql_constraints = [
        ("it_request_type_code_unique", "unique(code)", "The IT request type code must be unique."),
    ]

    @api.constrains("code")
    def _check_code(self):
        for rec in self:
            if rec.code and not rec.code.strip():
                raise ValidationError("The IT request type code cannot be empty.")


class PrItRequestTypeApprover(models.Model):
    _name = "pr.it.request.type.approver"
    _description = "IT Request Type Default Approver"
    _order = "sequence, id"

    request_type_id = fields.Many2one("pr.it.request.type", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Approval Order", required=True, default=10)
    approver_id = fields.Many2one(
        "res.users",
        required=True,
        domain="[('share', '=', False), ('active', '=', True)]",
    )

    _sql_constraints = [
        (
            "it_type_approver_sequence_unique",
            "unique(request_type_id, sequence)",
            "Each default approval step must have a unique sequence.",
        ),
        (
            "it_type_approver_user_unique",
            "unique(request_type_id, approver_id)",
            "A user can only appear once in a default approval chain.",
        ),
    ]

    @api.constrains("sequence")
    def _check_sequence(self):
        if any(line.sequence <= 0 for line in self):
            raise ValidationError("Approval sequence must be greater than zero.")
