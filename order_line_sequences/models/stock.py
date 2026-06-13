from odoo import api, fields, models


class StockMove(models.Model):
    """ Class for inherited model stock move. Contains a field for line
            numbers and a function for computing line numbers."""

    _inherit = 'stock.move'
    sequence_number = fields.Integer(string='#',
                                     compute='_compute_sequence_number',
                                     help='Line Numbers', default=False)
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
            line._onchange_product_id()
            warning = line._onchange_suggest_packaging()
            if warning:
                result = warning
        return result

    @api.depends('picking_id')
    def _compute_sequence_number(self):
        """Function to compute line numbers"""
        for picking in self.mapped('picking_id'):
            sequence_number = 1
            if picking.move_ids_without_package:
                for lines in picking.move_ids_without_package:
                    lines.sequence_number = sequence_number
                    sequence_number += 1
            else:
                self.sequence_number = ''


class StockPicking(models.Model):
    """ Class for inherited model stock picking. Contains
        a function for computing line numbers."""
    _inherit = 'stock.picking'

    @api.onchange('move_ids_without_package')
    def _onchange_move_ids_without_package(self):
        """For calculating line number of operations"""
        sequence_number = 1
        for rec in self.move_ids_without_package:
            rec.sequence_number = sequence_number
            sequence_number += 1
