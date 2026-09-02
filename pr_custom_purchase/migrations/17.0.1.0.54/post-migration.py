import re

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sequence = env.ref(
        "pr_custom_purchase.seq_purchase_order",
        raise_if_not_found=False,
    )
    if not sequence:
        return

    # A recently modified database sequence used an increment of three. Keep
    # every issued PO untouched, but continue immediately after the greatest
    # suffix issued in the current year with a normal increment of one.
    sequence.number_increment = 1
    current_year = fields.Date.today().year
    prefix = "PEC-PO-%s-" % current_year
    suffix_pattern = re.compile(r"^%s(\d+)$" % re.escape(prefix))
    issued_names = env["purchase.order"].sudo().search([
        ("name", "like", "%s%%" % prefix),
    ]).mapped("name")
    issued_numbers = [
        int(match.group(1))
        for name in issued_names
        for match in [suffix_pattern.match(name or "")]
        if match
    ]
    required_next = max(issued_numbers, default=0) + 1

    if sequence.use_date_range:
        today = fields.Date.today()
        date_range = sequence.date_range_ids.filtered(
            lambda item: item.date_from <= today <= item.date_to
        )[:1]
        if date_range:
            date_range.number_next_actual = required_next
            return
    sequence.number_next_actual = required_next
