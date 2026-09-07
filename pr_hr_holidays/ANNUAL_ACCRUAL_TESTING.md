# Ongoing annual accrual — version 17.0.1.4.1

## Deploy and configure

Restart Odoo with the updated code and upgrade Petroraq HR Holidays on the test database.
The workspace changes do not deploy or upgrade your running database.

Create one plan for 21-day employees and one for 26-day employees:

| Setting | General employees | Eligible / site employees |
| --- | ---: | ---: |
| Service-year earning limit | Enabled | Enabled |
| Annual entitlement (days) | 21 | 26 |
| Calendar days to earn entitlement | 330 | 330 |

Choose start-of-period gain to credit each day's amount on that morning, or
end-of-period gain to credit it the following morning. No milestone or standard
balance cap is needed. These plans use calendar days, not exactly 11 months.

Create ONE accrual allocation per employee:

- Start Date: the contract start date you want to use as the anniversary anchor.
- Run until: No Limit (leave empty).
- Accrual Plan: the appropriate 21-day or 26-day plan.
- Time Off Type: Annual Leave, measured in days or half days.

Approve the allocation. The standard Accrual Time Off scheduled action updates it.
No new allocation or separate carryover allocation is created on anniversaries.
Unused entitlement stays in the same balance. Approved leave reduces remaining
leave, but does not reduce gross earned leave or reopen that year's earning cap.

The daily rate is 21/330 or 26/330. After the year's full entitlement is earned,
credits pause until the next anniversary. The limit then resets within the SAME
allocation. Leap years use calendar anniversaries; a 29 February start uses
28 February in non-leap years and returns to 29 February in leap years.

Selecting a plan is manual. Existing contract onboarding searches for a plan named
exactly Annual Leave. If that selected plan has this mode enabled, onboarding now
creates an open-ended allocation. It does not choose between 21 and 26 by category.

## Existing allocations and history

Replacement workflow: you may create and approve the new allocation while old
allocations remain approved. The custom overlap restriction has been removed.
Then reconcile and refuse/remove the old allocations using Odoo's normal workflow.
Balances include both while they remain approved. Standard Odoo checks on deleting
allocations with consumed leave still apply; this change does not delete records
or bypass those checks. Test approval of overlapping replacements and verify the
final balance after old allocations are removed.

Earlier versions automatically filled a one-year end date. This update does not
clear stored end dates automatically, because they may represent a real termination.
For your intended ongoing allocation, clear Run until after upgrading. Use the actual
contract start date as Start Date; the calculation uses that date, not the old hidden
service-year anchor field.

A backdated allocation catches up ALL earned service years. Three completed years
on the 21-day plan produce 63 gross earned days, minus leave recorded against that
entitlement. Do not retain duplicate historical allocations/carryover for the same
entitlement. Reconcile old allocations and historical leave before using this on real
employees. Historical changes from 21 to 26 are not automatically inferred: a plan's
rate applies to the full allocation history. Policy fields remain locked once a plan
has allocations, to prevent accidental retrospective changes.

## Quick test

Use separate test employees and select end-of-period gain for these expectations.
You can backdate their allocations or call the processing method in a disposable
Odoo test database. Do not simulate future dates on production records.

| Time from allocation start | 21-day plan gross earned | 26-day plan gross earned |
| --- | ---: | ---: |
| 1 day | 0.063636 | 0.078788 |
| 165 days | 10.5 | 13 |
| 330 days | 21 | 26 |
| 350 days | 21 | 26 |
| First anniversary | 21 | 26 |
| First anniversary + 1 day | 21.063636 | 26.078788 |
| Third anniversary | 63 | 78 |

With start-of-period gain, the first daily credit is available on the start date,
and the first credit of the next year is available on the anniversary itself.

Run the accrual job twice on the same date: the amount must not duplicate.
Approve five days of leave after the first 330 days, then run accrual again before
the anniversary: gross earned stays 21/26, remaining balance becomes 16/21.
After the anniversary, remaining balance increases daily on the same allocation.
Run the PR annual rollover scheduled action: this plan must not create extra records.
Selecting the plan with Run until = No Limit must not show the earlier validation error.

## Termination

The existing contract Last Working Day/date_end workflow sets the allocation end date.
Processing also respects the employee's Last Working Day. Credits stop after that
inclusive cutoff, even when later dates are processed. Past termination dates settle
the completed final day immediately through the contract workflow; future termination
settles through scheduled processing. Test a cutoff during the first 330 days of a
later service year, then run both scheduled actions: no later credits or new allocations.
If retrospective termination would reduce entitlement below already approved leave,
Odoo may require the conflicting leave to be reconciled first.

## Automated checks

Local arithmetic tests (no Odoo database needed):

```bash
python pr_hr_holidays/tests/test_annual_accrual_math.py
```

Odoo integration suite, on a disposable database with the module dependencies:

```bash
odoo-bin -c /path/to/odoo.conf -d TEST_DATABASE -u pr_hr_holidays --test-enable --test-tags /pr_hr_holidays --stop-after-init
```

The local workspace has no Odoo runtime/database. Integration tests need to run on
an Odoo server. Tests cover daily credits, repeated runs, multi-year accrual, plan
selection, leave consumption, termination, replacement approval and standard-plan fallback.
