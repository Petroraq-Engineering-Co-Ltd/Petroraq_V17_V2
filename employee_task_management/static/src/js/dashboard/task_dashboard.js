/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";

/**
 * Employee Task Management dashboard.
 *
 * A banner header, a row of clickable KPI cards driven by
 * employee.task.list.get_dashboard_data(), and a genuine embedded
 * list view of Task Lists underneath - so the dashboard IS a list
 * view by default, per client feedback, with the banner/KPI styling
 * layered on top of it.
 */
export class TaskDashboard extends Component {
    static template = "employee_task_management.TaskDashboard";
    static components = { View };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            counts: {
                total: 0,
                pending_approval: 0,
                in_progress: 0,
                completed: 0,
                delayed: 0,
                closed: 0,
            },
            loading: true,
            // Bumped by Refresh. Used as the t-key of the embedded list
            // view so the list is re-mounted and really re-reads the
            // records, instead of only refreshing the KPI numbers.
            reloadKey: 0,
        });

        this.cardDomains = {
            total: [],
            pending_approval: [["state", "=", "submitted_manager"]],
            in_progress: [["state", "in", ["in_progress", "returned_after_completion"]]],
            completed: [["state", "=", "completed"]],
            delayed: [["is_delayed", "=", true]],
            closed: [["state", "in", ["closed", "rejected"]]],
        };

        // The dashboard's embedded view is always List - that is the
        // "list view on the dashboard by default" requirement.
        // searchViewId: false removes the search bar. context:
        // {create: false} removes the "New" button - record creation
        // belongs on the Task Lists menu, not the dashboard.
        //
        // selectRecord is what makes a row clickable. The embedded View
        // has no form view of its own to switch to, so without this the
        // list controller has nowhere to send the click and the rows
        // look dead. Handing it an action opens the task list form with
        // a proper breadcrumb back to the dashboard.
        this.listViewProps = {
            resModel: "employee.task.list",
            type: "list",
            domain: [],
            context: { create: false },
            searchViewId: false,
            selectRecord: (resId) => this.openRecord(resId),
        };

        onWillStart(async () => {
            await this.loadCounts();
        });
    }

    // Kanban/Graph buttons navigate to the real, standard Task Lists
    // action in that view type - opening the genuine native view
    // instead of trying to embed it inside our custom dashboard. Uses
    // the same doAction() call already proven to work for the KPI
    // cards below, rather than the embedded View component's own
    // (unverified) multi-type/switcher behavior.
    openView(type) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Task Lists",
            res_model: "employee.task.list",
            views: [
                [false, type],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    // Open one task list from the embedded dashboard list.
    openRecord(resId) {
        if (!resId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Task List",
            res_model: "employee.task.list",
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async loadCounts() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "employee.task.list",
                "get_dashboard_data",
                []
            );
            Object.assign(this.state.counts, data);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefresh() {
        await this.loadCounts();
        // Re-mount the embedded list view so the rows are reloaded too.
        this.state.reloadKey++;
    }

    openCard(key) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Task Lists",
            res_model: "employee.task.list",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
            ],
            domain: this.cardDomains[key] || [],
            target: "current",
        });
    }
}

registry
    .category("actions")
    .add("employee_task_management.task_dashboard", TaskDashboard);
