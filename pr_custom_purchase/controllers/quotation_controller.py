from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class PortalRFQ(http.Controller):

    def _resolve_rfq(self, rfq_id):
        """Resolve a portal RFQ without creating or migrating records."""
        return request.env["purchase.order"].sudo().browse(rfq_id).exists()

    def _can_access_rfq(self, rfq):
        partner = request.env.user.partner_id.commercial_partner_id
        rfq_partner = rfq.partner_id.commercial_partner_id
        follower_ids = rfq.message_partner_ids.mapped(
            "commercial_partner_id"
        ).ids
        return rfq_partner == partner or partner.id in follower_ids

    def _get_rfq_lines(self, rfq):
        return rfq.custom_line_ids or rfq.order_line.filtered(
            lambda line: not line.display_type
        )

    def _prepare_rfq_lines(self, rfq):
        values = []
        for line in self._get_rfq_lines(rfq):
            is_custom_line = line._name == "purchase.order.custom.line"
            quantity = line.quantity if is_custom_line else line.product_qty
            unit = line.unit if is_custom_line else line.product_uom.name
            if is_custom_line:
                product_type = line.type
            else:
                detailed_type = (
                    line.product_id.detailed_type
                    if "detailed_type" in line.product_id._fields
                    else line.product_id.type
                )
                product_type = (
                    "service" if detailed_type == "service" else "material"
                )
            values.append({
                "name": line.name,
                "quantity": quantity,
                "type": product_type,
                "unit": unit,
                "price_unit": line.price_unit,
                "subtotal": quantity * line.price_unit,
            })
        return values

    @http.route(
        "/my/rfq/<int:rfq_id>/quotation", type="http", auth="user", website=True
    )
    def portal_create_rfq_quotation(self, rfq_id, **kw):
        rfq = self._resolve_rfq(rfq_id)
        if not rfq or not self._can_access_rfq(rfq):
            return request.redirect("/my/rfq")
        rfq_lines = self._prepare_rfq_lines(rfq)
        company_registry = rfq.partner_id.company_registry
        return request.render(
            "pr_custom_purchase.portal_create_rfq_quotation_form",
            {
                "rfq": rfq,
                "rfq_lines": rfq_lines,
                "company_registry": company_registry,
            },
        )

    @http.route("/my/rfqs", type="http", auth="user", website=True)
    def portal_rfqs_legacy_redirect(self, **kw):
        return request.redirect("/my/rfq")

    @http.route("/my/rfqs/<int:rfq_id>", type="http", auth="user", website=True)
    def portal_rfq_view(self, rfq_id, **kw):
        rfq = self._resolve_rfq(rfq_id)
        if not rfq or not self._can_access_rfq(rfq):
            return request.redirect("/my")

        rfq_lines = self._prepare_rfq_lines(rfq)

        # Fetch all quotations related to this RFQ
        quotations = request.env["purchase.quotation"].sudo().search([
            ("custom_rfq_id", "=", rfq.id),
            (
                "vendor_id.commercial_partner_id",
                "=",
                request.env.user.partner_id.commercial_partner_id.id,
            ),
        ])

        return request.render(
            "pr_custom_purchase.portal_rfq_view_template",
            {
                "rfq": rfq,
                "rfq_lines": rfq_lines,
                "quotations": quotations,
            },
        )

    @http.route(
        "/my/rfq/<int:rfq_id>/quotation/submit",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def submit_rfq_quotation(self, rfq_id, **post):
        rfq = self._resolve_rfq(rfq_id)
        if not rfq or not self._can_access_rfq(rfq):
            return request.redirect("/my/rfq")
        partner = request.env.user.partner_id
        existing_quotation = request.env["purchase.quotation"].sudo().search([
            ("custom_rfq_id", "=", rfq.id),
            (
                "vendor_id.commercial_partner_id",
                "=",
                partner.commercial_partner_id.id,
            ),
        ], limit=1)
        if existing_quotation:
            return request.redirect("/my/rfq?quotation_already_submitted=1")

        # Create quotation record in your custom model
        quotation = (
            request.env["purchase.quotation"]
            .sudo()
            .create(
                {
                    "vendor_id": partner.id,
                    "pr_name": rfq.pr_name,
                    "rfq_origin": rfq.name,
                    "vendor_ref": rfq.origin,
                    "notes": post.get("description"),
                    "order_deadline": post.get("quotation_valid_till"),
                    "expected_arrival": rfq.date_planned,
                    "custom_rfq_id": rfq.id,
                    "supplier_name": post.get("supplier_name"),
                    "contact_person": post.get("contact_person"),
                    "company_address": post.get("company_address"),
                    "phone_number": post.get("phone_number"),
                    "email_address": post.get("email_address"),
                    "supplier_id": post.get("supplier_id"),
                    "quotation_ref": post.get("quotation_ref"),
                    # Payment Terms
                    "terms_net": bool(post.get("terms_net")),
                    "terms_30days": bool(post.get("terms_30days")),
                    "terms_advance": bool(post.get("terms_advance")),
                    "terms_advance_specify": (
                        post.get("terms_advance_specify")
                        if post.get("terms_advance")
                        else None
                    ),
                    "terms_delivery": bool(post.get("terms_delivery")),
                    "terms_other": bool(post.get("terms_other")),
                    "terms_others_specify": (
                        post.get("terms_others_specify")
                        if post.get("terms_others")
                        else None
                    ),
                    # Production / Material Availability
                    "ex_stock": bool(post.get("ex_stock")),
                    "required_days": bool(post.get("required_days")),
                    "production_days": (
                        post.get("production_days")
                        if post.get("required_days")
                        else None
                    ),
                    # Delivery Terms
                    "ex_work": bool(post.get("ex_work")),
                    "delivery_site": bool(post.get("delivery_site")),
                    # Delivery Date Expected
                    "delivery_date": post.get("delivery_date"),
                    # Delivery Method
                    "delivery_courier": bool(post.get("courier")),
                    "delivery_pickup": bool(post.get("pickup")),
                    "delivery_freight": bool(post.get("freight")),
                    "delivery_others": bool(post.get("delivery_others")),
                    "delivery_others_specify": (
                        post.get("delivery_others_specify")
                        if post.get("delivery_others")
                        else None
                    ),
                    # Partial Order Acceptable
                    "partial_yes": bool(post.get("partial_yes")),
                    "partial_no": bool(post.get("partial_no")),
                    "project_id": rfq.project_id.id,
                    #PO Info
                    "requested_by": rfq.requested_by,
                    "department": rfq.department,
                    "supervisor": rfq.supervisor,
                    "supervisor_partner_id": rfq.supervisor_partner_id,

                }
            )
        )
        rfq_line_by_index = {
            idx: line for idx, line in enumerate(self._get_rfq_lines(rfq))
        }

        product_indexes = set()
        for key in post:
            if key.startswith("product_description_"):
                try:
                    index = int(key.split("_")[-1])
                    product_indexes.add(index)
                except:
                    continue

        for i in sorted(product_indexes):
            description = post.get(f"product_description_{i}", "").strip()
            quantity = float(post.get(f"product_quantity_{i}", 0))
            unit = post.get(f"product_unit_{i}", "").strip()
            price_unit = float(post.get(f"product_price_{i}", 0))
            product_type = post.get(f"product_type_{i}", "").strip()

            if not description:
                continue

            rfq_line = rfq_line_by_index.get(i)
            cost_center = (
                getattr(rfq_line, "cost_center_id", False)
                if rfq_line
                else False
            )
            if (
                not cost_center
                and rfq_line
                and rfq_line._name == "purchase.order.line"
            ):
                cost_center = (
                    rfq_line.custom_requisition_line_id.cost_center_id
                )
            if not cost_center:
                return request.redirect(
                    f"/my/rfq/{rfq_id}/quotation?error=missing_cost_center"
                )
            request.env["purchase.quotation.line"].sudo().create(
                {
                    "quotation_id": quotation.id,
                    "name": description,
                    "quantity": quantity,
                    "type": product_type,
                    "unit": unit,
                    "price_unit": price_unit,
                    "cost_center_id": cost_center.id,
                }
            )

        all_quotations = (
            request.env["purchase.quotation"]
            .sudo()
            .search([("custom_rfq_id", "=", rfq.id)])
        )

        if all_quotations:
            min_total = min(all_quotations.mapped("total_incl_vat"))
            for q in all_quotations:
                q.is_best = q.total_incl_vat == min_total

        # ---------------- Email Notification Logic ----------------
        group_xml_ids = [
            "pr_custom_purchase.procurement_admin",
        ]

        recipient_users = request.env["res.users"].browse()
        for xml_id in group_xml_ids:
            try:
                # Use sudo() to avoid access error
                group = request.env.ref(xml_id).sudo()
                recipient_users |= group.users
            except ValueError:
                continue

        # Filter active users with email
        recipient_users = recipient_users.filtered(lambda u: u.active and u.email)

        # Email content
        subject = f"New Quotation Submitted for RFQ: {rfq.name}"
        body = f"""
        <p>Hello,</p>
        <p>A new quotation has been submitted by <strong>{partner.name}</strong> for RFQ <strong>{rfq.name}</strong>.</p>
        <p>
        Vendor Reference: {rfq.origin or 'N/A'}<br/>
        Total Quotation Value (incl. VAT): {quotation.total_incl_vat:.2f}
        </p>
        <p>You can view it in the system for further action.</p>
        <p>Regards,<br/>Odoo Purchase System</p>
        """

        # Send email
        for user in recipient_users:
            request.env["mail.mail"].sudo().create(
                {
                    "subject": subject,
                    "body_html": body,
                    "email_to": user.email,
                }
            ).send()

        # ---------------- Create Activity for Procurement Users ----------------
        procurement_group = request.env.ref(
            "pr_custom_purchase.procurement_admin"
        ).sudo()
        for user in procurement_group.users:
            if user.active:
                request.env["mail.activity"].sudo().create(
                    {
                        "res_model_id": request.env["ir.model"]
                        ._get("purchase.quotation")
                        .id,
                        "res_id": quotation.id,
                        "activity_type_id": request.env.ref(
                            "mail.mail_activity_data_todo"
                        ).id,
                        "summary": "Review Quotation",
                        "user_id": user.id,
                        "note": f"Please review the Quotation for RFQ {rfq.name}.",
                        "date_deadline": quotation.order_deadline,
                    }
                )

        return request.redirect("/my/rfq?quotation_submitted=1")
