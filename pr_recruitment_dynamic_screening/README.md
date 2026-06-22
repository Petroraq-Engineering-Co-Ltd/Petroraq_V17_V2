# Petroraq Dynamic Recruitment Screening

This Odoo 17 add-on extends the existing Petroraq careers flow with per-job,
typed application questions and server-side automatic screening.

## Existing application fields

The **Existing Field Screening** tab on Recruitment Requests and Job Positions
checks fields already collected by the careers form, without asking duplicate
questions:

- **Location** (`partner_location`): allow exact normalized locations or match
  any configured term such as `Jubail` within a longer address.
- **Nationality** (`nationality_id`): allow selected countries or allow every
  nationality except selected exclusions. Missing nationality fails whenever a
  nationality rule is active.
- **Highest Qualification** (`type_id`): allow selected recruitment degrees or
  require a minimum degree using the degree's Sequence as its rank.
- **Total Experience** (`experience`): require a minimum, maximum, or inclusive
  range in years.
- **Notice Period** (`notice_period`): require a minimum, maximum, or inclusive
  range in days.
- **Expected Salary** (`salary_expected`): require a minimum, maximum, or
  inclusive range in SAR.
- **National ID / Iqama** (`legally_required`, `national_id_iqama`): optionally
  require the candidate to select Yes and provide a valid 10-digit number.

Rules configured on a Recruitment Request synchronize to its linked job on
approval, manual synchronization, and subsequent approved-request edits.

## Configuration

Open a **Job Position** or **Recruitment Request**, then use the
**Application Questions** tab. Supported answers are short text, long text,
whole number, decimal number, selection, yes/no, and date.

Screening rules include numeric minimum/maximum/equality, exact text,
allowed selection options, minimum ranked selection, required yes/no, and
date boundaries. Screening questions are required except for a maximum-line
rule, where an omitted repeating answer correctly counts as zero entries.

**Related Record** questions use an allow-list of safe Odoo models: countries
and nationalities, education degrees, skills, and languages. Click **Load Odoo
Records**, then mark values as **Allowed** or mark one value as **Minimum
Level** directly in the Available Values table. The same related-record type is
available inside repeating line columns.

**Repeating Lines** questions support configurable short text, long text,
integer, decimal, selection, related-record, and date columns. They are useful
for employment history, certifications, education history, or multiple
languages. Automatic screening can require a minimum or maximum number of
completed entries. Applicants may add up to 20 rows.

For ranked choices, assign increasing option sequences. Example:

- Matric: 10
- FSC: 20
- BS: 30
- Masters: 40

Set the rule to **Selection: Minimum Level** and choose **BS**. BS and Masters
pass; Matric and FSC are automatically refused.

Screening requirements are hidden from applicants by default. Disable **Hide
Requirement from Applicant** on an individual question when the generated
eligibility note (for example, **Minimum accepted: 30**) should be visible.

Questions created on a Recruitment Request are copied to its job when the
request is approved. Questions added or edited after approval are synchronized
to the linked published job automatically; **Sync Questions to Job** is also
available for a manual refresh. Synchronization preserves the IDs used by
historical applicant answers. Removed choices and repeating columns are
archived, while incompatible types create a new live question/column instead
of corrupting old answers. Existing permanent application fields are inherited
and remain unchanged.

The website application uses Previous/Continue navigation. Personal and
professional details are separated from the CV, and more than four custom
questions are automatically split into pages of six questions each.

## Result

Answers and screening results appear on the applicant's **Application
Answers** tab. A failed application is marked **Automatically Refused**,
assigned Odoo's automatic-screening refusal reason, and receives an auditable
chatter note. Recruiters can review it with the standard **Refused** filter or
the dedicated **Automatically Refused** filter; it is no longer classified as
a generic archived application. Recruiters can use **Re-run Screening** after
changing a rule; repeated failures do not duplicate chatter, and an application
that recovers from an automatic refusal is reactivated without overriding a
separate manual refusal reason.

The Recruitment Dashboard includes an **Auto Refused** KPI, refusals and rates
by job position, and recent automatically refused candidates. Recruitment also
has an **Automatic Screening Refusals** menu with list, pivot, and graph views;
all views include archived refused applications and can be grouped by job.

Website submissions are validated again on the server. Selection IDs and
repeating-column IDs must belong to the published job, non-finite and oversized
values are rejected, repeating rows are capped at 20, and duplicate email/phone
identities are normalized and serialized to close concurrent-submit races. A
hidden honeypot rejects basic form bots, model constraints reject cross-job and
cross-column forged relations, and final-step browser validation cannot submit
after merely focusing an invalid field. Applicant names and locations support
Arabic and other Unicode scripts.

## Automated tests

The `tests` package covers all answer parsers, rule families, required and
optional values, forged and archived IDs, repeating-row limits, automatic
refusal and recovery, duplicate normalization, request/job synchronization,
historical answer preservation, configuration immutability, and requester vs.
recruiter record rules. It also covers stale-name synchronization collisions,
approved-request owner synchronization, manual-refusal preservation, optional
zero-line screening, model relation integrity, RPC authorization, nationality
exclusions, salary boundaries, required Iqama validation, request/job rule
synchronization, and dashboard refusal aggregation.
