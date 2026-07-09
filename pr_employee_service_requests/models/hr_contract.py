from odoo import fields, models


class HrContract(models.Model):
    _inherit = "hr.contract"

    exit_reentry_benefit_type = fields.Selection(
        [
            ("executive", "Executive"),
            ("non_executive", "Non Executive"),
        ],
        string="Exit/Re-entry Benefit Type",
        default="non_executive",
        tracking=True,
        help=(
            "Controls company-paid Exit/Re-entry eligibility: executives are eligible "
            "once every contract year after 11 months; non executives once every two "
            "contract years after 23 months."
        ),
    )
