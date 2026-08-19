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
        // ONLY the segment currently being typed is held here, and only
        // as a display buffer. The record itself is the single source of
        // truth for both halves.
        //
        // The previous version kept BOTH halves in component state and
        // wrote them on blur. Anything that interrupted between the two
        // boxes - the auto-advance blur, an Odoo list re-render, a
        // remount - threw away whichever half had not been written yet,
        // which is why hours kept vanishing while minutes survived.
        // Writing on every keystroke means there is never an unsaved
        // half to lose.
        this.state = useState({ editing: null, buffer: "" });
        this.hoursRef = useRef("hoursInput");
        this.minutesRef = useRef("minutesInput");
    }

    /** Both halves as they stand in the record, e.g. ["01", "30"]. */
    get _stored() {
        return floatToHHMM(this.props.record.data[this.props.name]).split(":");
    }

    get hoursText() {
        return this.state.editing === "hours"
            ? this.state.buffer : this._stored[0];
    }

    get minutesText() {
        return this.state.editing === "minutes"
            ? this.state.buffer : this._stored[1];
    }

    // ------------------------------------------------------------------
    // Editing - every keystroke is persisted immediately
    // ------------------------------------------------------------------
    onSegmentFocus(ev, segment) {
        // Start empty so the first digit REPLACES rather than appends.
        this.state.editing = segment;
        this.state.buffer = "";
        ev.target.select();
    }

    onSegmentBlur() {
        // Nothing to commit - it is already saved. Just stop showing the
        // buffer so the box falls back to the record's value.
        this.state.editing = null;
        this.state.buffer = "";
    }

    _write(segment, text) {
        // Read the OTHER half fresh from the record every time, so the
        // two can never disagree and neither can go stale.
        const stored = this._stored;
        const hours = segment === "hours" ? text : stored[0];
        const minutes = segment === "minutes" ? text : stored[1];
        const value = hhmmToFloat(hours, minutes);
        if (value !== this.props.record.data[this.props.name]) {
            this.props.record.update({ [this.props.name]: value });
        }
    }

    _handleKey(ev, segment, otherRef) {
        if (ev.key >= "0" && ev.key <= "9") {
            ev.preventDefault();
            const current = this.state.editing === segment
                ? this.state.buffer : "";
            const text = (current + ev.key).slice(-2);
            this.state.editing = segment;
            this.state.buffer = text;
            this._write(segment, text);
            if (segment === "hours" && text.length === 2 && otherRef.el) {
                // Full - hop to minutes so 0,7,3,0 types straight through
                // as 07:30. Safe now: the hours are already saved.
                otherRef.el.focus();
                otherRef.el.select();
            }
            return;
        }
        if (ev.key === "Backspace") {
            ev.preventDefault();
            const current = this.state.editing === segment
                ? this.state.buffer : this._stored[segment === "hours" ? 0 : 1];
            const text = current.slice(0, -1);
            this.state.editing = segment;
            this.state.buffer = text;
            this._write(segment, text);
            return;
        }
        // Tab / arrows / Enter / Escape fall through to the browser.
    }

    onHoursKeydown(ev) {
        this._handleKey(ev, "hours", this.minutesRef);
    }

    onMinutesKeydown(ev) {
        this._handleKey(ev, "minutes", this.hoursRef);
    }

    onPaste(ev, segment) {
        ev.preventDefault();
        const text = (ev.clipboardData || window.clipboardData).getData("text");
        const digits = String(text || "").replace(/\D/g, "");
        if (!digits) {
            return;
        }
        if (segment === "hours" && digits.length > 2) {
            // Pasting "0730" into hours fills both halves at once.
            const padded = digits.slice(-4).padStart(4, "0");
            this.state.editing = null;
            this.state.buffer = "";
            const value = hhmmToFloat(padded.slice(0, 2), padded.slice(2));
            this.props.record.update({ [this.props.name]: value });
            return;
        }
        const trimmed = digits.slice(-2);
        this.state.editing = segment;
        this.state.buffer = trimmed;
        this._write(segment, trimmed);
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
