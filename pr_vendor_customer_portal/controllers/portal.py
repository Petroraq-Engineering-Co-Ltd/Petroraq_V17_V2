# -*- coding: utf-8 -*-

import base64
from collections import OrderedDict

from odoo import _, fields, http
from odoo.exceptions import MissingError
from odoo.http import content_disposition, request
from odoo.osv import expression

from odoo.addons.account.controllers.portal import PortalAccount
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.purchase.controllers.portal import CustomerPortal as PurchasePortal
from odoo.addons.sale.controllers.portal import CustomerPortal as SalePortal


class PrVendorCustomerPortal(PurchasePortal, PortalAccount, SalePortal):
    def _commercial_partner(self):
        return request.env.user.partner_id.commercial_partner_id

    def _is_customer_portal_partner(self):
        return bool(self._commercial_partner().customer_rank)

    def _is_vendor_portal_partner(self):
        return bool(self._commercial_partner().supplier_rank)

    def _prepare_sale_partner_domain(self, partner):
        commercial_partner_id = partner.commercial_partner_id.id
        return [
            "|", "|", "|",
            ("message_partner_ids", "child_of", [commercial_partner_id]),
            ("partner_id", "child_of", [commercial_partner_id]),
            ("partner_invoice_id", "child_of", [commercial_partner_id]),
            ("partner_shipping_id", "child_of", [commercial_partner_id]),
        ]

    def _prepare_quotations_domain(self, partner):
        return expression.AND([
            self._prepare_sale_partner_domain(partner),
            [("state", "=", "sent")],
        ])

    def _prepare_orders_domain(self, partner):
        return expression.AND([
            self._prepare_sale_partner_domain(partner),
            [("state", "in", ["sale", "done"])],
        ])

    def _prepare_account_partner_domain(self):
        commercial_partner_id = self._commercial_partner().id
        return [
            "|", "|",
            ("message_partner_ids", "child_of", [commercial_partner_id]),
            ("partner_id", "child_of", [commercial_partner_id]),
            ("commercial_partner_id", "=", commercial_partner_id),
        ]

    def _get_invoices_domain(self, m_type=None):
        return expression.AND([
            super()._get_invoices_domain(m_type),
            self._prepare_account_partner_domain(),
        ])

    def _prepare_purchase_partner_domain(self):
        commercial_partner_id = self._commercial_partner().id
        return [
            "|",
            ("message_partner_ids", "child_of", [commercial_partner_id]),
            ("partner_id", "child_of", [commercial_partner_id]),
        ]

    def _prepare_purchase_order_domain(self, states=None):
        domain = self._prepare_purchase_partner_domain()
        if states:
            domain = expression.AND([domain, [("state", "in", states)]])
        return domain

    def _render_portal(
        self, template, page, date_begin, date_end, sortby, filterby,
        domain, searchbar_filters, default_filter, url, history, page_name, key,
    ):
        if key in ("rfqs", "orders"):
            domain = expression.AND([domain, self._prepare_purchase_partner_domain()])
        return super()._render_portal(
            template, page, date_begin, date_end, sortby, filterby,
            domain, searchbar_filters, default_filter, url, history, page_name, key,
        )

    def _prepare_deliveries_domain(self):
        commercial_partner_id = self._commercial_partner().id
        return [
            ("picking_type_code", "=", "outgoing"),
            ("state", "not in", ("draft", "cancel")),
            "|", "|", "|",
            ("message_partner_ids", "child_of", [commercial_partner_id]),
            ("partner_id", "child_of", [commercial_partner_id]),
            ("sale_id.partner_id", "child_of", [commercial_partner_id]),
            ("delivery_note_ship_to_partner_id", "child_of", [commercial_partner_id]),
        ]

    def _prepare_delivery_searchbar_sortings(self):
        return {
            "date": {"label": _("Newest"), "order": "scheduled_date desc, id desc"},
            "name": {"label": _("Reference"), "order": "name desc"},
            "state": {"label": _("Status"), "order": "state, scheduled_date desc"},
        }

    def _vendor_invoice_domain(self):
        return [("partner_id", "child_of", [self._commercial_partner().id])]

    def _vendor_invoice_sortings(self):
        return {
            "date": {"label": _("Newest"), "order": "create_date desc, id desc"},
            "name": {"label": _("Reference"), "order": "name desc"},
            "invoice_date": {"label": _("Invoice Date"), "order": "invoice_date desc, id desc"},
            "state": {"label": _("Status"), "order": "state, create_date desc"},
        }

    def _vendor_invoice_state_labels(self):
        selection = request.env["pr.portal.vendor.invoice"]._fields["state"].selection
        return dict(selection)

    def _vendor_invoice_state_classes(self):
        return {
            "submitted": "text-bg-secondary",
            "review": "text-bg-info",
            "approved": "text-bg-success",
            "rejected": "text-bg-danger",
        }

    def _get_accessible_delivery(self, delivery_id):
        domain = expression.AND([
            self._prepare_deliveries_domain(),
            [("id", "=", delivery_id)],
        ])
        return request.env["stock.picking"].sudo().search(domain, limit=1)

    def _get_accessible_vendor_invoice(self, invoice_id):
        domain = expression.AND([
            self._vendor_invoice_domain(),
            [("id", "=", invoice_id)],
        ])
        return request.env["pr.portal.vendor.invoice"].sudo().search(domain, limit=1)

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        commercial_partner = self._commercial_partner()

        if "quotation_count" in counters:
            values["quotation_count"] = 0
            if commercial_partner.customer_rank:
                values["quotation_count"] = request.env["sale.order"].sudo().search_count(
                    self._prepare_quotations_domain(commercial_partner)
                )
        if "order_count" in counters:
            values["order_count"] = 0
            if commercial_partner.customer_rank:
                values["order_count"] = request.env["sale.order"].sudo().search_count(
                    self._prepare_orders_domain(commercial_partner)
                )
        if "invoice_count" in counters:
            values["invoice_count"] = 0
            if commercial_partner.customer_rank:
                values["invoice_count"] = request.env["account.move"].sudo().search_count(
                    self._get_invoices_domain("out")
                )
        if "bill_count" in counters:
            values["bill_count"] = 0
            if commercial_partner.supplier_rank:
                values["bill_count"] = request.env["account.move"].sudo().search_count(
                    self._get_invoices_domain("in")
                )
        if "rfq_count" in counters:
            values["rfq_count"] = 0
            if commercial_partner.supplier_rank:
                values["rfq_count"] = request.env["purchase.order"].sudo().search_count(
                    self._prepare_purchase_order_domain(["sent"])
                )
        if "purchase_count" in counters:
            values["purchase_count"] = 0
            if commercial_partner.supplier_rank:
                values["purchase_count"] = request.env["purchase.order"].sudo().search_count(
                    self._prepare_purchase_order_domain(["purchase", "done", "cancel"])
                )
        if "delivery_count" in counters:
            values["delivery_count"] = 0
            if commercial_partner.customer_rank:
                values["delivery_count"] = request.env["stock.picking"].sudo().search_count(
                    self._prepare_deliveries_domain()
                )
        if "vendor_invoice_count" in counters:
            values["vendor_invoice_count"] = 0
            if commercial_partner.supplier_rank:
                values["vendor_invoice_count"] = request.env["pr.portal.vendor.invoice"].sudo().search_count(
                    self._vendor_invoice_domain()
                )
        return values

    @http.route()
    def portal_my_quotes(self, **kwargs):
        return super().portal_my_quotes(**kwargs)

    @http.route()
    def portal_my_orders(self, **kwargs):
        return super().portal_my_orders(**kwargs)

    @http.route()
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        return super().portal_my_invoices(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_requests_for_quotation(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        return super().portal_my_requests_for_quotation(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_purchase_orders(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        return super().portal_my_purchase_orders(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route(["/my/deliveries", "/my/deliveries/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_deliveries(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        if not self._is_customer_portal_partner():
            return request.redirect("/my")

        values = self._prepare_portal_layout_values()
        Picking = request.env["stock.picking"].sudo()
        domain = self._prepare_deliveries_domain()

        searchbar_sortings = self._prepare_delivery_searchbar_sortings()
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        if date_begin and date_end:
            domain = expression.AND([
                domain,
                [("scheduled_date", ">", date_begin), ("scheduled_date", "<=", date_end)],
            ])

        delivery_count = Picking.search_count(domain)
        pager = portal_pager(
            url="/my/deliveries",
            url_args={"date_begin": date_begin, "date_end": date_end, "sortby": sortby},
            total=delivery_count,
            page=page,
            step=self._items_per_page,
        )

        deliveries = Picking.search(domain, order=order, limit=self._items_per_page, offset=pager["offset"])
        request.session["my_deliveries_history"] = deliveries.ids[:100]

        values.update({
            "date": date_begin,
            "date_end": date_end,
            "deliveries": deliveries,
            "picking": False,
            "page_name": "delivery",
            "default_url": "/my/deliveries",
            "pager": pager,
            "searchbar_sortings": searchbar_sortings,
            "sortby": sortby,
        })
        return request.render("pr_vendor_customer_portal.portal_my_deliveries", values)

    @http.route(["/my/deliveries/<int:delivery_id>"], type="http", auth="user", website=True)
    def portal_my_delivery_detail(self, delivery_id, **kw):
        if not self._is_customer_portal_partner():
            return request.redirect("/my")

        picking = self._get_accessible_delivery(delivery_id)
        if not picking:
            raise MissingError(_("This delivery does not exist or you do not have access to it."))

        return request.render("pr_vendor_customer_portal.portal_delivery_page", {
            "picking": picking,
            "page_name": "delivery",
        })

    @http.route(["/my/deliveries/<int:delivery_id>/download"], type="http", auth="user", website=True)
    def portal_my_delivery_download(self, delivery_id, **kw):
        if not self._is_customer_portal_partner():
            return request.redirect("/my")

        picking = self._get_accessible_delivery(delivery_id)
        if not picking:
            raise MissingError(_("This delivery does not exist or you do not have access to it."))

        report = request.env.ref("stock.action_report_delivery").sudo()
        content, _report_type = report._render_qweb_pdf(report.report_name, res_ids=picking.ids)
        filename = "%s.pdf" % (picking.name or "delivery").replace("/", "_")
        return request.make_response(content, [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", content_disposition(filename)),
        ])

    @http.route(["/vendor", "/vendor/portal"], type="http", auth="user", website=True)
    def portal_vendor_home(self, **kw):
        return request.redirect("/my/home")

    @http.route(["/vendor/pos"], type="http", auth="user", website=True)
    def portal_vendor_purchase_orders(self, **kw):
        return request.redirect("/my/purchase")

    @http.route(["/vendor/po/<int:po_id>"], type="http", auth="user", website=True)
    def portal_vendor_purchase_order(self, po_id, **kw):
        return request.redirect("/my/purchase/%s" % po_id)

    @http.route(["/vendor/invoices", "/vendor/invoices/page/<int:page>"], type="http", auth="user", website=True)
    def portal_vendor_invoices(self, page=1, sortby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        values = self._prepare_portal_layout_values()
        VendorInvoice = request.env["pr.portal.vendor.invoice"].sudo()
        domain = self._vendor_invoice_domain()

        searchbar_sortings = self._vendor_invoice_sortings()
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        invoice_count = VendorInvoice.search_count(domain)
        pager = portal_pager(
            url="/vendor/invoices",
            url_args={"sortby": sortby},
            total=invoice_count,
            page=page,
            step=self._items_per_page,
        )
        invoices = VendorInvoice.search(domain, order=order, limit=self._items_per_page, offset=pager["offset"])

        values.update({
            "invoices": invoices,
            "vendor_invoice": False,
            "page_name": "vendor_invoice",
            "pager": pager,
            "default_url": "/vendor/invoices",
            "searchbar_sortings": OrderedDict(sorted(searchbar_sortings.items())),
            "sortby": sortby,
            "state_labels": self._vendor_invoice_state_labels(),
            "state_classes": self._vendor_invoice_state_classes(),
        })
        return request.render("pr_vendor_customer_portal.portal_vendor_invoices", values)

    @http.route(["/vendor/invoices/<int:invoice_id>/download"], type="http", auth="user", website=True)
    def portal_vendor_invoice_download(self, invoice_id, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        invoice = self._get_accessible_vendor_invoice(invoice_id)
        if not invoice or not invoice.attachment_id:
            return request.redirect("/vendor/invoices")

        attachment = invoice.attachment_id.sudo()
        content = base64.b64decode(attachment.datas or b"")
        filename = attachment.name or ("%s.pdf" % invoice.name)
        return request.make_response(content, [
            ("Content-Type", attachment.mimetype or "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", content_disposition(filename)),
        ])

    def _prepare_vendor_upload_values(self, form_data=None, error_message=None):
        PurchaseOrder = request.env["purchase.order"].sudo()
        form_data = form_data or {}
        try:
            selected_po_id = int(form_data.get("po_id") or 0)
        except ValueError:
            selected_po_id = 0
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "vendor_invoice",
            "vendor_invoice": False,
            "purchase_orders": PurchaseOrder.search(
                self._prepare_purchase_order_domain(["purchase", "done"]),
                order="date_order desc, id desc",
            ),
            "form_data": form_data,
            "selected_po_id": selected_po_id,
            "error_message": error_message or [],
        })
        return values

    @http.route(
        ["/vendor/invoice/upload"],
        type="http",
        auth="user",
        website=True,
        methods=["GET", "POST"],
        csrf=True,
    )
    def portal_vendor_invoice_upload(self, **post):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        if request.httprequest.method == "GET":
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                self._prepare_vendor_upload_values(),
            )

        error_message = []
        form_data = dict(post)
        po_id = post.get("po_id")
        vendor_invoice_number = (post.get("vendor_invoice_number") or "").strip()
        invoice_date = post.get("invoice_date")
        amount_total = post.get("amount_total")
        invoice_file = request.httprequest.files.get("invoice_file")

        PurchaseOrder = request.env["purchase.order"].sudo()
        po = PurchaseOrder.browse()
        if po_id:
            try:
                po_id = int(po_id)
            except ValueError:
                po_id = 0
            if po_id:
                po = PurchaseOrder.search(
                    expression.AND([
                        self._prepare_purchase_order_domain(["purchase", "done"]),
                        [("id", "=", po_id)],
                    ]),
                    limit=1,
                )
        if not po:
            error_message.append(_("Please select a valid purchase order."))
        if not vendor_invoice_number:
            error_message.append(_("Please enter the vendor invoice number."))
        if not invoice_date:
            error_message.append(_("Please select the invoice date."))
        if not invoice_file:
            error_message.append(_("Please attach the invoice document."))

        try:
            parsed_date = fields.Date.to_date(invoice_date) if invoice_date else False
        except (TypeError, ValueError):
            parsed_date = False
            error_message.append(_("Please enter a valid invoice date."))

        try:
            parsed_amount = float((amount_total or "0").replace(",", ""))
        except ValueError:
            parsed_amount = 0.0
            error_message.append(_("Please enter a valid invoice amount."))

        if error_message:
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                self._prepare_vendor_upload_values(form_data=form_data, error_message=error_message),
            )

        VendorInvoice = request.env["pr.portal.vendor.invoice"].sudo()
        try:
            vendor_invoice = VendorInvoice.create({
                "partner_id": self._commercial_partner().id,
                "po_id": po.id,
                "vendor_invoice_number": vendor_invoice_number,
                "invoice_date": parsed_date,
                "amount_total": parsed_amount,
                "currency_id": po.currency_id.id or request.env.company.currency_id.id,
                "notes": post.get("notes") or False,
                "portal_user_id": request.env.user.id,
            })
            attachment = request.env["ir.attachment"].sudo().create({
                "name": invoice_file.filename or vendor_invoice_number,
                "type": "binary",
                "datas": base64.b64encode(invoice_file.read()).decode(),
                "res_model": vendor_invoice._name,
                "res_id": vendor_invoice.id,
                "mimetype": invoice_file.mimetype,
            })
            vendor_invoice.write({"attachment_id": attachment.id})
        except Exception:
            request.env.cr.rollback()
            error_message.append(_("This vendor invoice could not be submitted. Please check that the invoice number is not already used for this vendor."))
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                self._prepare_vendor_upload_values(form_data=form_data, error_message=error_message),
            )

        return request.redirect("/vendor/invoices")
