/** @odoo-module **/

function normalizedValue(cell) {
    const text = (cell?.innerText || "").trim();
    const number = Number(text.replace(/[\s,]/g, "").replace(/[^\d.+-]/g, ""));
    if (
        text &&
        Number.isFinite(number) &&
        /^[^\d+-]*[+-]?\d[\d,\s]*(?:\.\d+)?[^\d]*$/.test(text)
    ) {
        return {type: "number", value: number};
    }
    const timestamp = Date.parse(text);
    if (text && Number.isFinite(timestamp) && /[-/]/.test(text)) {
        return {type: "number", value: timestamp};
    }
    return {type: "text", value: text.toLocaleLowerCase()};
}

function addSearch(table) {
    if (table.dataset.prSearchInitialized) {
        return;
    }
    table.dataset.prSearchInitialized = "1";
    const wrapper = document.createElement("div");
    wrapper.className = "o_pr_portal_table_search input-group mb-3";
    wrapper.innerHTML = `
        <span class="input-group-text" aria-hidden="true">🔎</span>
        <input type="search"
               class="form-control"
               placeholder="Search all columns..."
               aria-label="Search all columns"/>
        <button type="button" class="btn btn-outline-secondary">Clear</button>
    `;
    table.parentNode.insertBefore(wrapper, table);
    const input = wrapper.querySelector("input");
    const clear = wrapper.querySelector("button");
    const filter = () => {
        const terms = input.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
        [...table.tBodies[0].rows].forEach((row) => {
            const haystack = row.innerText.toLocaleLowerCase();
            row.hidden = !terms.every((term) => haystack.includes(term));
        });
    };
    input.addEventListener("input", filter);
    clear.addEventListener("click", () => {
        input.value = "";
        filter();
        input.focus();
    });
}

function addSorting(table) {
    const body = table.tBodies[0];
    const headerRow = table.tHead?.rows[0];
    if (!body || !headerRow) {
        return;
    }
    [...headerRow.cells].forEach((header, columnIndex) => {
        if (header.dataset.prSortableInitialized) {
            return;
        }
        header.dataset.prSortableInitialized = "1";
        header.classList.add("o_pr_portal_sortable");
        header.setAttribute("role", "button");
        header.setAttribute("tabindex", "0");
        const indicator = document.createElement("span");
        indicator.className = "o_pr_sort_indicator";
        indicator.textContent = "↕";
        indicator.setAttribute("aria-hidden", "true");
        header.appendChild(indicator);

        const sort = () => {
            const ascending = header.dataset.prSortDirection !== "asc";
            [...headerRow.cells].forEach((cell) => {
                delete cell.dataset.prSortDirection;
                cell.classList.remove("o_pr_sort_asc", "o_pr_sort_desc");
                const cellIndicator = cell.querySelector(".o_pr_sort_indicator");
                if (cellIndicator) {
                    cellIndicator.textContent = "↕";
                }
            });
            header.dataset.prSortDirection = ascending ? "asc" : "desc";
            header.classList.add(ascending ? "o_pr_sort_asc" : "o_pr_sort_desc");
            indicator.textContent = ascending ? "↑" : "↓";

            const rows = [...body.rows];
            rows.sort((left, right) => {
                const a = normalizedValue(left.cells[columnIndex]);
                const b = normalizedValue(right.cells[columnIndex]);
                const result = a.type === b.type
                    ? (a.value < b.value ? -1 : a.value > b.value ? 1 : 0)
                    : String(a.value).localeCompare(String(b.value));
                return ascending ? result : -result;
            });
            rows.forEach((row) => body.appendChild(row));
        };
        header.addEventListener("click", sort);
        header.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                sort();
            }
        });
    });
}

function initializePortalTables(root = document) {
    root.querySelectorAll(
        ".o_portal_wrap table, main table.table, #wrapwrap table.table"
    ).forEach((table) => {
        if (!table.tHead || !table.tBodies.length) {
            return;
        }
        addSorting(table);
        addSearch(table);
    });
}

function start() {
    initializePortalTables();
    new MutationObserver(() => initializePortalTables()).observe(document.body, {
        childList: true,
        subtree: true,
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, {once: true});
} else {
    start();
}
