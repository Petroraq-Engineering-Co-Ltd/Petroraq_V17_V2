/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AttendanceManagementDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: {},
            loading: true,
            selectedDate: "",
            departmentId: 0,
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.selectedDate = this.clampDateString(this.state.selectedDate || this.getLocalDateString());
        const data = await this.orm.call(
            "de.hr.attendance.management.dashboard",
            "get_dashboard_data",
            [this.state.selectedDate || false, this.state.departmentId || false]
        );
        this.state.data = data;
        this.state.selectedDate = data.selected_date || this.state.selectedDate;
        this.state.departmentId = Number(data.department_id || 0);
        this.state.loading = false;
    }

    async onDateChange(ev) {
        this.state.selectedDate = this.clampDateString(ev.target.value || this.getLocalDateString());
        await this.loadDashboardData();
    }

    async onDepartmentChange(ev) {
        this.state.departmentId = Number(ev.target.value || 0);
        await this.loadDashboardData();
    }

    isDepartmentSelected(departmentId) {
        return Number(this.state.departmentId || 0) === Number(departmentId || 0);
    }

    getLocalDateString(date = new Date()) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    addDaysToDateString(dateString, days) {
        const [year, month, day] = String(dateString || this.getLocalDateString())
            .split("-")
            .map((part) => Number(part));
        const date = new Date(year, month - 1, day);
        date.setDate(date.getDate() + days);
        return this.getLocalDateString(date);
    }

    clampDateString(dateString) {
        const today = this.getLocalDateString();
        return String(dateString || today) > today ? today : dateString;
    }

    isNextDayDisabled() {
        return String(this.state.selectedDate || this.getLocalDateString()) >= this.getLocalDateString();
    }

    async moveDay(delta) {
        if (delta > 0 && this.isNextDayDisabled()) {
            return;
        }
        this.state.selectedDate = this.clampDateString(this.addDaysToDateString(this.state.selectedDate, delta));
        await this.loadDashboardData();
    }

    async setToday() {
        this.state.selectedDate = this.getLocalDateString();
        await this.loadDashboardData();
    }

    openRecords(model, ids = [], name = "Records") {
        if (!model || !ids.length) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", ids]],
            target: "current",
        });
    }

    openEmployee(employeeId, name = "Employee") {
        if (!employeeId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "hr.employee",
            views: [[false, "form"]],
            res_id: employeeId,
            target: "current",
        });
    }

    openTimelineRow(row) {
        if ((row.attendance_ids || []).length) {
            this.openRecords("hr.attendance", row.attendance_ids, `${row.employee_name} Attendances`);
        } else if ((row.leave_ids || []).length) {
            this.openRecords("hr.leave", row.leave_ids, `${row.employee_name} Leaves`);
        } else {
            this.openEmployee(row.employee_id, row.employee_name);
        }
    }

    formatNumber(value, digits = 0) {
        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(Number(value || 0));
    }

    formatHours(value) {
        return this.formatDuration(value);
    }

    formatDuration(value) {
        const totalMinutes = Math.round(Number(value || 0) * 60);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        const parts = [];
        if (hours) {
            parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
        }
        if (minutes || !parts.length) {
            parts.push(`${minutes} min${minutes === 1 ? "" : "s"}`);
        }
        return parts.join(" ");
    }

    formatDuration(value) {
        const totalMinutes = Math.round(Number(value || 0) * 60);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        const parts = [];
        if (hours) {
            parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
        }
        if (minutes || !parts.length) {
            parts.push(`${minutes} min${minutes === 1 ? "" : "s"}`);
        }
        return parts.join(" ");
    }

    formatPercent(value) {
        return `${Math.round(Number(value || 0))}%`;
    }

    clampPercent(value) {
        return Math.max(0, Math.min(100, Number(value || 0)));
    }

    kpiToneClass(tone) {
        return `pr-att-mgmt-kpi pr-tone-${tone || "neutral"}`;
    }

    statusPillClass(status) {
        return `pr-att-mgmt-status pr-status-${status || "present"}`;
    }

    pipeSegmentClass(segment) {
        return `pr-att-mgmt-segment pr-status-${segment.status || "present"}`;
    }

    pipeSegmentStyle(segment) {
        const left = this.clampPercent(segment.start_percent);
        const width = Math.max(1, Math.min(100 - left, Number(segment.width_percent || 0)));
        return `left:${left}%; width:${width}%;`;
    }

    trendStackStyle(day, key) {
        const total = Number(day.total || 0) || 1;
        const value = Number(day[key] || 0);
        return `height:${this.clampPercent((value / total) * 100)}%;`;
    }

    departmentBarStyle(department, key) {
        const total = Number(department.total || 0) || 1;
        const value = Number(department[key] || 0);
        return `width:${this.clampPercent((value / total) * 100)}%;`;
    }

    get summaryCards() {
        const summary = this.state.data.summary || {};
        return [
            {
                key: "coverage",
                label: "Overall Attendance",
                value: this.formatPercent(summary.coverage || 0),
                sub: `${this.formatNumber(summary.with_punch || 0)} of ${this.formatNumber(summary.scheduled || 0)} Employee`,
                icon: "fa-check-circle",
                tone: "success",
            },
            {
                key: "absent",
                label: "Absent Today",
                value: this.formatNumber(summary.absent || 0),
                sub: `${this.formatNumber(summary.on_leave || 0)} on approved leave`,
                icon: "fa-user-times",
                tone: "danger",
            },
            {
                key: "exceptions",
                label: "Exceptions",
                value: this.formatNumber(summary.issues || 0),
                sub: `${this.formatNumber(summary.shortage || 0)} shortage, ${this.formatNumber(summary.missing_checkout || 0)} missing checkout`,
                icon: "fa-exclamation-triangle",
                tone: "warning",
            },
            {
                key: "hours",
                label: "Worked Hours",
                value: this.formatHours(summary.worked_hours || 0),
                sub: `${this.formatNumber(summary.total || 0)} active employees`,
                icon: "fa-clock-o",
                tone: "info",
            },
        ];
    }
}

AttendanceManagementDashboard.template = "de_hr_workspace_attendance.AttendanceManagementDashboard";

registry.category("actions").add(
    "de_hr_workspace_attendance.attendance_management_dashboard",
    AttendanceManagementDashboard
);
