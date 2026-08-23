from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _
from odoo.exceptions import UserError


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    rejection_email_queued_at = fields.Datetime(copy=False, readonly=True)

    def _next_rejection_email_send_at(self):
        timezone = pytz.timezone("Asia/Riyadh")
        now_local = datetime.now(timezone)
        send_date = now_local.date()
        if now_local.time() >= time(20, 0):
            send_date += timedelta(days=1)
        send_local = timezone.localize(datetime.combine(send_date, time(20, 0)))
        return send_local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _queue_rejection_email(self, template):
        if not template:
            return self.env["mail.mail"]
        queued = self.env["mail.mail"]
        scheduled_date = self._next_rejection_email_send_at()
        for applicant in self.filtered(
            lambda item: not item.rejection_email_queued_at
            and (item.email_from or item.partner_id.email)
        ):
            mail_id = template.send_mail(
                applicant.id,
                force_send=False,
                email_values={"scheduled_date": scheduled_date},
            )
            if mail_id:
                queued |= self.env["mail.mail"].browse(mail_id)
                applicant.sudo().write({"rejection_email_queued_at": fields.Datetime.now()})
                applicant.message_post(body=_(
                    "Candidate rejection email queued for delivery after 8:00 PM."
                ))
        return queued


class ApplicantGetRefuseReason(models.TransientModel):
    _inherit = "applicant.get.refuse.reason"

    def action_refuse_reason_apply(self):
        if self.send_mail:
            if not self.template_id:
                raise UserError(_("Email template must be selected to send a mail"))
            if not self.applicant_ids.filtered(lambda item: item.email_from or item.partner_id.email):
                raise UserError(_("Email of the applicant is not set, email won't be sent."))

        self.applicant_ids.write({
            "refuse_reason_id": self.refuse_reason_id.id,
            "active": False,
            "rejection_email_queued_at": False,
        })
        if self.send_mail:
            self.applicant_ids._queue_rejection_email(self.template_id)
        return {"type": "ir.actions.act_window_close"}
