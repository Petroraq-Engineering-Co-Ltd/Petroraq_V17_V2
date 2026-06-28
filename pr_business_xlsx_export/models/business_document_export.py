# -*- coding: utf-8 -*-

from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def action_export_business_xlsx(self):
        return self.env.ref(
            "pr_business_xlsx_export.action_purchase_order_xlsx"
        ).report_action(self)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_export_business_xlsx(self):
        return self.env.ref(
            "pr_business_xlsx_export.action_sale_order_xlsx"
        ).report_action(self)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_export_business_xlsx(self):
        return self.env.ref(
            "pr_business_xlsx_export.action_account_move_xlsx"
        ).report_action(self)

