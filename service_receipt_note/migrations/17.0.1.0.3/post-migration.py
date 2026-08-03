from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Continue the global SRN sequence above every number already issued."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    sequence = env.ref(
        "service_receipt_note.seq_service_receipt_note",
        raise_if_not_found=False,
    )
    if not sequence:
        return

    cr.execute(
        """
        SELECT COALESCE(MAX(substring(name FROM '(\\d+)$')::integer), 0)
          FROM service_receipt_note
         WHERE name ~ '^PEC-SRN-[0-9]{4}[-/][0-9]+$'
        """
    )
    highest_issued = cr.fetchone()[0]
    if sequence.number_next_actual <= highest_issued:
        sequence.number_next_actual = highest_issued + 1
