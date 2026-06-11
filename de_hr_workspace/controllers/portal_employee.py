# -*- coding: utf-8 -*-

from werkzeug.exceptions import NotFound

from odoo.http import request


def get_current_employee():
    return request.env["hr.employee"].sudo().search(
        [("user_id", "=", request.env.user.id), ("active", "=", True)],
        limit=1,
    )


def require_current_employee():
    employee = get_current_employee()
    if not employee:
        raise NotFound()
    return employee


def employee_portal_count(model_name, domain, minimum=1):
    if not get_current_employee():
        return 0
    count = request.env[model_name].search_count(domain)
    return max(count, minimum) if minimum else count
