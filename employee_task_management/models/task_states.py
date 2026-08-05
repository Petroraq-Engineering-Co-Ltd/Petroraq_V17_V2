# -*- coding: utf-8 -*-
"""Single source of truth for what may be edited in which status.

Kept in its own module so employee_task_list / employee_task_line /
employee_task_subtask can all import it without any import-order
dependency between them.
"""

# The task list is still being written: tasks and activities can be
# added, edited and deleted freely.
# Note: pending_acceptance is editable on purpose - it is the window in
# which an employee plans a task list the manager handed over empty.
# Once he clicks Accept, everything below locks.
EDITABLE_STATES = (
    'draft',
    'returned_manager',
    'pending_acceptance',
    'modification_requested',
)

# Execution is running: the employee ticks activities off.
EXECUTION_STATES = ('in_progress', 'returned_after_completion')

# Approved / running: the plan is frozen. No task or activity may be
# added or removed, and only the fields whitelisted below can change.
PARTIAL_LOCK_STATES = ('manager_approved',) + EXECUTION_STATES

# Nothing at all can be touched.
FULL_LOCK_STATES = ('submitted_manager', 'completed', 'closed', 'rejected')

# End of the road - Closed (accepted) or Rejected.
TERMINAL_STATES = ('closed', 'rejected')

# The only task-line fields that stay editable in PARTIAL_LOCK_STATES.
LINE_PARTIAL_FIELDS = {'remarks'}

# Task-line fields whose permission is decided by the ACTIVITY model,
# not by the task-line guard. The Activities dialog is a form on
# employee.task.line, so saving it writes subtask_ids on the line even
# when only an activity changed - that write is just the transport. Each
# individual command inside it still goes through
# employee.task.subtask's own create / write / unlink guards, so nothing
# is waved through here.
LINE_DELEGATED_FIELDS = {'subtask_ids'}

# The only activity fields that stay editable in PARTIAL_LOCK_STATES.
# (is_done is additionally gated by _check_done_allowed, which requires
# the task list to actually be in EXECUTION_STATES.)
SUBTASK_PARTIAL_FIELDS = {'is_done'}

# Activity fields a Manager / Administrator may still correct in
# PARTIAL_LOCK_STATES, on top of SUBTASK_PARTIAL_FIELDS. A plain
# employee never gets these. Full-lock states (Submitted, Completed,
# Closed, Rejected) stay closed to everybody.
SUBTASK_MANAGER_FIELDS = {'hours'}

# States in which a Manager / Administrator may still correct the hours.
# Every state EXCEPT Closed - a Closed task list is final for everybody.
# Listed explicitly rather than derived, so the one exception is obvious
# to whoever reads this next.
MANAGER_HOURS_STATES = (
    'draft',
    'submitted_manager',
    'returned_manager',
    'pending_acceptance',
    'modification_requested',
    'manager_approved',
    'in_progress',
    'returned_after_completion',
    'completed',
    'rejected',
)
