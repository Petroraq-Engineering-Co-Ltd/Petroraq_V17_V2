def migrate(cr, version):
    """Return employees using the removed Rental selection to Employee."""
    cr.execute(
        """
        UPDATE hr_employee
           SET employee_type = 'employee'
         WHERE employee_type = 'rental'
        """
    )
