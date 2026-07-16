from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    advance_payment_ids = fields.One2many(
        "account.payment",
        "purchase_order_id",
        string="Advance Payments",
        readonly=True,
    )
    advance_payment_count = fields.Integer(
        string="Advance Payment Count",
        compute="_compute_advance_payment_summary",
    )
    advance_payment_amount = fields.Monetary(
        string="Advance Payment Amount",
        compute="_compute_advance_payment_summary",
        currency_field="currency_id",
    )
    advance_payment_remaining_amount = fields.Monetary(
        string="Advance Payment Remaining",
        compute="_compute_advance_payment_summary",
        currency_field="currency_id",
    )
    advance_payment_has_vendor_bill = fields.Boolean(
        string="Has Vendor Bill",
        compute="_compute_advance_payment_summary",
    )

    @api.depends(
        "amount_total",
        "currency_id",
        "advance_payment_ids.amount",
        "advance_payment_ids.currency_id",
        "advance_payment_ids.date",
        "advance_payment_ids.state",
        "invoice_ids",
        "invoice_ids.state",
    )
    def _compute_advance_payment_summary(self):
        for order in self:
            active_payments = order.advance_payment_ids.filtered(
                lambda payment: payment.state != "cancel"
            )
            paid_amount = 0.0
            for payment in active_payments:
                payment_currency = payment.currency_id or payment.company_id.currency_id
                paid_amount += payment_currency._convert(
                    payment.amount,
                    order.currency_id,
                    order.company_id,
                    payment.date or fields.Date.context_today(payment),
                )
            order.advance_payment_count = len(active_payments)
            order.advance_payment_amount = paid_amount
            order.advance_payment_remaining_amount = max(order.amount_total - paid_amount, 0.0)
            order.advance_payment_has_vendor_bill = bool(order._get_advance_payment_blocking_bills())

    def _get_advance_payment_blocking_bills(self):
        self.ensure_one()
        return self.invoice_ids.filtered(
            lambda move: move.state != "cancel" and move.move_type in ("in_invoice", "in_refund")
        )

    def action_open_advance_payment_wizard(self):
        self.ensure_one()
        if self.state not in ("purchase", "done"):
            raise UserError(_("Advance payments can only be initiated from confirmed purchase orders."))
        if not self.partner_id:
            raise UserError(_("Please select a vendor before creating an advance payment."))
        if self._get_advance_payment_blocking_bills():
            raise UserError(_("Advance payments cannot be initiated because a vendor bill already exists for this purchase order."))
        if float_compare(
            self.advance_payment_remaining_amount,
            0.0,
            precision_rounding=self.currency_id.rounding,
        ) <= 0:
            raise UserError(_("This purchase order is already fully covered by linked advance payments."))
        return {
            "name": _("Create PO Advance Payment"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.order.advance.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_purchase_order_id": self.id,
            },
        }

    def action_view_advance_payments(self):
        self.ensure_one()
        payments = self.advance_payment_ids.filtered(lambda payment: payment.state != "cancel")
        action = {
            "name": _("Advance Payments"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "context": {"create": False},
        }
        if len(payments) == 1:
            action.update({
                "view_mode": "form",
                "res_id": payments.id,
            })
        else:
            action.update({
                "view_mode": "tree,form",
                "domain": [("id", "in", payments.ids)],
            })
        return action

    def _prepare_advance_payment_vals(self, wizard):
        self.ensure_one()
        vals = {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": self.partner_id.id,
            "amount": wizard.amount,
            "currency_id": self.currency_id.id,
            "date": wizard.payment_date,
            "ref": wizard.memo or _("Advance Payment for %s") % self.name,
            "purchase_order_id": self.id,
        }
        Payment = self.env["account.payment"]
        if "destination_account_id" in Payment._fields:
            vals["destination_account_id"] = self.partner_id.property_account_payable_id.id
        if "partner_bank_id" in Payment._fields and self.partner_id.bank_ids:
            vals["partner_bank_id"] = self.partner_id.bank_ids[:1].id
        return vals


class AccountPayment(models.Model):
    _inherit = "account.payment"

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Purchase Order",
        copy=False,
        index=True,
        readonly=True,
    )
    purchase_order_count = fields.Integer(
        string="Purchase Orders",
        compute="_compute_purchase_order_count",
    )

    def _compute_purchase_order_count(self):
        for payment in self:
            payment.purchase_order_count = 1 if payment.purchase_order_id else 0

    def action_view_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            return False
        return {
            "name": _("Purchase Order"),
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": self.purchase_order_id.id,
            "context": {"create": False},
        }


class PurchaseOrderAdvancePaymentWizard(models.TransientModel):
    _name = "purchase.order.advance.payment.wizard"
    _description = "Purchase Order Advance Payment Wizard"

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Purchase Order",
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="purchase_order_id.company_id",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="purchase_order_id.partner_id",
        string="Vendor",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="purchase_order_id.currency_id",
        readonly=True,
    )
    remaining_amount = fields.Monetary(
        string="Remaining Amount",
        related="purchase_order_id.advance_payment_remaining_amount",
        currency_field="currency_id",
        readonly=True,
    )
    amount = fields.Monetary(
        string="Advance Amount",
        required=True,
        currency_field="currency_id",
    )
    payment_date = fields.Date(
        string="Payment Date",
        default=fields.Date.context_today,
        required=True,
    )
    memo = fields.Char(
        string="Memo",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        order = self.env["purchase.order"].browse(values.get("purchase_order_id")).exists()
        if order:
            values.setdefault("amount", order.advance_payment_remaining_amount)
            values.setdefault("memo", _("Advance Payment for %s") % order.name)
        return values

    @api.constrains("amount")
    def _check_amount(self):
        for wizard in self:
            if float_compare(
                wizard.amount,
                0.0,
                precision_rounding=wizard.currency_id.rounding,
            ) <= 0:
                raise ValidationError(_("Advance amount must be greater than zero."))
            if wizard.purchase_order_id and float_compare(
                wizard.amount,
                wizard.purchase_order_id.advance_payment_remaining_amount,
                precision_rounding=wizard.currency_id.rounding,
            ) > 0:
                raise ValidationError(_("Advance amount cannot exceed the remaining PO amount."))

    def action_create_payment(self):
        self.ensure_one()
        order = self.purchase_order_id
        if order.state not in ("purchase", "done"):
            raise UserError(_("Advance payments can only be initiated from confirmed purchase orders."))
        if order._get_advance_payment_blocking_bills():
            raise UserError(_("Advance payments cannot be created because a vendor bill already exists for this purchase order."))
        self._check_amount()
        payment = self.env["account.payment"].create(order._prepare_advance_payment_vals(self))
        if hasattr(payment, "action_pr_vendor_payment_submit"):
            payment.action_pr_vendor_payment_submit()
        payment.message_post(body=_("Advance payment initiated from Purchase Order %s.") % order.name)
        order.message_post(body=_("Advance payment %s was initiated from this purchase order.") % payment.display_name)
        return {
            "name": _("Advance Payment"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "view_mode": "form",
            "res_id": payment.id,
            "target": "current",
            "context": {"create": False},
        }
