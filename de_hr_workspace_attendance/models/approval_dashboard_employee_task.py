# -*- coding: utf-8 -*-
"""Employee Task Management cards for the Approvals Dashboard.

Why this lives in its own file
------------------------------
`approval_dashboard.py` builds its cards by walking the menus under
`de_hr_workspace.menu_my_employee_approvals`. Employee Task Management
keeps its approval menu under its OWN root menu, so nothing of it is
ever discovered there - the workspace would show no task cards at all.

Rather than moving that menu (which would produce a single generic
"Employee Task Approvals" card lumping six very different actions
together), the cards are declared here explicitly - exactly the same
approach the base file already takes for the shortage-request card.

`employee_task_management` is NOT a dependency of this module. Every
entry point below is guarded, so if the module is not installed the
section simply does not appear.

Each card answers one question: "what is waiting for ME to act on right
now?" The domains therefore mirror the real permission checks in
`employee.task.list`:

  * `_check_approver_rights` - a Task Manager may only rule on lists
    where he is `manager_id`; an Administrator may rule on anything
    except his own list.
  * `_check_is_the_employee`  - accepting / requesting a modification /
    reworking a returned list is the employee's own act.

Record rules still apply on top, so a card can never surface a record
the user is not allowed to open.
"""

from odoo import _, api, models

TASK_MODEL = "employee.task.list"

GROUP_EMPLOYEE = "employee_task_management.group_task_employee"
GROUP_MANAGER = "employee_task_management.group_task_manager"
GROUP_ADMIN = "employee_task_management.group_task_admin"

# Change to "hr" to fold these cards into the existing HR section
# instead of giving them a section of their own.
TASK_SECTION_KEY = "employee_tasks"

TASK_SECTION = {
    "name": _("Employee Tasks"),
    "icon": "fa-tasks",
    "tone": "primary",
    # Between HR (10) and Accounts (20): task approvals are a daily
    # working tool, so they sit high on the dashboard.
    "sequence": 15,
}


class HrApprovalDashboardServiceTask(models.AbstractModel):
    _inherit = "de.hr.approval.dashboard.service"

    # ------------------------------------------------------------------
    # Scopes - who is allowed to act
    # ------------------------------------------------------------------
    @api.model
    def _employee_task_manager_scope(self):
        """Domain limiting task lists to the ones this user may approve.

        Returns None when the user is not an approver at all, which is
        the signal to skip every manager-side card.
        """
        user = self.env.user
        if user.has_group(GROUP_ADMIN):
            # An Administrator may act on anybody's list except his own -
            # nobody signs off their own work (_check_approver_rights).
            own_employees = self.env["hr.employee"].sudo().search([
                ("user_id", "=", self.env.uid),
            ])
            return [("employee_id", "not in", own_employees.ids)] if own_employees else []
        if user.has_group(GROUP_MANAGER):
            # A plain Task Manager is restricted to the lists where he is
            # the named immediate manager.
            return [("manager_id.user_id", "=", self.env.uid)]
        return None

    @api.model
    def _employee_task_employee_scope(self):
        """Domain limiting task lists to the ones this user owns."""
        return [("employee_id.user_id", "=", self.env.uid)]

    # ------------------------------------------------------------------
    # Card definitions
    # ------------------------------------------------------------------
    @api.model
    def _employee_task_card_specs(self):
        """Ordered list of (key, name, icon, tone, domain) card specs.

        Kept as data rather than code so adding or retiring a card is a
        one-line change.
        """
        specs = []
        manager_scope = self._employee_task_manager_scope()

        if manager_scope is not None:
            specs.extend([
                (
                    "to_approve",
                    _("Task Lists to Approve"),
                    "fa-check-square-o",
                    "warning",
                    [("state", "=", "submitted_manager")] + manager_scope,
                ),
                (
                    "started_without_approval",
                    _("Started Without Approval"),
                    "fa-bolt",
                    "danger",
                    [
                        ("state", "=", "in_progress"),
                        ("started_without_approval", "=", True),
                    ] + manager_scope,
                ),
                (
                    "modification_requested",
                    _("Modification Requests"),
                    "fa-pencil-square-o",
                    "info",
                    [("state", "=", "modification_requested")] + manager_scope,
                ),
                (
                    "pending_review",
                    _("Completed - Pending Review"),
                    "fa-flag-checkered",
                    "success",
                    [("state", "=", "completed")] + manager_scope,
                ),
            ])

        employee_scope = self._employee_task_employee_scope()
        specs.extend([
            (
                "to_accept",
                _("Waiting for My Acceptance"),
                "fa-hand-o-up",
                "warning",
                [("state", "=", "pending_acceptance")] + employee_scope,
            ),
            (
                "returned_to_me",
                _("Returned to Me"),
                "fa-reply",
                "danger",
                [
                    ("state", "in",
                     ["returned_manager", "returned_after_completion"]),
                ] + employee_scope,
            ),
        ])
        return specs

    @api.model
    def _employee_task_fallback_action_id(self):
        """The module's own workspace action, used only as a fallback if
        the tile cannot open a dynamic list for some reason."""
        action = self.env.ref(
            "employee_task_management.action_employee_task_pending_my_action",
            raise_if_not_found=False,
        )
        return action.id if action else False

    @api.model
    def _employee_task_tiles(self):
        """Build the Employee Task Management cards for this user."""
        if TASK_MODEL not in self.env:
            return []
        # No task role at all: the model would refuse the read anyway.
        if not self.env.user.has_group(GROUP_EMPLOYEE):
            return []

        task_model = self.env[TASK_MODEL]
        action_id = self._employee_task_fallback_action_id()
        tiles = []

        for key, name, icon, tone, domain in self._employee_task_card_specs():
            try:
                count = task_model.search_count(domain)
            except Exception:
                # Same defensive stance as _count_for_action: a broken
                # card must never take the whole dashboard down.
                continue
            tiles.append({
                "key": "%s|%s|%s" % (TASK_SECTION_KEY, TASK_MODEL, key),
                "name": name,
                "count": count,
                "icon": icon,
                "tone": tone,
                "action_id": action_id,
                "res_model": TASK_MODEL,
                "view_mode": "list,form",
                "domain": domain,
                "context": {"create": False},
            })

        # Pending cards first, then alphabetical - the ordering the base
        # dashboard applies to every other section.
        tiles.sort(key=lambda tile: (0 if tile["count"] else 1, tile["name"]))
        return tiles

    # ------------------------------------------------------------------
    # Injection into the dashboard
    # ------------------------------------------------------------------
    @api.model
    def _strip_auto_employee_task_tiles(self, sections):
        """Drop any auto-discovered card pointing at employee.task.list.

        If somebody later hangs the Employee Task Approvals menu under
        the workspace approvals menu, the base menu walk would generate a
        second, generic card next to the curated ones below. This keeps
        the cards in this file the single source of truth. Sections left
        empty by the removal are dropped as well.
        """
        cleaned = []
        for section in sections:
            tiles = [
                tile for tile in section.get("tiles", [])
                if tile.get("res_model") != TASK_MODEL
            ]
            if len(tiles) != len(section.get("tiles", [])):
                section = dict(section, tiles=tiles)
                section["count"] = sum(t.get("count", 0) for t in tiles)
            if tiles:
                cleaned.append(section)
        return cleaned

    @api.model
    def get_sections(self):
        sections = super().get_sections()
        tiles = self._employee_task_tiles()
        if not tiles:
            return sections

        sections = self._strip_auto_employee_task_tiles(sections)

        if TASK_SECTION_KEY == "hr":
            # Folded into the existing HR section rather than standing
            # alone - supported so the constant above is a real switch.
            for section in sections:
                if section.get("key") == "hr":
                    section["tiles"] = section.get("tiles", []) + tiles
                    section["tiles"].sort(
                        key=lambda tile: (0 if tile.get("count") else 1,
                                          tile["name"]))
                    section["count"] = sum(
                        t.get("count", 0) for t in section["tiles"])
                    return sections

        sections.append({
            "key": TASK_SECTION_KEY,
            "name": TASK_SECTION["name"],
            "icon": TASK_SECTION["icon"],
            "tone": TASK_SECTION["tone"],
            "sequence": TASK_SECTION["sequence"],
            "count": sum(tile.get("count", 0) for tile in tiles),
            "tiles": tiles,
        })
        sections.sort(key=lambda section: (section["sequence"], section["name"]))
        return sections
