/** @odoo-module **/

const QUESTIONS_PER_PAGE = 6;
const MAX_REPEATING_ROWS = 20;

function createElement(tagName, className, html) {
    const element = document.createElement(tagName);
    element.className = className || "";
    if (html) {
        element.innerHTML = html;
    }
    return element;
}

function findGroupByField(form, fieldName) {
    const field = form.querySelector(`[name="${fieldName}"]`);
    return field ? field.closest(".form-group") : null;
}

function buildStep(title, subtitle) {
    const step = createElement("section", "pr-form-step");
    const header = createElement("div", "pr-step-header");
    const heading = createElement(
        "div",
        "",
        `<h3 class="pr-step-title">${title}</h3><p class="pr-step-subtitle">${subtitle}</p>`
    );
    const badge = createElement("span", "pr-step-kicker");
    header.append(heading, badge);
    step.append(header);
    step.grid = createElement("div", "pr-step-grid");
    step.append(step.grid);
    step.stepTitle = title;
    step.stepBadge = badge;
    return step;
}

function appendNavigation(step, hasPrevious, hasNext, submitButton) {
    const actions = createElement("div", "pr-step-actions");
    if (hasPrevious) {
        const previous = createElement(
            "button",
            "pr-step-button pr-previous",
            '<i class="fa fa-arrow-left"></i><span>Previous</span>'
        );
        previous.type = "button";
        actions.append(previous);
    }
    if (hasNext) {
        const next = createElement(
            "button",
            "pr-step-button pr-next",
            '<span>Continue</span><i class="fa fa-arrow-right"></i>'
        );
        next.type = "button";
        actions.append(next);
    } else if (submitButton) {
        actions.append(submitButton);
    }
    step.append(actions);
}

function firstInvalidControl(container) {
    const controls = container.querySelectorAll("input, select, textarea");
    for (const control of controls) {
        if (!control.disabled && !control.checkValidity()) {
            return control;
        }
    }
    return null;
}

function findBusinessInvalidControl(form) {
    const businessFields = form.querySelectorAll(
        '[name="partner_name"], [name="email_from"], [name="partner_phone"], ' +
            '[name="partner_location"], [name="experience"], [name="salary_expected"], ' +
            '[name="notice_period"], [name="linkedin_profile"], ' +
            '[name="national_id_iqama"]'
    );
    for (const field of businessFields) {
        field.setCustomValidity("");
    }
    function invalid(field, message) {
        field.setCustomValidity(message);
        return field;
    }

    const checks = [
        [
            "partner_name",
            /^[\p{L}][\p{L}\p{M}\s'.-]{1,79}$/u,
            "Enter a valid full name.",
        ],
        [
            "email_from",
            /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/,
            "Enter a valid email address.",
        ],
        [
            "partner_phone",
            /^\+?[0-9][0-9\s().-]{7,19}$/,
            "Enter a valid phone number.",
        ],
        [
            "partner_location",
            /^[\p{L}\p{N}][\p{L}\p{M}\p{N},\s'.-]{1,99}$/u,
            "Enter a valid location.",
        ],
    ];
    for (const [name, pattern, message] of checks) {
        const field = form.querySelector(`[name="${name}"]`);
        if (field && !pattern.test(String(field.value || "").trim())) {
            return invalid(field, message);
        }
    }

    const ranges = [
        ["experience", 0, 60],
        ["salary_expected", 1, 100000000],
        ["notice_period", 0, 3650],
    ];
    for (const [name, minimum, maximum] of ranges) {
        const field = form.querySelector(`[name="${name}"]`);
        const value = field ? String(field.value || "").trim() : "";
        const number = Number(value);
        if (field && (!/^\d+$/.test(value) || number < minimum || number > maximum)) {
            return invalid(
                field,
                `Enter a whole number between ${minimum} and ${maximum}.`
            );
        }
    }

    const linkedIn = form.querySelector('[name="linkedin_profile"]');
    const linkedInValue = linkedIn ? String(linkedIn.value || "").trim() : "";
    if (
        linkedInValue &&
        !/^(https?:\/\/)?([a-z]{2,3}\.)?linkedin\.com\/.*$/i.test(linkedInValue)
    ) {
        return invalid(linkedIn, "Enter a valid LinkedIn profile URL.");
    }

    const legal = form.querySelector('[name="legally_required"]');
    const nationalId = form.querySelector('[name="national_id_iqama"]');
    if (legal && legal.value === "yes" && nationalId && !/^\d{10}$/.test(nationalId.value)) {
        return invalid(nationalId, "Enter a valid 10-digit national ID or Iqama number.");
    }
    return null;
}

function initializeRepeatableQuestions() {
    const repeatables = document.querySelectorAll("#jobApplicationForm .pr-repeatable");
    for (const repeatable of repeatables) {
        if (repeatable.dataset.ready === "true") {
            continue;
        }
        repeatable.dataset.ready = "true";
        const rowsContainer = repeatable.querySelector(".pr-repeat-rows");
        const rowTemplate = repeatable.querySelector(".pr-repeat-row-template");
        const tokenInput = repeatable.querySelector(".pr-repeat-row-tokens");
        const addButton = repeatable.querySelector(".pr-add-row");
        const questionRequired = repeatable.dataset.questionRequired === "true";
        let nextToken = 2;

        function rowControls(row) {
            return Array.from(row.querySelectorAll("input, select, textarea"));
        }

        function rowHasValue(row) {
            return rowControls(row).some((control) => String(control.value || "").trim());
        }

        function refreshRows() {
            const rows = Array.from(rowsContainer.querySelectorAll(":scope > .pr-repeat-row"));
            const hasAnyEntry = rows.some(rowHasValue);
            tokenInput.value = rows.map((row) => row.dataset.rowToken).join(",");
            rows.forEach((row, index) => {
                row.style.setProperty("--row-number", `'${index + 1}'`);
                const filled = rowHasValue(row);
                for (const control of rowControls(row)) {
                    control.setCustomValidity("");
                    if (control.dataset.rowRequired === "true") {
                        control.required = filled || (questionRequired && !hasAnyEntry && index === 0);
                    }
                }
            });
            if (questionRequired && !hasAnyEntry && rows.length) {
                const firstControl = rowControls(rows[0])[0];
                if (firstControl) {
                    firstControl.setCustomValidity("Please add at least one complete entry.");
                }
            }
            addButton.disabled = rows.length >= MAX_REPEATING_ROWS;
        }

        function addRow() {
            const rows = rowsContainer.querySelectorAll(":scope > .pr-repeat-row");
            if (rows.length >= MAX_REPEATING_ROWS) {
                return;
            }
            const fragment = rowTemplate.content.cloneNode(true);
            const row = fragment.querySelector(".pr-repeat-row");
            const token = String(nextToken++);
            row.dataset.rowToken = token;
            for (const element of row.querySelectorAll("[name], [id], [for]")) {
                for (const attribute of ["name", "id", "for"]) {
                    const value = element.getAttribute(attribute);
                    if (value) {
                        element.setAttribute(attribute, value.replaceAll("__ROW__", token));
                    }
                }
            }
            rowsContainer.append(fragment);
            refreshRows();
            row.querySelector("input, select, textarea")?.focus();
        }

        addButton.addEventListener("click", addRow);
        rowsContainer.addEventListener("input", refreshRows);
        rowsContainer.addEventListener("change", refreshRows);
        rowsContainer.addEventListener("click", (event) => {
            const removeButton = event.target.closest(".pr-remove-row");
            if (!removeButton) {
                return;
            }
            removeButton.closest(".pr-repeat-row")?.remove();
            if (!rowsContainer.querySelector(".pr-repeat-row")) {
                addRow();
            }
            refreshRows();
        });
        refreshRows();
    }
}

function initializeRecruitmentStepper() {
    const form = document.getElementById("jobApplicationForm");
    if (!form || form.dataset.prStepperReady === "true") {
        return;
    }

    const resumeGroup = findGroupByField(form, "resume");
    const submitButton = form.querySelector("#submitBtn");
    const directGroups = Array.from(form.children).filter((child) =>
        child.classList.contains("form-group")
    );
    if (!resumeGroup || !submitButton || directGroups.length < 9) {
        return;
    }

    form.dataset.prStepperReady = "true";
    form.classList.add("pr-stepped-form");

    const personalNames = new Set([
        "partner_name",
        "email_from",
        "partner_phone",
        "partner_location",
        "nationality_id",
        "experience",
    ]);
    const personalStep = buildStep(
        "Personal details",
        "Tell us how to reach you and where you are based."
    );
    const professionalStep = buildStep(
        "Professional details",
        "Your qualifications, availability, and job-specific answers."
    );
    const documentStep = buildStep(
        "Resume and submit",
        "Attach your CV, review your details, and send your application."
    );

    for (const group of directGroups) {
        if (group === resumeGroup) {
            continue;
        }
        const control = group.querySelector("[name]");
        if (control && personalNames.has(control.name)) {
            personalStep.grid.append(group);
        } else {
            professionalStep.grid.append(group);
        }
    }

    const steps = [personalStep, professionalStep];
    const dynamicSection = form.querySelector(":scope > .pr-dynamic-section");
    if (dynamicSection) {
        const questionFields = Array.from(
            dynamicSection.querySelectorAll(":scope .pr-question-field")
        );
        if (questionFields.length <= 4) {
            professionalStep.grid.append(dynamicSection);
        } else {
            for (let index = 0; index < questionFields.length; index += QUESTIONS_PER_PAGE) {
                const pageNumber = Math.floor(index / QUESTIONS_PER_PAGE) + 1;
                const pageCount = Math.ceil(questionFields.length / QUESTIONS_PER_PAGE);
                const questionStep = buildStep(
                    pageCount > 1 ? `Job questions ${pageNumber} of ${pageCount}` : "Job questions",
                    "Answer the requirements selected for this position."
                );
                for (const field of questionFields.slice(index, index + QUESTIONS_PER_PAGE)) {
                    questionStep.grid.append(field);
                }
                steps.push(questionStep);
            }
            dynamicSection.remove();
        }
    }

    documentStep.grid.append(resumeGroup);
    steps.push(documentStep);

    steps.forEach((step, index) => {
        step.stepBadge.textContent = `Step ${index + 1}/${steps.length}`;
        step.stepBadge.setAttribute(
            "aria-label",
            `Step ${index + 1} of ${steps.length}`
        );
    });

    for (const step of steps) {
        form.append(step);
    }
    steps.forEach((step, index) =>
        appendNavigation(step, index > 0, index < steps.length - 1, submitButton)
    );

    const progress = createElement("ol", "pr-form-progress");
    progress.setAttribute("aria-label", "Application progress");
    const progressItems = steps.map((step, index) => {
        const item = createElement("li", "pr-progress-item");
        item.innerHTML = `<span class="pr-progress-number">${index + 1}</span>`;
        const label = createElement("span", "pr-progress-label");
        label.textContent = step.stepTitle;
        item.append(label);
        progress.append(item);
        return item;
    });
    form.insertBefore(progress, steps[0]);

    let currentStep = 0;
    function showStep(index, shouldScroll = true) {
        currentStep = Math.max(0, Math.min(index, steps.length - 1));
        steps.forEach((step, stepIndex) => {
            step.hidden = stepIndex !== currentStep;
            step.setAttribute("aria-hidden", step.hidden ? "true" : "false");
        });
        progressItems.forEach((item, itemIndex) => {
            item.classList.toggle("is-active", itemIndex === currentStep);
            item.classList.toggle("is-complete", itemIndex < currentStep);
            if (itemIndex === currentStep) {
                item.setAttribute("aria-current", "step");
            } else {
                item.removeAttribute("aria-current");
            }
        });
        if (shouldScroll) {
            const applyHeader = form.closest(".apply-card")?.querySelector(".apply-header");
            applyHeader?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    form.addEventListener("click", (event) => {
        const next = event.target.closest(".pr-next");
        const previous = event.target.closest(".pr-previous");
        if (next) {
            const invalid =
                findBusinessInvalidControl(steps[currentStep]) ||
                firstInvalidControl(steps[currentStep]);
            if (invalid) {
                invalid.reportValidity();
                invalid.focus();
                return;
            }
            showStep(currentStep + 1);
        } else if (previous) {
            showStep(currentStep - 1);
        }
    });

    form.addEventListener("keydown", (event) => {
        if (
            event.key !== "Enter" ||
            currentStep >= steps.length - 1 ||
            event.target.tagName === "TEXTAREA" ||
            event.target.type === "submit"
        ) {
            return;
        }
        event.preventDefault();
        const invalid =
            findBusinessInvalidControl(steps[currentStep]) ||
            firstInvalidControl(steps[currentStep]);
        if (invalid) {
            invalid.reportValidity();
            invalid.focus();
            return;
        }
        showStep(currentStep + 1);
    });

    form.addEventListener(
        "invalid",
        (event) => {
            const index = steps.findIndex((step) => step.contains(event.target));
            if (index >= 0 && index !== currentStep) {
                showStep(index);
            }
        },
        true
    );

    form.addEventListener(
        "submit",
        (event) => {
            const invalid = findBusinessInvalidControl(form) || firstInvalidControl(form);
            if (!invalid) {
                return;
            }
            event.preventDefault();
            const index = steps.findIndex((step) => step.contains(invalid));
            if (index >= 0 && index !== currentStep) {
                showStep(index);
            }
            invalid.reportValidity();
            invalid.focus();
        },
        true
    );

    form.addEventListener("input", (event) => {
        if (
            event.target.matches(
                '[name="partner_name"], [name="email_from"], [name="partner_phone"], ' +
                    '[name="partner_location"], [name="experience"], ' +
                    '[name="salary_expected"], [name="notice_period"], ' +
                    '[name="linkedin_profile"], [name="national_id_iqama"]'
            )
        ) {
            event.target.setCustomValidity("");
        }
    });

    showStep(0, false);
}

function initializeDynamicScreening() {
    initializeRepeatableQuestions();
    initializeRecruitmentStepper();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeDynamicScreening);
} else {
    initializeDynamicScreening();
}
