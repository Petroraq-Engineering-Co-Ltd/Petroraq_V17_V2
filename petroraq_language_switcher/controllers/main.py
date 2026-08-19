from odoo import http
from odoo.http import request


class PetroraqLanguageSwitcherController(http.Controller):
    """Backend endpoint used by the navbar language switcher."""

    ALLOWED_LANGUAGES = {"en_US", "ar_001"}

    @http.route(
        "/petroraq_language_switcher/switch",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def switch_language(self, lang_code):
        """
        Change only the currently logged-in user's language.

        The route intentionally accepts only English and Arabic. It does not
        allow callers to modify any other user or any other user preference.
        """
        if lang_code not in self.ALLOWED_LANGUAGES:
            return {
                "success": False,
                "message": "Unsupported language.",
            }

        language = request.env["res.lang"].sudo().search(
            [("code", "=", lang_code), ("active", "=", True)],
            limit=1,
        )
        if not language:
            return {
                "success": False,
                "message": (
                    "The selected language is not active in Odoo. "
                    "Activate it from Settings > Translations > Languages first."
                ),
            }

        # sudo() is deliberately limited to the current user and the 'lang'
        # field only. No arbitrary user id or field is accepted from the client.
        request.env.user.sudo().write({"lang": lang_code})

        return {
            "success": True,
            "lang": lang_code,
        }
