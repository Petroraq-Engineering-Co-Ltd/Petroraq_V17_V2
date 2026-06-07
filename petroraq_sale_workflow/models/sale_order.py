from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_amount, html_escape
from odoo.tools.float_utils import float_round, float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"
    _description = "Quotation"

    def _notify_approval_users(self, users, subject, body_html, summary):
        self.ensure_one()
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for user in users.filtered(lambda u: u.active):
            if activity_type:
                self.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=body_html,
                )
            if user.email:
                self.env["mail.mail"].sudo().create({
                    "email_from": "noreply@petroraq.com",
                    "email_to": user.email,
                    "subject": subject,
                    "body_html": body_html,
                }).send()


    def _get_group_users(self, group_xml_id):
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        return group.users.filtered(lambda u: u.active) if group else self.env["res.users"]

    def _get_effective_md_users(self):
        """MD approvers excluding users already included in manager approval stage."""
        self.ensure_one()
        manager_users = self._get_group_users("petroraq_sale_workflow.group_sale_approval_manager")
        md_users = self._get_group_users("petroraq_sale_workflow.group_sale_approval_md")
        submitter_user = self.create_uid
        manager_effective = manager_users - submitter_user
        md_effective = md_users - submitter_user
        return md_effective - manager_effective

    def _notify_manager_approval(self):
        self.ensure_one()
        group = self.env.ref("petroraq_sale_workflow.group_sale_approval_manager", raise_if_not_found=False)
        if not group:
            return
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = f"{base_url}/web#id={self.id}&model=sale.order&view_type=form"
        body_html = _(
            """<p>Dear Approver,</p>
            <p>Quotation <b>%s</b> is waiting for your manager approval.</p>
            <p><a href=\"%s\">Open Quotation</a></p>"""
        ) % (self.name, record_url)
        manager_users = group.users.filtered(lambda u: u.active) - self.create_uid
        if not manager_users:
            return
        self._notify_approval_users(
            manager_users,
            _("Quotation %s waiting for manager approval") % self.name,
            body_html,
            _("Quotation requires manager approval"),
        )

    def _notify_md_approval(self):
        self.ensure_one()
        md_users = self._get_effective_md_users()
        if not md_users:
            return
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = f"{base_url}/web#id={self.id}&model=sale.order&view_type=form"
        body_html = _(
            """<p>Dear Approver,</p>
            <p>Quotation <b>%s</b> is waiting for your MD approval.</p>
            <p><a href=\"%s\">Open Quotation</a></p>"""
        ) % (self.name, record_url)
        self._notify_approval_users(
            md_users,
            _("Quotation %s waiting for MD approval") % self.name,
            body_html,
            _("Quotation requires MD approval"),
        )

    approval_state = fields.Selection([
        ("draft", "Draft"),
        ("to_manager", "Manager Approve"),
        ("to_md", "MD Approve"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], default="draft", tracking=True, copy=False)
    estimation_id = fields.Many2one(
        "petroraq.estimation",
        string="Estimation",
        readonly=True,
        copy=False,
    )
    estimation_line_ids = fields.One2many(
        "petroraq.estimation.line",
        related="estimation_id.line_ids",
        string="Estimation Lines",
        readonly=True,
    )
    project_attachment_ids = fields.Many2many(
        "ir.attachment",
        "sale_order_project_attachment_rel",
        "sale_order_id",
        "attachment_id",
        string="Project Attachments",
        help="Attachments required for project-type quotations.",
    )
    estimation_display_line_ids = fields.One2many(
        "petroraq.estimation.display.line",
        compute="_compute_estimation_display_line_ids",
        string="Estimation Lines",
        readonly=True,
    )

    can_create_remaining_delivery = fields.Boolean(
        compute="_compute_can_create_remaining_delivery",
    )

    @api.depends(
        "state",
        "order_line.display_type",
        "order_line.product_id",
        "order_line.product_uom_qty",
        "order_line.qty_delivered",
        "order_line.product_uom",
    )
    @api.constrains("inquiry_type", "project_attachment_ids")
    def _check_project_attachments(self):
        for order in self:
            if order.inquiry_type == "construction" and not order.project_attachment_ids:
                raise ValidationError(
                    _("Please upload at least one attachment for project-type quotations.")
                )

    def _compute_can_create_remaining_delivery(self):
        Picking = self.env["stock.picking"]
        for order in self:
            if order.state not in ("sale", "done"):
                order.can_create_remaining_delivery = False
                continue

            # find any open picking linked to this SO via sale_id
            open_pick = Picking.search_count([
                ("sale_id", "=", order.id),
                ("state", "not in", ("done", "cancel")),
            ]) > 0
            if open_pick:
                order.can_create_remaining_delivery = False
                continue

            remaining_found = False
            for line in order.order_line:
                if line.display_type:
                    continue
                if not line.product_id or line.product_id.type not in ("product", "consu"):
                    continue
                if float_compare(
                        line.product_uom_qty,
                        line.qty_delivered,
                        precision_rounding=line.product_uom.rounding,
                ) > 0:
                    remaining_found = True
                    break

            order.can_create_remaining_delivery = remaining_found

    @api.depends(
        "estimation_id",
        "estimation_id.line_ids",
        "estimation_id.display_line_ids",
    )
    def _compute_estimation_display_line_ids(self):
        for order in self:
            if not order.estimation_id:
                order.estimation_display_line_ids = False
                continue
            if not order.estimation_id.display_line_ids and order.estimation_id.line_ids:
                order.estimation_id._rebuild_display_lines()
            order.estimation_display_line_ids = order.estimation_id.display_line_ids

    def _prepare_sale_order_lines_from_estimation(self):
        self.ensure_one()
        estimation = self.estimation_id
        currency = self.currency_id or self.company_id.currency_id
        section_map = {
            "material": _("Material"),
            "labor": _("Labor"),
            "equipment": _("Equipment"),
            "subcontract": _("Sub Contract / TPS"),
        }
        commands = [(5, 0, 0)]
        sequence = 10
        synced_untaxed_total = 0.0
        adjustable_product_lines = []

        estimation_lines = estimation.line_ids.sorted(lambda line: (line.section_type or "", line.id))
        for section_type, section_label in [
            ("material", _("Material")),
            ("labor", _("Labor")),
            ("equipment", _("Equipment")),
            ("subcontract", _("Sub Contract / TPS")),
        ]:
            section_lines = estimation_lines.filtered(lambda line: line.section_type == section_type)
            if not section_lines:
                continue

            section_name = section_map.get(section_type, section_label)
            commands.append((0, 0, {
                "sequence": sequence,
                "display_type": "line_section",
                "name": section_name,
            }))
            sequence += 10

            for estimation_line in section_lines:
                line_name = estimation_line.name or (
                    estimation_line.product_id.display_name if estimation_line.product_id else section_name
                )
                if not estimation_line.product_id:
                    commands.append((0, 0, {
                        "sequence": sequence,
                        "display_type": "line_note",
                        "name": line_name,
                    }))
                    sequence += 10
                    continue

                qty = (
                    estimation_line.quantity_hours
                    if estimation_line.section_type in ("labor", "equipment")
                    else estimation_line.quantity
                ) or 0.0
                unit_cost = estimation_line.unit_cost or 0.0
                price_unit = self._costing_line_breakdown(
                    base_unit=unit_cost,
                    qty=qty,
                    currency=currency,
                )["final_u"]
                line_vals = {
                    "sequence": sequence,
                    "product_id": estimation_line.product_id.id,
                    "name": line_name,
                    "product_uom_qty": qty,
                    "cost_price_unit": unit_cost,
                    "price_unit": price_unit,
                }
                commands.append((0, 0, line_vals))
                synced_untaxed_total += currency.round(price_unit * qty)
                if qty:
                    adjustable_product_lines.append((line_vals, qty))
                sequence += 10

        target_total = currency.round(estimation.total_with_profit or 0.0)
        diff = currency.round(target_total - synced_untaxed_total)
        if adjustable_product_lines and diff:
            line_vals, qty = adjustable_product_lines[-1]
            line_vals["price_unit"] = (line_vals["price_unit"] or 0.0) + (diff / qty)

        return commands

    def action_sync_products_from_estimation(self):
        for order in self:
            if order.state != "draft" or order.approval_state != "draft":
                raise UserError(_("Products can only be synced on unapproved draft quotations."))
            if not order.estimation_id:
                raise UserError(_("No estimation is linked to this quotation."))
            if not order.estimation_id.line_ids:
                raise UserError(_("The linked estimation has no products to sync."))

            estimation = order.estimation_id
            order.write({
                "overhead_percent": estimation.overhead_percent or 0.0,
                "risk_percent": estimation.risk_percent or 0.0,
                "profit_percent": estimation.profit_percent or 0.0,
            })
            order.write({
                "order_line": order._prepare_sale_order_lines_from_estimation(),
            })
            order.message_post(body=_("Quotation products were synced from estimation %s.") % estimation.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Products Synced"),
                "message": _("Quotation products were synced from the linked estimation."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_create_remaining_delivery(self):
        self.ensure_one()

        if self.state in ("cancel",):
            raise UserError(_("Cancelled sale order."))
        # Find remaining qty per deliverable line
        remaining_lines = []
        for line in self.order_line:
            if line.display_type:
                continue
            if not line.product_id or line.product_id.type not in ("product", "consu"):
                continue

            remaining = line.product_uom_qty - line.qty_delivered
            if float_compare(remaining, 0.0, precision_rounding=line.product_uom.rounding) <= 0:
                continue

            remaining_lines.append((line, remaining))

        if not remaining_lines:
            raise UserError(_("Nothing remaining to deliver."))

        warehouse = self.warehouse_id
        if not warehouse:
            raise UserError(_("No warehouse set on this Sale Order."))

        picking_type = warehouse.out_type_id
        if not picking_type:
            raise UserError(_("No Delivery Picking Type (outgoing) found for this warehouse."))

        # Create new delivery picking linked to this sale order
        picking = self.env["stock.picking"].create({
            "partner_id": self.partner_shipping_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": self.partner_shipping_id.property_stock_customer.id,
            "sale_id": self.id,
            "origin": _("%s (Remaining Delivery)") % (self.name,),
            "company_id": self.company_id.id,
        })

        # Create moves for remaining qty
        move_vals = []
        for line, remaining in remaining_lines:
            move_vals.append({
                "name": line.name or line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": remaining,
                "product_uom": line.product_uom.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "picking_id": picking.id,
                "company_id": self.company_id.id,
                "sale_line_id": line.id,
                # keep procurement group consistent if you use it
                "group_id": self.procurement_group_id.id,
            })

        self.env["stock.move"].create(move_vals)

        picking.action_confirm()
        picking.action_assign()

        return {
            "type": "ir.actions.act_window",
            "name": _("Delivery"),
            "res_model": "stock.picking",
            "res_id": picking.id,
            "view_mode": "form",
            "target": "current",
        }

    approval_comment = fields.Text("Approval Comment", tracking=True)
    show_reject_button = fields.Boolean(compute="_compute_show_reject_button")
    dp_percent = fields.Float(string="Down Payment %", copy=False)
    po_date = fields.Date(string="PO Date", copy=False)
    po_number = fields.Char(string="PO Number", copy=False)

    proforma_dp = fields.Integer(
        string="Down payment Percentage",
        store=True,
        help="The amount of Advance payment required upon the order confirmation."
    )
    inquiry_type = fields.Selection(
        [('construction', 'Project'), ('trading', 'Trading')],
        string="Inquiry Type",
        default="trading",
    )
    payment_term_domain = fields.Char(
        compute="_compute_payment_term_domain",
        store=False, )
    overhead_percent = fields.Float(
        string="Over Head (%)",
        default=0.0,
        digits=(16, 2),
        help="Percentage applied on the total amount to cover overhead costs."
    )
    risk_percent = fields.Float(
        string="Risk (%)",
        default=0.0,
        digits=(16, 2),
        help="Percentage applied on the total amount to cover risk."
    )
    profit_percent = fields.Float(
        string="Profit (%)",
        default=0.0,
        digits=(16, 2),
        help="Percentage applied on the grand total to compute profit."
    )

    @api.onchange('overhead_percent', 'risk_percent', 'profit_percent')
    def _onchange_percent_validation(self):
        for field in ('overhead_percent', 'risk_percent', 'profit_percent'):
            value = self[field]
            if value < 0:
                raise UserError(_("Percentage cannot be negative."))
            if value > 100:
                raise UserError(_("Percentage cannot exceed 100%."))

    @api.constrains('overhead_percent', 'risk_percent', 'profit_percent')
    def _check_percentages(self):
        for rec in self:
            for field_name in ('overhead_percent', 'risk_percent', 'profit_percent'):
                value = rec[field_name]
                if value < 0:
                    raise ValidationError(
                        _("Percentages cannot be negative.")
                    )
                if value > 100:
                    raise ValidationError(
                        _("Percentages cannot exceed 100%.")
                    )

    overhead_amount = fields.Monetary(
        string="Over Head Amount",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=False,
        help="Calculated overhead amount based on the total amount."
    )
    risk_amount = fields.Monetary(
        string="Risk Amount",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=False,
        help="Calculated risk amount based on the total amount."
    )
    buffer_total_amount = fields.Monetary(
        string="Computed Total Amount",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=False,
        help="Total amount including overhead and risk percentages (no profit, no VAT)."
    )
    profit_amount = fields.Monetary(
        string="Profit Amount",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=True,
        help="Calculated profit amount (no VAT)."
    )
    profit_grand_total = fields.Monetary(
        string="Net Total",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=True,
        help="Grand total including profit (no VAT)."
    )
    final_grand_total = fields.Monetary(
        string="Grand Taxed Total",
        compute="_compute_costing_totals",
        currency_field="currency_id",
        store=True,
        help="Grand total including profit and VAT."
    )
    section_subtotal_summary = fields.Html(
        string="Section Subtotals",
        compute="_compute_section_subtotal_summary",
        sanitize=False,
        help="Displays a summary of section subtotals and their grand total."
    )
    discount_amount_total = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        compute="_compute_discount_breakdown",
        store=True,
    )
    amount_before_discount = fields.Monetary(
        string="Amount Before Discount",
        currency_field="currency_id",
        compute="_compute_discount_breakdown",
        store=True,
    )
    amount_to_invoice_untaxed = fields.Monetary(
        string="Amount To Invoice",
        currency_field="currency_id",
        compute="_compute_amount_to_invoice_untaxed",
        store=True,
        compute_sudo=True,
    )
    base_cost_total = fields.Monetary(
        string="Base Cost Total",
        currency_field="currency_id",
        compute="_compute_costing_totals",
        store=False,
    )

    @api.depends(
        "amount_untaxed",
        "currency_id",
        "invoice_ids.state",
        "invoice_ids.payment_state",
        "invoice_ids.date",
        "invoice_ids.currency_id",
        "invoice_ids.direction_sign",
        "invoice_ids.line_ids.price_subtotal",
        "invoice_ids.line_ids.display_type",
        "invoice_ids.line_ids.sale_line_ids",
    )
    def _compute_amount_to_invoice_untaxed(self):
        for order in self:
            currency = order.currency_id or order.company_id.currency_id
            invoiced_untaxed = 0.0
            invoices = order.invoice_ids.filtered(
                lambda move: move.state == "posted" or move.payment_state == "invoicing_legacy"
            )

            for invoice in invoices:
                invoice_lines = invoice.line_ids.filtered(
                    lambda line: (
                        line.display_type not in ("line_note", "line_section")
                        and order in line.sale_line_ids.order_id
                    )
                )
                subtotal = sum(invoice_lines.mapped("price_subtotal"))
                invoiced_untaxed += invoice.currency_id._convert(
                    subtotal * -invoice.direction_sign,
                    currency,
                    invoice.company_id,
                    invoice.date or fields.Date.context_today(order),
                )

            order.amount_to_invoice_untaxed = currency.round((order.amount_untaxed or 0.0) - invoiced_untaxed)

    @api.depends(
        "order_line.price_unit",
        "order_line.product_uom_qty",
        "order_line.discount",
        "order_line.price_subtotal",
        "order_line.display_type",
        "currency_id",
    )
    def _compute_discount_breakdown(self):
        for order in self:
            currency = order.currency_id or order.company_id.currency_id

            disc_from_percent = 0.0
            disc_from_negative_lines = 0.0

            for line in order.order_line.filtered(lambda l: not l.display_type):
                qty = line.product_uom_qty or 0.0
                unit = line.price_unit or 0.0
                disc = line.discount or 0.0

                if disc:
                    disc_from_percent += currency.round((unit * qty) * (disc / 100.0))

                if (line.price_subtotal or 0.0) < 0:
                    disc_from_negative_lines += currency.round(-(line.price_subtotal or 0.0))

            discount_total = currency.round(disc_from_percent + disc_from_negative_lines)

            order.discount_amount_total = discount_total
            order.amount_before_discount = currency.round((order.amount_untaxed or 0.0) + discount_total)

    @api.onchange("inquiry_type")
    def _onchange_inquiry_type_payment_term(self):
        for order in self:
            term = order.payment_term_id
            if not order.inquiry_type:
                continue

            if order.inquiry_type == "trading":
                if term and not term.is_trading_term:
                    order.payment_term_id = False
                if not order.payment_term_id:
                    order.payment_term_id = self.env.ref(
                        "petroraq_sale_workflow.payment_term_trading_advance",
                        raise_if_not_found=False
                    )
            else:
                if term and term.is_trading_term:
                    order.payment_term_id = False
                if not order.payment_term_id:
                    order.payment_term_id = self.env.ref(
                        "petroraq_sale_workflow.payment_term_immediate",
                        raise_if_not_found=False
                    )

    @api.depends("inquiry_type")
    def _compute_payment_term_domain(self):
        for order in self:
            if order.inquiry_type == "trading":
                order.payment_term_domain = "[('petroraq_selectable','=',True),('is_trading_term','=',True)]"
            else:
                order.payment_term_domain = "[('petroraq_selectable','=',True),('is_trading_term','=',False)]"

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        inquiry = defaults.get("inquiry_type", "trading")
        if "payment_term_id" in fields_list and not defaults.get("payment_term_id"):
            xmlid = (
                "petroraq_sale_workflow.payment_term_trading_advance"
                if inquiry == "trading"
                else "petroraq_sale_workflow.payment_term_immediate"
            )
            term = self.env.ref(xmlid, raise_if_not_found=False)
            if term:
                defaults["payment_term_id"] = term.id

        return defaults

    @api.constrains("payment_term_id", "inquiry_type")
    def _check_payment_term_selectable(self):
        for order in self:
            term = order.payment_term_id
            if not term:
                raise UserError(_("Please select a payment term before saving the quotation."))

            if not getattr(term, "petroraq_selectable", False):
                raise UserError(
                    _("The selected payment term is not allowed. Please choose one of the Petroraq payment terms.")
                )

            if order.inquiry_type == "trading":
                if not term.is_trading_term:
                    raise UserError(_("For Trading inquiries, only Advance and Credit payment terms are allowed."))
            else:
                if term.is_trading_term:
                    raise UserError(_("Advance/Credit payment terms are only allowed for Trading inquiries."))

    @api.constrains("proforma_dp")
    def _check_proforma_dp(self):
        for order in self:
            if order.proforma_dp > 100 or order.proforma_dp < 0:
                raise UserError(_("Down payment percentage must be between 0 and 100"))

    def _iter_costing_lines(self):
        """Only normal product lines (no sections/notes, no downpayment)."""
        self.ensure_one()
        return self.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment)

    def _costing_line_breakdown(self, base_unit, qty, currency):
        """
        Line-total based costing:
          cost_line = round(cost_unit * qty)
          risk_line = round(cost_line * risk%)
          oh_line   = round(cost_line * oh%)
          buffer_line = cost_line + risk_line + oh_line
          profit_line = round(buffer_line * profit%)
          sale_line = buffer_line + profit_line
          unit_sale = round(sale_line / qty)  (currency rounding)
        """
        self.ensure_one()
        qty = qty or 0.0

        base_u = currency.round(base_unit or 0.0)

        cost_line = currency.round((base_unit or 0.0) * qty) if qty else 0.0

        oh_line = currency.round(cost_line * (self.overhead_percent or 0.0) / 100.0)
        risk_line = currency.round(cost_line * (self.risk_percent or 0.0) / 100.0)

        buffer_line = currency.round(cost_line + oh_line + risk_line)

        profit_line = currency.round(buffer_line * (self.profit_percent or 0.0) / 100.0)

        sale_line = currency.round(buffer_line + profit_line)

        unit_sale = sale_line / qty if qty else 0.0

        return {
            "base_u": base_u,
            "oh_u": currency.round(oh_line / qty) if qty else 0.0,
            "risk_u": currency.round(risk_line / qty) if qty else 0.0,
            "profit_u": currency.round(profit_line / qty) if qty else 0.0,
            "final_u": unit_sale,

            "base_line": cost_line,
            "oh_line": oh_line,
            "risk_line": risk_line,
            "profit_line": profit_line,
            "total_line": sale_line,
            "buffer_line": buffer_line,
        }

    def _costing_compute_totals(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rounding_method = self.company_id.tax_calculation_rounding_method  # 'round_globally' / 'round_per_line'
        vat_rate = 0.15

        base_total = oh_total = risk_total = profit_total = gross_sale = 0.0
        vat_total = 0.0

        for line in self._iter_costing_lines():
            b = self._costing_line_breakdown(
                base_unit=line.cost_price_unit or 0.0,
                qty=line.product_uom_qty or 0.0,
                currency=currency,
            )

            base_total += b["base_line"]
            oh_total += b["oh_line"]
            risk_total += b["risk_line"]
            profit_total += b["profit_line"]

            line_gross = b["total_line"]  # sale_line (truth)
            gross_sale += line_gross

            if rounding_method == "round_per_line":
                disc = (line.discount or 0.0) / 100.0
                line_net = currency.round(line_gross * (1.0 - disc))
                vat_total += currency.round(line_net * vat_rate)

        buffer_total_no_vat = currency.round(base_total + oh_total + risk_total)
        profit_total = currency.round(profit_total)
        gross_sale = currency.round(gross_sale)

        discount_total = 0.0
        for line in self._iter_costing_lines():
            line_gross = self._costing_line_breakdown(
                base_unit=line.cost_price_unit or 0.0,
                qty=line.product_uom_qty or 0.0,
                currency=currency,
            )["total_line"]
            disc = (line.discount or 0.0) / 100.0
            if disc:
                discount_total += currency.round(line_gross * disc)

        for line in self.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment):
            if (line.price_subtotal or 0.0) < 0:
                discount_total += currency.round(-(line.price_subtotal or 0.0))

        discount_total = currency.round(discount_total)

        net_sale = currency.round(gross_sale - discount_total)
        if rounding_method != "round_per_line":
            vat_total = currency.round(net_sale * vat_rate)

        final_total = currency.round(net_sale + vat_total)
        return {
            "currency": currency,
            "base_total": base_total,
            "oh_total": oh_total,
            "risk_total": risk_total,
            "buffer_total_no_vat": buffer_total_no_vat,
            "profit_total": profit_total,
            "grand_no_vat": gross_sale,
            "discount_total": discount_total,
            "net_sale": net_sale,
            "vat_total": vat_total,
            "final_total": final_total,
        }

    @api.depends(
        "order_line.display_type",
        "order_line.is_downpayment",
        "order_line.cost_price_unit",
        "order_line.product_uom_qty",
        "order_line.discount",
        "overhead_percent",
        "risk_percent",
        "profit_percent",
        "currency_id",
    )
    def _compute_costing_totals(self):
        for order in self:
            vals = order._costing_compute_totals()
            order.overhead_amount = vals["oh_total"]
            order.risk_amount = vals["risk_total"]
            order.buffer_total_amount = vals["buffer_total_no_vat"]
            order.profit_amount = vals["profit_total"]
            order.profit_grand_total = vals["grand_no_vat"]
            order.base_cost_total = vals["base_total"]
            order.final_grand_total = vals["final_total"]

    def _costing_final_unit(self, base):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        b = self._costing_line_breakdown(base_unit=base or 0.0, qty=1.0, currency=currency)
        print(f"qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq{b['final_u']}")

        return b["final_u"]

    def _costing_total_no_vat_without_profit(self):
        self.ensure_one()
        return self._costing_compute_totals()["buffer_total_no_vat"]

    def _costing_total_no_vat(self):
        self.ensure_one()
        return self._costing_compute_totals()["grand_no_vat"]

    @api.depends(
        "amount_total",
        "currency_id",
        "buffer_total_amount",
        "profit_grand_total",
        "amount_untaxed",
    )
    def _compute_section_subtotal_summary(self):
        total_label = _("Total Amount")
        for order in self:
            currency = order.currency_id or order.company_id.currency_id
            total_value = (
                order.profit_grand_total
                if order.profit_grand_total or order.profit_grand_total == 0.0
                else order.buffer_total_amount or order.amount_untaxed
            )
            if currency:
                total_display = format_amount(order.env, total_value or 0.0, currency)
            else:
                total_display = f"{(total_value or 0.0):.2f}"
            order.section_subtotal_summary = (
                "<div class='o_section_total_summary'>"
                f"<span class='o_section_total_label'>{html_escape(total_label)}</span>"
                f"<span class='o_section_total_value'>{html_escape(total_display)}</span>"
                "</div>"
            )

    @api.onchange("overhead_percent", "risk_percent", "profit_percent", "order_line.cost_price_unit",
                  "order_line.product_uom_qty")
    def _onchange_reprice_lines_from_cost(self):
        for order in self:
            for line in order.order_line.filtered(
                    lambda l: not l.display_type and not l.is_downpayment and l.product_id):
                b = order._costing_line_breakdown(
                    base_unit=line.cost_price_unit or 0.0,
                    qty=line.product_uom_qty or 0.0,
                    currency=order.currency_id or order.company_id.currency_id,
                )
                print(f"qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq{b['final_u']}")
                line.price_unit = b["final_u"]

    def write(self, vals):
        res = super().write(vals)

        if any(k in vals for k in ("overhead_percent", "risk_percent", "profit_percent")):
            for order in self:
                currency = order.currency_id or order.company_id.currency_id
                lines = order.order_line.filtered(
                    lambda l: not l.display_type and not l.is_downpayment and l.product_id
                )
                for line in lines:
                    b = order._costing_line_breakdown(
                        base_unit=line.cost_price_unit or 0.0,
                        qty=line.product_uom_qty or 0.0,
                        currency=currency,
                    )
                    line.price_unit = b["final_u"]
        return res

    @api.depends_context("uid")
    @api.depends("approval_state")
    def _compute_show_reject_button(self):
        user = self.env.user
        for order in self:
            order.show_reject_button = (
                    (order.approval_state == "to_manager" and user.has_group(
                        "petroraq_sale_workflow.group_sale_approval_manager"))
                    or
                    (order.approval_state == "to_md" and user.has_group(
                        "petroraq_sale_workflow.group_sale_approval_md"))
            )

    def action_manager_approve(self):
        for order in self:
            if order.approval_state != "to_manager":
                raise UserError(_("This quotation is not awaiting manager approval."))
            md_users = order._get_effective_md_users()
            order.locked = True
            if md_users:
                order.approval_state = "to_md"
                order._notify_md_approval()
            else:
                order.approval_state = "approved"

    def action_confirm_quotation(self):
        for order in self:
            if not order.order_line:
                raise UserError(_("Please add at least one line item to the quotation."))
            if order.estimation_id:
                currency = order.currency_id or order.company_id.currency_id
                estimation_total = currency.round(order.estimation_id.total_with_profit or 0.0)
                quotation_total = currency.round(order.amount_untaxed or 0.0)
                if float_compare(estimation_total, quotation_total, precision_rounding=currency.rounding) != 0:
                    raise UserError(_("The quotation total must match the estimation total before submission."))

        self.write({
            "approval_state": "to_manager",
            "approval_comment": False,
        })
        for order in self:
            manager_group = order.env.ref("petroraq_sale_workflow.group_sale_approval_manager", raise_if_not_found=False)
            manager_users = manager_group.users.filtered(lambda u: u.active) - order.create_uid if manager_group else order.env["res.users"]
            if manager_users:
                order._notify_manager_approval()
            else:
                order.action_manager_approve()
        return True

    def action_md_approve(self):
        for order in self:
            if order.approval_state != "to_md":
                raise UserError(_("This quotation is not awaiting MD approval."))
            order.approval_state = "approved"
        return True

    def action_reject(self):
        for order in self:
            if order.approval_state not in ("to_manager", "to_md", "draft"):
                raise UserError(_("Only waiting approvals can be rejected."))
            order.approval_state = "rejected"
            order.state = "cancel"
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_draft(self):
        res = super().action_draft()
        for order in self:
            order.locked = False
            order.approval_state = "draft"
        return res

    def _action_cancel(self):
        res = super()._action_cancel()
        for order in self:
            order.locked = False
            order.approval_state = "rejected"
        return res

    def action_reset_to_draft(self):
        for order in self:
            if order.approval_state == "rejected":
                order.locked = False
                order.approval_state = "draft"

    def action_confirm(self):
        for order in self:
            if not order.order_line:
                raise UserError(_("Please add at least one line item to the quotation."))
            if order.approval_state != "approved":
                raise UserError(_("You cannot confirm the order before final approval."))

        locked_orders = self.filtered("locked")
        if locked_orders:
            locked_orders.action_unlock()

        try:
            res = super().action_confirm()
        finally:
            if locked_orders:
                locked_orders.action_lock()

        return res

    def _get_quotation_section_amounts(self):
        self.ensure_one()
        amounts = {}
        current_section = False
        for line in self.order_line.sorted(lambda order_line: (order_line.sequence, order_line.id)):
            if line.display_type == "line_section":
                current_section = line.name
                amounts.setdefault(current_section, 0.0)
                continue
            if line.display_type or line.is_downpayment or not line.product_id:
                continue
            section_name = current_section or _("General")
            amounts.setdefault(section_name, 0.0)
            amounts[section_name] += (line.cost_price_unit or 0.0) * (
                line.product_uom_qty or 0.0
            )
        return amounts

    def _sync_work_order_cost_centers_from_quotation(self, work_order):
        self.ensure_one()
        analytic_model = self.env["account.analytic.account"].sudo()
        wo_cost_center_model = self.env["pr.work.order.cost.center"].sudo()
        analytic_plan = self.env.ref("pr_account.pr_account_analytic_plan_our_project", raise_if_not_found=False)
        existing_by_section = {
            line.section_name: line
            for line in work_order.cost_center_ids.filtered("section_name")
        }

        for section_name, amount in self._get_quotation_section_amounts().items():
            cost_center = existing_by_section.get(section_name)
            if not cost_center:
                analytic_vals = {
                    "name": work_order._format_section_cost_center_name(section_name),
                    "company_id": self.company_id.id,
                    "partner_id": self.partner_id.id,
                }
                if analytic_plan and "plan_id" in analytic_model._fields:
                    analytic_vals["plan_id"] = analytic_plan.id
                if "budget_type" in analytic_model._fields:
                    analytic_vals["budget_type"] = "capex"
                if "budget_allowance" in analytic_model._fields:
                    analytic_vals["budget_allowance"] = amount
                analytic = analytic_model.create(analytic_vals)
                wo_cost_center_model.create({
                    "work_order_id": work_order.id,
                    "section_name": section_name,
                    "analytic_account_id": analytic.id,
                    "partner_id": self.partner_id.id,
                    "department_id": False,
                    "section_id": False,
                })
                continue

            vals = {"partner_id": self.partner_id.id}
            if cost_center.analytic_account_id:
                analytic_vals = {"partner_id": self.partner_id.id}
                if "budget_allowance" in cost_center.analytic_account_id._fields:
                    analytic_vals["budget_allowance"] = amount
                cost_center.analytic_account_id.sudo().write(analytic_vals)
            cost_center.write(vals)

    def _prepare_work_order_boq_lines_from_quotation(self):
        self.ensure_one()
        lines = []
        current_section = False
        for line in self.order_line.sorted(lambda order_line: (order_line.sequence, order_line.id)):
            if line.display_type == "line_section":
                current_section = line.name
                lines.append({
                    "display_type": "line_section",
                    "name": line.name,
                    "product_id": False,
                    "uom_id": False,
                    "qty": 0.0,
                    "unit_cost": 0.0,
                    "section_name": current_section,
                    "sale_order_line_id": line.id,
                    "estimation_line_id": False,
                })
                continue
            if line.display_type == "line_note":
                lines.append({
                    "display_type": "line_note",
                    "name": line.name,
                    "product_id": False,
                    "uom_id": False,
                    "qty": 0.0,
                    "unit_cost": 0.0,
                    "section_name": current_section,
                    "sale_order_line_id": line.id,
                    "estimation_line_id": False,
                })
                continue
            if line.is_downpayment or not line.product_id:
                continue
            section_name = current_section or _("General")
            lines.append({
                "display_type": "product",
                "name": line.name or line.product_id.display_name,
                "product_id": line.product_id.id,
                "uom_id": (line.product_uom or line.product_id.uom_id).id,
                "qty": line.product_uom_qty or 0.0,
                "unit_cost": line.cost_price_unit or 0.0,
                "section_name": section_name,
                "sale_order_line_id": line.id,
                "estimation_line_id": False,
            })
        return lines

    def _match_existing_quotation_boq_line(self, existing_lines, used_lines, target):
        used_line_ids = set(used_lines.ids)
        source_line = target.get("sale_order_line_id")
        if source_line:
            match = existing_lines.filtered(
                lambda line: line.sale_order_line_id.id == source_line and line.id not in used_line_ids
            )[:1]
            if match:
                return match

        def _same_line(line):
            if line.id in used_line_ids:
                return False
            if line.display_type != target.get("display_type"):
                return False
            if (line.section_name or "") != (target.get("section_name") or ""):
                return False
            if target.get("display_type") == "product":
                return line.product_id.id == target.get("product_id")
            return (line.name or "") == (target.get("name") or "")

        return existing_lines.filtered(_same_line)[:1]

    def _quotation_boq_line_has_commitments(self, boq_line, work_order):
        if self.env["stock.move"].sudo().search_count([("work_order_boq_line_id", "=", boq_line.id)]):
            return True
        if not boq_line.product_id:
            return False
        cost_center = work_order.cost_center_ids.filtered(lambda line: line.section_name == boq_line.section_name)[:1]
        analytic = cost_center.analytic_account_id
        if not analytic:
            return False

        legacy_pr_line_count = self.env["custom.pr.line"].sudo().search_count([
            ("cost_center_id", "=", analytic.id),
            ("description", "=", boq_line.product_id.id),
            ("pr_id.approval", "!=", "rejected"),
        ])
        requisition_line_count = self.env["purchase.requisition.line"].sudo().search_count([
            ("cost_center_id", "=", analytic.id),
            ("description", "=", boq_line.product_id.id),
            ("requisition_id.approval", "!=", "rejected"),
        ])
        if legacy_pr_line_count or requisition_line_count:
            return True

        po_lines = self.env["purchase.order.line"].sudo().search([
            ("order_id.state", "in", ["pending", "purchase", "done"]),
            ("product_id", "=", boq_line.product_id.id),
            ("analytic_distribution", "!=", False),
        ])
        for po_line in po_lines:
            distribution = po_line.analytic_distribution or {}
            analytic_ids = {
                str(key_part).strip()
                for key in distribution
                for key_part in str(key).split(",")
            }
            if str(analytic.id) in analytic_ids:
                return True
        return False

    def _sync_work_order_boq_lines_from_quotation(self, work_order):
        self.ensure_one()
        target_lines = self._prepare_work_order_boq_lines_from_quotation()
        existing_lines = work_order.boq_line_ids.sorted(lambda line: (line.sequence, line.id))
        used_lines = self.env["pr.work.order.boq"]
        sequence = 10

        for target in target_lines:
            target = dict(target, sequence=sequence)
            sequence += 10
            match = self._match_existing_quotation_boq_line(existing_lines, used_lines, target)
            if match:
                match.with_context(skip_estimation_sync=True).write(target)
                used_lines |= match
            else:
                used_lines |= self.env["pr.work.order.boq"].create(dict(target, work_order_id=work_order.id))

        obsolete_lines = existing_lines - used_lines
        for line in obsolete_lines:
            if line.display_type == "product" and self._quotation_boq_line_has_commitments(line, work_order):
                line.write({"qty": 0.0, "unit_cost": 0.0, "sequence": sequence})
                sequence += 10
            elif line.display_type == "product":
                line.unlink()
            else:
                line.write({"sequence": sequence})
                sequence += 10

    def _sync_work_order_tasks_from_quotation(self, work_order):
        self.ensure_one()
        project = work_order.project_id
        if not project:
            return
        existing_task_names = set(work_order.task_ids.mapped("name"))
        section_names = list(self._get_quotation_section_amounts())
        for section_name in section_names:
            if section_name in existing_task_names:
                continue
            self.env["project.task"].create({
                "name": section_name,
                "project_id": project.id,
                "work_order_id": work_order.id,
                "company_id": work_order.company_id.id,
            })

    def _sync_work_order_from_quotation(self, work_order):
        self.ensure_one()
        work_order.ensure_one()
        if work_order.state in ("done", "cancel"):
            raise UserError(_("Completed or cancelled Work Orders cannot be synced."))

        work_order_vals = {
            "sale_order_id": self.id,
            "company_id": self.company_id.id,
            "partner_id": self.partner_id.id,
            "contract_amount": self.final_grand_total or self.amount_total,
            "overhead_percent": self.overhead_percent or 0.0,
            "risk_percent": self.risk_percent or 0.0,
            "profit_percent": self.profit_percent or 0.0,
        }
        if self.project_id:
            work_order_vals["project_id"] = self.project_id.id
        if self.analytic_account_id:
            work_order_vals["analytic_account_id"] = self.analytic_account_id.id
        work_order.with_context(skip_estimation_sync=True).write(work_order_vals)

        self._sync_work_order_cost_centers_from_quotation(work_order)
        self._sync_work_order_boq_lines_from_quotation(work_order)
        self._sync_work_order_tasks_from_quotation(work_order)
        work_order._ensure_project_expense_bucket(sync_budget=True)
        if "last_source_sync_date" in work_order._fields:
            work_order.write({"last_source_sync_date": fields.Datetime.now()})
        work_order.message_post(body=_("Work Order and budget were synced from quotation %s.") % self.name)
        return work_order

    def action_sync_work_order_budget(self):
        self.ensure_one()
        if not self.env.user.has_group("pr_work_order.custom_group_work_order_user"):
            raise UserError(_("Only users in the Work Order / Estimation group can sync Work Orders."))
        if not self.work_order_id:
            raise UserError(_("No Work Order is linked to this quotation."))
        self._sync_work_order_from_quotation(self.work_order_id)
        return {
            "type": "ir.actions.act_window",
            "name": _("Work Order"),
            "res_model": "pr.work.order",
            "res_id": self.work_order_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_quotation_send(self):
        self.ensure_one()

        if self.approval_state != "approved":
            raise UserError(_("You can only send the quotation to the customer after final approval."))

        self.order_line._validate_analytic_distribution()

        lang = self.env.context.get("lang")

        if self.env.context.get("proforma"):
            mail_template = self.env.ref(
                "petroraq_sale_workflow.petroraq_custom_proforma_email",
                raise_if_not_found=False,
            )
        else:
            mail_template = self.env.ref(
                "petroraq_sale_workflow.petroraq_custom_sale_email",
                raise_if_not_found=False,
            ) or self._find_mail_template()

        if mail_template and mail_template.lang:
            lang = mail_template._render_lang(self.ids)[self.id]

        partner_ids = []
        if self.partner_id:
            partner_ids.append(self.partner_id.id)

        if self.order_inquiry_id and self.order_inquiry_id.contact_partner_id:
            partner_ids.append(self.order_inquiry_id.contact_partner_id.id)

        ctx = {
            "default_model": "sale.order",
            "default_res_ids": self.ids,
            "default_template_id": mail_template.id if mail_template else None,
            "default_composition_mode": "comment",
            "mark_so_as_sent": True,
            "default_email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
            "proforma": self.env.context.get("proforma", False),
            "force_email": True,
            "model_description": self.with_context(lang=lang).type_name,
            "default_partner_ids": [(6, 0, list(set(partner_ids)))],
        }

        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mail.compose.message",
            "views": [(False, "form")],
            "target": "new",
            "context": ctx,
        }

    @api.model
    def translate_sale_name(self, name):
        if not name:
            return ""
        numerals_map = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
        return str(name).translate(numerals_map)

    @api.model
    def convert_phone_to_eastern_arabic_numerals(self, value):
        if not value:
            return ""
        numerals_map = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
        return str(value).translate(numerals_map)


class WorkOrderBOQ(models.Model):
    _inherit = "pr.work.order.boq"

    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        string="Quotation Line",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
