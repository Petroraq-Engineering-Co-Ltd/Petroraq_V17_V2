# -*- coding: utf-8 -*-
from odoo import models, fields


class EmployeeTaskApprovalHistory(models.Model):
    _name = 'employee.task.approval.history'
    _description = 'Employee Task Approval History'
    _order = 'action_datetime desc, id desc'

    task_list_id = fields.Many2one(
        'employee.task.list', string='Task List Reference',
        required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='Approved / Returned By',
        required=True, default=lambda self: self.env.user)
    action = fields.Selection([
        ('submitted', 'Submitted'),
        ('assigned', 'Assigned by Manager'),
        ('approved', 'Approved'),
        ('returned', 'Returned'),
        ('accepted', 'Accepted by Employee'),
        ('modification_requested', 'Modification Requested'),
        ('resent', 'Modified & Re-sent to Employee'),
        ('auto_applied', 'Auto-Applied (No Manager Response)'),
        ('started', 'Work Started'),
        ('completed', 'Completed'),
        ('returned_completed', 'Returned after Completion'),
        ('rejected', 'Rejected by Manager'),
        ('closed', 'Closed'),
        ('unlocked', 'Unlocked'),
        ('resubmitted', 'Resubmitted to Employee'),
    ], string='Action', required=True)
    approval_level = fields.Selection([
        ('employee', 'Employee'),
        ('manager', 'Immediate Manager'),
        ('admin', 'Administrator'),
    ], string='Approval Level')
    action_datetime = fields.Datetime(
        string='Date and Time', default=fields.Datetime.now, required=True)
    state = fields.Selection(
        related='task_list_id.state', string='Status', store=True)
    remarks = fields.Text(string='Remarks')
    company_id = fields.Many2one(
        related='task_list_id.company_id', store=True, string='Company')
