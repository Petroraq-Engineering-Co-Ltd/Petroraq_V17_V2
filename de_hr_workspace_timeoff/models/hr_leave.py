from odoo import models, fields, api
from odoo.tools import format_date
from datetime import date

# Same fallback as pr.hr.leave.request._get_available_days_for_request for
# sick leave types that do not require an allocation.
SICK_LEAVE_DEFAULT_DAYS = 30.0


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model
    def _de_leave_dashboard_sort_key(self, leave_type):
        name = (leave_type.name or "").strip().lower()
        leave_type_code = leave_type.leave_type or ""
        priority = 50
        if leave_type_code == "annual_leave" or "annual" in name:
            priority = 0
        elif "marriage" in name or "marrige" in name or "marrigge" in name:
            priority = 1
        elif "emergency" in name:
            priority = 2
        elif "hajj" in name or "haj" in name:
            priority = 3
        elif leave_type_code == "sick_leave" or "sick" in name:
            priority = 4
        return (priority, leave_type.sequence or 100, name, leave_type.id)

    @api.model
    def _de_get_leave_balance_summary(self, employee, leave_types):
        """Return one balance row per leave type for ``employee``.

        Allocation-based types use ``get_allocation_data`` (which syncs due
        accruals first through ``_pr_sync_due_accrual_allocations``) so the
        portal shows the same figures as the backend.
        """
        employee = employee.sudo()
        leave_types = leave_types.sudo()
        allocation_types = leave_types.filtered(lambda lt: lt.requires_allocation == "yes")
        allocation_data = {}
        if allocation_types:
            allocation_data = {
                leave_type_id: data
                for _name, data, _requires_allocation, leave_type_id
                in allocation_types.get_allocation_data(employee).get(employee, [])
            }
        taken_by_type = {
            leave_type.id: days
            for leave_type, days in self.env["hr.leave"].sudo()._read_group(
                [
                    ("employee_id", "=", employee.id),
                    ("holiday_status_id", "in", leave_types.ids),
                    ("state", "=", "validate"),
                ],
                ["holiday_status_id"],
                ["number_of_days:sum"],
            )
        }
        summary = []
        for leave_type in leave_types:
            taken_days = round(taken_by_type.get(leave_type.id, 0.0), 2)
            if leave_type.requires_allocation == "yes":
                data = allocation_data.get(leave_type.id, {})
                allocation_days = round(data.get("max_leaves", 0.0), 2)
                leave_days = round(data.get("leaves_taken", 0.0), 2)
                available_days = round(max(data.get("remaining_leaves", 0.0), 0.0), 2)
            else:
                allocation_days = SICK_LEAVE_DEFAULT_DAYS if leave_type.leave_type == "sick_leave" else 0.0
                leave_days = taken_days
                available_days = round(max(allocation_days - leave_days, 0.0), 2)
            summary.append({
                "sort_key": self._de_leave_dashboard_sort_key(leave_type),
                "leave_type_id": leave_type.id,
                "leave_name": leave_type.name,
                "allocation_days": allocation_days,
                "leave_days": leave_days,
                "taken_days": taken_days,
                "available_days": available_days,
                "remaining_days": leave_days,
                "requires_allocation": leave_type.requires_allocation if leave_type.leave_type != "sick_leave" else "yes",
            })
        summary.sort(key=lambda item: item["sort_key"])
        return summary

    @api.model
    def get_dashboard_data(self):
        today = fields.Date.today()
        current_user = self.env.user
        current_employee_id = self.env["hr.employee"].sudo().search([("user_id", "=", current_user.id), ("active", "=", True)], limit=1)
        summary = []
        if current_employee_id:
            leave_type_ids = self.env["hr.leave.type"].sudo().search(["|", ("company_id", "=", self.env.company.id), ("company_id", "=", False)])
            summary = self._de_get_leave_balance_summary(current_employee_id, leave_type_ids)

            upcoming_leaves = self.env["hr.leave"].sudo().search([
                ('state', '=', 'validate'),
                ('request_date_from', '>=', today),
                ('employee_id', '=', current_employee_id.id)
            ], limit=5, order='request_date_from asc')

            upcoming = [{
                'employee': l.employee_id.name,
                'leave_type': l.holiday_status_id.name,
                'from': format_date(self.env, l.request_date_from),
                'to': format_date(self.env, l.request_date_to),
                'days': l.number_of_days_display,
            } for l in upcoming_leaves]

            pending = [{
                'employee': l.employee_id.name,
                'leave_type': l.holiday_status_id.name,
                'from': format_date(self.env, l.request_date_from),
                'to': format_date(self.env, l.request_date_to),
                'days': l.number_of_days_display,
                'status': l.state,
            } for l in self.search([('state', '=', 'confirm')], limit=5)]

            chart_data = {
                'labels': ['7 Dec', '8 Dec', '9 Dec', '10 Dec', '11 Dec', '12 Dec', '13 Dec'],
                'datasets': [
                    {
                        'label': 'Emergency Leave',
                        'data': [4, 3, 2, 1, 5, 2, 3],
                        'backgroundColor': 'rgba(255, 99, 132, 0.6)',
                    },
                    {
                        'label': 'Annual Leave',
                        'data': [6, 5, 4, 3, 7, 5, 4],
                        'backgroundColor': 'rgba(54, 162, 235, 0.6)',
                    },
                ]
            }

            return {
                'summary': summary,
                'upcoming': upcoming,
                'pending': pending,
                'chart': chart_data,
            }
        return None

    @api.model
    def get_taken_leaves(self):
        current_user = self.env.user
        current_employee_id = self.env["hr.employee"].sudo().search(
            [("user_id", "=", current_user.id), ("active", "=", True)], limit=1)
        taken_leaves = {}
        if current_employee_id:
            leave_type_ids = self.env["hr.leave.type"].sudo().search(
                ["|", ("company_id", "=", self.env.company.id), ("company_id", "=", False)])
            if leave_type_ids:
                for leave_type in leave_type_ids:
                    leave_ids = self.env["hr.leave"].sudo().search([("employee_id", "=", current_employee_id.id),
                                                                    ("holiday_status_id", "=", leave_type.id),
                                                                    ("state", "=", "validate")])
                    if leave_ids:
                        for leave in leave_ids:
                            if leave.holiday_status_id.name not in taken_leaves:
                                taken_leaves[leave.holiday_status_id.name] = leave.number_of_days
                            else:
                                taken_leaves[leave.holiday_status_id.name] += leave.number_of_days
                    else:
                        taken_leaves[leave_type.name] = 0
        return taken_leaves

    @api.model
    def get_our_base_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return base_url

