/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { archParseBoolean } from "@web/views/utils";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { TranslationButton } from "@web/views/fields/translation_button";
import { Component, useEffect, useRef } from "@odoo/owl";

export function toTitleCase(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function titleCaseInputElement(input) {
    const value = input.value;
    const titleValue = toTitleCase(value);

    if (value === titleValue) {
        return;
    }

    const selectionStart = input.selectionStart;
    const selectionEnd = input.selectionEnd;
    input.value = titleValue;

    if (
        selectionStart !== null &&
        selectionEnd !== null &&
        typeof input.setSelectionRange === "function"
    ) {
        input.setSelectionRange(selectionStart, selectionEnd);
    }
}

function titleCaseTextNode(node) {
    const value = node.nodeValue;
    const titleValue = toTitleCase(value);
    if (value !== titleValue) {
        node.nodeValue = titleValue;
    }
}

function titleCaseReadOnlyElement(element) {
    const walker = document.createTreeWalker(
        element,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode(node) {
                if (!node.nodeValue || !node.nodeValue.trim()) {
                    return NodeFilter.FILTER_REJECT;
                }
                const parent = node.parentElement;
                if (
                    parent &&
                    parent.closest("input, textarea, select, button, .o_field_translate")
                ) {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            },
        }
    );
    const nodes = [];
    while (walker.nextNode()) {
        nodes.push(walker.currentNode);
    }
    nodes.forEach(titleCaseTextNode);
}

function applyTitleCaseFallback(root = document) {
    const elements = [];
    if (root.nodeType === Node.ELEMENT_NODE && root.matches(".o_title_case_field")) {
        elements.push(root);
    }
    elements.push(...root.querySelectorAll?.(".o_title_case_field") || []);

    for (const element of elements) {
        const input = element.matches("input, textarea")
            ? element
            : element.querySelector("input, textarea");
        if (input) {
            titleCaseInputElement(input);
            if (!input.dataset.prTitleCaseBound) {
                input.dataset.prTitleCaseBound = "1";
                input.addEventListener("input", () => titleCaseInputElement(input));
                input.addEventListener("change", () => titleCaseInputElement(input));
                input.addEventListener("blur", () => titleCaseInputElement(input));
            }
            continue;
        }
        titleCaseReadOnlyElement(element);
    }
}

function registerTitleCaseFallback() {
    if (window.__prTitleCaseFallbackRegistered) {
        return;
    }
    window.__prTitleCaseFallbackRegistered = true;
    applyTitleCaseFallback();
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    applyTitleCaseFallback(node);
                }
            }
            if (
                mutation.type === "characterData" &&
                mutation.target.parentElement?.closest(".o_title_case_field")
            ) {
                titleCaseTextNode(mutation.target);
            }
        }
    });
    observer.observe(document.body, {
        childList: true,
        characterData: true,
        subtree: true,
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", registerTitleCaseFallback, { once: true });
} else {
    registerTitleCaseFallback();
}

export class TitleCaseField extends Component {
    static template = "pr_title_case_widget.TitleCaseField";
    static components = {
        TranslationButton,
    };
    static props = {
        ...standardFieldProps,
        autocomplete: { type: String, optional: true },
        isPassword: { type: Boolean, optional: true },
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.input = useRef("input");
        useInputField({
            getValue: () => this.displayValue,
            parse: (value) => this.parse(value),
        });

        useEffect(
            (input) => {
                if (!input) {
                    return;
                }
                const onInput = () => titleCaseInputElement(input);
                input.addEventListener("input", onInput);
                return () => input.removeEventListener("input", onInput);
            },
            () => [this.input.el]
        );
    }

    get rawValue() {
        return this.props.record.data[this.props.name] || "";
    }

    get displayValue() {
        return toTitleCase(this.rawValue);
    }

    get shouldTrim() {
        return this.props.record.fields[this.props.name].trim && !this.props.isPassword;
    }

    get maxLength() {
        return this.props.record.fields[this.props.name].size;
    }

    get isTranslatable() {
        return this.props.record.fields[this.props.name].translate;
    }

    parse(value) {
        const parsedValue = this.shouldTrim ? value.trim() : value;
        return toTitleCase(parsedValue);
    }

}

export const titleCaseField = {
    component: TitleCaseField,
    displayName: _t("Title Case"),
    supportedTypes: ["char"],
    extractProps: ({ attrs }) => ({
        isPassword: archParseBoolean(attrs.password),
        autocomplete: attrs.autocomplete,
        placeholder: attrs.placeholder,
    }),
};

registry.category("fields").add("title_case", titleCaseField);
