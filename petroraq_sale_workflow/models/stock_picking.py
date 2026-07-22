from odoo import models, _, api, fields
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = "stock.move"

    def _pr_get_delivery_line_description(self):
        """Return a useful DN description for both sales and purchase moves."""
        self.ensure_one()
        product = self.product_id
        product_headings = {
            (product.name or "").strip(),
            (product.display_name or "").strip(),
        }
        if product.default_code:
            product_headings.add(
                "[%s] %s" % (product.default_code, product.name or "")
            )

        def clean_description(value):
            lines = (value or "").strip().splitlines()
            while lines and lines[0].strip() in product_headings:
                lines = lines[1:]
            return "\n".join(lines).strip()

        # Purchase receipts normally carry their entered text directly on the
        # move. Sales deliveries can contain only the auto-generated product
        # heading there, so fall back to the originating SO line description.
        candidates = [self.description_picking]
        if self.sale_line_id:
            candidates.append(self.sale_line_id.name)
        if self.purchase_line_id:
            candidates.append(self.purchase_line_id.name)
        candidates.append(self.name)

        for candidate in candidates:
            description = clean_description(candidate)
            if description:
                return description

        return (product.name or product.display_name or "").strip()


class StockPicking(models.Model):
    _inherit = "stock.picking"

    sale_state = fields.Selection(related="sale_id.state", string="Sale Order Status", readonly=True)
    delivery_note_po_number = fields.Char(related="sale_id.po_number", string="PO Number", readonly=True)
    delivery_note_po_date = fields.Date(related="sale_id.po_date", string="PO Date", readonly=True)
    delivery_note_ship_to_partner_id = fields.Many2one("res.partner", string="Ship To")
    delivery_note_ship_to_address = fields.Text(string="Ship To Address")
    delivery_note_contact_person_name = fields.Char(string="Contact Person Name")
    delivery_note_contact_person_phone = fields.Char(string="Contact Person Contact")

    def _pr_format_partner_address(self, partner):
        if not partner:
            return ""

        partner = partner.sudo()
        lines = []
        if partner.name:
            lines.append(partner.name)

        address = partner._display_address(without_company=True) or ""
        lines.extend(line for line in address.splitlines() if line)

        phone = partner.phone or partner.mobile
        if phone:
            lines.append(phone)

        return "\n".join(lines)

    def _pr_get_default_delivery_contact(self):
        self.ensure_one()
        sale = self.sale_id
        if not sale:
            return "", ""

        name = sale.inquiry_contact_person if "inquiry_contact_person" in sale._fields else ""
        phone = sale.inquiry_contact_person_phone if "inquiry_contact_person_phone" in sale._fields else ""
        if name or phone:
            return name or "", phone or ""

        inquiry = sale.order_inquiry_id if "order_inquiry_id" in sale._fields else False
        contact = inquiry.contact_partner_id if inquiry and inquiry.contact_partner_id else False
        if contact:
            return contact.name or "", contact.phone or contact.mobile or ""

        partner = sale.partner_id
        return partner.name or "", partner.phone or partner.mobile or ""

    def _pr_set_delivery_note_defaults(self):
        for picking in self:
            if picking.picking_type_code != "outgoing":
                continue

            vals = {}
            partner = picking.delivery_note_ship_to_partner_id or picking.partner_id
            if partner and not picking.delivery_note_ship_to_partner_id:
                vals["delivery_note_ship_to_partner_id"] = partner.id
            if partner and not picking.delivery_note_ship_to_address:
                vals["delivery_note_ship_to_address"] = picking._pr_format_partner_address(partner)

            contact_name, contact_phone = picking._pr_get_default_delivery_contact()
            if contact_name and not picking.delivery_note_contact_person_name:
                vals["delivery_note_contact_person_name"] = contact_name
            if contact_phone and not picking.delivery_note_contact_person_phone:
                vals["delivery_note_contact_person_phone"] = contact_phone

            if vals:
                picking.write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        pickings._pr_set_delivery_note_defaults()
        return pickings

    @api.onchange("partner_id", "sale_id")
    def _onchange_delivery_note_sale_defaults(self):
        for picking in self:
            partner = picking.delivery_note_ship_to_partner_id or picking.partner_id
            if partner and not picking.delivery_note_ship_to_partner_id:
                picking.delivery_note_ship_to_partner_id = partner
            if partner and not picking.delivery_note_ship_to_address:
                picking.delivery_note_ship_to_address = picking._pr_format_partner_address(partner)

            contact_name, contact_phone = picking._pr_get_default_delivery_contact()
            if contact_name and not picking.delivery_note_contact_person_name:
                picking.delivery_note_contact_person_name = contact_name
            if contact_phone and not picking.delivery_note_contact_person_phone:
                picking.delivery_note_contact_person_phone = contact_phone

    @api.onchange("delivery_note_ship_to_partner_id")
    def _onchange_delivery_note_ship_to_partner_id(self):
        for picking in self:
            if picking.delivery_note_ship_to_partner_id:
                picking.delivery_note_ship_to_address = picking._pr_format_partner_address(
                    picking.delivery_note_ship_to_partner_id
                )

    def button_validate(self):
        for picking in self:
            if picking.picking_type_code != "outgoing":
                continue

            sale = picking.sale_id
            if not sale:
                continue

            # ==========================================================
            # (1) BLOCK OVER-DELIVERY (supports partial deliveries)
            # total_after = already_delivered + done_in_this_picking
            # ==========================================================
            done_by_sol = {}

            # Use move lines (qty_done) because that's what user edits/validates
            for ml in picking.move_line_ids:
                move = ml.move_id
                sol = move.sale_line_id

                if not sol or move.scrapped or move.state == "cancel":
                    continue

                sale_uom = sol.product_uom
                qty_sale_uom = ml.product_uom_id._compute_quantity(ml.quantity, sale_uom)

                done_by_sol[sol] = done_by_sol.get(sol, 0.0) + qty_sale_uom

            for sol, done_this in done_by_sol.items():
                ordered = sol.product_uom_qty  # in sale UoM
                delivered = sol.qty_delivered  # already delivered (historical), in sale UoM
                total_after = delivered + done_this
                prec = sol.product_uom.rounding

                if float_compare(total_after, ordered, precision_rounding=prec) > 0:
                    raise UserError(_(
                        "Over-delivery is not allowed.\n\n"
                        "Delivery: %(picking)s\n"
                        "Sale Order: %(so)s\n"
                        "Product: %(product)s\n"
                        "Ordered: %(ordered)s\n"
                        "Already delivered: %(delivered)s\n"
                        "This delivery: %(this)s\n"
                        "Total after: %(total)s"
                    ) % {
                                        "picking": picking.name,
                                        "so": sale.name,
                                        "product": sol.product_id.display_name,
                                        "ordered": ordered,
                                        "delivered": delivered,
                                        "this": done_this,
                                        "total": total_after,
                                    })

            # ==========================================================
            # (2) ADVANCE requires paid DP (your rule)
            # ==========================================================
            if sale.payment_term_id and (sale.payment_term_id.name or "").strip().lower() == "advance":
                dp_invoices = sale.invoice_ids.filtered(lambda inv:
                                                        inv.state == "posted"
                                                        and inv.move_type == "out_invoice"
                                                        and inv.payment_state in ("paid", "in_payment")
                                                        and any(
                                                            (aml.price_subtotal or 0.0) > 0
                                                            and aml.sale_line_ids.filtered(
                                                                lambda sol: getattr(sol, "is_downpayment", False))
                                                            for aml in inv.invoice_line_ids
                                                        )
                                                        )
                if not dp_invoices:
                    raise UserError(_(
                        "You cannot validate this delivery.\n\n"
                        "A Down Payment invoice must be posted and paid (or in payment) "
                        "before delivering an Advance order."
                    ))

        return super().button_validate()


# class StockMoveLine(models.Model):
#     _inherit = "stock.move.line"
#
#     @api.constrains("qty_done")
#     def _constrains_no_overdelivery(self):
#         for ml in self:
#             picking = ml.picking_id
#             move = ml.move_id
#
#             if not picking or picking.picking_type_code != "outgoing" or not picking.sale_id:
#                 continue
#             if not move.sale_line_id or move.scrapped:
#                 continue
#
#             ordered = move.sale_line_id.product_uom_qty
#             done = sum(move.move_line_ids.mapped("qty_done"))
#             rounding = move.product_uom.rounding or 0.0
#
#             if done > ordered + rounding:
#                 raise ValidationError(_(
#                     "Over-delivery is not allowed.\n\n"
#                     "Product: %(product)s\n"
#                     "Ordered: %(ordered)s\n"
#                     "Trying to deliver: %(done)s"
#                 ) % {
#                                           "product": move.product_id.display_name,
#                                           "ordered": ordered,
#                                           "done": done,
#                                       })


class SaleOrderDiscount(models.TransientModel):
    _inherit = "sale.order.discount"

    @api.model
    def _get_discount_type_selection(self):
        """Keep only 'On All Order Lines'"""
        return [
            ('sol_discount', "On All Order Lines"),
        ]

    discount_type = fields.Selection(
        selection=_get_discount_type_selection,
        default='sol_discount',
        required=True,
    )
