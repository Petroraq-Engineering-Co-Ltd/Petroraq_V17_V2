/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { getCSSRules } from "@web_editor/js/backend/convert_inline";
import { HtmlField } from "@web_editor/js/backend/html_field";

/**
 * Odoo's email inliner runs every stylesheet selector against the composer.
 * A selector containing a comma inside a quoted attribute value can be split
 * into an invalid fragment by getCSSRules (for example `"][style$=...]`).
 * Ignore only those unusable fragments; all valid rules are still inlined.
 */
export function filterUsableCSSRules(editable, cssRules) {
    return cssRules.filter((rule) => {
        try {
            editable.querySelectorAll(rule.selector);
            return true;
        } catch (error) {
            if (error?.name === "SyntaxError") {
                return false;
            }
            throw error;
        }
    });
}

patch(HtmlField.prototype, {
    async _toInline() {
        if (this.props.record.resModel === "mail.compose.message") {
            const editable = this.wysiwyg.getEditable().get(0);
            const cssRules = this.wysiwyg._rulesCache || getCSSRules(editable.ownerDocument);
            this.wysiwyg._rulesCache = filterUsableCSSRules(editable, cssRules);
        }
        return super._toInline(...arguments);
    },
});
