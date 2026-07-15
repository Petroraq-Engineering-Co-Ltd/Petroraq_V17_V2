from odoo import _, api, models
from odoo.tools.safe_eval import safe_eval
from odoo.osv import expression


class HrApprovalDashboardService(models.AbstractModel):
    _name = "de.hr.approval.dashboard.service"
    _description = "HR Approval Dashboard Service"

    APPROVAL_SECTIONS = {
        "hr": {
            "name": _("HR"),
            "icon": "fa-users",
            "tone": "info",
            "sequence": 10,
        },
        "accounts": {
            "name": _("Accounts"),
            "icon": "fa-money",
            "tone": "danger",
            "sequence": 20,
        },
        "purchase": {
            "name": _("Purchase"),
            "icon": "fa-shopping-cart",
            "tone": "primary",
            "sequence": 30,
        },
        "sales": {
            "name": _("Sales"),
            "icon": "fa-line-chart",
            "tone": "success",
            "sequence": 40,
        },
        "other": {
            "name": _("Other"),
            "icon": "fa-check-square-o",
            "tone": "primary",
            "sequence": 99,
        },
    }

    @api.model
    def _get_visible_approval_menus(self):
        parent = self.env.ref(
            "de_hr_workspace.menu_my_employee_approvals",
            raise_if_not_found=False,
        )
        dashboard_menu = self.env.ref(
            "de_hr_workspace_attendance.menu_hr_approval_dashboard",
            raise_if_not_found=False,
        )
        if not parent:
            return self.env["ir.ui.menu"]

        menus = self.env["ir.ui.menu"].sudo().search([
            ("id", "child_of", parent.id),
            ("id", "!=", parent.id),
        ], order="sequence, id")

        filter_visible = getattr(self.env["ir.ui.menu"], "_filter_visible_menus", None)
        if filter_visible:
            menus = menus._filter_visible_menus()
        else:
            user_groups = self.env.user.groups_id
            menus = menus.filtered(
                lambda m: not m.groups_id or bool(m.groups_id & user_groups)
            )

        return menus.filtered(
            lambda m: bool(m.action)
            and (not dashboard_menu or m.id != dashboard_menu.id)
            and not (
                m.action
                and getattr(m.action, "_name", "") == "ir.actions.client"
                and getattr(m.action, "tag", "") == "de_hr_workspace_attendance.approval_dashboard"
            )
        )

    @api.model
    def _domain_from_action(self, action):
        domain_str = action.domain or "[]"
        eval_context = {
            "uid": self.env.uid,
            "user": self.env.user,
            "context": dict(self.env.context),
        }
        try:
            domain = safe_eval(domain_str, eval_context)
            return domain if isinstance(domain, (list, tuple)) else []
        except Exception:
            return []

    @api.model
    def _context_from_action(self, action):
        context_str = action.context or "{}"
        eval_context = {
            "uid": self.env.uid,
            "user": self.env.user,
            "context": dict(self.env.context),
        }
        try:
            context = safe_eval(context_str, eval_context)
            return context if isinstance(context, dict) else {}
        except Exception:
            return {}

    @api.model
    def _domain_for_menu_action(self, menu, action):
        domain = self._domain_from_action(action)
        return self._override_domain_for_menu(menu, action, domain)

    @api.model
    def _shortage_pending_domain(self):
        user = self.env.user
        role_domains = [
            [("employee_manager_id.user_id", "=", self.env.uid), ("state", "=", "draft")],
        ]
        if user.has_group("hr_attendance.group_hr_attendance_manager"):
            role_domains.append([
                ("state", "=", "hr_supervisor"),
                ("hr_manager_ids", "in", self.env.uid),
            ])
        if user.has_group("pr_hr_attendance.custom_group_hr_attendance_supervisor"):
            role_domains.append([
                ("state", "=", "manager_approve"),
                ("hr_supervisor_ids", "in", self.env.uid),
            ])
        return expression.OR(role_domains)

    @api.model
    def _leave_pending_domain(self):
        return [
            ("state", "in", ["confirm", "validate1"]),
            "|",
            ("employee_id.parent_id.user_id", "=", self.env.uid),
            ("holiday_status_id.responsible_id", "=", self.env.uid),
        ]

    @api.model
    def _leave_request_pending_domain(self):
        user = self.env.user
        role_domains = [
            [("employee_manager_id.user_id", "=", self.env.uid), ("state", "=", "draft")],
            [("state", "=", "cancel_request")],
        ]

        if user.has_group("hr_holidays.group_hr_holidays_manager"):
            role_domains.append([
                ("state", "=", "hr_supervisor"),
                ("hr_manager_ids", "in", self.env.uid),
            ])
        if user.has_group("pr_hr_holidays.custom_group_hr_holidays_supervisor"):
            role_domains.append([
                ("state", "=", "manager_approve"),
                ("hr_supervisor_ids", "in", self.env.uid),
            ])

        return expression.OR(role_domains)

    @api.model
    def _work_order_pending_domain(self):
        states = []
        user = self.env.user
        if user.has_group("pr_work_order.custom_group_work_order_operations"):
            states.append("ops_approval")
        if user.has_group("pr_work_order.custom_group_work_order_accounts"):
            states.append("acc_approval")
        if user.has_group("pr_work_order.custom_group_work_order_management"):
            states.append("final_approval")
        return [("state", "in", states)] if states else [("id", "=", False)]

    @api.model
    def _budget_requisition_pending_domain(self):
        user = self.env.user
        role_domains = [
            [
                ("state", "=", "department_approval"),
                ("department_manager_user_id", "=", self.env.uid),
            ],
        ]

        if user.has_group("account.group_account_manager") or user.has_group("account.group_account_user"):
            role_domains.append([("state", "=", "accounts_approval")])
        if user.has_group("pr_custom_purchase.managing_director"):
            role_domains.append([("state", "=", "md_approval")])
        if (
            user.has_group("pr_custom_purchase.procurement_admin")
            or user.has_group("purchase.group_purchase_manager")
        ):
            role_domains.append([
                ("state", "in", ["department_approval", "accounts_approval", "md_approval"]),
            ])

        return expression.OR(role_domains) if role_domains else [("id", "=", False)]

    @api.model
    def _is_work_order_approval_menu(self, menu, action):
        work_order_menu = self.env.ref(
            "de_hr_workspace_sale.work_order_ops_approvals_view_menu",
            raise_if_not_found=False,
        )
        work_order_action = self.env.ref(
            "de_hr_workspace_sale.pr_sale_work_order_approvals_server_action",
            raise_if_not_found=False,
        )
        return bool(
            (work_order_menu and menu.id == work_order_menu.id)
            or (work_order_action and action.id == work_order_action.id)
        )

    @api.model
    def _account_payment_approval_domain(self):
        user = self.env.user
        if user.has_group("pr_account.custom_group_accounting_manager"):
            return [("state", "=", "finance_approve")]
        if (
            user.has_group("account.group_account_manager")
            or user.has_group("pr_account.custom_group_account_supervisor")
        ):
            return [("state", "=", "submit")]
        if user.has_group("base.group_system"):
            return [("state", "in", ["submit", "finance_approve"])]
        return [("id", "=", 0)]

    @api.model
    def _account_payment_approval_model(self, menu, action):
        refs = (
            (
                "de_hr_workspace_account.pr_account_bank_payment_approvals_view_menu",
                "de_hr_workspace_account.pr_account_bank_payment_approvals_workspace_action",
                "pr.account.bank.payment",
            ),
            (
                "de_hr_workspace_account.pr_account_cash_payment_approvals_view_menu",
                "de_hr_workspace_account.pr_account_cash_payment_approvals_workspace_action",
                "pr.account.cash.payment",
            ),
        )
        for menu_xmlid, action_xmlid, model_name in refs:
            payment_menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            payment_action = self.env.ref(action_xmlid, raise_if_not_found=False)
            if (payment_menu and menu.id == payment_menu.id) or (
                payment_action and action.id == payment_action.id
            ):
                return model_name
        return False

    @api.model
    def _override_domain_for_menu(self, menu, action, domain):
        menu_name = (menu.name or "").lower()
        if action.res_model == "pr.hr.shortage.request" or "shortage" in menu_name:
            return self._shortage_pending_domain()
        if action.res_model == "pr.hr.leave.request":
            return self._leave_request_pending_domain()
        if action.res_model == "hr.leave" or "leave" in menu_name:
            return self._leave_pending_domain()
        if action.res_model == "pr.budget.requisition":
            return self._budget_requisition_pending_domain()
        return domain

    @api.model
    def _count_for_action(self, menu, action):
        try:
            if self._is_work_order_approval_menu(menu, action):
                if "pr.work.order" not in self.env:
                    return 0
                return self.env["pr.work.order"].search_count(self._work_order_pending_domain())
            account_payment_model = self._account_payment_approval_model(menu, action)
            if account_payment_model:
                if account_payment_model not in self.env:
                    return 0
                return self.env[account_payment_model].search_count(
                    self._account_payment_approval_domain()
                )
            if action._name != "ir.actions.act_window" or not action.res_model:
                return 0
            return self.env[action.res_model].search_count(self._domain_for_menu_action(menu, action))
        except Exception:
            return 0

    @api.model
    def _style_for_menu(self, menu_name):
        name = (menu_name or "").lower()
        if "leave" in name:
            return "fa-calendar-check-o", "success"
        if "shortage" in name:
            return "fa-clock-o", "warning"
        if "account" in name:
            return "fa-money", "info"
        if "pay" in name:
            return "fa-file-text-o", "danger"
        if "sale" in name:
            return "fa-line-chart", "primary"
        if "recruit" in name:
            return "fa-users", "warning"
        if "purchase" in name:
            return "fa-shopping-cart", "primary"
        if "budget" in name:
            return "fa-pie-chart", "info"
        if "hr" in name:
            return "fa-id-badge", "info"
        return "fa-check-square-o", "primary"

    @api.model
    def _menu_path(self, menu):
        names = []
        while menu:
            if menu.name:
                names.append(menu.name)
            menu = menu.parent_id
        return " / ".join(reversed(names)).lower()

    @api.model
    def _section_key_for_menu(self, menu, action):
        name = (menu.name or "").lower()
        path = self._menu_path(menu)
        model = (action.res_model or "").lower() if action and action._name == "ir.actions.act_window" else ""
        text = " ".join([name, path, model])

        if any(token in text for token in ("bank", "cash", "vendor payment", "payment", "account", "finance", "bpv", "cpv")):
            return "accounts"
        if any(token in text for token in ("purchase", "rfq", "po ", "quotation comparison", "budget", "requisition")):
            return "purchase"
        if any(token in text for token in ("sale", "estimation", "quotation", "work order")):
            return "sales"
        if model == "sign.request" or any(token in text for token in ("sign", "signature")):
            return "hr"
        if any(token in text for token in ("payroll", "payslip", "salary", "overtime")):
            return "hr"
        if any(token in text for token in (
            "hr",
            "employee",
            "attendance",
            "leave",
            "shortage",
            "recruit",
            "onboarding",
            "offboarding",
            "accommodation",
            "medical",
            "iqama",
            "exit",
            "reimbursement",
        )):
            return "hr"
        return "other"

    @api.model
    def _tile_record_payload(self, menu, action):
        if self._is_work_order_approval_menu(menu, action):
            model_name = "pr.work.order"
            if model_name not in self.env:
                return False
            domain = self._work_order_pending_domain()
            records = self.env[model_name].search(domain)
            return {
                "res_model": model_name,
                "view_mode": "list,form",
                "domain": [("id", "in", records.ids)],
                "context": {},
                "ids": set(records.ids),
            }

        account_payment_model = self._account_payment_approval_model(menu, action)
        if account_payment_model:
            if account_payment_model not in self.env:
                return False
            domain = self._account_payment_approval_domain()
            records = self.env[account_payment_model].search(domain)
            return {
                "res_model": account_payment_model,
                "view_mode": "list,form",
                "domain": [("id", "in", records.ids)],
                "context": {},
                "ids": set(records.ids),
            }

        if action._name != "ir.actions.act_window" or not action.res_model:
            return False
        if action.res_model not in self.env:
            return False

        domain = self._domain_for_menu_action(menu, action)
        try:
            records = self.env[action.res_model].search(domain)
        except Exception:
            return False
        return {
            "res_model": action.res_model,
            "view_mode": action.view_mode or "list,form",
            "domain": [("id", "in", records.ids)],
            "context": self._context_from_action(action),
            "ids": set(records.ids),
        }

    @api.model
    def _dedupe_key_for_tile(self, section_key, menu, action, payload):
        normalized_name = " ".join((menu.name or _("Approval")).lower().split())
        if payload and payload.get("res_model"):
            return "%s|%s|%s" % (section_key, payload["res_model"], normalized_name)
        return "%s|action|%s|%s" % (section_key, action.id, normalized_name)

    @api.model
    def _make_tile(self, section_key, menu, action):
        payload = self._tile_record_payload(menu, action)
        icon, tone = self._style_for_menu(menu.name)
        tile = {
            "key": self._dedupe_key_for_tile(section_key, menu, action, payload),
            "name": menu.name or _("Approval"),
            "count": len(payload["ids"]) if payload else self._count_for_action(menu, action),
            "icon": icon,
            "tone": tone,
            "action_id": action.id,
        }
        if payload:
            tile.update({
                "res_model": payload["res_model"],
                "view_mode": payload["view_mode"],
                "domain": payload["domain"],
                "context": payload["context"],
                "_ids": payload["ids"],
            })
        return tile

    @api.model
    def _merge_tile(self, existing, tile):
        existing_ids = existing.get("_ids")
        tile_ids = tile.get("_ids")
        if existing_ids is not None and tile_ids is not None:
            merged_ids = existing_ids | tile_ids
            existing["_ids"] = merged_ids
            existing["count"] = len(merged_ids)
            existing["domain"] = [("id", "in", sorted(merged_ids))]
            return existing

        existing["count"] = max(existing.get("count", 0), tile.get("count", 0))
        return existing

    @api.model
    def get_sections(self):
        grouped_tiles = {}
        for menu in self._get_visible_approval_menus():
            action = menu.sudo().action
            section_key = self._section_key_for_menu(menu, action)
            tile = self._make_tile(section_key, menu, action)
            section_tiles = grouped_tiles.setdefault(section_key, {})
            if tile["key"] in section_tiles:
                self._merge_tile(section_tiles[tile["key"]], tile)
            else:
                section_tiles[tile["key"]] = tile

        sections = []
        for section_key, tiles_by_key in grouped_tiles.items():
            definition = self.APPROVAL_SECTIONS.get(section_key, self.APPROVAL_SECTIONS["other"])
            tiles = list(tiles_by_key.values())
            tiles.sort(key=lambda item: (0 if item.get("count", 0) else 1, item["name"]))
            for tile in tiles:
                tile.pop("_ids", None)
            sections.append({
                "key": section_key,
                "name": definition["name"],
                "icon": definition["icon"],
                "tone": definition["tone"],
                "sequence": definition["sequence"],
                "count": sum(tile.get("count", 0) for tile in tiles),
                "tiles": tiles,
            })

        sections.sort(key=lambda section: (section["sequence"], section["name"]))
        return sections

    @api.model
    def get_tiles(self):
        return [
            tile
            for section in self.get_sections()
            for tile in section.get("tiles", [])
        ]
