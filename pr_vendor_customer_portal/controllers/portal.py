# -*- coding: utf-8 -*-

import base64
import logging
from math import isfinite
from markupsafe import Markup, escape

from odoo import _, fields, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.osv import expression
from odoo.tools import config, format_amount

from odoo.addons.account.controllers.portal import PortalAccount
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.purchase.controllers.portal import CustomerPortal as PurchasePortal
from odoo.addons.sale.controllers.portal import CustomerPortal as SalePortal


_logger = logging.getLogger(__name__)


class PrVendorCustomerPortal(PurchasePortal, PortalAccount, SalePortal):
    _vendor_invoice_max_file_size = 10 * 1024 * 1024
    _vendor_document_max_file_size = 10 * 1024 * 1024

    def _vendor_upload_error(self, message, exception):
        """Keep production errors private, but make local --dev failures actionable."""
        errors = [message]
        if config.get("dev_mode"):
            errors.append(
                _(
                    "Development details: %(error_type)s: %(error)s",
                    error_type=type(exception).__name__,
                    error=str(exception),
                )
            )
        return errors

    def _commercial_partner(self):
        return request.env.user.partner_id.commercial_partner_id

    def _is_customer_portal_partner(self):
        return False

    def _is_vendor_portal_partner(self):
        return bool(self._commercial_partner().supplier_rank)

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

    def _prepare_vendor_delivery_domain(self):
        commercial_partner_id = self._commercial_partner().id
        return [
            ("picking_type_code", "=", "incoming"),
            ("state", "not in", ("draft", "cancel")),
            "|", "|",
            ("message_partner_ids", "child_of", [commercial_partner_id]),
            ("partner_id", "child_of", [commercial_partner_id]),
            ("purchase_id.partner_id", "child_of", [commercial_partner_id]),
        ]

    def _prepare_vendor_delivery_searchbar_sortings(self):
        return {
            "date": {"label": _("Newest"), "order": "scheduled_date desc, id desc"},
            "name": {"label": _("Reference"), "order": "name desc"},
            "state": {"label": _("Status"), "order": "state, scheduled_date desc"},
        }

    def _get_accessible_vendor_delivery(self, delivery_id):
        domain = expression.AND([
            self._prepare_vendor_delivery_domain(),
            [("id", "=", delivery_id)],
        ])
        return request.env["stock.picking"].sudo().search(domain, limit=1)

    def _prepare_srn_domain(self):
        commercial_partner_id = self._commercial_partner().id
        return [
            ("state", "!=", "cancel"),
            "|",
            ("partner_id", "child_of", [commercial_partner_id]),
            ("purchase_id.partner_id", "child_of", [commercial_partner_id]),
        ]

    def _prepare_srn_searchbar_sortings(self):
        return {
            "date": {"label": _("Newest"), "order": "date desc, id desc"},
            "name": {"label": _("Reference"), "order": "name desc"},
            "state": {"label": _("Status"), "order": "state, date desc"},
        }

    def _get_accessible_srn(self, srn_id):
        domain = expression.AND([
            self._prepare_srn_domain(),
            [("id", "=", srn_id)],
        ])
        return request.env["service.receipt.note"].sudo().search(domain, limit=1)

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        commercial_partner = self._commercial_partner()

        if "quotation_count" in counters:
            values["quotation_count"] = 0
        if "order_count" in counters:
            values["order_count"] = 0
        if "invoice_count" in counters:
            values["invoice_count"] = 0
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
        if "vendor_delivery_count" in counters:
            values["vendor_delivery_count"] = 0
            if commercial_partner.supplier_rank:
                values["vendor_delivery_count"] = request.env["stock.picking"].sudo().search_count(
                    self._prepare_vendor_delivery_domain()
                )
        if "srn_count" in counters:
            values["srn_count"] = 0
            if commercial_partner.supplier_rank:
                values["srn_count"] = request.env["service.receipt.note"].sudo().search_count(
                    self._prepare_srn_domain()
                )
        if "statement_count" in counters:
            values["statement_count"] = 0
        return values

    @http.route()
    def portal_my_quotes(self, **kwargs):
        if not self._is_customer_portal_partner():
            return request.redirect("/my")
        return super().portal_my_quotes(**kwargs)

    @http.route()
    def portal_my_orders(self, **kwargs):
        if not self._is_customer_portal_partner():
            return request.redirect("/my")
        return super().portal_my_orders(**kwargs)

    @http.route()
    def portal_quote_page(self, *args, **kwargs):
        return request.redirect("/my")

    @http.route()
    def portal_order_page(self, *args, **kwargs):
        return request.redirect("/my")

    @http.route()
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")
        filterby = "bills"
        return super().portal_my_invoices(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_invoice_detail(
        self, invoice_id, access_token=None, report_type=None, download=False, **kw
    ):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")
        if report_type in ("html", "pdf", "text"):
            try:
                invoice = self._document_check_access(
                    "account.move", invoice_id, access_token
                )
            except (AccessError, MissingError):
                return request.redirect("/my")
            if invoice.move_type not in ("in_invoice", "in_refund"):
                return request.redirect("/my")
            return self._show_report(
                model=invoice,
                report_type=report_type,
                report_ref=(
                    "account.account_invoices"
                    if report_type == "html"
                    else "pr_tax_Invoice_report_custom.petroraq_invoice_report_action_id"
                ),
                download=download,
            )
        try:
            invoice = self._document_check_access(
                "account.move", invoice_id, access_token
            )
        except (AccessError, MissingError):
            return request.redirect("/my")
        if invoice.move_type not in ("in_invoice", "in_refund"):
            return request.redirect("/my")
        return super().portal_my_invoice_detail(
            invoice_id,
            access_token=access_token,
            report_type=report_type,
            download=download,
            **kw,
        )

    @http.route()
    def portal_my_requests_for_quotation(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")
        return super().portal_my_requests_for_quotation(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_purchase_orders(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")
        return super().portal_my_purchase_orders(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw)

    @http.route()
    def portal_my_purchase_order(self, order_id=None, access_token=None, **kw):
        report_type = kw.get("report_type")
        if report_type in ("html", "pdf", "text"):
            try:
                order = self._document_check_access(
                    "purchase.order", order_id, access_token
                )
            except (AccessError, MissingError):
                return request.redirect("/my")
            return self._show_report(
                model=order,
                report_type=report_type,
                report_ref="pr_custom_purchase.petroraq_purchase_order_action_id",
                download=kw.get("download"),
            )
        return super().portal_my_purchase_order(
            order_id=order_id,
            access_token=access_token,
            **kw,
        )

    @http.route(
        ["/vendor/delivery-notes", "/vendor/delivery-notes/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_vendor_delivery_notes(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        values = self._prepare_portal_layout_values()
        Picking = request.env["stock.picking"].sudo()
        domain = self._prepare_vendor_delivery_domain()

        searchbar_sortings = self._prepare_vendor_delivery_searchbar_sortings()
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
            url="/vendor/delivery-notes",
            url_args={"date_begin": date_begin, "date_end": date_end, "sortby": sortby},
            total=delivery_count,
            page=page,
            step=self._items_per_page,
        )

        deliveries = Picking.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager["offset"],
        )
        delivery_rows = []
        status_labels = {
            "pending": _("Pending"),
            "partial": _("Partially Delivered"),
            "received": _("Delivered"),
            "cancel": _("Cancelled"),
        }
        for delivery in deliveries:
            moves = delivery.move_ids_without_package
            demanded_quantity = sum(moves.mapped("product_uom_qty"))
            delivered_quantity = sum(
                move.quantity if "quantity" in move._fields else move.quantity_done
                for move in moves
            )
            status = delivery._pr_portal_delivery_status_from_quantities(
                delivery.state, demanded_quantity, delivered_quantity
            )
            delivery_rows.append({
                "delivery": delivery,
                "delivered_quantity": delivered_quantity,
                "pending_quantity": max(demanded_quantity - delivered_quantity, 0.0),
                "status": status_labels[status],
            })
        request.session["vendor_delivery_notes_history"] = deliveries.ids[:100]

        values.update({
            "date": date_begin,
            "date_end": date_end,
            "delivery_notes": deliveries,
            "delivery_rows": delivery_rows,
            "picking": False,
            "page_name": "vendor_delivery",
            "default_url": "/vendor/delivery-notes",
            "pager": pager,
            "searchbar_sortings": searchbar_sortings,
            "sortby": sortby,
        })
        return request.render("pr_vendor_customer_portal.portal_vendor_delivery_notes", values)

    @http.route(["/vendor/delivery-notes/<int:delivery_id>"], type="http", auth="user", website=True)
    def portal_vendor_delivery_note_detail(self, delivery_id, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        picking = self._get_accessible_vendor_delivery(delivery_id)
        if not picking:
            raise MissingError(_("This delivery note does not exist or you do not have access to it."))

        return request.render("pr_vendor_customer_portal.portal_vendor_delivery_note_page", {
            "picking": picking,
            "page_name": "vendor_delivery",
        })

    @http.route(["/vendor/delivery-notes/<int:delivery_id>/download"], type="http", auth="user", website=True)
    def portal_vendor_delivery_note_download(self, delivery_id, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        picking = self._get_accessible_vendor_delivery(delivery_id)
        if not picking:
            raise MissingError(_("This delivery note does not exist or you do not have access to it."))

        report = request.env.ref("stock.action_report_delivery").sudo()
        content, _report_type = report._render_qweb_pdf(report.report_name, res_ids=picking.ids)
        filename = "%s.pdf" % (picking.name or "delivery-note").replace("/", "_")
        return request.make_response(content, [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", content_disposition(filename)),
        ])

    @http.route(
        ["/vendor/srns", "/vendor/srns/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_vendor_srns(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        values = self._prepare_portal_layout_values()
        Receipt = request.env["service.receipt.note"].sudo()
        domain = self._prepare_srn_domain()

        searchbar_sortings = self._prepare_srn_searchbar_sortings()
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        if date_begin and date_end:
            domain = expression.AND([
                domain,
                [("date", ">", date_begin), ("date", "<=", date_end)],
            ])

        srn_count = Receipt.search_count(domain)
        pager = portal_pager(
            url="/vendor/srns",
            url_args={"date_begin": date_begin, "date_end": date_end, "sortby": sortby},
            total=srn_count,
            page=page,
            step=self._items_per_page,
        )

        srns = Receipt.search(
            domain,
            order=order,
            limit=self._items_per_page,
            offset=pager["offset"],
        )
        request.session["vendor_srns_history"] = srns.ids[:100]

        values.update({
            "date": date_begin,
            "date_end": date_end,
            "srns": srns,
            "srn": False,
            "page_name": "vendor_srn",
            "default_url": "/vendor/srns",
            "pager": pager,
            "searchbar_sortings": searchbar_sortings,
            "sortby": sortby,
        })
        return request.render("pr_vendor_customer_portal.portal_vendor_srns", values)

    @http.route(["/vendor/srns/<int:srn_id>"], type="http", auth="user", website=True)
    def portal_vendor_srn_detail(self, srn_id, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        srn = self._get_accessible_srn(srn_id)
        if not srn:
            raise MissingError(_("This SRN does not exist or you do not have access to it."))

        return request.render("pr_vendor_customer_portal.portal_vendor_srn_page", {
            "srn": srn,
            "page_name": "vendor_srn",
        })

    @http.route(["/vendor", "/vendor/portal"], type="http", auth="user", website=True)
    def portal_vendor_home(self, **kw):
        return request.redirect("/my/home")

    @http.route(
        ["/vendor/invoices", "/vendor/invoices/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_legacy_vendor_invoices(self, page=1, **kw):
        return request.redirect("/my/purchase")

    @http.route(["/vendor/pos"], type="http", auth="user", website=True)
    def portal_vendor_purchase_orders(self, **kw):
        return request.redirect("/my/purchase")

    @http.route(["/vendor/po/<int:po_id>"], type="http", auth="user", website=True)
    def portal_vendor_purchase_order(self, po_id, **kw):
        return request.redirect("/my/purchase/%s" % po_id)

    def _prepare_vendor_upload_values(self, form_data=None, error_message=None):
        PurchaseOrder = request.env["purchase.order"].sudo()
        form_data = form_data or {}
        try:
            selected_po_id = int(form_data.get("po_id") or 0)
        except ValueError:
            selected_po_id = 0
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "vendor_invoice_upload",
            "purchase_orders": PurchaseOrder.search(
                self._prepare_purchase_order_domain(["purchase", "done"]),
                order="date_order desc, id desc",
            ),
            "form_data": form_data,
            "selected_po_id": selected_po_id,
            "error_message": error_message or [],
        })
        return values

    def _vendor_document_type_options(self):
        return {
            "po_acceptance": {
                "label": _("PO Acceptance"),
                "number_label": _("PO Acceptance Reference"),
                "file_label": _("PO Acceptance File"),
                "activity_summary": _("Review Vendor PO Acceptance"),
            },
            "gdn": {
                "label": _("Goods Delivery Note"),
                "number_label": _("GDN Number"),
                "file_label": _("GDN File"),
                "activity_summary": _("Review Vendor GDN"),
            },
            "delivery_note": {
                "label": _("Delivery Note"),
                "number_label": _("Delivery Note Number"),
                "file_label": _("Delivery Note File"),
                "activity_summary": _("Review Vendor Delivery Note"),
            },
            "ses": {
                "label": _("Service Entry Sheet"),
                "number_label": _("SES Number"),
                "file_label": _("SES File"),
                "activity_summary": _("Review Vendor SES"),
            },
        }

    def _prepare_vendor_document_upload_values(self, form_data=None, error_message=None):
        PurchaseOrder = request.env["purchase.order"].sudo()
        form_data = form_data or {}
        document_types = self._vendor_document_type_options()
        try:
            selected_po_id = int(form_data.get("po_id") or 0)
        except ValueError:
            selected_po_id = 0
        try:
            selected_delivery_id = int(form_data.get("delivery_id") or 0)
        except ValueError:
            selected_delivery_id = 0
        selected_document_type = form_data.get("document_type")
        if selected_document_type not in document_types:
            selected_document_type = "delivery_note"
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "vendor_document_upload",
            "purchase_orders": PurchaseOrder.search(
                self._prepare_purchase_order_domain(["purchase", "done"]),
                order="date_order desc, id desc",
            ),
            "document_types": document_types,
            "selected_document_type": selected_document_type,
            "selected_document_type_meta": document_types[selected_document_type],
            "form_data": form_data,
            "selected_po_id": selected_po_id,
            "selected_delivery_id": selected_delivery_id,
            "error_message": error_message or [],
        })
        return values

    def _is_allowed_vendor_document_file(self, content):
        return (
            content.startswith(b"%PDF-")
            or content.startswith(b"\xff\xd8\xff")
            or content.startswith(b"\x89PNG\r\n\x1a\n")
        )

    def _vendor_upload_reviewers(self, po, reviewer_group_xmlids):
        reviewers = request.env["res.users"].sudo()
        for xmlid in reviewer_group_xmlids:
            group = request.env.ref(xmlid, raise_if_not_found=False)
            if group:
                reviewers |= group.users.filtered("active")
        reviewers = reviewers.filtered(lambda user: po.company_id in user.company_ids)
        if not reviewers and po.user_id and po.user_id.active:
            reviewers = po.user_id
        return reviewers

    def _schedule_vendor_upload_reviewers(self, po, reviewers, summary, note):
        for reviewer in reviewers:
            po.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=reviewer.id,
                summary=summary,
                note=note,
            )

    @http.route(
        ["/vendor/document/upload"],
        type="http",
        auth="user",
        website=True,
        methods=["GET", "POST"],
        csrf=True,
    )
    def portal_vendor_document_upload(self, **post):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        if request.httprequest.method == "GET":
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_document_upload",
                self._prepare_vendor_document_upload_values(form_data=post),
            )

        document_types = self._vendor_document_type_options()
        error_message = []
        form_data = dict(post)
        po_id = post.get("po_id")
        delivery_id = post.get("delivery_id")
        document_type = post.get("document_type")
        if document_type not in document_types:
            document_type = "delivery_note"
            form_data["document_type"] = document_type
        document_meta = document_types[document_type]
        document_number = (post.get("document_number") or "").strip()
        document_date = post.get("document_date")
        document_file = request.httprequest.files.get("document_file")

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
        delivery = request.env["stock.picking"].sudo().browse()
        if delivery_id:
            try:
                delivery_id = int(delivery_id)
            except ValueError:
                delivery_id = 0
            if delivery_id:
                delivery = self._get_accessible_vendor_delivery(delivery_id)
                if not delivery or delivery.purchase_id != po:
                    error_message.append(_("Please select a valid delivery note for this purchase order."))
        if not document_number:
            error_message.append(_("Please enter the %(document)s number.", document=document_meta["label"]))
        if not document_date:
            error_message.append(_("Please select the document date."))
        if not document_file:
            error_message.append(_("Please attach the document file."))

        document_file_content = b""
        if document_file:
            document_file_content = document_file.read(
                self._vendor_document_max_file_size + 1
            )
            if len(document_file_content) > self._vendor_document_max_file_size:
                error_message.append(_("The document file must be 10 MB or smaller."))
            elif not self._is_allowed_vendor_document_file(document_file_content):
                error_message.append(_("Please upload a valid PDF, JPG, or PNG file."))

        try:
            parsed_date = fields.Date.to_date(document_date) if document_date else False
        except (TypeError, ValueError):
            parsed_date = False
            error_message.append(_("Please enter a valid document date."))

        if error_message:
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_document_upload",
                self._prepare_vendor_document_upload_values(
                    form_data=form_data,
                    error_message=error_message,
                ),
            )

        try:
            vendor = self._commercial_partner().sudo()
            target = delivery or po
            attachment = request.env["ir.attachment"].sudo().create({
                "name": document_file.filename or ("%s-%s" % (document_type, document_number)),
                "type": "binary",
                "datas": base64.b64encode(document_file_content).decode(),
                "res_model": target._name,
                "res_id": target.id,
                "mimetype": document_file.mimetype,
                "description": _(
                    "Vendor %(document)s %(number)s uploaded through the portal.",
                    document=document_meta["label"],
                    number=document_number,
                ),
                "pr_vendor_portal_upload": True,
                "pr_vendor_portal_visible": True,
                "pr_vendor_portal_document_type": document_type,
                "pr_vendor_id": vendor.id,
                "pr_vendor_document_number": document_number,
                "pr_vendor_document_date": parsed_date,
                "pr_vendor_portal_user_id": request.env.user.id,
            })

            note = (post.get("notes") or "").strip()
            message_body = Markup(
                "<p><strong>Vendor {document} uploaded through the portal</strong></p>"
                "<ul>"
                "<li><strong>Vendor:</strong> {vendor}</li>"
                "<li><strong>Purchase Order:</strong> {po}</li>"
                "<li><strong>Document number:</strong> {number}</li>"
                "<li><strong>Document date:</strong> {date}</li>"
                "{notes}"
                "</ul>"
            ).format(
                document=escape(document_meta["label"]),
                vendor=escape(vendor.display_name),
                po=escape(po.name or ""),
                number=escape(document_number),
                date=escape(fields.Date.to_string(parsed_date)),
                notes=Markup("<li><strong>Vendor notes:</strong> {}</li>").format(
                    escape(note)
                ) if note else Markup(""),
            )
            try:
                with request.env.cr.savepoint():
                    target.sudo().message_post(
                        body=message_body,
                        attachment_ids=attachment.ids,
                        author_id=request.env.user.partner_id.id,
                        subtype_xmlid="mail.mt_note",
                    )
            except Exception:
                _logger.exception(
                    "Vendor document %s was attached to PO %s, but chatter posting failed",
                    attachment.id,
                    po.id,
                )

            try:
                with request.env.cr.savepoint():
                    reviewers = self._vendor_upload_reviewers(
                        po,
                        (
                            "pr_custom_purchase.inventory_qc",
                            "pr_custom_purchase.inventory_admin",
                        ),
                    )
                    self._schedule_vendor_upload_reviewers(
                        po,
                        reviewers,
                        _(
                            "%(summary)s %(number)s",
                            summary=document_meta["activity_summary"],
                            number=document_number,
                        ),
                        message_body,
                    )
            except Exception:
                _logger.exception(
                    "Vendor document %s was attached to PO %s, but reviewer notification failed",
                    attachment.id,
                    po.id,
                )
        except Exception as exception:
            _logger.exception(
                "Vendor portal document upload failed for PO %s and document %s",
                po.id,
                document_number,
            )
            request.env.cr.rollback()
            error_message.extend(self._vendor_upload_error(
                _("The document could not be attached to the purchase order. Please try again or contact Procurement."),
                exception,
            ))
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_document_upload",
                self._prepare_vendor_document_upload_values(
                    form_data=form_data,
                    error_message=error_message,
                ),
            )

        if delivery:
            return request.redirect("/vendor/delivery-notes/%s?document_uploaded=1" % delivery.id)
        return request.redirect(po.get_portal_url(query_string="&vendor_document_uploaded=1"))

    @http.route(
        ["/vendor/attachment/<int:attachment_id>/download"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_vendor_attachment_download(self, attachment_id, **kw):
        if not self._is_vendor_portal_partner():
            return request.redirect("/my")

        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_field:
            raise MissingError(_("This attachment is not available in the vendor portal."))

        allowed = False
        if attachment.res_model == "purchase.order":
            allowed = bool(request.env["purchase.order"].sudo().search_count(
                expression.AND([
                    self._prepare_purchase_order_domain(),
                    [("id", "=", attachment.res_id)],
                ])
            ))
        elif attachment.res_model == "stock.picking":
            allowed = bool(self._get_accessible_vendor_delivery(attachment.res_id))
        elif attachment.res_model == "account.move":
            allowed = bool(request.env["account.move"].sudo().search_count(
                expression.AND([
                    self._get_invoices_domain("in"),
                    [("id", "=", attachment.res_id)],
                ])
            ))
        elif attachment.res_model == "service.receipt.note":
            allowed = bool(self._get_accessible_srn(attachment.res_id))
        if not allowed:
            raise MissingError(_("This attachment does not exist or you do not have access to it."))

        content = attachment.raw or b""
        return request.make_response(content, [
            ("Content-Type", attachment.mimetype or "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", content_disposition(attachment.name or "document")),
        ])

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
                self._prepare_vendor_upload_values(form_data=post),
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
            error_message.append(_("Please attach the invoice PDF."))

        invoice_file_content = b""
        if invoice_file:
            invoice_file_content = invoice_file.read(
                self._vendor_invoice_max_file_size + 1
            )
            if len(invoice_file_content) > self._vendor_invoice_max_file_size:
                error_message.append(
                    _("The invoice PDF must be 10 MB or smaller.")
                )
            elif not invoice_file_content.startswith(b"%PDF-"):
                error_message.append(_("Please upload a valid PDF invoice."))

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
        else:
            if not isfinite(parsed_amount) or parsed_amount <= 0:
                error_message.append(
                    _("The invoice amount must be greater than zero.")
                )

        if error_message:
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                self._prepare_vendor_upload_values(form_data=form_data, error_message=error_message),
            )

        try:
            vendor = self._commercial_partner().sudo()
            duplicate = request.env["ir.attachment"].sudo().search_count([
                ("pr_vendor_portal_upload", "=", True),
                ("pr_vendor_id", "child_of", [vendor.id]),
                ("pr_vendor_invoice_number", "=ilike", vendor_invoice_number),
            ])
            duplicate += request.env["pr.portal.vendor.invoice"].sudo().search_count([
                ("partner_id", "child_of", [vendor.id]),
                ("vendor_invoice_number", "=ilike", vendor_invoice_number),
            ])
            if duplicate:
                error_message.append(_(
                    "Invoice number %(number)s has already been uploaded for this vendor.",
                    number=vendor_invoice_number,
                ))
                return request.render(
                    "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                    self._prepare_vendor_upload_values(
                        form_data=form_data,
                        error_message=error_message,
                    ),
                )

            attachment = request.env["ir.attachment"].sudo().create({
                "name": invoice_file.filename or ("%s.pdf" % vendor_invoice_number),
                "type": "binary",
                "datas": base64.b64encode(invoice_file_content).decode(),
                "res_model": "purchase.order",
                "res_id": po.id,
                "mimetype": "application/pdf",
                "description": _("Vendor invoice %(number)s uploaded through the portal.", number=vendor_invoice_number),
                "pr_vendor_portal_upload": True,
                "pr_vendor_portal_visible": True,
                "pr_vendor_portal_document_type": "invoice",
                "pr_vendor_id": vendor.id,
                "pr_vendor_invoice_number": vendor_invoice_number,
                "pr_vendor_invoice_date": parsed_date,
                "pr_vendor_invoice_amount": parsed_amount,
                "pr_vendor_invoice_currency_id": po.currency_id.id,
                "pr_vendor_document_number": vendor_invoice_number,
                "pr_vendor_document_date": parsed_date,
                "pr_vendor_portal_user_id": request.env.user.id,
            })

            note = (post.get("notes") or "").strip()
            message_body = Markup(
                "<p><strong>Vendor invoice uploaded through the portal</strong></p>"
                "<ul>"
                "<li><strong>Vendor:</strong> {vendor}</li>"
                "<li><strong>Invoice number:</strong> {number}</li>"
                "<li><strong>Invoice date:</strong> {date}</li>"
                "<li><strong>Amount:</strong> {amount}</li>"
                "{notes}"
                "</ul>"
            ).format(
                vendor=escape(vendor.display_name),
                number=escape(vendor_invoice_number),
                date=escape(fields.Date.to_string(parsed_date)),
                amount=escape(format_amount(request.env, parsed_amount, po.currency_id)),
                notes=Markup("<li><strong>Vendor notes:</strong> {}</li>").format(
                    escape(note)
                ) if note else Markup(""),
            )
            try:
                with request.env.cr.savepoint():
                    po.sudo().message_post(
                        body=message_body,
                        attachment_ids=attachment.ids,
                        author_id=request.env.user.partner_id.id,
                        subtype_xmlid="mail.mt_note",
                    )
            except Exception:
                _logger.exception(
                    "Vendor invoice %s was attached to PO %s, but chatter posting failed",
                    attachment.id,
                    po.id,
                )

            try:
                with request.env.cr.savepoint():
                    reviewer_group = request.env.ref(
                        "pr_vendor_customer_portal.group_vendor_invoice_reviewer",
                        raise_if_not_found=False,
                    )
                    reviewers = reviewer_group.users.filtered("active") if reviewer_group else request.env["res.users"]
                    reviewers = reviewers.filtered(
                        lambda user: po.company_id in user.company_ids
                    )
                    if not reviewers:
                        accounting_group = request.env.ref(
                            "account.group_account_manager",
                            raise_if_not_found=False,
                        )
                        reviewers = accounting_group.users.filtered("active") if accounting_group else request.env["res.users"]
                        reviewers = reviewers.filtered(
                            lambda user: po.company_id in user.company_ids
                        )
                    if not reviewers and po.user_id and po.user_id.active:
                        reviewers = po.user_id
                    for reviewer in reviewers:
                        po.sudo().activity_schedule(
                            "mail.mail_activity_data_todo",
                            user_id=reviewer.id,
                            summary=_("Review Vendor Invoice %(number)s", number=vendor_invoice_number),
                            note=message_body,
                        )
            except Exception:
                _logger.exception(
                    "Vendor invoice %s was attached to PO %s, but reviewer notification failed",
                    attachment.id,
                    po.id,
                )
        except Exception as exception:
            _logger.exception(
                "Vendor portal invoice upload failed for PO %s and invoice %s",
                po.id,
                vendor_invoice_number,
            )
            request.env.cr.rollback()
            error_message.extend(self._vendor_upload_error(
                _("The invoice could not be attached to the purchase order. Please try again or contact Accounts."),
                exception,
            ))
            return request.render(
                "pr_vendor_customer_portal.portal_vendor_invoice_upload",
                self._prepare_vendor_upload_values(form_data=form_data, error_message=error_message),
            )

        return request.redirect(
            po.get_portal_url(query_string="&invoice_uploaded=1")
        )
