from odoo import fields, models, api, _
from odoo.http import request

class ir_ui_menu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def search(self, args, offset=0, limit=None, order=None):
        if self.env.context.get('buypass_access') or self.env.context.get('bypass_access'):
            return super(ir_ui_menu, self).search(args, offset=offset, limit=limit, order=order)
        ids = super(ir_ui_menu, self).search(args, offset=0, limit=None, order=order)
        user = self.env.user
        # user.clear_caches()
        try:
            cids = request.httprequest.cookies.get('cids') and request.httprequest.cookies.get('cids').split(',')[0] or self.env.company.id
            for menu_id in user.access_management_ids.filtered(lambda line: int(cids) in line.company_ids.ids).mapped('hide_menu_ids.menu_id'):
                menu_id = self.browse(menu_id)
                if menu_id in ids:
                    ids = ids - menu_id
            if offset:
                ids = ids[offset:]
            if limit:
                ids = ids[:limit]
        except:
            pass
        return ids
        # return len(ids) if count else ids
    
    @api.model_create_multi
    def create(self, vals_list):
        res = super(ir_ui_menu, self).create(vals_list)
        menu_item_obj = self.env['menu.item'].sudo()
        for record in res:
            item = menu_item_obj.search([('menu_id', '=', record.id)], limit=1)
            vals = {'name': menu_item_obj._get_menu_item_name(record), 'menu_id': record.id}
            if item:
                item.write(vals)
            else:
                menu_item_obj.create(vals)
        return res

    def write(self, vals):
        res = super(ir_ui_menu, self).write(vals)
        if {'name', 'parent_id', 'sequence', 'active'}.intersection(vals):
            menu_item_obj = self.env['menu.item'].sudo()
            for record in self:
                item = menu_item_obj.search([('menu_id', '=', record.id)], limit=1)
                if item:
                    item.write({'name': menu_item_obj._get_menu_item_name(record)})
        return res

    def unlink(self):
        menu_item_obj = self.env['menu.item'].sudo()
        for record in self:
            menu_item_obj.search([('menu_id','=',record.id)]).unlink()
        return super(ir_ui_menu, self).unlink()

