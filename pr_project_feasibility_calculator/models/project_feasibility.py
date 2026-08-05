from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectFeasibilityCalculation(models.Model):
    _name = "project.feasibility.calculation"
    _description = "Project Feasibility Calculation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    project_name = fields.Char(required=True, tracking=True)
    calculation_date = fields.Date(
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    investment_amount = fields.Monetary(required=True, tracking=True)
    total_project_amount = fields.Monetary(
        string="Total Project Amount",
        tracking=True,
    )
    projected_total_profit = fields.Monetary(
        string="Projected Total Project Profit",
        required=True,
        tracking=True,
    )
    investor_ratio = fields.Float(
        string="Investor Profit Share (%)",
        required=True,
        default=50.0,
        digits=(5, 2),
        tracking=True,
    )
    partner_ratio = fields.Float(
        string="Partner Profit Share (%)",
        compute="_compute_results",
        store=True,
    )
    expected_monthly_rate = fields.Float(
        string="Expected Fixed Return per Month (%)",
        required=True,
        default=5.0,
        tracking=True,
    )
    duration_months = fields.Integer(
        string="Project Duration (Months)",
        required=True,
        default=6,
        tracking=True,
    )
    investor_projected_profit = fields.Monetary(
        compute="_compute_results",
        store=True,
    )
    required_profit = fields.Monetary(
        string="Required Profit",
        compute="_compute_results",
        store=True,
    )
    profit_variance = fields.Monetary(
        compute="_compute_results",
        store=True,
    )
    projected_monthly_profit = fields.Monetary(
        compute="_compute_results",
        store=True,
    )
    minimum_feasible_ratio = fields.Float(
        string="Minimum Feasible Investor Share (%)",
        compute="_compute_results",
        store=True,
        digits=(5, 2),
    )
    required_total_project_profit = fields.Monetary(
        compute="_compute_results",
        store=True,
    )
    projected_roi = fields.Float(
        string="Projected Investor ROI (%)",
        compute="_compute_results",
        store=True,
    )
    feasible = fields.Boolean(compute="_compute_results", store=True, index=True)
    feasibility_status = fields.Selection(
        [
            ("feasible", "Feasible"),
            ("not_feasible", "Not Feasible"),
            ("impossible", "Not Feasible at Any Split"),
        ],
        compute="_compute_results",
        store=True,
        index=True,
    )
    notes = fields.Text()

    @api.depends(
        "investment_amount",
        "projected_total_profit",
        "investor_ratio",
        "expected_monthly_rate",
        "duration_months",
    )
    def _compute_results(self):
        for record in self:
            ratio = max(min(record.investor_ratio or 0.0, 100.0), 0.0)
            investment = max(record.investment_amount or 0.0, 0.0)
            total_profit = max(record.projected_total_profit or 0.0, 0.0)
            months = max(record.duration_months or 0, 0)
            rate = max(record.expected_monthly_rate or 0.0, 0.0)

            investor_profit = total_profit * ratio / 100.0
            required = investment * rate / 100.0 * months
            minimum_ratio = required / total_profit * 100.0 if total_profit else 0.0
            required_total = required / (ratio / 100.0) if ratio else 0.0

            record.partner_ratio = 100.0 - ratio
            record.investor_projected_profit = investor_profit
            record.required_profit = required
            record.profit_variance = investor_profit - required
            record.projected_monthly_profit = investor_profit / months if months else 0.0
            record.minimum_feasible_ratio = minimum_ratio
            record.required_total_project_profit = required_total
            record.projected_roi = investor_profit / investment * 100.0 if investment else 0.0
            record.feasible = bool(
                investment > 0
                and months > 0
                and investor_profit >= required
            )
            if total_profit and minimum_ratio > 100.0:
                record.feasibility_status = "impossible"
            elif record.feasible:
                record.feasibility_status = "feasible"
            else:
                record.feasibility_status = "not_feasible"

    @api.constrains(
        "investment_amount",
        "total_project_amount",
        "projected_total_profit",
        "investor_ratio",
        "expected_monthly_rate",
        "duration_months",
    )
    def _check_inputs(self):
        for record in self:
            if record.investment_amount <= 0:
                raise ValidationError(_("Investment Amount must be greater than zero."))
            if record.total_project_amount < 0:
                raise ValidationError(_("Total Project Amount cannot be negative."))
            if record.projected_total_profit < 0:
                raise ValidationError(_("Projected Profit cannot be negative."))
            if not 0 < record.investor_ratio <= 100:
                raise ValidationError(_("Investor Profit Share must be between 0 and 100."))
            if record.expected_monthly_rate < 0:
                raise ValidationError(_("Expected Monthly Rate cannot be negative."))
            if record.duration_months <= 0:
                raise ValidationError(_("Project Duration must be greater than zero."))
            if record.duration_months > 120:
                raise ValidationError(_("Project Duration cannot exceed 120 months."))

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    sequence.next_by_code("project.feasibility.calculation")
                    or _("New")
                )
        return super().create(vals_list)

    def _calculator_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "project_name": self.project_name,
            "calculation_date": fields.Date.to_string(self.calculation_date),
            "currency_id": self.currency_id.id,
            "currency_name": self.currency_id.name,
            "currency_symbol": self.currency_id.symbol,
            "investment_amount": self.investment_amount,
            "total_project_amount": self.total_project_amount,
            "projected_total_profit": self.projected_total_profit,
            "investor_ratio": self.investor_ratio,
            "partner_ratio": self.partner_ratio,
            "expected_monthly_rate": self.expected_monthly_rate,
            "duration_months": self.duration_months,
            "investor_projected_profit": self.investor_projected_profit,
            "required_profit": self.required_profit,
            "profit_variance": self.profit_variance,
            "projected_monthly_profit": self.projected_monthly_profit,
            "minimum_feasible_ratio": self.minimum_feasible_ratio,
            "required_total_project_profit": self.required_total_project_profit,
            "projected_roi": self.projected_roi,
            "feasible": self.feasible,
            "feasibility_status": self.feasibility_status,
            "notes": self.notes or "",
        }

    def action_export_xlsx(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/project-feasibility/%s/xlsx" % self.id,
            "target": "new",
        }

    @api.model
    def get_calculator_data(self, limit=12):
        currency = self.env.company.currency_id
        records = self.search([], limit=max(min(int(limit or 12), 50), 1))
        return {
            "currency": {
                "id": currency.id,
                "name": currency.name,
                "symbol": currency.symbol,
                "position": currency.position,
            },
            "records": [record._calculator_dict() for record in records],
        }

    @api.model
    def save_calculation(self, values):
        allowed_fields = {
            "project_name",
            "investment_amount",
            "total_project_amount",
            "projected_total_profit",
            "investor_ratio",
            "expected_monthly_rate",
            "duration_months",
            "notes",
        }
        clean_values = {
            field_name: values[field_name]
            for field_name in allowed_fields
            if field_name in values
        }
        record_id = int(values.get("id") or 0)
        if record_id:
            record = self.browse(record_id).exists()
            if not record:
                raise ValidationError(_("The saved calculation no longer exists."))
            record.write(clean_values)
        else:
            record = self.create(clean_values)
        return record._calculator_dict()
