# Missing checkout must not block later days

Deploy the updated code, restart Odoo and upgrade **Biometric Attendance Machines
Integration** (`pr_attendance_device`) to **17.0.1.3.1** on the test database first.

The sync engine now matches open attendance within the punch's local day. An older
open attendance stays open, with its linked check-in marked Needs Review. No checkout
or worked hours are invented. Existing absent/missing-punch handling and shortage
approval remain responsible for resolving that date. This preserves the existing
one-record-per-local-day policy; it does not introduce overnight shift pairing.

Test with a biometric employee:

1. Day 1: sync an 08:00 check-in without any checkout.
2. Day 2: sync 08:00 and 17:00 punches. Expect a separate complete Day 2 record,
   while Day 1 remains missing checkout/absent and available for shortage correction.
3. Repeat with two consecutive missing-checkout days, then a complete third day.
4. Re-sync all punches. Expect no duplicate records or loss of the Day 1 raw link.
5. Submit and approve the normal shortage request with evidence for Day 1. Confirm
   its checkout is corrected and Day 2 remains unchanged.
6. Test a delayed Day 1 checkout arriving after Day 2 was synced. It must update
   Day 1 only. Also verify punches around local midnight use the correct dates.

For punches already blocked by the previous-day error, run **Synchronize attendances
scheduler**. The exact English legacy error is automatically eligible for retry.
For translated errors or other review messages, select the affected unlinked raw
punches and use their **Sync Attendance** action. Other Needs Review records are
not automatically retried. No raw punches or existing attendance are deleted.

Integration tests (requires an Odoo server and disposable database):

```bash
odoo-bin -c /path/to/odoo.conf -d TEST_DATABASE -u pr_attendance_device --test-enable --test-tags /pr_attendance_device --stop-after-init
```

The local workspace has no Odoo runtime/database; integration tests must be run on
the server. Python syntax and diff checks can run locally.
