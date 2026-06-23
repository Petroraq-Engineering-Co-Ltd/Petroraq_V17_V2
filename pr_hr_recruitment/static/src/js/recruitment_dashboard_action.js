/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class RecruitmentDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            data: {},
            loading: true,
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        this.state.data = await this.orm.call("hr.applicant", "get_recruitment_dashboard_data", []);
        this.state.loading = false;
    }

    openRecords(model, domain = [], name = "Records", context = {}) {
        if (!model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain,
            context,
            target: "current",
        });
    }

    openApplicant(applicantId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Applicant",
            res_model: "hr.applicant",
            views: [[false, "form"]],
            res_id: applicantId,
            target: "current",
        });
    }

    openStage(stageId, stageName) {
        this.openRecords("hr.applicant", [["stage_id", "=", stageId]], stageName);
    }

    openJob(jobId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Job Position",
            res_model: "hr.job",
            views: [[false, "form"]],
            res_id: jobId,
            target: "current",
        });
    }
}

RecruitmentDashboardAction.template = "pr_hr_recruitment.RecruitmentDashboardAction";

registry.category("actions").add("pr_hr_recruitment.recruitment_dashboard", RecruitmentDashboardAction);
