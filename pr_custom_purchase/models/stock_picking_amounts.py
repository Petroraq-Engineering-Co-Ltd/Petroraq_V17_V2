from odoo import api, fields, models
from odoo.tools.float_utils import float_is_zero


class StockMove(models.Model):
    _inherit = "stock.move"

    pr_currency_id = fields.Many2one(
        "res.currency",
        string="Order Currency",
        compute="_compute_pr_currency_id",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_unit_price = fields.Float(
        string="Unit Price",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        digits="Product Price",
        store=True,
        readonly=True,
    )
    pr_price_subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="pr_currency_id",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_price_tax = fields.Float(
        string="Tax",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_price_total = fields.Monetary(
        string="Total",
        currency_field="pr_currency_id",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )

    def _get_pr_effective_picking_code(self):
        self.ensure_one()
        return self.picking_id.picking_type_code or self.picking_code

    def _get_pr_order_line_valuation(self):
        """Return pricing details from the linked order line, or False when unlinked."""
        self.ensure_one()
        pol = self.purchase_line_id
        if not pol:
            return False
        order = pol.order_id
        company = order.company_id or self.company_id or self.env.company
        return {
            "currency": order.currency_id or company.currency_id,
            "partner": order.partner_id,
            "company": company,
            "product": pol.product_id or self.product_id,
            "taxes": pol.taxes_id,
            "price_unit": pol.price_unit or 0.0,
            "discount": getattr(pol, "discount", 0.0) or 0.0,
            "uom": pol.product_uom,
            "handle_price_include": True,
        }

    def _get_pr_converted_prices(self, valuation):
        self.ensure_one()
        gross_price = valuation["price_unit"] or 0.0
        discount = valuation["discount"] or 0.0
        src_uom = valuation["uom"]
        dst_uom = self.product_uom or src_uom
        if src_uom and dst_uom and src_uom != dst_uom:
            gross_price = src_uom._compute_price(gross_price, dst_uom)
        net_price = gross_price * (1.0 - discount / 100.0)
        return gross_price, net_price, discount

    def _prepare_pr_tax_base_line_dict(self, valuation=None):
        self.ensure_one()
        if valuation is None:
            valuation = self._get_pr_order_line_valuation()
        company = (
            valuation["company"]
            or self.company_id
            or self.picking_id.company_id
            or self.env.company
        )
        currency = valuation["currency"] or self.pr_currency_id or company.currency_id
        gross_price, _net_price, discount = self._get_pr_converted_prices(valuation)
        return self.env["account.tax"]._convert_to_tax_base_line_dict(
            self,
            partner=valuation["partner"],
            currency=currency,
            product=valuation["product"] or self.product_id,
            taxes=valuation["taxes"],
            price_unit=gross_price,
            quantity=self.quantity or 0.0,
            discount=discount,
            handle_price_include=valuation.get("handle_price_include", True),
        )

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "picking_code",
        "picking_id.picking_type_code",
        "picking_id.company_id",
        "purchase_line_id",
        "purchase_line_id.order_id.currency_id",
    )
    def _compute_pr_currency_id(self):
        for move in self:
            company = move.company_id or move.picking_id.company_id or self.env.company
            if move._get_pr_effective_picking_code() not in ("incoming", "outgoing"):
                move.pr_currency_id = company.currency_id
                continue
            valuation = move._get_pr_order_line_valuation()
            move.pr_currency_id = (
                valuation["currency"] if valuation else False
            ) or company.currency_id

    @api.depends(
        "quantity",
        "product_uom",
        "state",
        "scrapped",
        "picking_code",
        "picking_id.picking_type_code",
        "picking_id.company_id",
        "company_id",
        "company_id.currency_id",
        "company_id.tax_calculation_rounding_method",
        "purchase_line_id",
        "purchase_line_id.price_unit",
        "purchase_line_id.discount",
        "purchase_line_id.taxes_id",
        "purchase_line_id.product_uom",
        "purchase_line_id.order_id.currency_id",
        "purchase_line_id.order_id.partner_id",
    )
    def _compute_pr_amounts(self):
        AccountTax = self.env["account.tax"]
        for move in self:
            if move._get_pr_effective_picking_code() not in ("incoming", "outgoing"):
                move.pr_unit_price = 0.0
                move.pr_price_subtotal = 0.0
                move.pr_price_tax = 0.0
                move.pr_price_total = 0.0
                continue
            valuation = move._get_pr_order_line_valuation()
            if not valuation:
                move.pr_unit_price = 0.0
                move.pr_price_subtotal = 0.0
                move.pr_price_tax = 0.0
                move.pr_price_total = 0.0
                continue
            company = (
                valuation["company"]
                or move.company_id
                or move.picking_id.company_id
                or self.env.company
            )
            currency = valuation["currency"] or move.pr_currency_id or company.currency_id
            _gross_price, net_price, _discount = move._get_pr_converted_prices(valuation)
            move.pr_unit_price = net_price
            uom_rounding = (move.product_uom or valuation["uom"]).rounding or 0.001
            if (
                move.state == "cancel"
                or move.scrapped
                or float_is_zero(move.quantity or 0.0, precision_rounding=uom_rounding)
            ):
                move.pr_price_subtotal = 0.0
                move.pr_price_tax = 0.0
                move.pr_price_total = 0.0
                continue
            tax_results = AccountTax.with_company(company)._compute_taxes([
                move._prepare_pr_tax_base_line_dict(valuation)
            ])
            totals = tax_results["totals"].get(currency) or next(
                iter(tax_results["totals"].values()), {}
            )
            amount_untaxed = totals.get("amount_untaxed", 0.0)
            amount_tax = totals.get("amount_tax", 0.0)
            move.pr_price_subtotal = amount_untaxed
            move.pr_price_tax = amount_tax
            move.pr_price_total = currency.round(amount_untaxed + amount_tax)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    pr_currency_id = fields.Many2one(
        "res.currency",
        string="Order Currency",
        compute="_compute_pr_currency_id",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_amount_untaxed = fields.Monetary(
        string="Untaxed Amount",
        currency_field="pr_currency_id",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_amount_tax = fields.Monetary(
        string="Taxes",
        currency_field="pr_currency_id",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    pr_amount_total = fields.Monetary(
        string="Total",
        currency_field="pr_currency_id",
        compute="_compute_pr_amounts",
        compute_sudo=True,
        store=True,
        readonly=True,
    )

    def _get_pr_amount_moves(self, include_inactive=False):
        self.ensure_one()
        moves = self.move_ids_without_package
        if self.picking_type_entire_packs:
            packaged_moves = self.move_ids.filtered(
                lambda m: m.package_level_id and m not in moves
            )
            moves = moves | packaged_moves
        if include_inactive:
            return moves
        return moves.filtered(lambda m: m.state != "cancel" and not m.scrapped)

    def _get_pr_currency(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        if self.picking_type_code not in ("incoming", "outgoing"):
            return company.currency_id
        for move in self._get_pr_amount_moves(include_inactive=True):
            valuation = move._get_pr_order_line_valuation()
            if valuation and valuation.get("currency"):
                return valuation["currency"]
        if self.purchase_id and self.purchase_id.currency_id:
            return self.purchase_id.currency_id
        return company.currency_id

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "picking_type_id",
        "picking_type_code",
        "picking_type_entire_packs",
        "purchase_id",
        "purchase_id.currency_id",
        "move_ids_without_package.purchase_line_id",
        "move_ids_without_package.pr_currency_id",
        "move_ids.purchase_line_id",
        "move_ids.package_level_id",
        "move_ids.pr_currency_id",
    )
    def _compute_pr_currency_id(self):
        for picking in self:
            picking.pr_currency_id = picking._get_pr_currency()

    @api.depends(
        "company_id",
        "company_id.currency_id",
        "company_id.tax_calculation_rounding_method",
        "picking_type_id",
        "picking_type_code",
        "picking_type_entire_packs",
        "purchase_id",
        "purchase_id.currency_id",
        "move_ids_without_package.state",
        "move_ids_without_package.scrapped",
        "move_ids_without_package.quantity",
        "move_ids_without_package.product_uom",
        "move_ids_without_package.purchase_line_id",
        "move_ids_without_package.pr_currency_id",
        "move_ids_without_package.pr_unit_price",
        "move_ids_without_package.pr_price_subtotal",
        "move_ids_without_package.pr_price_tax",
        "move_ids_without_package.pr_price_total",
        "move_ids.state",
        "move_ids.scrapped",
        "move_ids.quantity",
        "move_ids.product_uom",
        "move_ids.purchase_line_id",
        "move_ids.package_level_id",
        "move_ids.pr_currency_id",
        "move_ids.pr_unit_price",
        "move_ids.pr_price_subtotal",
        "move_ids.pr_price_tax",
        "move_ids.pr_price_total",
    )
    def _compute_pr_amounts(self):
        AccountTax = self.env["account.tax"]
        for picking in self:
            company = picking.company_id or self.env.company
            currency = picking.pr_currency_id or picking._get_pr_currency()
            if picking.picking_type_code not in ("incoming", "outgoing"):
                picking.pr_amount_untaxed = 0.0
                picking.pr_amount_tax = 0.0
                picking.pr_amount_total = 0.0
                continue
            active_moves = picking._get_pr_amount_moves()
            valued_pairs = []
            for move in active_moves:
                valuation = move._get_pr_order_line_valuation()
                if not valuation:
                    continue
                uom_rounding = (move.product_uom or valuation["uom"]).rounding or 0.001
                if float_is_zero(move.quantity or 0.0, precision_rounding=uom_rounding):
                    continue
                valued_pairs.append((move, valuation))
            if not valued_pairs:
                picking.pr_amount_untaxed = 0.0
                picking.pr_amount_tax = 0.0
                picking.pr_amount_total = 0.0
                continue
            convert_date = (
                picking.scheduled_date.date()
                if picking.scheduled_date
                else fields.Date.context_today(picking)
            )
            amount_untaxed = 0.0
            amount_tax = 0.0
            if company.tax_calculation_rounding_method == "round_globally":
                base_lines = [
                    move._prepare_pr_tax_base_line_dict(valuation)
                    for move, valuation in valued_pairs
                ]
                tax_results = AccountTax.with_company(company)._compute_taxes(base_lines)
                for tot_currency, tot_vals in tax_results["totals"].items():
                    line_untaxed = tot_vals.get("amount_untaxed", 0.0)
                    line_tax = tot_vals.get("amount_tax", 0.0)
                    if tot_currency and currency and tot_currency != currency:
                        amount_untaxed += tot_currency._convert(
                            line_untaxed, currency, company, convert_date, round=False
                        )
                        amount_tax += tot_currency._convert(
                            line_tax, currency, company, convert_date, round=False
                        )
                    else:
                        amount_untaxed += line_untaxed
                        amount_tax += line_tax
            else:
                for move, valuation in valued_pairs:
                    move_currency = valuation["currency"] or move.pr_currency_id or currency
                    if move_currency != currency:
                        amount_untaxed += move_currency._convert(
                            move.pr_price_subtotal, currency, company, convert_date, round=False
                        )
                        amount_tax += move_currency._convert(
                            move.pr_price_tax, currency, company, convert_date, round=False
                        )
                    else:
                        amount_untaxed += move.pr_price_subtotal
                        amount_tax += move.pr_price_tax
            amount_untaxed = currency.round(amount_untaxed)
            amount_tax = currency.round(amount_tax)
            picking.pr_amount_untaxed = amount_untaxed
            picking.pr_amount_tax = amount_tax
            picking.pr_amount_total = currency.round(amount_untaxed + amount_tax)

