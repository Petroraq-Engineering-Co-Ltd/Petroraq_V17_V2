/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HRReminderDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: {
                tiles: [],
                expiry_rows: [],
                task_rows: [],
                activity_rows: [],
            },
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "hr.compliance.expiry.reminder.log",
            "get_reminder_dashboard_data",
            []
        );
        this.state.loading = false;
    }

    openTile(tile) {
        if (!tile.model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: tile.title,
            res_model: tile.model,
            view_mode: "tree,form",
            views: [[false, "list"], [false, "form"]],
            domain: tile.domain || [],
            target: "current",
        });
    }

    openRecord(row) {
        if (!row.model || !row.res_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: row.record_name || row.task || row.summary,
            res_model: row.model,
            res_id: row.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

HRReminderDashboardAction.template = "qiwa_contract_ocr.HRReminderDashboardAction";

registry.category("actions").add("qiwa_contract_ocr.reminder_dashboard", HRReminderDashboardAction);
