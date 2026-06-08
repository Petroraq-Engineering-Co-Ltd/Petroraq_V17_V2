from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import json


CODE_SEQUENCE_START = 1001


class AccountAnalyticAccount(models.Model):
    # region [Initial]
    _inherit = 'account.analytic.account'
    # endregion [Initial]


    project_code = fields.Char(string="Legacy Project Code")
    project_partner_id = fields.Many2one("res.partner", string="Manager", tracking=True)
    analytic_plan_type = fields.Selection([
        ("department", "Department"),
        ("section", "Section"),
        ("project", "Project"),
        ("employee", "Employee"),
        ("asset", "Asset"),
    ], related="plan_id.analytic_plan_type", string="Plan Type", store=True, tracking=True)
    department_id = fields.Many2one("account.analytic.account", string="Department", domain="[('analytic_plan_type', '=', 'department')]")
    section_id = fields.Many2one("account.analytic.account", string="Section", domain="[('analytic_plan_type', '=', 'section')]")
    section_id_domain = fields.Char(string='Section Domain', compute="_compute_section_id_domain")
    project_id = fields.Many2one("account.analytic.account", string="Project", domain="[('analytic_plan_type', '=', 'project')]")

    @api.constrains("project_code")
    def _check_project_code(self):
        if self.env.context.get("skip_cost_center_code_check"):
            return
        for rec in self:
            if rec.project_code:
                project_cost_center_id = self.env["account.analytic.account"].sudo().search([
                    ("project_code", "=", rec.project_code),
                    ("analytic_plan_type", "=", "project"),
                    ("id", "!=", rec.id),
                ], limit=1)
                if project_cost_center_id:
                    raise ValidationError(f"This Project Code {rec.project_code} Exists Before With Project {project_cost_center_id.name}, Please Check !!")

    @api.constrains("code")
    def _check_cost_center_code(self):
        if self.env.context.get("skip_cost_center_code_check"):
            return
        for rec in self:
            if not rec.code:
                raise ValidationError(_("Cost Center Code is required."))
            duplicate = self.sudo().search([
                ("code", "=", rec.code),
                ("id", "!=", rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("Cost Center Code %(code)s already exists on %(cost_center)s.")
                    % {"code": rec.code, "cost_center": duplicate.display_name}
                )

    @api.depends("analytic_plan_type", "department_id")
    def _compute_section_id_domain(self):
        for rec in self:
            if rec.analytic_plan_type == "project" and rec.department_id:
                section_ids = self.env["account.analytic.account"].sudo().search([("analytic_plan_type", "=", "section"), ("department_id", "=", rec.department_id.id)])
                if section_ids:
                    rec.section_id_domain = json.dumps([('id', 'in', section_ids.ids)])
                else:
                    rec.section_id_domain = "[('analytic_plan_type', '=', 'section')]"
            else:
                rec.section_id_domain = "[('analytic_plan_type', '=', 'section')]"

    @api.model
    def _split_yearly_cost_center_code(self, code):
        if not code or "-" not in code:
            return False, False
        year, number = code.split("-", 1)
        if len(year) != 4 or not year.isdigit() or not number.isdigit():
            return False, False
        return int(year), int(number)

    @api.model
    def _format_yearly_cost_center_code(self, year, number):
        return "%s-%04d" % (year, number)

    @api.model
    def _cost_center_code_year(self, value=False):
        value = value or self.env.context.get("pr_cost_center_code_date") or fields.Date.context_today(self)
        return fields.Date.to_date(value).year

    @api.model
    def _next_cost_center_number_by_year(self):
        numbers_by_year = {}
        accounts = self.with_context(active_test=False).sudo().search([("code", "!=", False)])
        for account in accounts:
            year, number = self._split_yearly_cost_center_code(account.code)
            if year:
                numbers_by_year[year] = max(numbers_by_year.get(year, CODE_SEQUENCE_START - 1), number)
        return numbers_by_year

    @api.model_create_multi
    def create(self, vals_list):
        numbers_by_year = self._next_cost_center_number_by_year()
        for vals in vals_list:
            if not vals.get("code"):
                year = self._cost_center_code_year()
                number = numbers_by_year.get(year, CODE_SEQUENCE_START - 1) + 1
                numbers_by_year[year] = number
                vals["code"] = self._format_yearly_cost_center_code(year, number)

        records = super().create(vals_list)
        projects = records.filtered(lambda rec: rec.analytic_plan_type == "project" and rec.project_code != rec.code)
        for project in projects:
            project.with_context(skip_cost_center_code_check=True).project_code = project.code
        return records

    def write(self, vals):
        result = super().write(vals)
        if "code" in vals:
            projects = self.filtered(lambda rec: rec.analytic_plan_type == "project" and rec.project_code != rec.code)
            for project in projects:
                project.with_context(skip_cost_center_code_check=True).project_code = project.code
        return result

    @api.model
    def action_resequence_cost_center_codes(self):
        records = self.with_context(active_test=False).sudo().search([], order="create_date, id")
        counters = {}
        for rec in records:
            code_date = rec.create_date or fields.Date.context_today(self)
            year = rec._cost_center_code_year(code_date)
            counters[year] = counters.get(year, CODE_SEQUENCE_START - 1) + 1
            code = rec._format_yearly_cost_center_code(year, counters[year])
            vals = {"code": code}
            if rec.analytic_plan_type == "project":
                vals["project_code"] = code
            rec.with_context(skip_cost_center_code_check=True).write(vals)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Cost Center Codes Resequenced"),
                "message": _("%s cost centers were resequenced by creation year.") % len(records),
                "type": "success",
                "sticky": False,
            },
        }

    @api.depends('name', 'code', 'project_code', 'analytic_plan_type')
    def _compute_display_name(self):
        for rec in self:
            if rec.code:
                rec.display_name = rec.code
            elif rec.project_code:
                rec.display_name = rec.project_code
            elif rec.name:
                rec.display_name = rec.name
            else:
                rec.display_name = False

    def name_get(self):
        result = []
        for rec in self:
            name = rec.code or rec.project_code or rec.name or _("Unnamed Cost Center")
            result.append((rec.id, name))
        return result

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        args = args or []
        if name:
            domain = ["|", "|", ("code", operator, name), ("project_code", operator, name), ("name", operator, name)]
            return self.search(domain + args, limit=limit).name_get()
        return super().name_search(name=name, args=args, operator=operator, limit=limit)
