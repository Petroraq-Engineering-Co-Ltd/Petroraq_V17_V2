/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

const SELECTED_SECTION_STORAGE_KEY = "de_hr_workspace_attendance.approval_dashboard.section";

class ApprovalDashboard extends Component {
    static template = "de_hr_workspace_attendance.ApprovalDashboard";
    static props = {"*": true};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            sections: [],
            selectedSectionKey: this.getStoredSectionKey(),
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
            !sections.some(
                (section) =>
                    section.key === this.state.selectedSectionKey &&
                    (section.tiles || []).length > 1
            )
        ) {
            this.state.selectedSectionKey = "";
            this.storeSectionKey("");
        }
        this.state.loading = false;
    }

    openSection(ev) {
        const sectionKey = ev.currentTarget.dataset.sectionKey || "";
        const section = this.state.sections.find((item) => item.key === sectionKey);
        // A section holding a single approval menu is shown as that menu
        // itself, so clicking it must open the list straight away instead
        // of drilling into a page with one card on it.
        const tiles = section && section.tiles ? section.tiles : [];
        if (tiles.length === 1) {
            this.openTileRecord(tiles[0]);
            return;
        }
        this.state.selectedSectionKey = sectionKey;
        this.storeSectionKey(sectionKey);
    }

    sectionDisplay(section) {
        const tiles = section.tiles || [];
        if (tiles.length === 1) {
            const tile = tiles[0];
            return {
                name: tile.name,
                icon: tile.icon,
                tone: tile.tone,
                count: section.count,
                hint: "Open approval list",
                direct: true,
            };
        }
        return {
            name: section.name,
            icon: section.icon,
            tone: section.tone,
            count: section.count,
            hint: `${tiles.length} approval menu${tiles.length === 1 ? "" : "s"}`,
            direct: false,
        };
    }

    backToSections() {
        this.state.selectedSectionKey = "";
        this.storeSectionKey("");
    }

    getStoredSectionKey() {
        try {
            return window.sessionStorage.getItem(SELECTED_SECTION_STORAGE_KEY) || "";
        } catch {
            return "";
        }
    }

    storeSectionKey(sectionKey) {
        try {
            if (sectionKey) {
                window.sessionStorage.setItem(SELECTED_SECTION_STORAGE_KEY, sectionKey);
            } else {
                window.sessionStorage.removeItem(SELECTED_SECTION_STORAGE_KEY);
            }
        } catch {
            // Storage can be unavailable in privacy-restricted browser contexts.
        }
    }

    openTile(ev) {
        const key = ev.currentTarget.dataset.tileKey || "";
        this.openTileRecord(this.allTiles.find((item) => item.key === key));
    }

    openTileRecord(tile) {
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

        const actionId = Number((tile && tile.action_id) || 0);
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
