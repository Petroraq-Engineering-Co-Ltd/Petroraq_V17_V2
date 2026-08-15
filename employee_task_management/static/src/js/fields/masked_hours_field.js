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
        // `digits` holds EXACTLY what the user has typed, as raw digits.
        //
        // This must stay separate from what is displayed. The first
        // version re-read the masked text off the input on every
        // keystroke, so the clamp fed back into the input: typing 7,7,7
        // gave 00:07 -> 00:59 (77 clamped) -> 05:59, because the "5" of
        // the clamped "59" slid into the hours slot. Keeping the raw
        // digits means clamping only ever affects what is SHOWN, never
        // what the next keystroke builds on.
        //
        // null = not being edited, fall back to the record's value.
        this.state = useState({ digits: null });
    }

    get displayValue() {
        if (this.state.digits === null || this.state.digits === "") {
            return floatToHHMM(this.props.record.data[this.props.name]);
        }
        return maskDigits(this.state.digits);
    }

    onFocus(ev) {
        // Fresh entry - the first digit typed replaces the old value
        // rather than appending to it.
        this.state.digits = "";
        ev.target.select();
    }

    onKeydown(ev) {
        if (ev.key >= "0" && ev.key <= "9") {
            ev.preventDefault();
            if (this.state.digits === null) {
                this.state.digits = "";
            }
            // Cap at 4 digits (99:59). Oldest digit drops off the left,
            // matching the right-aligned feel of a clock entry.
            this.state.digits = (this.state.digits + ev.key).slice(-4);
            return;
        }
        if (ev.key === "Backspace") {
            ev.preventDefault();
            if (this.state.digits) {
                this.state.digits = this.state.digits.slice(0, -1);
            } else {
                this.state.digits = "";
            }
            return;
        }
        if (ev.key === "Enter") {
            this.commit();
        }
        // Tab / arrows / Escape fall through to the browser untouched.
    }

    onPaste(ev) {
        // Typing is fully intercepted above, so paste is the only other
        // way characters can arrive. Take its digits and nothing else.
        ev.preventDefault();
        const text = (ev.clipboardData || window.clipboardData).getData("text");
        this.state.digits = String(text || "").replace(/\D/g, "").slice(-4);
    }

    commit() {
        if (this.state.digits === null || this.state.digits === "") {
            // Focused and left without typing - leave the value alone.
            this.state.digits = null;
            return;
        }
        const value = hhmmToFloat(maskDigits(this.state.digits));
        this.state.digits = null;
        if (value !== this.props.record.data[this.props.name]) {
            this.props.record.update({ [this.props.name]: value });
        }
    }

    onBlur() {
        this.commit();
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
