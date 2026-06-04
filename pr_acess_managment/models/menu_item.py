from odoo import api, fields, models


class menu_item(models.Model):
    _name = 'menu.item'
    _description = "Menu Item"
    _rec_name = 'name'
    _order = 'name, id'

    name = fields.Char('Menu')
    menu_id = fields.Integer('Menu ID', required=True, index=True)

    def init(self):
        self._sync_from_ir_ui_menu()

    @api.model
    def _get_menu_item_name(self, menu):
        complete_name = menu.complete_name if 'complete_name' in menu._fields else False
        return complete_name or menu.display_name or menu.name or str(menu.id)

    @api.model
    def _sync_from_ir_ui_menu(self):
        menus = self.env['ir.ui.menu'].sudo().with_context(buypass_access=True).search([])
        menu_ids = set(menus.ids)
        items = self.sudo().search([])
        existing_by_menu_id = {}
        duplicate_items = self.sudo().browse()

        for item in items:
            if not item.menu_id:
                duplicate_items |= item
                continue
            if item.menu_id in existing_by_menu_id:
                duplicate_items |= item
            else:
                existing_by_menu_id[item.menu_id] = item

        created_count = 0
        updated_count = 0
        vals_list = []
        for menu in menus:
            name = self._get_menu_item_name(menu)
            item = existing_by_menu_id.get(menu.id)
            if item:
                if item.name != name:
                    item.write({'name': name})
                    updated_count += 1
            else:
                vals_list.append({'name': name, 'menu_id': menu.id})

        if vals_list:
            self.sudo().create(vals_list)
            created_count = len(vals_list)

        obsolete_items = items.filtered(lambda item: item.menu_id and item.menu_id not in menu_ids)
        cleanup_items = obsolete_items | duplicate_items
        removed_count = len(cleanup_items)
        if cleanup_items:
            cleanup_items.unlink()

        return {
            'created': created_count,
            'updated': updated_count,
            'removed': removed_count,
            'total': self.sudo().search_count([]),
        }
