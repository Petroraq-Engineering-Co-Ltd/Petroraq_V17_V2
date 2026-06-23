from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class HrJob(models.Model):
    """
    """
    # region [Initial]
    _inherit = 'hr.job'
    # endregion [Initial]

    # region [Fields]

    job_salary = fields.Float(string="Gross Salary")
    experience_years = fields.Float(string="Years Of Experience")
    # Compatibility for mixed Odoo 17 source trees. Some patch levels ship
    # hr.job views/domains that reference this field while an older hr.job
    # model from another addons path does not define it.
    allowed_user_ids = fields.Many2many(
        "res.users", compute="_compute_allowed_user_ids", readonly=True
    )
    job_state = fields.Selection([
        ("initialize", "Initialized"),
        ("review", "Reviewed"),
        ("post", "Posted"),
        ("reject", "Rejected"),
    ], string="Status", default="post")
    approval_state = fields.Selection([
        ("initialize", "Initialized"),
        ("review", "Reviewed / Pending Approval"),
        ("post", "Posted"),
        ("reject", "Rejected"),
    ], string="Status", default="post")

    # endregion [Fields]

    @api.depends("company_id")
    def _compute_allowed_user_ids(self):
        company_ids = self.company_id.ids
        domain = [("share", "=", False)]
        if company_ids:
            domain.append(("company_ids", "in", company_ids))
        users_by_company = dict(
            self.env["res.users"]._read_group(
                domain=domain,
                groupby=["company_id"],
                aggregates=["id:recordset"],
            )
        )
        all_users = self.env["res.users"]
        for users in users_by_company.values():
            all_users |= users
        for job in self:
            job.allowed_user_ids = users_by_company.get(job.company_id, all_users)

    def action_review(self):
        for rec in self:
            rec.job_state = "review"
            rec.approval_state = "review"

    def action_post(self):
        for rec in self:
            rec.website_published = True
            rec.job_state = "post"
            rec.approval_state = "post"

    def action_reject(self):
        for rec in self:
            rec.job_state = "reject"
            rec.approval_state = "reject"

    def _compute_website_url(self):
        super()._compute_website_url()
        for job in self:
            job.website_url = f"/job/{job.id}"
