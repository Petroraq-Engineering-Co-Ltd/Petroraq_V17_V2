import io

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools.misc import xlsxwriter


class ProjectFeasibilityExportController(http.Controller):

    @http.route(
        "/project-feasibility/<int:record_id>/xlsx",
        type="http",
        auth="user",
    )
    def export_calculation(self, record_id, **kwargs):
        calculation = request.env["project.feasibility.calculation"].browse(
            record_id
        ).exists()
        if not calculation:
            return request.not_found()
        calculation.check_access_rights("read")
        calculation.check_access_rule("read")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Feasibility")
        navy = "#102A56"
        blue = "#1F5FCC"
        green = "#16865A"
        red = "#C93B34"
        pale_blue = "#EAF1FD"
        pale_green = "#EAF7F1"
        pale_red = "#FDEDEC"

        title = workbook.add_format({
            "bold": True, "font_size": 20, "font_color": "#FFFFFF",
            "bg_color": navy, "align": "center", "valign": "vcenter",
        })
        section = workbook.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": blue,
            "border": 1, "align": "left",
        })
        label = workbook.add_format({
            "bold": True, "bg_color": pale_blue, "border": 1,
        })
        money = workbook.add_format({
            "num_format": '#,##0.00', "border": 1, "align": "right",
        })
        percent = workbook.add_format({
            "num_format": '0.00"%"', "border": 1, "align": "right",
        })
        date_format = workbook.add_format({
            "num_format": "dd-mmm-yyyy", "border": 1,
        })
        value = workbook.add_format({"border": 1})
        status = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": green if calculation.feasible else red,
            "align": "center",
            "border": 1,
        })
        result_fill = workbook.add_format({
            "bold": True,
            "bg_color": pale_green if calculation.feasible else pale_red,
            "border": 1,
            "num_format": '#,##0.00',
        })

        sheet.set_column("A:A", 34)
        sheet.set_column("B:B", 24)
        sheet.set_column("C:C", 4)
        sheet.set_column("D:D", 38)
        sheet.set_column("E:E", 24)
        sheet.set_row(0, 34)
        sheet.merge_range("A1:E1", "PROJECT FEASIBILITY ANALYSIS", title)
        sheet.merge_range("A2:E2", calculation.project_name, workbook.add_format({
            "bold": True, "font_size": 13, "align": "center",
            "font_color": navy,
        }))

        sheet.merge_range("A4:B4", "PROJECT ASSUMPTIONS", section)
        assumptions = [
            ("Reference", calculation.name, value),
            ("Calculation Date", calculation.calculation_date, date_format),
            ("Total Project Amount", calculation.total_project_amount, money),
            ("Investment Amount", calculation.investment_amount, money),
            ("Projected Total Project Profit", calculation.projected_total_profit, money),
            ("Investor Profit Share", calculation.investor_ratio, percent),
            ("Partner Profit Share", calculation.partner_ratio, percent),
            ("Expected Fixed Return / Month", calculation.expected_monthly_rate, percent),
            ("Project Duration (Months)", calculation.duration_months, value),
        ]
        for row, (text, item, item_format) in enumerate(assumptions, 4):
            sheet.write(row, 0, text, label)
            sheet.write(row, 1, item, item_format)

        sheet.merge_range("D4:E4", "FEASIBILITY RESULTS", section)
        results = [
            ("Investor Projected Profit", calculation.investor_projected_profit, money),
            ("Required Profit", calculation.required_profit, money),
            ("Profit Variance", calculation.profit_variance, result_fill),
            ("Projected Monthly Profit", calculation.projected_monthly_profit, money),
            ("Projected Investor ROI", calculation.projected_roi, percent),
            (
                "Status",
                dict(calculation._fields["feasibility_status"].selection).get(
                    calculation.feasibility_status
                ),
                status,
            ),
        ]
        for row, (text, item, item_format) in enumerate(results, 4):
            sheet.write(row, 3, text, label)
            sheet.write(row, 4, item, item_format)

        sheet.merge_range("D12:E12", "REVERSE CALCULATOR", section)
        reverse = [
            ("Minimum Feasible Investor Share", calculation.minimum_feasible_ratio, percent),
            ("Required Total Project Profit", calculation.required_total_project_profit, money),
        ]
        for row, (text, item, item_format) in enumerate(reverse, 12):
            sheet.write(row, 3, text, label)
            sheet.write(row, 4, item, item_format)

        sheet.merge_range("A15:E15", "Notes", section)
        sheet.merge_range("A16:E18", calculation.notes or "", workbook.add_format({
            "text_wrap": True, "valign": "top", "border": 1,
        }))
        sheet.set_landscape()
        sheet.fit_to_pages(1, 1)
        workbook.close()
        content = output.getvalue()
        filename = "%s_Project_Feasibility.xlsx" % calculation.name.replace("/", "-")
        return request.make_response(content, [
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", content_disposition(filename)),
        ])
