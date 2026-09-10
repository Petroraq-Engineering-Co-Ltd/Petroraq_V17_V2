/** @odoo-module **/

function initializeVendorInvoiceReceiptFilter() {
    const poSelect = document.querySelector("#po_id");
    const receiptSelect = document.querySelector("#receipt_token");
    if (poSelect && receiptSelect) {
        const originalOptions = Array.from(receiptSelect.options).map((option) => option.cloneNode(true));
        const amountPanel = document.querySelector("#receipt_amount_panel");
        const amountValue = document.querySelector("#receipt_amount_value");
        const filterReceipts = () => {
            const poId = poSelect.value;
            const priorValue = receiptSelect.value;
            const matchingOptions = originalOptions
                .filter((option) => !option.value || (poId && option.dataset.poId === poId))
                .map((option) => option.cloneNode(true));
            receiptSelect.replaceChildren(...matchingOptions);
            if (matchingOptions.some((option) => option.value === priorValue)) {
                receiptSelect.value = priorValue;
            }
            const selected = receiptSelect.selectedOptions[0];
            if (amountPanel && amountValue && selected && selected.value) {
                const amount = Number(selected.dataset.amount || 0);
                amountValue.textContent = `${amount.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                })} ${selected.dataset.currency || ""}`;
                amountPanel.classList.remove("d-none");
            } else if (amountPanel) {
                amountPanel.classList.add("d-none");
            }
        };
        poSelect.addEventListener("change", filterReceipts);
        receiptSelect.addEventListener("change", filterReceipts);
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
