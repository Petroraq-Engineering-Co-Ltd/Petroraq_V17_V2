from odoo import api, fields, models, _
from odoo.tools import format_amount, html_escape
from odoo.tools.float_utils import float_compare


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    section_subtotal_amount = fields.Monetary(
        string="Section Subtotal",
        compute="_compute_section_subtotal_amount",
        store=False,
        currency_field="currency_id",
        help="Subtotal of the products within this section."
    )
    section_subtotal_display = fields.Html(
        string="Section Subtotal Display",
        compute="_compute_section_subtotal_amount",
        sanitize=False,
        help="Formatted subtotal snippet for section headers."
    )

    # IMPORTANT: not stored, and use Monetary
    final_price_unit = fields.Monetary(
        string="Final Unit Price",
        compute="_compute_final_price_unit",
        store=False,
        currency_field="currency_id",
    )

    use_manual_cost_price_unit = fields.Boolean(copy=True)
    manual_cost_price_unit = fields.Float(copy=True, digits="Product Price")
    cost_price_unit = fields.Float(
        string="Unit Cost",
        compute="_compute_cost_price_unit",
        inverse="_inverse_cost_price_unit",
        store=True,
        readonly=False,
        digits="Product Price",
    )
    net_unit_price = fields.Float(
        string="Net Unit Price",
        currency_field="currency_id",
        compute="_compute_net_unit_price",
        store=True,
        readonly=True,
        digits='Product Price',
        precompute=True
    )

    @api.depends("price_unit", "discount")
    def _compute_net_unit_price(self):
        for line in self:
            price = line.price_unit or 0.0
            disc = line.discount or 0.0
            net = price * (1 - disc / 100.0)
            line.net_unit_price = net

    @api.depends("product_id.standard_price", "manual_cost_price_unit", "use_manual_cost_price_unit")
    def _compute_cost_price_unit(self):
        for line in self:
            if line.use_manual_cost_price_unit:
                line.cost_price_unit = line.manual_cost_price_unit
            else:
                line.cost_price_unit = line.product_id.standard_price if line.product_id else 0.0

    def _inverse_cost_price_unit(self):
        for line in self:
            line.manual_cost_price_unit = line.cost_price_unit
            line.use_manual_cost_price_unit = True

    def _get_sale_price_from_cost(self, cost):
        self.ensure_one()
        order = self.order_id
        currency = self.currency_id or order.currency_id or order.company_id.currency_id
        b = order._costing_line_breakdown(base_unit=cost or 0.0, qty=1.0, currency=currency)
        return b["final_u"]

    @api.onchange("product_id")
    def _onchange_product_id_set_cost_price_unit(self):
        for line in self:
            if line.display_type or getattr(line, "is_downpayment", False) or not line.order_id:
                continue
            if not line.product_id:
                line.use_manual_cost_price_unit = False
                line.manual_cost_price_unit = 0.0
                line.cost_price_unit = 0.0
                continue

            cost = line.product_id.standard_price or 0.0
            line.use_manual_cost_price_unit = True
            line.manual_cost_price_unit = cost
            line.cost_price_unit = cost
            line.price_unit = line._get_sale_price_from_cost(cost)

    @api.onchange("product_uom_qty", "cost_price_unit")
    def _onchange_set_sale_price_from_cost(self):
        for line in self:
            if line.display_type or getattr(line, "is_downpayment", False) or not line.order_id:
                continue
            if not line.product_id:
                continue
            cost = line.cost_price_unit or 0.0
            line.use_manual_cost_price_unit = True
            line.manual_cost_price_unit = cost
            line.price_unit = line._get_sale_price_from_cost(cost)

    def _sync_price_unit_from_product_cost(self):
        for line in self:
            if line.display_type or getattr(line, "is_downpayment", False) or not line.order_id:
                continue
            if not line.product_id:
                continue

            cost = line.manual_cost_price_unit if line.use_manual_cost_price_unit else line.cost_price_unit
            sale_price = line._get_sale_price_from_cost(cost)
            precision_cost = self.env["decimal.precision"].precision_get("Product Price")
            if (
                not self.env.context.get("skip_sync_price_unit")
                and float_compare(line.price_unit, sale_price, precision_digits=precision_cost) != 0
            ):
                line.with_context(skip_sync_price_unit=True).price_unit = sale_price

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            cost = vals.pop("cost_price_unit", None)
            if cost is None and "manual_cost_price_unit" in vals:
                cost = vals["manual_cost_price_unit"]
            if (
                cost is None
                and vals.get("product_id")
                and not vals.get("use_manual_cost_price_unit")
            ):
                cost = self.env["product.product"].browse(vals["product_id"]).standard_price or 0.0
            if cost is not None:
                vals["manual_cost_price_unit"] = cost
                vals["use_manual_cost_price_unit"] = True

        lines = super().create(vals_list)
        lines_to_sync = self.browse()
        for line, vals in zip(lines, vals_list):
            if "price_unit" in vals:
                continue
            lines_to_sync |= line

        if lines_to_sync:
            lines_to_sync._sync_price_unit_from_product_cost()
        if not self.env.context.get("skip_confirmation_approval_reset"):
            lines.mapped("order_id")._reset_confirmation_approval()
        return lines

    def _get_delivery_description_picking(self, picking_type=False):
        """Return the delivery move description for a sales order line.

        Prefers the non-empty sales order line ``name`` verbatim, falling back
        to Odoo's product delivery description and variant attributes only when
        the SO line description is blank.
        """
        self.ensure_one()
        if (self.name or "").strip():
            return self.name
        if not self.product_id:
            return ""
        partner = self.order_id.partner_shipping_id or self.order_id.partner_id
        lang = partner.lang or self.env.user.lang
        product = self.product_id.with_context(lang=lang)
        if picking_type:
            picking_description = product._get_description(picking_type) or ""
        else:
            picking_description = product.description_pickingout or product.name or ""
        variant_lang = self.order_id.partner_id.lang or self.env.user.lang
        variants = self.with_context(
            lang=variant_lang
        )._get_sale_order_line_multiline_description_variants()
        if variants:
            picking_description = f"{picking_description}{variants}"
        return picking_description

    def _prepare_procurement_values(self, group_id=False):
        values = super()._prepare_procurement_values(group_id=group_id)
        if (self.name or "").strip():
            values["sale_description_picking"] = self.name
        return values

    def _get_open_delivery_chain_moves(self):
        """Return open SO-owned delivery-chain moves (Pick/Pack/Ship)."""
        self.ensure_one()
        StockMove = self.env["stock.move"]
        if (
            self.display_type
            or getattr(self, "is_downpayment", False)
            or not self.product_id
            or not self.move_ids
        ):
            return StockMove

        candidate_moves = self.move_ids | StockMove.browse(self.move_ids._rollup_move_origs())
        open_moves = candidate_moves.filtered(
            lambda m: m.state not in ("done", "cancel")
            and not m.purchase_line_id
            and not m.origin_returned_move_id
            and m.product_id == self.product_id
            and (m.picking_type_id.code or m.picking_id.picking_type_id.code)
            in ("outgoing", "internal")
        )
        result = StockMove
        for move in open_moves:
            if move.sale_line_id == self:
                result |= move
            elif not move.sale_line_id:
                dest_moves = StockMove.browse(move._rollup_move_dests()).filtered(
                    lambda dm: not dm.purchase_line_id and not dm.origin_returned_move_id
                )
                if dest_moves.sale_line_id == self:
                    result |= move
        return result

    def _sync_open_delivery_descriptions(self):
        for line in self:
            moves = line._get_open_delivery_chain_moves()
            if not moves:
                continue
            if (line.name or "").strip():
                moves_to_update = moves.filtered(lambda m: m.description_picking != line.name)
                if moves_to_update:
                    moves_to_update.write({"description_picking": line.name})
            else:
                for move in moves:
                    picking_type = move.picking_type_id or move.picking_id.picking_type_id
                    target_desc = line._get_delivery_description_picking(picking_type=picking_type)
                    if move.description_picking != target_desc:
                        move.write({"description_picking": target_desc})

    def write(self, vals):
        orders = self.mapped("order_id")
        vals = dict(vals)
        if "cost_price_unit" in vals:
            vals["manual_cost_price_unit"] = vals.pop("cost_price_unit")
            vals["use_manual_cost_price_unit"] = True
        elif "manual_cost_price_unit" in vals:
            vals["use_manual_cost_price_unit"] = True
        elif vals.get("product_id") and not vals.get("use_manual_cost_price_unit"):
            vals["manual_cost_price_unit"] = (
                self.env["product.product"].browse(vals["product_id"]).standard_price or 0.0
            )
            vals["use_manual_cost_price_unit"] = True

        res = super().write(vals)
        if "name" in vals:
            self._sync_open_delivery_descriptions()
        # if product or costing inputs changed, resync
        if "price_unit" not in vals and set(vals).intersection({
            "product_id",
            "product_template_id",
            "manual_cost_price_unit",
            "use_manual_cost_price_unit",
        }):
            self._sync_price_unit_from_product_cost()
        confirmation_sensitive_fields = {
            "product_id", "product_template_id", "name", "display_type",
            "product_uom_qty", "product_uom", "price_unit", "discount",
            "tax_id", "manual_cost_price_unit", "use_manual_cost_price_unit",
        }
        if (
            not self.env.context.get("skip_confirmation_approval_reset")
            and confirmation_sensitive_fields.intersection(vals)
        ):
            orders._reset_confirmation_approval()
        return res

    def unlink(self):
        orders = self.mapped("order_id")
        res = super().unlink()
        if not self.env.context.get("skip_confirmation_approval_reset"):
            orders._reset_confirmation_approval()
        return res

    @api.depends("price_unit")
    def _compute_final_price_unit(self):
        for line in self:
            line.final_price_unit = line.price_unit or 0.0


    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)

        if not self.display_type and not getattr(self, "is_downpayment", False):
            return vals

        # Downpayment deduction line: force amount-based deduction
        if getattr(self, "is_downpayment", False) and not self.display_type:
            qty = vals.get("quantity") or 0.0
            if qty < 0:  # deduction line
                amount_map = self.env.context.get("dp_deduct_amounts") or {}
                target_amount = amount_map.get(self.order_id.id)

                if target_amount:
                    vals["quantity"] = -1.0
                    vals["price_unit"] = target_amount
                    vals["discount"] = 0.0

                    # Create deduction as a regular invoice line (same as manual add):
                    # keep taxes, but remove sale_line_ids linkage that forces
                    # account.move.line.is_downpayment=True.
                    vals["sale_line_ids"] = [fields.Command.clear()]
                    vals["dp_source_sale_line_id"] = self.id

        return vals

    # =========================
    # Section subtotal chips
    # =========================
    @api.depends(
        "display_type",
        "sequence",
        "order_id.order_line.display_type",
        "order_id.order_line.sequence",
        "order_id.order_line.cost_price_unit",
        "order_id.order_line.product_uom_qty",
        "order_id.order_line.is_downpayment",
        "order_id.overhead_percent",
        "order_id.risk_percent",
        "order_id.profit_percent",
        "currency_id",
    )
    def _compute_section_subtotal_amount(self):
        label = _("Sub Total")

        for line in self:
            line.section_subtotal_amount = 0.0
            line.section_subtotal_display = False

        for order in self.mapped("order_id"):
            currency = order.currency_id or order.company_id.currency_id

            subtotal = 0.0
            current_section = None

            ordered_lines = order.order_line.sorted(key=lambda l: (l.sequence or 0, l.id or 0))
            for line in ordered_lines:
                if line.display_type == "line_section":
                    if current_section:
                        current_section._set_section_subtotal_values(subtotal, label)
                    current_section = line
                    subtotal = 0.0
                    line.section_subtotal_amount = 0.0
                    line.section_subtotal_display = False
                    continue

                if line.display_type or getattr(line, "is_downpayment", False):
                    continue

                # Costing subtotal (same as PDF)
                breakdown = order._costing_line_breakdown(
                    base_unit=line.cost_price_unit or 0.0,  # ✅ use COST as base
                    qty=line.product_uom_qty or 0.0,
                    currency=currency,
                )
                subtotal += breakdown["total_line"]

            if current_section:
                current_section._set_section_subtotal_values(subtotal, label)

    def _set_section_subtotal_values(self, amount, label):
        self.ensure_one()
        currency = self.order_id.currency_id or self.order_id.company_id.currency_id
        amount_display = format_amount(self.env, amount or 0.0, currency) if currency else f"{(amount or 0.0):.2f}"

        self.section_subtotal_amount = amount
        self.section_subtotal_display = (
            f"<span class='o_section_subtotal_chip_label'>{html_escape(label)}</span>"
            f"<span class='o_section_subtotal_chip_value'>{html_escape(amount_display)}</span>"
        )
