# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestApprovalDashboardFiltering(TransactionCase):
    """Automated unit and integration tests for role-based approval dashboard filtering
    in pr_employee_service_requests (Milestone 3 - Automated Test Verification R3).

    Verifies that users in each approval role strictly see only service request records
    matching their single primary approval state, and that multi-role/admin users
    resolve to a single primary role rather than accumulating multiple stages.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # -----------------------------------------------------------------
        # Security Groups
        # -----------------------------------------------------------------
        cls.group_internal_user = cls.env.ref("base.group_user")
        cls.group_admin = cls.env.ref("base.group_system")
        cls.group_hr_md = cls.env.ref("pr_hr.group_hr_md")
        cls.group_finance_manager = cls.env.ref("pr_account.custom_group_accounting_manager")
        cls.group_accounts_manager = cls.env.ref("account.group_account_manager")
        cls.group_hr_manager = cls.env.ref("pr_hr.group_hr_manager")
        cls.group_hr_supervisor = cls.env.ref("pr_hr.group_hr_supervisor")

        # -----------------------------------------------------------------
        # Test Users with Isolated Roles
        # -----------------------------------------------------------------
        # 1. MD User
        cls.user_md = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User MD",
            "login": "test.user.md@example.com",
            "email": "test.md@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_hr_md.id])],
        })

        # 2. Finance Manager User (Accounting Manager)
        cls.user_finance = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Finance Manager",
            "login": "test.user.finance@example.com",
            "email": "test.finance@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_finance_manager.id])],
        })

        # 3. Accounts User (Account Manager, explicitly without Finance Manager)
        cls.user_accounts = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Accounts Manager",
            "login": "test.user.accounts@example.com",
            "email": "test.accounts@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_accounts_manager.id])],
        })

        # 4. HR Manager User
        cls.user_hr_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User HR Manager",
            "login": "test.user.hrm@example.com",
            "email": "test.hrm@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_hr_manager.id])],
        })

        # 5. HR Supervisor User
        cls.user_hr_supervisor = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User HR Supervisor",
            "login": "test.user.hrsup@example.com",
            "email": "test.hrsup@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_hr_supervisor.id])],
        })

        # 6. Employee Manager User (manages Employee A)
        cls.user_employee_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Employee Manager",
            "login": "test.user.empmgr@example.com",
            "email": "test.empmgr@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id])],
        })

        # 6b. Other Employee Manager User (manages Employee B, for manager isolation check)
        cls.user_other_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Other Manager",
            "login": "test.user.othermgr@example.com",
            "email": "test.othermgr@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id])],
        })

        # 7. Multi-Role User (assigned BOTH MD and HR Supervisor groups)
        cls.user_multi_role = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Multi-Role (MD + HR Sup)",
            "login": "test.user.multirole@example.com",
            "email": "test.multirole@example.com",
            "groups_id": [(6, 0, [
                cls.group_internal_user.id,
                cls.group_hr_md.id,
                cls.group_hr_supervisor.id,
            ])],
        })

        # 8. Admin User (System Administrator)
        cls.user_admin = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Administrator",
            "login": "test.user.admin@example.com",
            "email": "test.admin@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id, cls.group_admin.id])],
        })

        # 9. Regular Employee User (no approval roles)
        cls.user_regular = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Regular Employee",
            "login": "test.user.regular@example.com",
            "email": "test.regular@example.com",
            "groups_id": [(6, 0, [cls.group_internal_user.id])],
        })

        # -----------------------------------------------------------------
        # Employee Records with Manager Linkages
        # -----------------------------------------------------------------
        cls.employee_mgr_record = cls.env["hr.employee"].create({
            "name": "Employee Manager Record",
            "user_id": cls.user_employee_manager.id,
            "identification_id": "TEST-IQAMA-MGR01",
        })

        cls.employee_other_mgr_record = cls.env["hr.employee"].create({
            "name": "Other Manager Record",
            "user_id": cls.user_other_manager.id,
            "identification_id": "TEST-IQAMA-OMGR01",
        })

        cls.employee_a = cls.env["hr.employee"].create({
            "name": "Employee A (Managed by user_employee_manager)",
            "user_id": cls.user_regular.id,
            "parent_id": cls.employee_mgr_record.id,
            "identification_id": "TEST-IQAMA-A01",
        })

        cls.employee_b = cls.env["hr.employee"].create({
            "name": "Employee B (Managed by user_other_manager)",
            "parent_id": cls.employee_other_mgr_record.id,
            "identification_id": "TEST-IQAMA-B01",
        })

        # -----------------------------------------------------------------
        # Service Request Fixtures Across All States
        # -----------------------------------------------------------------
        def _create_service_request(employee, state, payment_resp="company", req_type="reimbursement"):
            return cls.env["pr.employee.service.request"].create({
                "request_type": req_type,
                "reimbursement_type": "fuel",
                "employee_id": employee.id,
                "company_id": cls.env.company.id,
                "requested_amount": 150.0,
                "expense_date": date.today(),
                "payment_responsibility": payment_resp,
                "state": state,
                "reason": f"Automated Test - State {state}",
            })

        # 1. Employment Manager Approval (Employee A -> user_employee_manager is direct manager)
        cls.req_mgr = _create_service_request(cls.employee_a, "employee_manager_approval")

        # 1b. Employment Manager Approval (Employee B -> user_other_manager is direct manager)
        cls.req_mgr_other = _create_service_request(cls.employee_b, "employee_manager_approval")

        # 2. HR Supervisor Approval
        cls.req_sup = _create_service_request(cls.employee_a, "hr_supervisor_approval")

        # 3. HR Manager Approval
        cls.req_hr_mgr = _create_service_request(cls.employee_a, "hr_manager_approval")

        # 4. Accounts Approval
        cls.req_accounts = _create_service_request(cls.employee_a, "accounts_approval", payment_resp="company")

        # 5. Finance Approval
        cls.req_finance = _create_service_request(cls.employee_a, "finance_approval", payment_resp="company")

        # 6. MD Approval
        cls.req_md = _create_service_request(cls.employee_a, "md_approval", payment_resp="company")

        # 7. Draft State
        cls.req_draft = _create_service_request(cls.employee_a, "draft")

        # 8. Paid State
        cls.req_paid = _create_service_request(cls.employee_a, "paid", payment_resp="company")

        # -----------------------------------------------------------------
        # Multi-Role Cascade Test Users & Linkages
        # -----------------------------------------------------------------
        # 10. Finance Manager + Accounts Manager User (Priority 2 > 3)
        cls.user_finance_and_accounts = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User Finance & Accounts",
            "login": "test.user.finacc@example.com",
            "email": "test.finacc@example.com",
            "groups_id": [(6, 0, [
                cls.group_internal_user.id,
                cls.group_finance_manager.id,
                cls.group_accounts_manager.id,
            ])],
        })

        # 11. HR Manager + HR Supervisor User (Priority 4 > 5)
        cls.user_hrm_and_hrsup = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User HR Manager & HR Supervisor",
            "login": "test.user.hrmsup@example.com",
            "email": "test.hrmsup@example.com",
            "groups_id": [(6, 0, [
                cls.group_internal_user.id,
                cls.group_hr_manager.id,
                cls.group_hr_supervisor.id,
            ])],
        })

        # 12. 3-Role Cascade User: Employee Manager + HR Supervisor + Finance Manager (Priority 2 > 5 > 6)
        cls.user_3role_cascade = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Test User 3-Role (Manager + HR Sup + Finance)",
            "login": "test.user.3role@example.com",
            "email": "test.3role@example.com",
            "groups_id": [(6, 0, [
                cls.group_internal_user.id,
                cls.group_finance_manager.id,
                cls.group_hr_supervisor.id,
            ])],
        })

        cls.employee_mgr_3role_record = cls.env["hr.employee"].create({
            "name": "3-Role Manager Record",
            "user_id": cls.user_3role_cascade.id,
            "identification_id": "TEST-IQAMA-3R01",
        })

        cls.employee_c = cls.env["hr.employee"].create({
            "name": "Employee C (Managed by user_3role_cascade)",
            "parent_id": cls.employee_mgr_3role_record.id,
            "identification_id": "TEST-IQAMA-C01",
        })

        cls.req_mgr_3role = _create_service_request(cls.employee_c, "employee_manager_approval")

        # 13. Self-Paid Service Requests (for financial approver inverted query compound OR validation)
        cls.req_finance_self = _create_service_request(
            cls.employee_a, "finance_approval", payment_resp="self"
        )
        cls.req_accounts_self = _create_service_request(
            cls.employee_a, "accounts_approval", payment_resp="self"
        )

    # =========================================================================
    # Sanity & Fixture Assertions
    # =========================================================================
    def test_00_fixture_setup_integrity(self):
        """Verify test fixture linkages and group memberships."""
        self.assertEqual(
            self.req_mgr.employee_manager_user_id,
            self.user_employee_manager,
            "req_mgr must resolve to user_employee_manager as direct manager.",
        )
        self.assertEqual(
            self.req_mgr_other.employee_manager_user_id,
            self.user_other_manager,
            "req_mgr_other must resolve to user_other_manager as direct manager.",
        )
        self.assertEqual(
            self.req_mgr_3role.employee_manager_user_id,
            self.user_3role_cascade,
            "req_mgr_3role must resolve to user_3role_cascade as direct manager.",
        )
        self.assertFalse(
            self.user_accounts.has_group("pr_account.custom_group_accounting_manager"),
            "user_accounts must NOT possess the Finance Manager group.",
        )
        self.assertTrue(
            self.user_finance.has_group("pr_account.custom_group_accounting_manager"),
            "user_finance must possess the Finance Manager group.",
        )
        self.assertTrue(
            self.user_finance_and_accounts.has_group("pr_account.custom_group_accounting_manager"),
            "user_finance_and_accounts must possess the Finance Manager group.",
        )
        self.assertTrue(
            self.user_finance_and_accounts.has_group("account.group_account_manager"),
            "user_finance_and_accounts must possess the Accounts Manager group.",
        )
        self.assertTrue(
            self.user_hrm_and_hrsup.has_group("pr_hr.group_hr_manager"),
            "user_hrm_and_hrsup must possess the HR Manager group.",
        )
        self.assertTrue(
            self.user_hrm_and_hrsup.has_group("pr_hr.group_hr_supervisor"),
            "user_hrm_and_hrsup must possess the HR Supervisor group.",
        )
        self.assertTrue(
            self.user_3role_cascade.has_group("pr_account.custom_group_accounting_manager"),
            "user_3role_cascade must possess the Finance Manager group.",
        )
        self.assertTrue(
            self.user_3role_cascade.has_group("pr_hr.group_hr_supervisor"),
            "user_3role_cascade must possess the HR Supervisor group.",
        )
        self.assertEqual(
            self.employee_c.parent_id.user_id,
            self.user_3role_cascade,
            "user_3role_cascade must be manager of employee_c.",
        )
        self.assertTrue(
            self.user_multi_role.has_group("pr_hr.group_hr_md"),
            "user_multi_role must possess the MD group.",
        )
        self.assertTrue(
            self.user_multi_role.has_group("pr_hr.group_hr_supervisor"),
            "user_multi_role must possess the HR Supervisor group.",
        )

    # =========================================================================
    # Role-Based Search Filtering Tests
    # =========================================================================
    def test_md_role_filtering(self):
        """Test MD role sees strictly and only md_approval records."""
        results = self.env["pr.employee.service.request"].with_user(self.user_md).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(self.req_md, results, "MD must see records in md_approval state.")
        self.assertNotIn(self.req_mgr, results, "MD must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_mgr_other, results, "MD must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_sup, results, "MD must NOT see records in hr_supervisor_approval state.")
        self.assertNotIn(self.req_hr_mgr, results, "MD must NOT see records in hr_manager_approval state.")
        self.assertNotIn(self.req_accounts, results, "MD must NOT see records in accounts_approval state.")
        self.assertNotIn(self.req_finance, results, "MD must NOT see records in finance_approval state.")
        self.assertNotIn(self.req_draft, results, "MD must NOT see records in draft state.")
        self.assertNotIn(self.req_paid, results, "MD must NOT see records in paid state.")
        self.assertTrue(
            all(rec.state == "md_approval" for rec in results),
            "Every record returned to MD must strictly have state == 'md_approval'.",
        )

    def test_hr_supervisor_role_filtering(self):
        """Test HR Supervisor role sees strictly and only hr_supervisor_approval records."""
        results = self.env["pr.employee.service.request"].with_user(self.user_hr_supervisor).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(self.req_sup, results, "HR Supervisor must see records in hr_supervisor_approval state.")
        self.assertNotIn(self.req_mgr, results, "HR Supervisor must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_mgr_other, results, "HR Supervisor must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_hr_mgr, results, "HR Supervisor must NOT see records in hr_manager_approval state.")
        self.assertNotIn(self.req_accounts, results, "HR Supervisor must NOT see records in accounts_approval state.")
        self.assertNotIn(self.req_finance, results, "HR Supervisor must NOT see records in finance_approval state.")
        self.assertNotIn(self.req_md, results, "HR Supervisor must NOT see records in md_approval state.")
        self.assertNotIn(self.req_draft, results, "HR Supervisor must NOT see records in draft state.")
        self.assertNotIn(self.req_paid, results, "HR Supervisor must NOT see records in paid state.")
        self.assertTrue(
            all(rec.state == "hr_supervisor_approval" for rec in results),
            "Every record returned to HR Supervisor must strictly have state == 'hr_supervisor_approval'.",
        )

    def test_hr_manager_role_filtering(self):
        """Test HR Manager role sees strictly and only hr_manager_approval records."""
        results = self.env["pr.employee.service.request"].with_user(self.user_hr_manager).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(self.req_hr_mgr, results, "HR Manager must see records in hr_manager_approval state.")
        self.assertNotIn(self.req_mgr, results, "HR Manager must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_mgr_other, results, "HR Manager must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_sup, results, "HR Manager must NOT see records in hr_supervisor_approval state.")
        self.assertNotIn(self.req_accounts, results, "HR Manager must NOT see records in accounts_approval state.")
        self.assertNotIn(self.req_finance, results, "HR Manager must NOT see records in finance_approval state.")
        self.assertNotIn(self.req_md, results, "HR Manager must NOT see records in md_approval state.")
        self.assertNotIn(self.req_draft, results, "HR Manager must NOT see records in draft state.")
        self.assertNotIn(self.req_paid, results, "HR Manager must NOT see records in paid state.")
        self.assertTrue(
            all(rec.state == "hr_manager_approval" for rec in results),
            "Every record returned to HR Manager must strictly have state == 'hr_manager_approval'.",
        )

    def test_employee_manager_role_filtering(self):
        """Test Employee Manager role sees strictly and only employee_manager_approval
        records where they are the direct manager."""
        results = self.env["pr.employee.service.request"].with_user(self.user_employee_manager).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(
            self.req_mgr,
            results,
            "Employee Manager must see records for their direct subordinate in employee_manager_approval state.",
        )
        self.assertNotIn(
            self.req_mgr_other,
            results,
            "Employee Manager must NOT see employee_manager_approval records for employees they do NOT manage.",
        )
        self.assertNotIn(self.req_sup, results, "Employee Manager must NOT see hr_supervisor_approval records.")
        self.assertNotIn(self.req_hr_mgr, results, "Employee Manager must NOT see hr_manager_approval records.")
        self.assertNotIn(self.req_accounts, results, "Employee Manager must NOT see accounts_approval records.")
        self.assertNotIn(self.req_finance, results, "Employee Manager must NOT see finance_approval records.")
        self.assertNotIn(self.req_md, results, "Employee Manager must NOT see md_approval records.")
        self.assertNotIn(self.req_draft, results, "Employee Manager must NOT see draft records.")
        self.assertNotIn(self.req_paid, results, "Employee Manager must NOT see paid records.")
        self.assertTrue(
            all(
                rec.state == "employee_manager_approval"
                and rec.employee_manager_user_id == self.user_employee_manager
                for rec in results
            ),
            "Every record returned must belong to employee_manager_approval and the direct manager.",
        )

    def test_accounts_role_filtering(self):
        """Test Accounts role sees strictly and only accounts_approval records."""
        results = self.env["pr.employee.service.request"].with_user(self.user_accounts).search([
            ("is_current_user_financial_approver", "=", True),
        ])
        self.assertIn(self.req_accounts, results, "Accounts must see records in accounts_approval state.")
        self.assertNotIn(self.req_finance, results, "Accounts must NOT see records in finance_approval state.")
        self.assertNotIn(self.req_mgr, results, "Accounts must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_sup, results, "Accounts must NOT see records in hr_supervisor_approval state.")
        self.assertNotIn(self.req_hr_mgr, results, "Accounts must NOT see records in hr_manager_approval state.")
        self.assertNotIn(self.req_md, results, "Accounts must NOT see records in md_approval state.")
        self.assertNotIn(self.req_draft, results, "Accounts must NOT see records in draft state.")
        self.assertNotIn(self.req_paid, results, "Accounts must NOT see records in paid state.")
        self.assertTrue(
            all(rec.state == "accounts_approval" for rec in results),
            "Every financial record returned to Accounts must strictly have state == 'accounts_approval'.",
        )

    def test_finance_role_filtering(self):
        """Test Finance role sees strictly and only finance_approval records."""
        results = self.env["pr.employee.service.request"].with_user(self.user_finance).search([
            ("is_current_user_financial_approver", "=", True),
        ])
        self.assertIn(self.req_finance, results, "Finance must see records in finance_approval state.")
        self.assertNotIn(self.req_accounts, results, "Finance must NOT see records in accounts_approval state.")
        self.assertNotIn(self.req_mgr, results, "Finance must NOT see records in employee_manager_approval state.")
        self.assertNotIn(self.req_sup, results, "Finance must NOT see records in hr_supervisor_approval state.")
        self.assertNotIn(self.req_hr_mgr, results, "Finance must NOT see records in hr_manager_approval state.")
        self.assertNotIn(self.req_md, results, "Finance must NOT see records in md_approval state.")
        self.assertNotIn(self.req_draft, results, "Finance must NOT see records in draft state.")
        self.assertNotIn(self.req_paid, results, "Finance must NOT see records in paid state.")
        self.assertTrue(
            all(rec.state == "finance_approval" for rec in results),
            "Every financial record returned to Finance must strictly have state == 'finance_approval'.",
        )

    # =========================================================================
    # Multi-Role, Admin, and Regular User Priority Tests
    # =========================================================================
    def test_multi_role_user_resolves_to_md(self):
        """Test Multi-Role user (MD + HR Supervisor) strictly resolves to single primary role (MD)
        and sees only md_approval records, seeing 0 records from lower stages."""
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_multi_role)
        self.assertEqual(role, "md", "Multi-role user with MD and HR Supervisor groups must resolve to 'md'.")

        results = self.env["pr.employee.service.request"].with_user(self.user_multi_role).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(self.req_md, results, "Multi-role user must see md_approval records.")
        self.assertNotIn(
            self.req_sup,
            results,
            "Multi-role user must NOT see hr_supervisor_approval records despite possessing that group.",
        )
        self.assertNotIn(self.req_mgr, results, "Multi-role user must NOT see employee_manager_approval records.")
        self.assertNotIn(self.req_hr_mgr, results, "Multi-role user must NOT see hr_manager_approval records.")
        self.assertNotIn(self.req_accounts, results, "Multi-role user must NOT see accounts_approval records.")
        self.assertNotIn(self.req_finance, results, "Multi-role user must NOT see finance_approval records.")
        self.assertTrue(
            all(rec.state == "md_approval" for rec in results),
            "Multi-role user must see strictly and only records in md_approval state.",
        )

    def test_admin_user_resolves_to_md(self):
        """Test Admin user (base.group_system) strictly resolves to single primary role (MD)
        and sees only md_approval records."""
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_admin)
        self.assertEqual(role, "md", "System Administrator must resolve to 'md' as primary role.")

        results = self.env["pr.employee.service.request"].with_user(self.user_admin).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertIn(self.req_md, results, "Admin must see md_approval records.")
        self.assertNotIn(self.req_mgr, results, "Admin must NOT see employee_manager_approval records.")
        self.assertNotIn(self.req_sup, results, "Admin must NOT see hr_supervisor_approval records.")
        self.assertNotIn(self.req_hr_mgr, results, "Admin must NOT see hr_manager_approval records.")
        self.assertNotIn(self.req_accounts, results, "Admin must NOT see accounts_approval records.")
        self.assertNotIn(self.req_finance, results, "Admin must NOT see finance_approval records.")
        self.assertTrue(
            all(rec.state == "md_approval" for rec in results),
            "Admin user must see strictly and only records in md_approval state.",
        )

    def test_regular_employee_sees_zero_approval_records(self):
        """Test Regular employee with no approval roles sees 0 approval records."""
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_regular)
        self.assertIsNone(role, "Regular employee must resolve to None for primary role.")

        results_mgr = self.env["pr.employee.service.request"].with_user(self.user_regular).search([
            ("is_current_user_service_request_approver", "=", True),
        ])
        self.assertEqual(
            len(results_mgr),
            0,
            "Regular employee must see 0 service request approver records.",
        )

        results_fin = self.env["pr.employee.service.request"].with_user(self.user_regular).search([
            ("is_current_user_financial_approver", "=", True),
        ])
        self.assertEqual(
            len(results_fin),
            0,
            "Regular employee must see 0 financial approver records.",
        )

    # =========================================================================
    # Approval Dashboard Service Integration Tests
    # =========================================================================
    def test_dashboard_service_domain_override_and_tile_queries(self):
        """Test dashboard tile query via de.hr.approval.dashboard.service
        evaluating _override_domain_for_menu and _service_request_pending_domain."""
        dashboard_service = self.env["de.hr.approval.dashboard.service"]

        role_users = [
            (self.user_md, "md_approval", self.req_md),
            (self.user_finance, "finance_approval", self.req_finance),
            (self.user_accounts, "accounts_approval", self.req_accounts),
            (self.user_hr_manager, "hr_manager_approval", self.req_hr_mgr),
            (self.user_hr_supervisor, "hr_supervisor_approval", self.req_sup),
            (self.user_employee_manager, "employee_manager_approval", self.req_mgr),
            (self.user_multi_role, "md_approval", self.req_md),
            (self.user_admin, "md_approval", self.req_md),
        ]

        # Verify _service_request_pending_domain for each role
        for user, expected_state, expected_record in role_users:
            domain = dashboard_service.with_user(user)._service_request_pending_domain()
            results = self.env["pr.employee.service.request"].with_user(user).search(domain)
            self.assertIn(
                expected_record,
                results,
                f"User {user.name} must see {expected_record.display_name} via dashboard domain.",
            )
            self.assertTrue(
                all(r.state == expected_state for r in results),
                f"All records for {user.name} must have state == '{expected_state}'.",
            )

        # Verify regular employee gets empty domain
        regular_domain = dashboard_service.with_user(self.user_regular)._service_request_pending_domain()
        regular_results = self.env["pr.employee.service.request"].with_user(self.user_regular).search(regular_domain)
        self.assertEqual(
            len(regular_results),
            0,
            "Regular employee must receive 0 records from dashboard domain.",
        )

        # Verify _override_domain_for_menu preserves specific action filter criteria
        menu = self.env.ref("pr_employee_service_requests.menu_pr_employee_manager_approvals", raise_if_not_found=False)
        action = self.env.ref("pr_employee_service_requests.action_pr_employee_manager_approvals", raise_if_not_found=False)
        if menu and action:
            # Test override on general approval menu action
            action_domain = safe_eval(action.domain or "[]")
            overridden_domain = dashboard_service.with_user(self.user_hr_supervisor)._override_domain_for_menu(
                menu, action, action_domain
            )
            sup_results = self.env["pr.employee.service.request"].with_user(self.user_hr_supervisor).search(overridden_domain)
            self.assertIn(self.req_sup, sup_results)
            self.assertNotIn(self.req_mgr, sup_results)
            self.assertNotIn(self.req_md, sup_results)

            # Test preserving submenu request_type constraint
            category_domain = [("request_type", "=", "reimbursement"), ("state", "in", ["hr_supervisor_approval", "hr_manager_approval"])]
            overridden_cat_domain = dashboard_service.with_user(self.user_hr_supervisor)._service_request_pending_domain(
                menu=menu, action=action, domain=category_domain
            )
            cat_results = self.env["pr.employee.service.request"].with_user(self.user_hr_supervisor).search(overridden_cat_domain)
            self.assertIn(self.req_sup, cat_results)
            self.assertNotIn(self.req_hr_mgr, cat_results)

    # =========================================================================
    # Computed Fields Consistency Tests
    # =========================================================================
    def test_computed_fields_consistency(self):
        """Test that computed fields match the strict single primary role expectations."""
        # MD User
        self.assertTrue(self.req_md.with_user(self.user_md).is_current_user_service_request_approver)
        self.assertFalse(self.req_sup.with_user(self.user_md).is_current_user_service_request_approver)
        self.assertFalse(self.req_mgr.with_user(self.user_md).is_current_user_service_request_approver)

        # HR Supervisor User
        self.assertTrue(self.req_sup.with_user(self.user_hr_supervisor).is_current_user_service_request_approver)
        self.assertFalse(self.req_md.with_user(self.user_hr_supervisor).is_current_user_service_request_approver)
        self.assertFalse(self.req_mgr.with_user(self.user_hr_supervisor).is_current_user_service_request_approver)

        # Employee Manager User
        self.assertTrue(self.req_mgr.with_user(self.user_employee_manager).is_current_user_service_request_approver)
        self.assertFalse(self.req_mgr_other.with_user(self.user_employee_manager).is_current_user_service_request_approver)
        self.assertFalse(self.req_sup.with_user(self.user_employee_manager).is_current_user_service_request_approver)

        # Accounts User
        self.assertTrue(self.req_accounts.with_user(self.user_accounts).is_current_user_financial_approver)
        self.assertFalse(self.req_finance.with_user(self.user_accounts).is_current_user_financial_approver)

        # Finance User
        self.assertTrue(self.req_finance.with_user(self.user_finance).is_current_user_financial_approver)
        self.assertFalse(self.req_accounts.with_user(self.user_finance).is_current_user_financial_approver)

        # Multi-Role User (Finance & Accounts)
        self.assertTrue(self.req_finance.with_user(self.user_finance_and_accounts).is_current_user_service_request_approver)
        self.assertFalse(self.req_accounts.with_user(self.user_finance_and_accounts).is_current_user_service_request_approver)
        self.assertTrue(self.req_finance.with_user(self.user_finance_and_accounts).is_current_user_financial_approver)
        self.assertFalse(self.req_accounts.with_user(self.user_finance_and_accounts).is_current_user_financial_approver)

        # Multi-Role User (HR Manager & HR Supervisor)
        self.assertTrue(self.req_hr_mgr.with_user(self.user_hrm_and_hrsup).is_current_user_service_request_approver)
        self.assertFalse(self.req_sup.with_user(self.user_hrm_and_hrsup).is_current_user_service_request_approver)

        # 3-Role Cascade User (Manager + HR Sup + Finance)
        self.assertTrue(self.req_finance.with_user(self.user_3role_cascade).is_current_user_service_request_approver)
        self.assertFalse(self.req_sup.with_user(self.user_3role_cascade).is_current_user_service_request_approver)
        self.assertFalse(self.req_mgr_3role.with_user(self.user_3role_cascade).is_current_user_service_request_approver)
        self.assertTrue(self.req_finance.with_user(self.user_3role_cascade).is_current_user_financial_approver)
        self.assertFalse(self.req_accounts.with_user(self.user_3role_cascade).is_current_user_financial_approver)

        # Self-paid Requests (Financial approver strictly excludes self-paid requests)
        self.assertFalse(self.req_finance_self.with_user(self.user_finance).is_current_user_financial_approver)
        self.assertFalse(self.req_accounts_self.with_user(self.user_accounts).is_current_user_financial_approver)

    # =========================================================================
    # Inverted / Negative Search Hardening Tests
    # =========================================================================
    def test_service_request_approver_negative_searches(self):
        """Test negative searches on 'is_current_user_service_request_approver'
        using both '=' False and '!=' True across all approval roles.

        Verifies that:
        1. No exception (e.g. AttributeError on expression.NOT) is raised.
        2. Queries with ('is_current_user_service_request_approver', '=', False) and
           ('is_current_user_service_request_approver', '!=', True) yield identical recordsets.
        3. Queries with ('is_current_user_service_request_approver', '!=', False) and
           ('is_current_user_service_request_approver', '=', True) yield identical recordsets.
        4. Positive and negative searches are strictly disjoint (intersection is empty).
        5. The returned recordset strictly matches the mathematical complement of the positive search
           (universe - positive == negative).
        6. Positive approver records are strictly excluded from negative search results.
        7. Non-approver records are correctly included in negative search results.
        """
        all_fixtures = (
            self.req_mgr
            | self.req_mgr_other
            | self.req_sup
            | self.req_hr_mgr
            | self.req_accounts
            | self.req_finance
            | self.req_md
            | self.req_draft
            | self.req_paid
            | self.req_finance_self
            | self.req_accounts_self
            | self.req_mgr_3role
        )

        test_roles = [
            (self.user_md, self.req_md, "md_approval"),
            (self.user_hr_supervisor, self.req_sup, "hr_supervisor_approval"),
            (self.user_hr_manager, self.req_hr_mgr, "hr_manager_approval"),
            (self.user_employee_manager, self.req_mgr, "employee_manager_approval"),
            (self.user_finance, self.req_finance, "finance_approval"),
            (self.user_accounts, self.req_accounts, "accounts_approval"),
            (self.user_multi_role, self.req_md, "md_approval"),
            (self.user_admin, self.req_md, "md_approval"),
        ]

        for user, expected_pos_record, expected_pos_state in test_roles:
            with self.subTest(user=user.name):
                SR = self.env["pr.employee.service.request"].with_user(user)

                # Total accessible universe of service requests for this user
                universe = SR.search([])

                # Positive search evaluations
                pos_eq = SR.search([("is_current_user_service_request_approver", "=", True)])
                pos_ne = SR.search([("is_current_user_service_request_approver", "!=", False)])

                # Negative / Inverted search evaluations
                neg_eq = SR.search([("is_current_user_service_request_approver", "=", False)])
                neg_ne = SR.search([("is_current_user_service_request_approver", "!=", True)])

                # 1. Operator Symmetry & Equivalence
                self.assertEqual(
                    pos_eq, pos_ne,
                    f"Positive '=' True and '!=' False must return identical recordsets for {user.name}."
                )
                self.assertEqual(
                    neg_eq, neg_ne,
                    f"Negative '=' False and '!=' True must return identical recordsets for {user.name}."
                )

                # 2. Strict Inclusion of Approver Record in Positive
                self.assertIn(
                    expected_pos_record, pos_eq,
                    f"User {user.name} must see {expected_pos_record.display_name} in positive search."
                )
                self.assertTrue(
                    all(r.state == expected_pos_state for r in pos_eq),
                    f"All positive records for {user.name} must strictly have state '{expected_pos_state}'.",
                )

                # 3. Strict Exclusion of Approver Record from Negative
                self.assertNotIn(
                    expected_pos_record, neg_eq,
                    f"User {user.name} must NOT see {expected_pos_record.display_name} in negative search."
                )

                # 4. Strict Disjointness: Pos ∩ Neg == ∅
                intersection = pos_eq & neg_eq
                self.assertEqual(
                    intersection, self.env["pr.employee.service.request"],
                    f"Positive and negative recordsets must have an empty intersection for {user.name}. Overlap: {intersection}."
                )

                # 5. Exhaustive Partition: Pos ∪ Neg == Universe
                union = pos_eq | neg_eq
                self.assertEqual(
                    union, universe,
                    f"Union of positive and negative search must equal the total accessible universe for {user.name}."
                )

                # 6. Exact Mathematical Complement: Neg == Universe \ Pos
                expected_complement = universe - pos_eq
                self.assertEqual(
                    neg_eq, expected_complement,
                    f"Negative search must exactly match mathematical complement (universe - pos) for {user.name}."
                )
                self.assertEqual(
                    pos_eq, universe - neg_eq,
                    f"Positive search must exactly match mathematical complement (universe - neg) for {user.name}."
                )

                # 7. Fixture-level negative inclusion verification
                for other_rec in all_fixtures:
                    if other_rec in universe and other_rec != expected_pos_record:
                        # Extra check: if employee manager, ensure subordinate request is handled correctly
                        if user == self.user_employee_manager and other_rec.state == "employee_manager_approval":
                            if other_rec.employee_manager_user_id == user:
                                continue
                        self.assertIn(
                            other_rec, neg_eq,
                            f"Non-approver accessible record {other_rec.display_name} (state: {other_rec.state}) "
                            f"must be included in negative search for {user.name}."
                        )

        # 8. Regular employee verification (no approval role -> pos is empty, neg is full universe)
        SR_reg = self.env["pr.employee.service.request"].with_user(self.user_regular)
        universe_reg = SR_reg.search([])
        pos_reg = SR_reg.search([("is_current_user_service_request_approver", "=", True)])
        neg_reg_eq = SR_reg.search([("is_current_user_service_request_approver", "=", False)])
        neg_reg_ne = SR_reg.search([("is_current_user_service_request_approver", "!=", True)])

        self.assertEqual(len(pos_reg), 0, "Regular employee positive search must return 0 records.")
        self.assertEqual(neg_reg_eq, neg_reg_ne, "Regular employee negative search operators must yield identical sets.")
        self.assertEqual(neg_reg_eq, universe_reg, "Regular employee negative search must equal full accessible universe.")
        self.assertEqual(pos_reg & neg_reg_eq, self.env["pr.employee.service.request"])
        self.assertEqual(pos_reg | neg_reg_eq, universe_reg)

    def test_financial_approver_negative_searches(self):
        """Test negative searches on 'is_current_user_financial_approver'
        using both '=' False and '!=' True for Accounts, Finance, and non-financial roles.

        Verifies that:
        1. Clean execution without AttributeError on expression.NOT.
        2. Exact mathematical complement (universe - positive == negative).
        3. Equivalence of '=' False and '!=' True.
        4. Equivalence of '=' True and '!=' False.
        5. Accounts User:
           - Sees accounts_approval (company-paid) in positive.
           - Strictly excludes accounts_approval (company-paid) from negative.
           - Sees finance_approval (company-paid) in negative.
           - Sees accounts_approval (self-paid) in negative (validates OR condition on payment_responsibility).
        6. Finance User:
           - Sees finance_approval (company-paid) in positive.
           - Strictly excludes finance_approval (company-paid) from negative.
           - Sees accounts_approval (company-paid) in negative.
           - Sees finance_approval (self-paid) in negative (validates OR condition on payment_responsibility).
        7. Non-financial User (MD, HR, Regular):
           - Positive search is empty (0 records).
           - Negative search equals complete accessible universe.
        """
        # 1. Accounts User
        SR_acc = self.env["pr.employee.service.request"].with_user(self.user_accounts)
        universe_acc = SR_acc.search([])
        pos_acc_eq = SR_acc.search([("is_current_user_financial_approver", "=", True)])
        pos_acc_ne = SR_acc.search([("is_current_user_financial_approver", "!=", False)])
        neg_acc_eq = SR_acc.search([("is_current_user_financial_approver", "=", False)])
        neg_acc_ne = SR_acc.search([("is_current_user_financial_approver", "!=", True)])

        self.assertEqual(pos_acc_eq, pos_acc_ne, "Accounts positive operators must return identical results.")
        self.assertEqual(neg_acc_eq, neg_acc_ne, "Accounts negative operators must return identical results.")

        # Positive & Negative inclusions/exclusions
        self.assertIn(self.req_accounts, pos_acc_eq, "Accounts must see company-paid accounts_approval in positive search.")
        self.assertNotIn(self.req_accounts, neg_acc_eq, "Accounts must NOT see company-paid accounts_approval in negative search.")
        self.assertNotIn(self.req_finance, pos_acc_eq, "Accounts must NOT see finance_approval in positive search.")
        self.assertIn(self.req_finance, neg_acc_eq, "Accounts must see finance_approval in negative search.")

        # Self-paid request edge case
        self.assertNotIn(self.req_accounts_self, pos_acc_eq, "Self-paid accounts request must NOT be in positive search.")
        self.assertIn(self.req_accounts_self, neg_acc_eq, "Self-paid accounts request MUST be in negative search.")
        self.assertNotIn(self.req_finance_self, pos_acc_eq, "Self-paid finance request must NOT be in positive search for Accounts.")
        self.assertIn(self.req_finance_self, neg_acc_eq, "Self-paid finance request MUST be in negative search for Accounts.")

        # Mathematical Complement for Accounts
        self.assertEqual(pos_acc_eq & neg_acc_eq, self.env["pr.employee.service.request"], "Accounts pos and neg must be disjoint.")
        self.assertEqual(pos_acc_eq | neg_acc_eq, universe_acc, "Accounts pos and neg union must equal universe.")
        self.assertEqual(neg_acc_eq, universe_acc - pos_acc_eq, "Accounts negative search must equal universe - pos.")
        self.assertEqual(pos_acc_eq, universe_acc - neg_acc_eq, "Accounts positive search must equal universe - neg.")

        # 2. Finance User
        SR_fin = self.env["pr.employee.service.request"].with_user(self.user_finance)
        universe_fin = SR_fin.search([])
        pos_fin_eq = SR_fin.search([("is_current_user_financial_approver", "=", True)])
        pos_fin_ne = SR_fin.search([("is_current_user_financial_approver", "!=", False)])
        neg_fin_eq = SR_fin.search([("is_current_user_financial_approver", "=", False)])
        neg_fin_ne = SR_fin.search([("is_current_user_financial_approver", "!=", True)])

        self.assertEqual(pos_fin_eq, pos_fin_ne, "Finance positive operators must return identical results.")
        self.assertEqual(neg_fin_eq, neg_fin_ne, "Finance negative operators must return identical results.")

        # Positive & Negative inclusions/exclusions
        self.assertIn(self.req_finance, pos_fin_eq, "Finance must see company-paid finance_approval in positive search.")
        self.assertNotIn(self.req_finance, neg_fin_eq, "Finance must NOT see company-paid finance_approval in negative search.")
        self.assertNotIn(self.req_accounts, pos_fin_eq, "Finance must NOT see accounts_approval in positive search.")
        self.assertIn(self.req_accounts, neg_fin_eq, "Finance must see accounts_approval in negative search.")

        # Self-paid request edge case
        self.assertNotIn(self.req_finance_self, pos_fin_eq, "Self-paid finance request must NOT be in positive search.")
        self.assertIn(self.req_finance_self, neg_fin_eq, "Self-paid finance request MUST be in negative search.")
        self.assertNotIn(self.req_accounts_self, pos_fin_eq, "Self-paid accounts request must NOT be in positive search for Finance.")
        self.assertIn(self.req_accounts_self, neg_fin_eq, "Self-paid accounts request MUST be in negative search for Finance.")

        # Mathematical Complement for Finance
        self.assertEqual(pos_fin_eq & neg_fin_eq, self.env["pr.employee.service.request"], "Finance pos and neg must be disjoint.")
        self.assertEqual(pos_fin_eq | neg_fin_eq, universe_fin, "Finance pos and neg union must equal universe.")
        self.assertEqual(neg_fin_eq, universe_fin - pos_fin_eq, "Finance negative search must equal universe - pos.")
        self.assertEqual(pos_fin_eq, universe_fin - neg_fin_eq, "Finance positive search must equal universe - neg.")

        # 3. Non-financial user (MD)
        SR_md = self.env["pr.employee.service.request"].with_user(self.user_md)
        universe_md = SR_md.search([])
        pos_md = SR_md.search([("is_current_user_financial_approver", "=", True)])
        neg_md_eq = SR_md.search([("is_current_user_financial_approver", "=", False)])
        neg_md_ne = SR_md.search([("is_current_user_financial_approver", "!=", True)])

        self.assertEqual(len(pos_md), 0, "MD user is not a financial approver, pos search must return empty.")
        self.assertEqual(neg_md_eq, neg_md_ne, "MD financial negative operators must return identical results.")
        self.assertEqual(neg_md_eq, universe_md, "MD financial negative search must equal entire universe.")
        self.assertEqual(pos_md & neg_md_eq, self.env["pr.employee.service.request"])
        self.assertEqual(pos_md | neg_md_eq, universe_md)

        # 4. Regular user
        SR_reg = self.env["pr.employee.service.request"].with_user(self.user_regular)
        universe_reg = SR_reg.search([])
        pos_reg = SR_reg.search([("is_current_user_financial_approver", "=", True)])
        neg_reg_eq = SR_reg.search([("is_current_user_financial_approver", "=", False)])
        neg_reg_ne = SR_reg.search([("is_current_user_financial_approver", "!=", True)])

        self.assertEqual(len(pos_reg), 0, "Regular employee is not a financial approver, pos search must return empty.")
        self.assertEqual(neg_reg_eq, neg_reg_ne, "Regular employee financial negative operators must return identical results.")
        self.assertEqual(neg_reg_eq, universe_reg, "Regular employee financial negative search must equal entire universe.")
        self.assertEqual(pos_reg & neg_reg_eq, self.env["pr.employee.service.request"])
        self.assertEqual(pos_reg | neg_reg_eq, universe_reg)

    # =========================================================================
    # Multi-Role Combination & Priority Cascade Tests
    # =========================================================================
    def test_multi_role_finance_and_accounts_resolves_to_finance(self):
        """Test user possessing BOTH Finance Manager and Accounts Manager groups
        strictly resolves to single primary role 'finance' (Cascade Priority 2 > 3).

        Verifies:
        1. _get_user_primary_service_request_role evaluates to 'finance'.
        2. Positive search sees finance_approval and NOT accounts_approval.
        3. Negative search excludes finance_approval and includes accounts_approval.
        4. Financial approver search behaves identically (seeing finance, excluding accounts).
        """
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_finance_and_accounts)
        self.assertEqual(role, "finance", "User with Finance and Accounts groups must resolve to 'finance'.")

        SR = self.env["pr.employee.service.request"].with_user(self.user_finance_and_accounts)
        universe = SR.search([])

        # Service request approver searches
        pos_sr = SR.search([("is_current_user_service_request_approver", "=", True)])
        neg_sr = SR.search([("is_current_user_service_request_approver", "=", False)])
        self.assertIn(self.req_finance, pos_sr, "Must see finance_approval in positive search.")
        self.assertNotIn(self.req_accounts, pos_sr, "Must NOT see accounts_approval in positive search.")
        self.assertNotIn(self.req_finance, neg_sr, "Must NOT see finance_approval in negative search.")
        self.assertIn(self.req_accounts, neg_sr, "Must see accounts_approval in negative search.")
        self.assertEqual(pos_sr & neg_sr, self.env["pr.employee.service.request"])
        self.assertEqual(neg_sr, universe - pos_sr)

        # Financial approver searches
        pos_fin = SR.search([("is_current_user_financial_approver", "=", True)])
        neg_fin = SR.search([("is_current_user_financial_approver", "=", False)])
        self.assertIn(self.req_finance, pos_fin, "Must see finance_approval in positive financial search.")
        self.assertNotIn(self.req_accounts, pos_fin, "Must NOT see accounts_approval in positive financial search.")
        self.assertNotIn(self.req_finance, neg_fin, "Must NOT see finance_approval in negative financial search.")
        self.assertIn(self.req_accounts, neg_fin, "Must see accounts_approval in negative financial search.")
        self.assertEqual(pos_fin & neg_fin, self.env["pr.employee.service.request"])
        self.assertEqual(neg_fin, universe - pos_fin)

    def test_multi_role_hr_manager_and_supervisor_resolves_to_hr_manager(self):
        """Test user possessing BOTH HR Manager and HR Supervisor groups
        strictly resolves to single primary role 'hr_manager' (Cascade Priority 4 > 5).

        Verifies:
        1. _get_user_primary_service_request_role evaluates to 'hr_manager'.
        2. Positive search sees hr_manager_approval and NOT hr_supervisor_approval.
        3. Negative search excludes hr_manager_approval and includes hr_supervisor_approval.
        4. Mathematical complement holds.
        """
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_hrm_and_hrsup)
        self.assertEqual(role, "hr_manager", "User with HR Manager and HR Supervisor groups must resolve to 'hr_manager'.")

        SR = self.env["pr.employee.service.request"].with_user(self.user_hrm_and_hrsup)
        universe = SR.search([])

        pos_sr = SR.search([("is_current_user_service_request_approver", "=", True)])
        neg_sr = SR.search([("is_current_user_service_request_approver", "=", False)])
        self.assertIn(self.req_hr_mgr, pos_sr, "Must see hr_manager_approval in positive search.")
        self.assertNotIn(self.req_sup, pos_sr, "Must NOT see hr_supervisor_approval in positive search.")
        self.assertNotIn(self.req_hr_mgr, neg_sr, "Must NOT see hr_manager_approval in negative search.")
        self.assertIn(self.req_sup, neg_sr, "Must see hr_supervisor_approval in negative search.")
        self.assertEqual(pos_sr & neg_sr, self.env["pr.employee.service.request"])
        self.assertEqual(neg_sr, universe - pos_sr)

        # Financial approver search (HR Manager has no financial approver role)
        pos_fin = SR.search([("is_current_user_financial_approver", "=", True)])
        neg_fin = SR.search([("is_current_user_financial_approver", "=", False)])
        self.assertEqual(len(pos_fin), 0, "HR Manager is not financial approver, pos search must be 0.")
        self.assertEqual(neg_fin, universe, "HR Manager financial neg search must be full universe.")
        self.assertEqual(pos_fin & neg_fin, self.env["pr.employee.service.request"])

    def test_3_role_cascade_manager_supervisor_finance_resolves_to_finance(self):
        """Test user possessing THREE roles simultaneously:
        - Direct Employee Manager (cls.employee_c)
        - HR Supervisor (pr_hr.group_hr_supervisor)
        - Finance Manager (pr_account.custom_group_accounting_manager)
        Strictly resolves to single primary role 'finance' (Cascade Priority: Finance(2) > HR Sup(5) > Emp Mgr(6)).

        Verifies:
        1. _get_user_primary_service_request_role evaluates to 'finance'.
        2. Positive search sees finance_approval only, and NOT hr_supervisor_approval or employee_manager_approval.
        3. Negative search excludes finance_approval and includes hr_supervisor_approval and manager requests.
        4. Mathematical complement holds.
        """
        role = self.env["pr.employee.service.request"]._get_user_primary_service_request_role(self.user_3role_cascade)
        self.assertEqual(
            role, "finance",
            "3-Role user (Manager + HR Sup + Finance) must resolve to 'finance' by cascade priority."
        )

        SR = self.env["pr.employee.service.request"].with_user(self.user_3role_cascade)
        universe = SR.search([])

        pos_sr = SR.search([("is_current_user_service_request_approver", "=", True)])
        neg_sr = SR.search([("is_current_user_service_request_approver", "=", False)])

        # Must see Finance
        self.assertIn(self.req_finance, pos_sr, "Must see finance_approval in positive search.")
        self.assertNotIn(self.req_finance, neg_sr, "Must NOT see finance_approval in negative search.")

        # Must NOT see HR Supervisor
        self.assertNotIn(self.req_sup, pos_sr, "Must NOT see hr_supervisor_approval in positive search.")
        self.assertIn(self.req_sup, neg_sr, "Must see hr_supervisor_approval in negative search.")

        # Must NOT see Employee Manager request for direct subordinate (req_mgr_3role)
        self.assertNotIn(self.req_mgr_3role, pos_sr, "Must NOT see employee_manager_approval in positive search.")
        self.assertIn(self.req_mgr_3role, neg_sr, "Must see employee_manager_approval in negative search.")

        # Mathematical complement
        self.assertEqual(pos_sr & neg_sr, self.env["pr.employee.service.request"])
        self.assertEqual(neg_sr, universe - pos_sr)

        # Financial approver search
        pos_fin = SR.search([("is_current_user_financial_approver", "=", True)])
        neg_fin = SR.search([("is_current_user_financial_approver", "=", False)])
        self.assertIn(self.req_finance, pos_fin, "Must see finance_approval in positive financial search.")
        self.assertNotIn(self.req_finance, neg_fin, "Must NOT see finance_approval in negative financial search.")
        self.assertNotIn(self.req_accounts, pos_fin, "Must NOT see accounts_approval in positive financial search.")
        self.assertIn(self.req_accounts, neg_fin, "Must see accounts_approval in negative financial search.")
        self.assertNotIn(self.req_finance_self, pos_fin, "Must NOT see self-paid finance in positive financial search.")
        self.assertIn(self.req_finance_self, neg_fin, "Must see self-paid finance in negative financial search.")
        self.assertEqual(pos_fin & neg_fin, self.env["pr.employee.service.request"])
        self.assertEqual(neg_fin, universe - pos_fin)

    # =========================================================================
    # Unsupported Search Operators Error Handling
    # =========================================================================
    def test_approver_search_unsupported_operators_raise(self):
        """Test that invalid or unsupported search operators on computed search fields
        cleanly raise NotImplementedError instead of crashing or generating invalid SQL."""
        SR = self.env["pr.employee.service.request"]
        unsupported_ops = ["in", "not in", "like", "ilike", ">", "<"]

        for op in unsupported_ops:
            with self.subTest(field="is_current_user_service_request_approver", op=op):
                with self.assertRaises(NotImplementedError):
                    SR.search([("is_current_user_service_request_approver", op, True)])

            with self.subTest(field="is_current_user_financial_approver", op=op):
                with self.assertRaises(NotImplementedError):
                    SR.search([("is_current_user_financial_approver", op, True)])

