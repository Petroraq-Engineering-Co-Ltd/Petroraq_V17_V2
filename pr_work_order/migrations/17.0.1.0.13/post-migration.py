def migrate(cr, version):
    """Link existing WO BOQ rows to the SO rows copied into them.

    Work Orders historically copied every SO row in the same order, including
    sections and notes, but did not retain the source id.  The positional match
    is additionally guarded by product and display type so unrelated rows are
    never linked.
    """
    cr.execute(
        """
        WITH ranked_boq AS (
            SELECT
                boq.id,
                wo.sale_order_id,
                boq.product_id,
                COALESCE(boq.display_type, 'product') AS display_type,
                ROW_NUMBER() OVER (
                    PARTITION BY boq.work_order_id
                    ORDER BY boq.sequence, boq.id
                ) AS row_number
            FROM pr_work_order_boq AS boq
            JOIN pr_work_order AS wo ON wo.id = boq.work_order_id
            WHERE wo.sale_order_id IS NOT NULL
              AND boq.sale_order_line_id IS NULL
        ),
        ranked_sale AS (
            SELECT
                line.id,
                line.order_id,
                line.product_id,
                COALESCE(line.display_type, 'product') AS display_type,
                ROW_NUMBER() OVER (
                    PARTITION BY line.order_id
                    ORDER BY line.sequence, line.id
                ) AS row_number
            FROM sale_order_line AS line
        )
        UPDATE pr_work_order_boq AS boq
           SET sale_order_line_id = sale.id
          FROM ranked_boq AS legacy
          JOIN ranked_sale AS sale
            ON sale.order_id = legacy.sale_order_id
           AND sale.row_number = legacy.row_number
           AND sale.product_id IS NOT DISTINCT FROM legacy.product_id
           AND sale.display_type = legacy.display_type
         WHERE boq.id = legacy.id
        """
    )
