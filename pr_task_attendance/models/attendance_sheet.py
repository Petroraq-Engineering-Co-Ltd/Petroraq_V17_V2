from odoo import _, fields, models


SNAPSHOT_FIELDS = (
    "status", "note", "worked_hours", "overtime", "act_overtime",
    "late_in", "act_late_in", "late_in_minutes", "early_check_out",
    "early_check_out_minutes", "diff_time", "act_diff_time",
)


class AttendanceSheet(models.Model):
    _inherit = "attendance.sheet"

    def get_attendances(self):
        result = super().get_attendances()
        self._apply_daily_task_absences()
        return result

    def action_confirm(self):
        self._apply_daily_task_absences()
        return super().action_confirm()

    def action_approve(self):
        self._apply_daily_task_absences()
        return super().action_approve()

    def _apply_daily_task_absences(self):
        for sheet in self.filtered(lambda sheet: sheet.state in ("draft", "confirm")):
            days = self.env["hr.task.attendance.day"].sudo().search([
                ("employee_id", "=", sheet.employee_id.id),
                ("date", ">=", sheet.date_from), ("date", "<=", sheet.date_to),
            ])
            blocked_dates = set(days.filtered(lambda day: day.state != "approved").mapped("date"))
            for line in sheet.line_ids:
                if line.date in blocked_dates and line.status not in ("leave", "weekend", "ph"):
                    if line.task_absence_snapshot:
                        continue
                    snapshot = {name: line[name] for name in SNAPSHOT_FIELDS}
                    values = {name: 0.0 for name in SNAPSHOT_FIELDS if name not in ("status", "note")}
                    values.update({
                        "status": "ab", "note": _("Absent: no daily task submission; HR mark-present approval required."),
                        "task_absence_snapshot": snapshot,
                        "diff_time": max(line.pl_sign_out - line.pl_sign_in, 0.0),
                        "act_diff_time": max(line.pl_sign_out - line.pl_sign_in, 0.0),
                    })
                    line.write(values)
                elif line.task_absence_snapshot:
                    values = dict(line.task_absence_snapshot)
                    values["task_absence_snapshot"] = False
                    line.write(values)


class AttendanceSheetLine(models.Model):
    _inherit = "attendance.sheet.line"

    task_absence_snapshot = fields.Json(readonly=True, copy=False)
