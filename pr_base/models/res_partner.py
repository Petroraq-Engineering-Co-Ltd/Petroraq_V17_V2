# -*- coding: utf-8 -*-

import re

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    partner_code = fields.Char(string='Code', required=False)
    arabic_name = fields.Char(string='Arabic Name', required=False)
    arabic_street = fields.Char(string='Arabic Street', required=False)
    arabic_street2 = fields.Char(string='Arabic Street', required=False)

    def _pr_normalize_partner_identifier(self, value):
        return re.sub(r"[^0-9A-Z]", "", (value or "").upper())

    def _pr_context_requires_partner_identifiers(self):
        return self.env.context.get("res_partner_search_mode") in {"customer", "supplier"}

    def _pr_requires_partner_vat(self):
        """
        VAT is required only for main company records.

        Child contacts should not be forced to have VAT because Odoo usually
        uses the commercial partner/company VAT through commercial_partner_id.
        """
        self.ensure_one()
        return bool(
            self.active
            and not self.parent_id
            and self.is_company
        )

    def _pr_find_duplicate_partner_identifier(self, field_name, normalized_value):
        """
        Duplicate VAT/code check should only compare against main company partners.

        This avoids blocking child contacts that may have the same VAT as their
        parent company.
        """
        self.ensure_one()
        if not normalized_value:
            return self.env["res.partner"]

        candidates = self.search([
            ("id", "!=", self.id),
            ("active", "=", True),
            ("parent_id", "=", False),
            ("is_company", "=", True),
            (field_name, "!=", False),
        ])

        return candidates.filtered(
            lambda partner: partner._pr_normalize_partner_identifier(partner[field_name]) == normalized_value
        )[:1]

    def _pr_check_partner_identifier_rules(self, force_required=False):
        for partner in self:
            # Completely ignore child contacts.
            # VAT uniqueness/requirement should only apply to the main customer/vendor company.
            if partner.parent_id:
                continue

            requires_vat = partner._pr_requires_partner_vat()
            vat = partner._pr_normalize_partner_identifier(partner.vat)

            if requires_vat and not vat:
                raise ValidationError(_("VAT / Tax ID is required for companies."))

            if not partner.active or not vat:
                continue

            duplicate_vat_partner = partner._pr_find_duplicate_partner_identifier("vat", vat)
            if duplicate_vat_partner:
                raise ValidationError(_(
                    "VAT / Tax ID '%(vat)s' is already used by '%(partner)s'."
                ) % {
                    "vat": partner.vat,
                    "partner": duplicate_vat_partner.display_name,
                })

    def name_create(self, name):
        if self._pr_context_requires_partner_identifiers():
            raise ValidationError(_(
                "Quick create is disabled for customers and vendors. "
                "Use Create and Edit, then fill VAT / Tax ID for companies."
            ))
        return super().name_create(name)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if (
            self._pr_context_requires_partner_identifiers()
            and "l10n_sa_additional_identification_scheme" in fields_list
        ):
            values.setdefault("l10n_sa_additional_identification_scheme", "CRN")
        return values

    def _get_auto_code_sequence_code(self):
        self.ensure_one()
        if not self.active or self.parent_id:
            return False
        if self.customer_rank > 0:
            return 'res.partner.customer.code'
        if self.supplier_rank > 0:
            return 'res.partner.vendor.code'
        return False

    def _assign_missing_partner_codes(self):
        for partner in self.filtered(lambda p: not p.partner_code):
            sequence_code = partner._get_auto_code_sequence_code()
            if sequence_code:
                partner.partner_code = self.env['ir.sequence'].next_by_code(sequence_code)

    def _pr_partner_code_sort_key(self):
        self.ensure_one()
        return (
            self.create_date or fields.Datetime.to_datetime("1970-01-01 00:00:00"),
            self.id,
        )

    def _pr_update_partner_code_sequence_next(self, sequence_code, next_number):
        sequence = self.env["ir.sequence"].sudo().search([
            ("code", "=", sequence_code),
            ("company_id", "=", False),
        ], limit=1)
        if sequence:
            sequence.number_next_actual = next_number

    def action_pr_resequence_all_partner_codes(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only Settings users can resequence customer/vendor codes."))

        Partner = self.env["res.partner"].sudo().with_context(pr_skip_partner_identifier_check=True)

        eligible_partners = Partner.search([
            ("active", "=", True),
            ("parent_id", "=", False),
            "|",
            ("customer_rank", ">", 0),
            ("supplier_rank", ">", 0),
        ])

        customer_partners = eligible_partners.filtered(
            lambda partner: partner.customer_rank > 0
        ).sorted(
            lambda partner: partner._pr_partner_code_sort_key()
        )

        vendor_partners = (eligible_partners - customer_partners).filtered(
            lambda partner: partner.supplier_rank > 0
        ).sorted(
            lambda partner: partner._pr_partner_code_sort_key()
        )

        next_customer_code = 1001
        for partner in customer_partners:
            partner.partner_code = str(next_customer_code)
            next_customer_code += 1

        next_vendor_code = 2001
        for partner in vendor_partners:
            partner.partner_code = str(next_vendor_code)
            next_vendor_code += 1

        clear_partners = Partner.search([
            ("active", "=", True),
            ("partner_code", "!=", False),
            "!",
            ("id", "in", eligible_partners.ids),
        ])
        clear_count = len(clear_partners)
        clear_partners.write({"partner_code": False})

        self._pr_update_partner_code_sequence_next("res.partner.customer.code", next_customer_code)
        self._pr_update_partner_code_sequence_next("res.partner.vendor.code", next_vendor_code)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Customer/Vendor codes resequenced"),
                "message": _(
                    "%(customers)s customer(s) resequenced from 1001. "
                    "%(vendors)s vendor(s) resequenced from 2001. "
                    "%(cleared)s non-customer/vendor code(s) cleared."
                ) % {
                    "customers": len(customer_partners),
                    "vendors": len(vendor_partners),
                    "cleared": clear_count,
                },
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)

        partners._assign_missing_partner_codes()

        if not self.env.context.get("pr_skip_partner_identifier_check"):
            partners._pr_check_partner_identifier_rules(
                force_required=self._pr_context_requires_partner_identifiers()
            )

        return partners

    def write(self, vals):
        res = super().write(vals)

        if {'customer_rank', 'supplier_rank', 'partner_code'} & set(vals):
            self._assign_missing_partner_codes()

        if self.env.context.get("pr_skip_partner_identifier_check"):
            return res

        self._pr_check_partner_identifier_rules(
            force_required=self._pr_context_requires_partner_identifiers()
        )

        return res