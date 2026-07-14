from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .eos_calculation import get_eosb_breakdown, get_service_duration


class PrEosCalculator(models.Model):
    _name = "pr.eos.calculator"
    _description = "EOSB Calculator"
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        compute="_compute_name",
        store=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        default=lambda self: self._default_employee_id(),
    )
    contract_id = fields.Many2one(
        "hr.contract",
        string="Latest Contract",
        compute="_compute_contract_inputs",
        store=True,
        readonly=False,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_contract_inputs",
        store=True,
        readonly=False,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        readonly=True,
    )
    contract_start_date = fields.Date(
        string="Contract Start Date",
        compute="_compute_contract_inputs",
        store=True,
        readonly=False,
        required=True,
    )
    contract_end_date = fields.Date(
        string="Contract End Date",
        compute="_compute_contract_inputs",
        store=True,
        readonly=False,
        required=True,
    )
    monthly_salary = fields.Monetary(
        string="Monthly Salary",
        compute="_compute_contract_inputs",
        store=True,
        readonly=False,
        currency_field="currency_id",
        help="Latest gross salary from the employee contract.",
    )
    service_period = fields.Char(
        string="Service Period",
        compute="_compute_eosb",
        store=True,
    )
    service_years = fields.Float(
        string="Service Years",
        compute="_compute_eosb",
        store=True,
    )
    completed_years = fields.Integer(
        string="Completed Years",
        compute="_compute_eosb",
        store=True,
    )
    remaining_months = fields.Integer(
        string="Remaining Months",
        compute="_compute_eosb",
        store=True,
    )
    remaining_days = fields.Integer(
        string="Remaining Days",
        compute="_compute_eosb",
        store=True,
    )
    eligibility_status = fields.Selection(
        [
            ("eligible", "Eligible"),
            ("not_eligible", "Not Eligible"),
        ],
        string="Eligibility Status",
        compute="_compute_eosb",
        store=True,
    )
    eligibility_message = fields.Char(
        string="Eligibility Message",
        compute="_compute_eosb",
        store=True,
    )
    eosb_formula_applied = fields.Text(
        string="EOSB Formula Applied",
        compute="_compute_eosb",
        store=True,
    )
    final_eosb_amount = fields.Monetary(
        string="Final EOSB Amount",
        compute="_compute_eosb",
        store=True,
        currency_field="currency_id",
    )

    @api.model
    def _default_employee_id(self):
        return self.env.user.employee_id.id if self.env.user.employee_id else False

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        employee = self.env["hr.employee"].browse(vals.get("employee_id")).exists()
        if not employee:
            employee = self._current_user_employee()
        if not employee:
            return vals

        contract = self._get_latest_contract(employee)
        today = fields.Date.context_today(self)
        vals.setdefault("employee_id", employee.id)
        if "company_id" in fields_list:
            company = employee.company_id or (contract.company_id if contract else False) or self.env.company
            vals["company_id"] = company.id
        if contract:
            if "contract_id" in fields_list:
                vals["contract_id"] = contract.id
            if "contract_start_date" in fields_list:
                vals["contract_start_date"] = contract.joining_date or contract.date_start
            if "contract_end_date" in fields_list:
                vals["contract_end_date"] = contract.date_end or getattr(contract, "expected_end_date", False) or today
            if "monthly_salary" in fields_list:
                vals["monthly_salary"] = self._get_contract_monthly_salary(contract)
        elif "contract_end_date" in fields_list:
            vals["contract_end_date"] = today
        return vals

    def _get_latest_contract(self, employee):
        if not employee:
            return self.env["hr.contract"]
        if employee.contract_id:
            return employee.contract_id
        return self.env["hr.contract"].search(
            [("employee_id", "=", employee.id)],
            order="date_start desc, id desc",
            limit=1,
        )

    def _get_contract_monthly_salary(self, contract):
        if not contract:
            return 0.0
        return contract.gross_amount or contract.net_amount or contract.wage or 0.0

    def _current_user_employee(self):
        return self.env.user.employee_id

    def _is_self_service_user(self):
        user = self.env.user
        return (
            user.has_group("de_hr_workspace.group_hr_employee_workspace")
            and not user.has_group("hr.group_hr_user")
        )

    def _check_self_service_employee(self, employee_id):
        if not self._is_self_service_user():
            return
        employee = self._current_user_employee()
        if not employee:
            raise AccessError(_("Your user is not linked to an employee record."))
        if employee_id and employee_id != employee.id:
            raise AccessError(_("You can only calculate EOSB for your own employee record."))

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        self._compute_contract_inputs()

    @api.depends("employee_id", "contract_end_date")
    def _compute_name(self):
        for rec in self:
            employee_name = rec.employee_id.display_name or _("Employee")
            end_date = rec.contract_end_date or fields.Date.context_today(rec)
            rec.name = _("EOSB - %(employee)s - %(date)s") % {
                "employee": employee_name,
                "date": end_date,
            }

    @api.depends(
        "employee_id",
        "employee_id.contract_id",
        "employee_id.contract_id.joining_date",
        "employee_id.contract_id.date_start",
        "employee_id.contract_id.date_end",
        "employee_id.contract_id.expected_end_date",
        "employee_id.contract_id.gross_amount",
        "employee_id.contract_id.net_amount",
        "employee_id.contract_id.wage",
    )
    def _compute_contract_inputs(self):
        today = fields.Date.context_today(self)
        for rec in self:
            contract = rec._get_latest_contract(rec.employee_id)
            rec.contract_id = contract
            contract_company = contract.company_id if contract else False
            rec.company_id = (
                rec.employee_id.company_id
                or contract_company
                or rec.company_id
                or self.env.company
            )
            if contract:
                rec.contract_start_date = contract.joining_date or contract.date_start
                rec.contract_end_date = (
                    contract.date_end
                    or getattr(contract, "expected_end_date", False)
                    or rec.contract_end_date
                    or today
                )
                rec.monthly_salary = rec._get_contract_monthly_salary(contract)
            else:
                rec.contract_start_date = False
                rec.contract_end_date = rec.contract_end_date or today
                rec.monthly_salary = 0.0

    @api.depends("contract_start_date", "contract_end_date", "monthly_salary")
    def _compute_eosb(self):
        for rec in self:
            duration = get_service_duration(rec.contract_start_date, rec.contract_end_date)
            breakdown = get_eosb_breakdown(
                rec.monthly_salary,
                duration["service_years"],
                duration["years"],
            )
            rec.service_period = duration["period_display"]
            rec.service_years = duration["service_years"]
            rec.completed_years = duration["years"]
            rec.remaining_months = duration["months"]
            rec.remaining_days = duration["days"]
            rec.eligibility_status = breakdown["status"]
            rec.eligibility_message = breakdown["message"]
            rec.eosb_formula_applied = breakdown["formula"]
            rec.final_eosb_amount = breakdown["amount"]

    @api.constrains("contract_start_date", "contract_end_date", "monthly_salary")
    def _check_inputs(self):
        for rec in self:
            if rec.contract_start_date and rec.contract_end_date and rec.contract_end_date < rec.contract_start_date:
                raise ValidationError(_("Contract End Date cannot be before Contract Start Date."))
            if rec.monthly_salary < 0.0:
                raise ValidationError(_("Monthly Salary cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        employee = self._current_user_employee()
        prepared_vals = []
        for vals in vals_list:
            vals = dict(vals)
            if self._is_self_service_user() and employee:
                vals["employee_id"] = employee.id
            self._check_self_service_employee(vals.get("employee_id"))
            prepared_vals.append(vals)
        return super().create(prepared_vals)

    def write(self, vals):
        if "employee_id" in vals:
            self._check_self_service_employee(vals.get("employee_id"))
        return super().write(vals)


class HrWorkspaceDashboardService(models.AbstractModel):
    _inherit = "de.hr.workspace.dashboard.service"

    @api.model
    def _style_for_menu(self, menu_name):
        name = (menu_name or "").lower()
        if "eos" in name or "end of service" in name:
            return "fa-calculator", "success"
        return super()._style_for_menu(menu_name)
