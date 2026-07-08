def migrate(cr, version):
    """Restore previously rejected POs that were stored as cancelled."""
    cr.execute(
        """
        UPDATE purchase_order
           SET state = 'rejected'
         WHERE state = 'cancel'
           AND COALESCE(rejection_reason, '') <> ''
           AND UPPER(COALESCE(name, '')) NOT LIKE '%%RFQ%%'
        """
    )
