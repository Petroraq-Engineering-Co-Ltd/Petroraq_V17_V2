/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Masked HH:MM hours input.
 *
 * Why this exists instead of Odoo's float_time: float_time happily
 * accepts BOTH "1:30" and "1.5". A user typing "1.50" means one hour
 * fifty minutes, but float_time reads it as 1.5 and stores 1:30 - a
 * silent, confusing difference on a field the whole capacity check
 * depends on.
 *
 * This widget only ever lets digits through. The colon is part of the
 * mask and cannot be deleted, so a decimal point can never be typed in
 * the first place. Storage is unchanged - still a plain float, so every
 * existing sum, total and capacity constraint keeps working.
 */

const MAX_MINUTES = 59;

export function floatToHHMM(value) {
    const totalMinutes = Math.round((value || 0) * 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/**
 * Digits -> "HH:MM". Right-aligned, so typing 1 5 0 gives 01:50 - the
 * reading a user typing "1.50" intended. Minutes above 59 roll DOWN to
 * 59 rather than spilling into the next hour, which is what was agreed:
 * 01:75 becomes 01:59, never 02:15.
 */
export function maskDigits(raw) {
    const digits = String(raw || "").replace(/\D/g, "").slice(-4);
    if (!digits) {
        return "00:00";
    }
    const padded = digits.padStart(4, "0");
    const hours = parseInt(padded.slice(0, 2), 10);
    let minutes = parseInt(padded.slice(2), 10);
    if (minutes > MAX_MINUTES) {
        minutes = MAX_MINUTES;
    }
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function hhmmToFloat(text) {
    const [rawHours, rawMinutes] = String(text || "").split(":");
    const hours = parseInt(rawHours, 10) || 0;
    let minutes = parseInt(rawMinutes, 10) || 0;
    if (minutes > MAX_MINUTES) {
        minutes = MAX_MINUTES;
    }
    return hours + minutes / 60;
}

export class MaskedHoursField extends Component {
    static template = "employee_task_management.MaskedHoursField";
    static props = { ...standardFieldProps };

    setup() {
        // `buffer` holds what the user is typing. It is null whenever the
        // field is not focused, so the displayed text falls back to the
        // record's own value and stays in step with changes made
        // elsewhere (recomputes, onchanges, another widget).
        this.state = useState({ buffer: null });
    }

    get displayValue() {
        if (this.state.buffer !== null) {
            return this.state.buffer;
        }
        return floatToHHMM(this.props.record.data[this.props.name]);
    }

    onInput(ev) {
        this.state.buffer = maskDigits(ev.target.value);
    }

    onFocus(ev) {
        this.state.buffer = this.displayValue;
        // Select everything so the next keystroke replaces the value
        // instead of appending to it - otherwise the right-aligned mask
        // makes an existing entry very fiddly to correct.
        ev.target.select();
    }

    commit() {
        if (this.state.buffer === null) {
            return;
        }
        const value = hhmmToFloat(this.state.buffer);
        this.state.buffer = null;
        if (value !== this.props.record.data[this.props.name]) {
            this.props.record.update({ [this.props.name]: value });
        }
    }

    onBlur() {
        this.commit();
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.commit();
        }
    }
}

export const maskedHoursField = {
    component: MaskedHoursField,
    displayName: "Hours (HH:MM)",
    supportedTypes: ["float"],
};

registry.category("fields").add("masked_hours", maskedHoursField);

// The list view formats COLUMN AGGREGATES (sum="Total Hours") through a
// SEPARATE registry - registry.category("formatters").get(widget || type).
// Registering the component alone is not enough: without this entry the
// lookup misses, Odoo falls back to the raw float, and the total prints
// as "3.67" instead of "03:40" - which reads exactly like the hours are
// being added base-100. Reuses floatToHHMM above so the total and the
// cells can never disagree about how a float becomes HH:MM.
registry.category("formatters").add("masked_hours", floatToHHMM);
