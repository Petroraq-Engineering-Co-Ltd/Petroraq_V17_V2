/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class EmployeeTaskDashboard extends Component {
    static template = "pr_employee_task_management.TaskDashboard";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: {
                counts: {},
                states: [],
                departments: [],
                employees: [],
                months: [],
            },
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "employee.task.list",
            "get_dashboard_data",
            []
        );
        this.state.loading = false;
    }

    openTasks(domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Employee Task Lists",
            res_model: "employee.task.list",
            views: [[false, "tree"], [false, "kanban"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    get maxStateCount() {
        return Math.max(...this.state.data.states.map((item) => item.count), 1);
    }

    get maxEmployeeCount() {
        return Math.max(...this.state.data.employees.map((item) => item.count), 1);
    }

    get maxMonthCount() {
        return Math.max(...this.state.data.months.map((item) => item.count), 1);
    }
}

registry.category("actions").add(
    "employee_task_management.dashboard",
    EmployeeTaskDashboard
);
