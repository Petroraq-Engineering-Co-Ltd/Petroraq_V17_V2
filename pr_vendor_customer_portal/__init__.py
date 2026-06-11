# -*- coding: utf-8 -*-

from . import controllers
from . import models

from odoo import api, SUPERUSER_ID


def post_init_cleanup_legacy_portal_access(env, registry=None):
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})

    legacy_xmlids = [
        "petroraq_sale_workflow.stock_picking_rule_portal_customer_deliveries",
        "petroraq_sale_workflow.access_stock_picking_portal_customer_delivery",
    ]
    for xmlid in legacy_xmlids:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.unlink()
