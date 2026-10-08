# Daily task attendance

Install `pr_task_attendance` after updating the app list. It also auto-installs
when its three dependencies are installed together, but auto-installation only
runs after Odoo has refreshed its module list. Merely copying or pulling this
new add-on into an already-running server does not deploy the feature. Restart
Odoo when deploying the Python files. No employee group reassignment is required.

For an existing database, deploy it explicitly (replace the placeholders with
the server's normal executable, config, and database):

```text
odoo-bin -c <odoo.conf> -d <database> -i pr_task_attendance --stop-after-init
```

For later releases of an already-installed database, use `-u` instead of `-i`.
In **Apps**, removing the default `Apps` filter and searching for the technical
name `pr_task_attendance` must show the module as **Installed**. Under
**Settings → Technical → Automation → Scheduled Actions**, **Finalize Daily
Task Attendance at Local Midnight** must be active.

## Policy

- Each employee must submit a task list covering that working day **on that day**.
  A previous day's submission, a saved draft, or a manager assignment does not count.
  The existing task approval history supplies the submission timestamp. A submitted
  list returned by a manager still counts as a submission.
- For an ongoing task list spanning multiple days, the employee uses **Submit
  for Today** each working day. It records a fresh submission without resetting
  the task workflow. The initial normal submission also counts for its day.
- Use the employee's local attendance timezone and resource working calendar,
  including alternating weeks, calendar leave, and public holidays. If no working
  intervals remain, no task submission is required.
- At the first scheduler tick after local midnight (normally within one minute),
  an employee with attendance but no qualifying submission is marked absent.
  Actual check-in/check-out, worked hours, and attendance-source audit data are
  retained. No synthetic punches are created for employees without attendance.
- The cron catches up after downtime and also processes attendance imported late.
  One absence/request record exists per employee/date. A late submission does not
  clear a recorded absence; HR approval is required.
- Enforcement starts on the module's installation date (Saudi business date),
  stored in `pr_task_attendance.enforce_from`. Earlier history is untouched.

## Employee and HR workflow

Employees open **My Workspace → Attendance → My Mark Present Requests**, select
the affected day, enter a reason, and click **Request Mark Present**. The same
record can be opened from the employee's attendance form. The employee's
**My Attendance** list also shows a **Mark Present Request** button on every
attendance affected by this rule, so the request is reachable directly from the
row that was marked absent.

The request appears under **My Approvals → Mark Present Requests** and in the HR
approval dashboard. Existing HR Manager groups receive review activities.
HR can approve actual attendance or reject with a reason. Rejected requests can
be resubmitted; chatter and decision fields retain the approval trail.

Approval removes only the missing-task penalty. Existing late-arrival and
missing-checkout policies are then applied to the original punches. Employees
cannot approve requests, overwrite their state, or access another employee's
requests. Company record rules apply to HR as well.

Draft and confirmed attendance sheets apply the absence and restore their
underlying attendance values on approval. Finalized sheets/payslips are not
rewritten; their normal payroll adjustment/reopening process must be used.

## Validation

Run the Odoo regression suite with `--test-tags /pr_task_attendance` against a
test database after installing the module. The suite covers midnight, daily
submission dates, schedule exceptions, late imports, access control, approval,
and preservation of actual punches.

## UAT demo (one working day)

1. Confirm the test employee has a user, a working calendar for the chosen day,
   and an actual check-in/check-out in **My Attendance**.
2. Do not submit a task list for that employee on the chosen day. A draft task
   list, an earlier submission, or a manager assignment does not count.
3. After the employee's local midnight, let the scheduled action run (normally
   within one minute). For a live demo, an administrator may open the scheduled
   action above and click **Run Manually** after midnight.
4. Reopen **My Attendance**. The original check-in, check-out, and worked hours
   still exist, while **Daily Attendance Status** is **Absent**. Click **Mark
   Present Request**, enter the employee's reason, and click **Request Mark
   Present**.
5. Sign in as an HR Manager and open **My Approvals → Mark Present Requests**.
   Open the pending request and click **Approve Actual Attendance** (or enter an
   HR decision note and reject it).
6. After approval, reopen the original attendance. The missing-task-list penalty
   is removed and the system recalculates the original punches. A separate late
   arrival or missing-checkout violation can therefore still leave the result
   absent; approval does not erase those independent rules.
