from odoo.tests.common import TransactionCase


class TestWorkOrderRevision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "WO Revision Test Customer",
        })
        cls.company = cls.env.company

    def test_work_order_revision_lifecycle(self):
        # 1. Create original Work Order
        wo_0 = self.env["pr.work.order"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
        })
        base_name = wo_0.name
        self.assertNotIn("-R", base_name)
        self.assertEqual(wo_0.revision_number, 0)
        self.assertEqual(wo_0.state, "draft")

        # 2. Click "Revise WO" -> creates R1
        action_1 = wo_0.action_new_revision()
        self.assertEqual(action_1.get("res_model"), "pr.work.order")
        wo_1 = self.env["pr.work.order"].browse(action_1["res_id"])

        self.assertEqual(wo_1.name, "%s-R1" % base_name)
        self.assertEqual(wo_1.revision_number, 1)
        self.assertEqual(wo_1.unrevisioned_name, base_name)
        self.assertEqual(wo_1.previous_revision_id.id, wo_0.id)
        self.assertEqual(wo_1.state, "draft")
        self.assertEqual(wo_0.name, base_name)

        # 3. Click "Revise WO" on R1 -> creates R2
        action_2 = wo_1.action_new_revision()
        wo_2 = self.env["pr.work.order"].browse(action_2["res_id"])

        self.assertEqual(wo_2.name, "%s-R2" % base_name)
        self.assertEqual(wo_2.revision_number, 2)
        self.assertEqual(wo_2.unrevisioned_name, base_name)
        self.assertEqual(wo_2.previous_revision_id.id, wo_1.id)
        self.assertEqual(wo_2.state, "draft")

        # 4. Check revision count and action_view_revisions
        self.assertEqual(wo_0.revision_count, 3)
        self.assertEqual(wo_2.revision_count, 3)

        view_action = wo_2.action_view_revisions()
        self.assertEqual(view_action["res_model"], "pr.work.order")
        all_revisions = self.env["pr.work.order"].search(view_action["domain"])
        self.assertEqual(len(all_revisions), 3)
        self.assertSetEqual(set(all_revisions.ids), {wo_0.id, wo_1.id, wo_2.id})

    def test_approving_work_order_revision_cancels_other_revisions(self):
        # 1. Create original Work Order and approve it
        wo_0 = self.env["pr.work.order"].create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
        })
        wo_0.write({"state": "approved"})
        self.assertEqual(wo_0.state, "approved")

        # 2. Create revision wo_1 from wo_0
        action_1 = wo_0.action_new_revision()
        wo_1 = self.env["pr.work.order"].browse(action_1["res_id"])
        self.assertEqual(wo_1.state, "draft")
        self.assertEqual(wo_0.state, "approved")

        # 3. Approve wo_1 -> wo_0 should be automatically cancelled
        wo_1.write({"state": "approved"})
        self.assertEqual(wo_1.state, "approved")
        self.assertEqual(wo_0.state, "cancel")

    def test_revise_wo_button_groups(self):
        view = self.env.ref("pr_work_order.view_pr_work_order_form")
        arch = view.arch
        self.assertIn('name="action_new_revision"', arch)
        self.assertIn('groups="sales_team.group_sale_manager,sales_team.group_sale_salesman,pr_work_order.custom_group_work_order_user"', arch)

