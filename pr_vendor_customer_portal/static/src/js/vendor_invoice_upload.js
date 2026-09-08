/** @odoo-module **/

function initializeVendorInvoiceReceiptFilter() {
    const poSelect = document.querySelector("#po_id");
    const receiptSelect = document.querySelector("#receipt_token");
    if (poSelect && receiptSelect) {
        const filterReceipts = () => {
            const poId = poSelect.value;
            let selectedIsVisible = !receiptSelect.value;
            for (const option of receiptSelect.options) {
                if (!option.value) {
                    option.hidden = false;
                    continue;
                }
                option.hidden = !poId || option.dataset.poId !== poId;
                if (!option.hidden && option.selected) {
                    selectedIsVisible = true;
                }
            }
            if (!selectedIsVisible) {
                receiptSelect.value = "";
            }
        };
        poSelect.addEventListener("change", filterReceipts);
        filterReceipts();
    }

    for (const input of document.querySelectorAll(
        "input[name='company_registry'], input[name='cr_number'], input[name='cr_no']"
    )) {
        input.type = "text";
        input.inputMode = "numeric";
        input.pattern = "[0-9]{10}";
        input.minLength = 10;
        input.maxLength = 10;
        input.title = "CR Number must contain exactly 10 numeric digits.";
        input.addEventListener("input", () => {
            input.value = input.value.replace(/\D/g, "").slice(0, 10);
        });
    }
}

document.addEventListener("DOMContentLoaded", initializeVendorInvoiceReceiptFilter);
