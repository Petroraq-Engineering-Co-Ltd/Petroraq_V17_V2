/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

class ApprovalDashboard extends Component {
    static template = "de_hr_workspace_attendance.ApprovalDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            sections: [],
            selectedSectionKey: "",
            loading: true,
            userName: session.user_name || session.name || session.username || "",
        });

        onWillStart(async () => {
            await this.loadTiles();
        });
    }

    async loadTiles() {
        this.state.loading = true;
        const sections = await this.orm.call("de.hr.approval.dashboard.service", "get_sections", []);
        this.state.sections = sections;
        if (
            this.state.selectedSectionKey &&
            !sections.some((section) => section.key === this.state.selectedSectionKey)
        ) {
            this.state.selectedSectionKey = "";
        }
        this.state.loading = false;
    }

    openSection(ev) {
        this.state.selectedSectionKey = ev.currentTarget.dataset.sectionKey || "";
    }

    backToSections() {
        this.state.selectedSectionKey = "";
    }

    openTile(ev) {
        const key = ev.currentTarget.dataset.tileKey || "";
        const tile = this.allTiles.find((item) => item.key === key);
        if (tile && tile.res_model) {
            const viewModes = (tile.view_mode || "list,form")
                .split(",")
                .map((mode) => mode.trim())
                .filter(Boolean)
                .map((mode) => (mode === "tree" ? "list" : mode));
            this.action.doAction({
                type: "ir.actions.act_window",
                name: tile.name,
                res_model: tile.res_model,
                views: viewModes.map((mode) => [false, mode]),
                domain: tile.domain || [],
                context: tile.context || {},
            });
            return;
        }

        const actionId = Number(ev.currentTarget.dataset.actionId || 0);
        if (actionId) {
            this.action.doAction(actionId);
        }
    }

    async refresh() {
        await this.loadTiles();
    }


    get salutation() {
        const hour = new Date().getHours();
        if (hour < 12) {
            return "Good Morning";
        }
        if (hour < 17) {
            return "Good Afternoon";
        }
        return "Good Evening";
    }

    get greetingText() {
        const name = (this.state.userName || "").trim();
        return name ? `${this.salutation}, Mr. ${name}` : this.salutation;
    }

    get selectedSection() {
        return this.state.sections.find((section) => section.key === this.state.selectedSectionKey);
    }

    get selectedTiles() {
        return this.selectedSection ? this.selectedSection.tiles || [] : [];
    }

    get allTiles() {
        return this.state.sections.flatMap((section) => section.tiles || []);
    }

    get totalPendingCount() {
        return this.state.sections.reduce((total, section) => total + (section.count || 0), 0);
    }

    tileClass(tile) {
        const hasPending = (tile.count || 0) > 0 ? "de-dashboard-tile-pending" : "";
        return `de-dashboard-tile de-dashboard-tile-${tile.tone || "primary"} ${hasPending}`.trim();
    }

    sectionClass(section) {
        const hasPending = (section.count || 0) > 0 ? "de-dashboard-section-pending" : "";
        return `de-dashboard-section-card de-dashboard-section-${section.tone || "primary"} ${hasPending}`.trim();
    }

    iconBoxClass(tile) {
        return `de-dashboard-icon-box de-tone-${tile.tone || "primary"}`;
    }
}

registry.category("actions").add("de_hr_workspace_attendance.approval_dashboard", ApprovalDashboard);
