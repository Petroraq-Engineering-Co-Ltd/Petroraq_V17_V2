import re

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError


PRODUCT_INTERNAL_REFERENCE_SEQUENCE = "product.internal.reference"
SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK = "skip_product_internal_reference_unique_check"


class ProductInternalReferenceLookup(models.Model):
    _name = "product.internal.reference.lookup"
    _description = "Product Internal Reference Lookup"
    _auto = False
    _order = "default_code, id"
    _rec_name = "default_code"

    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    default_code = fields.Char(string="Internal Reference", readonly=True)
    active = fields.Boolean(readonly=True)
    sale_ok = fields.Boolean(readonly=True)
    purchase_ok = fields.Boolean(readonly=True)
    detailed_type = fields.Char(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW product_internal_reference_lookup AS (
                SELECT
                    pp.id AS id,
                    pp.id AS product_id,
                    pp.default_code AS default_code,
                    pt.active AS active,
                    pt.sale_ok AS sale_ok,
                    pt.purchase_ok AS purchase_ok,
                    pt.detailed_type AS detailed_type,
                    pt.company_id AS company_id
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
            )
        """)

    @api.depends("default_code", "product_id")
    def _compute_display_name(self):
        for ref in self:
            ref.display_name = ref.default_code or ref.product_id.display_name or str(ref.id)

    @api.model
    def _name_search(self, name="", args=None, operator="ilike", limit=100, order=None):
        args = list(args or [])
        if name:
            args = ["|", ("default_code", operator, name), ("product_id.name", operator, name)] + args
        return self._search(args, limit=limit, order=order)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _clean_product_display_name(self, value):
        value = re.sub(r"<[^>]+>", " ", value or "")
        value = re.sub(r"^\s*\[[^\]]+\]\s*", "", value)
        return " ".join(value.split())

    def _get_display_name_without_internal_reference(self):
        self.ensure_one()
        code = self.default_code or ""
        candidates = [
            self.name,
            self.description_sale,
            self.description_purchase,
            self.description,
            self.product_tmpl_id.name,
        ]
        for candidate in candidates:
            name = self._clean_product_display_name(candidate)
            if name and name != code and name.lower() != "unnamed":
                variant = self.product_template_attribute_value_ids._get_combination_name()
                return variant and "%s (%s)" % (name, variant) or name
        return self.name or code or False

    @api.depends("name", "default_code", "product_tmpl_id", "description", "description_sale", "description_purchase")
    @api.depends_context(
        "display_default_code",
        "seller_id",
        "company_id",
        "partner_id",
        "use_partner_name",
        "show_product_internal_reference",
        "show_product_internal_reference_only",
        "show_product_name_only",
    )
    def _compute_display_name(self):
        if self.env.context.get("show_product_name_only"):
            for product in self:
                product.display_name = product._get_display_name_without_internal_reference()
            return
        if self.env.context.get("show_product_internal_reference"):
            return super()._compute_display_name()
        if self.env.context.get("show_product_internal_reference_only"):
            for product in self:
                product.display_name = product.default_code or product.name or False
            return
        for product in self:
            product.display_name = product._get_display_name_without_internal_reference()

    def _default_code_exists(self, code, exclude_product_ids=None):
        domain = [("default_code", "=", code)]
        if exclude_product_ids:
            domain.append(("id", "not in", exclude_product_ids))
        return bool(self.with_context(active_test=False).search_count(domain))

    def _next_unique_internal_reference(self, reserved_codes=None, exclude_product_ids=None):
        reserved_codes = reserved_codes if reserved_codes is not None else set()
        Product = self.with_context(active_test=False)
        for __ in range(10000):
            code = self.env["ir.sequence"].next_by_code(PRODUCT_INTERNAL_REFERENCE_SEQUENCE)
            if code and code not in reserved_codes and not Product._default_code_exists(
                code, exclude_product_ids=exclude_product_ids
            ):
                reserved_codes.add(code)
                return code
        raise ValidationError(
            _("Could not generate a unique product internal reference. Please check the product sequence.")
        )

    def _normalize_default_code_vals(self, vals_list):
        reserved_codes = set()
        for vals in vals_list:
            code = vals.get("default_code")
            if not code or code in reserved_codes or self._default_code_exists(code):
                vals["default_code"] = self._next_unique_internal_reference(reserved_codes=reserved_codes)
            else:
                reserved_codes.add(code)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK):
            self._normalize_default_code_vals(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        if (
            "default_code" in vals
            and not self.env.context.get(SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK)
        ):
            code = vals.get("default_code")
            if not code:
                for product in self:
                    product_vals = dict(vals)
                    product_vals["default_code"] = product._next_unique_internal_reference(
                        exclude_product_ids=product.ids
                    )
                    super(ProductProduct, product.with_context(
                        **{SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK: True}
                    )).write(product_vals)
                return True

            if len(self) > 1:
                raise ValidationError(
                    _("The same Internal Reference cannot be assigned to multiple products.")
                )
            duplicate = self.with_context(active_test=False).search([
                ("default_code", "=", code),
                ("id", "not in", self.ids),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("Internal Reference %s is already used by %s.") % (code, duplicate.display_name)
                )

        return super().write(vals)

    def _reassign_internal_references(self):
        Product = self.env["product.product"].with_context(active_test=False)
        products = self.with_context(active_test=False).exists().sorted("id")
        if not products:
            return 0

        reserved_codes = set(Product.search([
            ("id", "not in", products.ids),
            ("default_code", "!=", False),
        ]).mapped("default_code"))

        for product in products:
            product.with_context(**{SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK: True}).write({
                "default_code": product._next_unique_internal_reference(
                    reserved_codes=reserved_codes,
                    exclude_product_ids=products.ids,
                )
            })
        return len(products)

    def action_reassign_internal_references(self):
        count = self._reassign_internal_references()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Internal References Reassigned"),
                "message": _("%s product internal reference(s) were reassigned.") % count,
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def action_reassign_all_internal_references(self):
        products = self.with_context(active_test=False).search([], order="id")
        count = products._reassign_internal_references()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("All Internal References Reassigned"),
                "message": _(
                    "%s product internal reference(s) were reassigned. "
                    "New products will continue from the next sequence number."
                ) % count,
                "type": "success",
                "sticky": False,
            },
        }


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _clean_product_display_name(self, value):
        value = re.sub(r"<[^>]+>", " ", value or "")
        value = re.sub(r"^\s*\[[^\]]+\]\s*", "", value)
        return " ".join(value.split())

    def _get_display_name_without_internal_reference(self):
        self.ensure_one()
        code = self.default_code or ""
        candidates = [
            self.name,
            self.description_sale,
            self.description_purchase,
            self.description,
        ]
        for candidate in candidates:
            name = self._clean_product_display_name(candidate)
            if name and name != code and name.lower() != "unnamed":
                return name
        return self.name or code or False

    @api.depends("name", "default_code", "description", "description_sale", "description_purchase")
    @api.depends_context(
        "show_product_internal_reference",
        "show_product_internal_reference_only",
        "show_product_name_only",
    )
    def _compute_display_name(self):
        if self.env.context.get("show_product_name_only"):
            for template in self:
                template.display_name = template._get_display_name_without_internal_reference()
            return
        if self.env.context.get("show_product_internal_reference"):
            return super()._compute_display_name()
        if self.env.context.get("show_product_internal_reference_only"):
            for template in self:
                template.display_name = template.default_code or template.name or False
            return
        for template in self:
            template.display_name = template._get_display_name_without_internal_reference()

    @api.model_create_multi
    def create(self, vals_list):
        Product = self.env["product.product"]
        reserved_codes = set()
        for vals in vals_list:
            code = vals.get("default_code")
            if not code or code in reserved_codes or Product._default_code_exists(code):
                vals["default_code"] = Product._next_unique_internal_reference(
                    reserved_codes=reserved_codes
                )
            else:
                reserved_codes.add(code)
        return super().create(vals_list)

    def action_reassign_internal_references(self):
        return self.with_context(active_test=False).mapped(
            "product_variant_ids"
        ).action_reassign_internal_references()

    @api.model
    def action_reassign_all_internal_references(self):
        return self.env["product.product"].action_reassign_all_internal_references()
