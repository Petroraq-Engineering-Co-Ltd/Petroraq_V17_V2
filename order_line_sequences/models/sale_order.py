from odoo import api, fields, models


class SaleOrderLine(models.Model):
    """ Class for inherited model sale order line. Contains a field for line
            numbers and a function for computing line numbers.
    """

    _inherit = 'sale.order.line'

    sequence_number = fields.Integer(string='#', compute='_compute_sequence_number', help='Line Numbers')
    product_internal_reference = fields.Many2one(
        'product.internal.reference.lookup',
        string='Product Code',
        compute='_compute_product_internal_reference',
        inverse='_inverse_product_internal_reference',
        readonly=False,
    )

    @api.depends('product_id')
    def _compute_product_internal_reference(self):
        ProductRef = self.env['product.internal.reference.lookup']
        for line in self:
            line.product_internal_reference = ProductRef.browse(line.product_id.id) if line.product_id else False

    def _inverse_product_internal_reference(self):
        for line in self:
            line.product_id = line.product_internal_reference.product_id

    @api.onchange('product_internal_reference')
    def _onchange_product_internal_reference(self):
        result = {}
        for line in self:
            line.product_id = line.product_internal_reference.product_id
            warning = line._onchange_product_id_warning()
            if warning:
                result = warning
            onchange_cost = getattr(line, '_onchange_product_id_set_cost_price_unit', False)
            if onchange_cost:
                onchange_cost()
            if not line.product_id:
                line.product_internal_reference = False
        return result

    @api.depends('sequence', 'order_id')
    def _compute_sequence_number(self):
        """Function to compute line numbers"""
        for order in self.mapped('order_id'):
            sequence_number = 1
            for lines in order.order_line:
                if lines.display_type:
                    lines.sequence_number = sequence_number
                    sequence_number += 0
                else:
                    lines.sequence_number = sequence_number
                    sequence_number += 1
