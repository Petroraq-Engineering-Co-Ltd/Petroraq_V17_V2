/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PetroraqLanguageSwitcher extends Component {
    static template = "petroraq_language_switcher.LanguageSwitcher";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = useState({ loading: false });
    }

    switchToEnglish() {
        return this.switchLanguage("en_US");
    }

    switchToArabic() {
        return this.switchLanguage("ar_001");
    }

    async switchLanguage(langCode) {
        if (this.state.loading) {
            return;
        }

        this.state.loading = true;
        try {
            const result = await this.rpc(
                "/petroraq_language_switcher/switch",
                { lang_code: langCode }
            );

            if (result && result.success) {
                // A full reload is intentional. Odoo rebuilds the web client
                // with the newly selected language and the correct RTL/LTR
                // direction after the user's language has been updated.
                window.location.reload();
                return;
            }

            this.notification.add(
                (result && result.message) || "Unable to change language.",
                { type: "warning", title: "Language Switcher" }
            );
        } catch (error) {
            console.error("Petroraq language switcher error:", error);
            this.notification.add(
                "An unexpected error occurred while changing the language.",
                { type: "danger", title: "Language Switcher" }
            );
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("systray").add(
    "petroraq_language_switcher.LanguageSwitcher",
    { Component: PetroraqLanguageSwitcher },
    { sequence: 5 }
);
