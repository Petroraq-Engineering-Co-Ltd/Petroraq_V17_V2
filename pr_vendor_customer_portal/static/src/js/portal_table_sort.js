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

function addClickableRows(table) {
    [...table.tBodies].flatMap((body) => [...body.rows]).forEach((row) => {
        if (!row.dataset.href || row.dataset.prClickableInitialized) {
            return;
        }
        row.dataset.prClickableInitialized = "1";
        const openRecord = (event) => {
            if (event.target.closest("a, button, input, select, textarea, label")) {
                return;
            }
            window.location.assign(row.dataset.href);
        };
        row.addEventListener("click", openRecord);
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openRecord(event);
            }
        });
    });
}

function addColumnResizing(table) {
    if (table.dataset.prResizeInitialized) {
        return;
    }
    const headers = [...table.tHead.rows[0].cells];
    // Grouped headers need a different column mapping.
    if (table.tHead.rows.length !== 1 || headers.some((cell) => cell.colSpan !== 1)) {
        return;
    }
    table.dataset.prResizeInitialized = "1";
    if (!table.closest(".table-responsive")) {
        const wrapper = document.createElement("div");
        wrapper.className = "table-responsive o_pr_resize_wrapper";
        table.before(wrapper);
        wrapper.appendChild(table);
    }
    let columns;
    const minimumWidth = 64;
    const prepare = () => {
        if (columns) {
            return;
        }
        const widths = headers.map((header) => header.getBoundingClientRect().width);
        const width = table.getBoundingClientRect().width;
        const group = document.createElement("colgroup");
        columns = widths.map((value) => {
            const column = document.createElement("col");
            column.style.width = `${value}px`;
            group.appendChild(column);
            return column;
        });
        table.querySelectorAll(":scope > colgroup").forEach((old) => old.remove());
        table.insertBefore(group, table.tHead);
        table.classList.add("o_pr_columns_resized");
        table.style.width = `${width}px`;
    };
    const resize = (index, width) => {
        const column = columns[index];
        const previous = parseFloat(column.style.width);
        const next = Math.max(minimumWidth, width);
        column.style.width = `${next}px`;
        table.style.width = `${parseFloat(table.style.width) + next - previous}px`;
    };
    headers.forEach((header, index) => {
        const handle = document.createElement("span");
        handle.className = "o_pr_column_resize_handle";
        handle.tabIndex = 0;
        handle.setAttribute("role", "separator");
        handle.setAttribute("aria-orientation", "vertical");
        handle.setAttribute("aria-label", `Resize ${header.textContent.replace(/[↕↑↓]/g, "").trim()} column`);
        handle.title = "Drag to resize column; use left/right arrow keys when focused";
        header.classList.add("o_pr_resizable_column");
        header.appendChild(handle);
        let drag;
        handle.addEventListener("click", (event) => event.stopPropagation());
        handle.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            prepare();
            drag = {
                x: event.clientX,
                width: parseFloat(columns[index].style.width),
                direction: getComputedStyle(table).direction === "rtl" ? -1 : 1,
            };
            handle.setPointerCapture(event.pointerId);
            document.documentElement.classList.add("o_pr_column_resizing");
        });
        handle.addEventListener("pointermove", (event) => {
            if (drag) {
                resize(index, drag.width + (event.clientX - drag.x) * drag.direction);
            }
        });
        const finish = () => {
            drag = null;
            document.documentElement.classList.remove("o_pr_column_resizing");
        };
        handle.addEventListener("pointerup", finish);
        handle.addEventListener("pointercancel", finish);
        handle.addEventListener("lostpointercapture", finish);
        handle.addEventListener("keydown", (event) => {
            event.stopPropagation();
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
                return;
            }
            event.preventDefault();
            prepare();
            const direction = getComputedStyle(table).direction === "rtl" ? -1 : 1;
            const delta = (event.key === "ArrowRight" ? 10 : -10) * direction;
            resize(index, parseFloat(columns[index].style.width) + delta);
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
        addClickableRows(table);
        addColumnResizing(table);
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
