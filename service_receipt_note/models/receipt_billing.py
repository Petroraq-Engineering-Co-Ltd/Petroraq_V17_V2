from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


class ReceiptBilling(models.AbstractModel):
    _name = "purchase.receipt.billing"
    _description = "Validated receipt billing"

    def _create_receipt_bill(self, receipt, order, quantities, source_field):
        if not self.env.user.has_group("account.group_account_invoice"):
            raise AccessError(_("Only Accounts can create vendor bills from receipts."))
        receipt.check_access_rights("read")
        receipt.check_access_rule("read")
        # Serialize requests so two clicks cannot create two bills for one receipt.
        self.env.cr.execute('SELECT id FROM "%s" WHERE id = %%s FOR UPDATE' % receipt._table, [receipt.id])
        moves = self.env["account.move"]
        existing = moves.search([(source_field, "=", receipt.id), ("state", "!=", "cancel"),
                                 ("move_type", "=", "in_invoice")], limit=1)
        if existing:
            bill = existing
        else:
            lines = []
            for line, quantity in quantities:
                if quantity <= 0:
                    continue
                vals = line._prepare_account_move_line()
                vals["quantity"] = quantity
                lines.append((0, 0, vals))
            if not lines:
                raise UserError(_("This receipt has no received quantities to bill."))
            values = order._prepare_invoice()
            values.update({source_field: receipt.id, "invoice_line_ids": lines,
                           "invoice_date": fields.Date.context_today(receipt)})
            bill = moves.with_company(order.company_id).create(values)
            order._copy_purchase_attachments_to_moves(bill)
            if "attachment_ids" in receipt._fields:
                for attachment in receipt.attachment_ids:
                    attachment.copy({"res_model": "account.move", "res_id": bill.id})
        return {"type": "ir.actions.act_window", "name": _("Vendor Bill"),
                "res_model": "account.move", "res_id": bill.id, "view_mode": "form"}


class ServiceReceipt(models.Model):
    _inherit = "service.receipt.note"

    def action_create_vendor_bill(self):
        self.ensure_one()
        if self.state != "done" or not self.payment_requested:
            raise UserError(_("Validate the SRN and submit the end user's payment request first."))
        return self.env["purchase.receipt.billing"]._create_receipt_bill(
            self, self.purchase_id,
            [(line.purchase_line_id, line.done_qty) for line in self.line_ids], "service_receipt_id",
        )


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_create_receipt_vendor_bill(self):
        self.ensure_one()
        if self.state != "done" or self.picking_type_code != "incoming" or not self.purchase_id:
            raise UserError(_("Only a validated incoming purchase receipt can create a vendor bill."))
        if self._get_receipt_approval_state() != "approved":
            raise UserError(_("The goods receipt must be approved by Inventory Administration."))
        quantities = []
        for move in self.move_ids.filtered(lambda move: move.state == "done" and move.purchase_line_id):
            line = move.purchase_line_id
            quantities.append((line, move.product_uom._compute_quantity(move.quantity, line.product_uom)))
        return self.env["purchase.receipt.billing"]._create_receipt_bill(
            self, self.purchase_id, quantities, "purchase_receipt_id",
        )


class LegacyReceipt(models.Model):
    _inherit = "grn.ses"

    def _require_material_receipt(self):
        if any(line.type == "service" for line in self.line_ids):
            raise UserError(_("Service acceptance now uses Service Receipt Notes. Initiate an SRN from the PO for department-manager validation and an end-user payment request."))

    def action_approve(self):
        self._require_material_receipt()
        if not self.env.user.has_group("pr_custom_purchase.inventory_admin"):
            raise AccessError(_("Only Inventory Administration can approve goods receipts."))
        return super().action_approve()

    def action_create_vendor_bill(self):
        self._require_material_receipt()
        return super().action_create_vendor_bill()


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def action_create_invoice(self):
        raise UserError(_("Create the vendor bill from the validated Goods Receipt or Service Receipt Note, not directly from the PO."))


class AccountMove(models.Model):
    _inherit = "account.move"

    service_receipt_id = fields.Many2one("service.receipt.note", string="Source SRN", copy=False, readonly=True)
    purchase_receipt_id = fields.Many2one("stock.picking", string="Source Goods Receipt", copy=False, readonly=True)

    @api.constrains("invoice_line_ids", "service_receipt_id", "purchase_receipt_id", "state")
    def _check_receipt_bill_source(self):
        for bill in self.filtered(lambda rec: rec.move_type == "in_invoice" and rec.state != "cancel"):
            purchase_lines = bill.invoice_line_ids.purchase_line_id
            if not purchase_lines:
                continue  # Non-PO expenses are outside this workflow.
            if not bill.service_receipt_id and not bill.purchase_receipt_id:
                if "grn_ses_id" in bill._fields and bill.grn_ses_id:
                    continue
                raise ValidationError(_("A purchase-linked vendor bill must originate from a validated receipt."))
            if bill.service_receipt_id and bill.purchase_receipt_id:
                raise ValidationError(_("A bill can reference only one type of receipt."))
            receipt = bill.service_receipt_id or bill.purchase_receipt_id
            order = receipt.purchase_id
            source_field = "service_receipt_id" if bill.service_receipt_id else "purchase_receipt_id"
            self.env.cr.execute('SELECT id FROM "%s" WHERE id = %%s FOR UPDATE' % receipt._table, [receipt.id])
            if self.sudo().search_count([(source_field, "=", receipt.id), ("id", "!=", bill.id),
                                         ("state", "!=", "cancel"), ("move_type", "=", "in_invoice")]):
                raise ValidationError(_("This receipt already has an active vendor bill."))
            if bill.service_receipt_id and not receipt.payment_requested:
                raise ValidationError(_("The requester must submit the SRN payment request before billing."))
            if receipt.state != "done" or any(line.order_id != order for line in purchase_lines):
                raise ValidationError(_("Bill lines must belong to the validated receipt's PO."))
            if bill.partner_id != order.partner_id or bill.company_id != order.company_id:
                raise ValidationError(_("The bill vendor and company must match the receipt's PO."))
            for line in purchase_lines:
                invoice_lines = bill.invoice_line_ids.filtered(lambda item: item.purchase_line_id == line)
                if any(item.quantity < 0 for item in invoice_lines):
                    raise ValidationError(_("Use a vendor credit note for negative receipt quantities."))
                billed = sum(item.product_uom_id._compute_quantity(item.quantity, line.product_uom)
                             for item in invoice_lines)
                if bill.service_receipt_id:
                    received = sum(receipt.line_ids.filtered(lambda item: item.purchase_line_id == line).mapped("done_qty"))
                else:
                    received = sum(move.product_uom._compute_quantity(move.quantity, line.product_uom)
                                   for move in receipt.move_ids.filtered(lambda move: move.purchase_line_id == line and move.state == "done"))
                if float_compare(billed, received, precision_rounding=line.product_uom.rounding) > 0:
                    raise ValidationError(_("Bill quantity cannot exceed the quantity on the source receipt."))


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.constrains("quantity", "product_uom_id", "purchase_line_id", "move_id")
    def _check_source_receipt_quantities(self):
        self.move_id.filtered(lambda move: move.service_receipt_id or move.purchase_receipt_id)._check_receipt_bill_source()
