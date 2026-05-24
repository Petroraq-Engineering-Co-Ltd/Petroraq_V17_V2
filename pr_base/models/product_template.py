from odoo import _, api, models
from odoo.exceptions import ValidationError


PRODUCT_INTERNAL_REFERENCE_SEQUENCE = "product.internal.reference"
SKIP_INTERNAL_REFERENCE_UNIQUE_CHECK = "skip_product_internal_reference_unique_check"


class ProductProduct(models.Model):
    _inherit = "product.product"

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
