/** @odoo-module **/

import { registry } from "@web/core/registry";

const activityVisibilityService = {
    dependencies: ["orm"],

    async start(env, { orm }) {
        const result = await orm.call(
            "access.management",
            "get_global_activity_visibility",
            []
        );
        document.body.classList.toggle(
            "o_pr_hide_activities",
            Boolean(result.hide_activities)
        );
    },
};

registry.category("services").add(
    "pr_access_activity_visibility",
    activityVisibilityService
);
