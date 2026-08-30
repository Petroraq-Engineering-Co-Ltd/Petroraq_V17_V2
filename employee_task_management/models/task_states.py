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

# Editable, but only by a Manager / Administrator.
#
# Modification Requested means the employee has asked the MANAGER to
# change something - typically the dates. If the employee could just
# change them himself he would be answering his own request, and the
# manager would never see it. So the plan stays open (someone has to be
# able to act on the request) but only for the person the request was
# addressed to. The employee has already said what he wants, in the
# request reason.
MANAGER_ONLY_EDITABLE_STATES = (
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

# States in which a Delayed (Days) figure is meaningful and must be
# REPORTED, not zeroed. Execution has started, so an end-date overrun is
# real; and once the work is Completed / Closed / Rejected the figure
# settles on End Date -> Completion Date rather than resetting, so the
# manager can still see that a finished task ran late.
# Deliberately EXCLUDES draft / submitted_manager / pending_acceptance /
# modification_requested: nothing is being executed there, and that
# waiting time is tracked separately by is_delayed + pending_since.
REPORTABLE_DELAY_STATES = (
    ('manager_approved', 'completed') + EXECUTION_STATES + TERMINAL_STATES
)

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


# Task-list states whose hours do NOT consume the employee's daily
# capacity. DRAFT ONLY.
#
# A draft is a private scratchpad - nothing is committed until the
# employee submits it, so it cannot occupy his day.
#
# Everything else counts, INCLUDING Rejected. Rejected used to be listed
# here, which meant rejecting a whole task list made its hours disappear
# from the report altogether: not into the Rejected column, not into
# Allocated, just gone - and the day turned idle. That contradicted the
# rule the client settled on, that hours consumed are consumed whatever
# the manager thought of the output. It also silently erased task-level
# rejections already recorded on that list.
#
# Rejecting a whole list now behaves exactly like rejecting each task on
# it: the hours stay counted and show up under Rejected Hours.
UNALLOCATED_STATES = ('draft',)
