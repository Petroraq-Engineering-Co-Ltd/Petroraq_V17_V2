from odoo import _, models
from odoo.exceptions import UserError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _get_inline_preview_url(self):
        self.ensure_one()
        if self.type == "url":
            if not self.url:
                raise UserError(_("This attachment does not have a URL to preview."))
            return self.url
        return "/web/content/%s" % self.id

    def action_preview_inline(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self._get_inline_preview_url(),
            "target": "new",
        }
