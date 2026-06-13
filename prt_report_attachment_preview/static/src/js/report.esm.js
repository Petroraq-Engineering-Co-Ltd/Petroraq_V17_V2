/** @odoo-module **/

/** ********************************************************************************
 *
 *    Copyright (C) 2020 Cetmix OÜ
 *
 *    This program is free software: you can redistribute it and/or modify
 *    it under the terms of the GNU LESSER GENERAL PUBLIC LICENSE as
 *    published by the Free Software Foundation, either version 3 of the
 *    License, or (at your option) any later version.
 *
 *    This program is distributed in the hope that it will be useful,
 *    but WITHOUT ANY WARRANTY; without even the implied warranty of
 *    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *    GNU LESSER GENERAL PUBLIC LICENSE for more details.
 *
 *    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
 *    along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 **********************************************************************************/

import {WARNING_MESSAGE, WKHTMLTOPDF_MESSAGES, _getReportUrl} from "./tools.esm";
import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";

/* eslint-disable init-declarations */
let wkhtmltopdfStateProm;
registry
    .category("ir.actions.report handlers")
    .add("open_report_handler", async function (action, options, env) {
        if (action.type === "ir.actions.report" && action.report_type === "qweb-pdf") {
            // Check the state of wkhtmltopdf before proceeding
            if (!wkhtmltopdfStateProm) {
                wkhtmltopdfStateProm = env.services.rpc("/report/check_wkhtmltopdf");
            }
            const state = await wkhtmltopdfStateProm;
            if (state in WKHTMLTOPDF_MESSAGES) {
                env.services.notification.add(WKHTMLTOPDF_MESSAGES[state], {
                    sticky: true,
                    title: _t("Report"),
                });
            }
            if (state === "upgrade" || state === "ok") {
                // Trigger the download of the PDF report
                const url = _getReportUrl(action, "pdf", env);
                // AAB: this check should be done in get_file service directly,
                // should not be the concern of the caller (and that way, get_file
                // could return a deferred)
                if (!window.open(url)) {
                    env.services.notification.add(WARNING_MESSAGE, {
                        type: "warning",
                    });
                }
            }
            return Promise.resolve(true);
        }
        return Promise.resolve(false);
    });
