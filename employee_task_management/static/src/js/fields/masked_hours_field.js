/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, useRef } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * HH : MM hours entry, as two independent segments.
 *
 * Why this exists instead of Odoo's float_time: float_time accepts BOTH
 * "1:30" and "1.5". Someone typing "1.50" means one hour fifty minutes,
 * but float_time reads 1.5 and stores 1:30 - a silent, confusing
 * difference on the field the whole capacity check depends on. Only
 * digits ever reach this widget, so a decimal point cannot be typed.
 *
 * Why TWO inputs rather than one masked box: the first version filled a
 * single box right-to-left, so selecting the hours and typing pushed the
 * digits into the minutes instead - reported as confusing, and it was.
 * Two segments mean the box you click is the box you type into, which
 * needs no explaining. Hours auto-advance to minutes once full, and
 * Backspace at the start of minutes steps back into hours, so fast
 * left-to-right typing still works without touching the mouse.
 *
 * Storage is unchanged - still a plain float, so every existing sum,
 * total and capacity constraint keeps working.
 */

const MAX_MINUTES = 59;

export function floatToHHMM(value) {
    const totalMinutes = Math.round((value || 0) * 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function hhmmToFloat(hoursText, minutesText) {
    const hours = parseInt(hoursText, 10) || 0;
    let minutes = parseInt(minutesText, 10) || 0;
    if (minutes > MAX_MINUTES) {
        minutes = MAX_MINUTES;
    }
    return hours + minutes / 60;
}

export class MaskedHoursField extends Component {
    static template = "employee_task_management.MaskedHoursField";
    static props = { ...standardFieldProps };

    setup() {
        // null = not being edited, so the segment shows the record's
        // value. A string = exactly what the user has typed in that
        // segment, kept raw so clamping never feeds back into the next
        // keystroke.
        this.state = useState({ hours: null, minutes: null });
        this.hoursRef = useRef("hoursInput");
        this.minutesRef = useRef("minutesInput");
    }

    get _stored() {
        return floatToHHMM(this.props.record.data[this.props.name]).split(":");
    }

    get hoursText() {
        return this.state.hours === null ? this._stored[0] : this.state.hours;
    }

    get minutesText() {
        return this.state.minutes === null ? this._stored[1] : this.state.minutes;
    }

    // ------------------------------------------------------------------
    // Editing
    // ------------------------------------------------------------------
    onSegmentFocus(ev, segment) {
        // Start the segment empty so the first digit REPLACES what was
        // there. Selecting the text as well means a mouse user sees the
        // old value highlighted, which matches the usual expectation.
        this.state[segment] = "";
        ev.target.select();
    }

    _push(segment, digit, maxLength) {
        const current = this.state[segment] === null ? "" : this.state[segment];
        this.state[segment] = (current + digit).slice(-maxLength);
        return this.state[segment];
    }

    onHoursKeydown(ev) {
        if (ev.key >= "0" && ev.key <= "9") {
            ev.preventDefault();
            const value = this._push("hours", ev.key, 2);
            if (value.length === 2 && this.minutesRef.el) {
                // Full - hop to minutes so 0,7,3,0 types straight
                // through as 07:30 without reaching for the mouse.
                this.minutesRef.el.focus();
                this.minutesRef.el.select();
            }
            return;
        }
        this._handleCommonKeys(ev, "hours");
    }

    onMinutesKeydown(ev) {
        if (ev.key >= "0" && ev.key <= "9") {
            ev.preventDefault();
            this._push("minutes", ev.key, 2);
            return;
        }
        if (ev.key === "Backspace" && !this.minutesText.replace(/0/g, "")
                && this.hoursRef.el) {
            // Nothing meaningful left in minutes - step back into hours
            // rather than sitting on an empty segment.
            ev.preventDefault();
            this.state.minutes = "";
            this.hoursRef.el.focus();
            this.hoursRef.el.select();
            return;
        }
        this._handleCommonKeys(ev, "minutes");
    }

    _handleCommonKeys(ev, segment) {
        if (ev.key === "Backspace") {
            ev.preventDefault();
            const current = this.state[segment] === null
                ? "" : this.state[segment];
            this.state[segment] = current.slice(0, -1);
            return;
        }
        if (ev.key === "Enter") {
            this.commit();
        }
        // Tab / arrows / Escape fall through to the browser untouched.
    }

    onPaste(ev, segment) {
        ev.preventDefault();
        const text = (ev.clipboardData || window.clipboardData).getData("text");
        const digits = String(text || "").replace(/\D/g, "");
        if (!digits) {
            return;
        }
        if (segment === "hours" && digits.length > 2) {
            // Pasting "0730" into the hours segment fills both.
            const padded = digits.slice(-4).padStart(4, "0");
            this.state.hours = padded.slice(0, 2);
            this.state.minutes = padded.slice(2);
            return;
        }
        this.state[segment] = digits.slice(-2);
    }

    // ------------------------------------------------------------------
    // Commit
    // ------------------------------------------------------------------
    onBlur(ev) {
        // Moving between the two segments is not leaving the field, so
        // do not commit yet - relatedTarget is the segment being entered.
        const next = ev.relatedTarget;
        if (next && (next === this.hoursRef.el || next === this.minutesRef.el)) {
            return;
        }
        this.commit();
    }

    commit() {
        if (this.state.hours === null && this.state.minutes === null) {
            return;                       // focused and left without typing
        }
        const value = hhmmToFloat(this.hoursText, this.minutesText);
        this.state.hours = null;
        this.state.minutes = null;
        if (value !== this.props.record.data[this.props.name]) {
            this.props.record.update({ [this.props.name]: value });
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
