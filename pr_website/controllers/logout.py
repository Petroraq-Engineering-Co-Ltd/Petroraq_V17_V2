from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.session import Session


class PetroraqSession(Session):
    """Send every ERP and portal logout to the access-type selector."""

    @http.route()
    def logout(self, redirect="/sign-in"):
        request.session.logout(keep_db=True)
        return request.redirect("/sign-in", 303)
