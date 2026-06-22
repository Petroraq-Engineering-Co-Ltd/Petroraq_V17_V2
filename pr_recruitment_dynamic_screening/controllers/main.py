# -*- coding: utf-8 -*-

from urllib.parse import quote_plus

from odoo import http
from odoo.http import request

from odoo.addons.pr_website.controllers.main import CareersController


class DynamicRecruitmentController(CareersController):

    @http.route()
    def job_apply(self, job_id, **post):
        job = request.env["hr.job"].sudo().browse(job_id)
        if not job.exists() or not job.website_published:
            return request.not_found()

        if (post.get("pr_screening_website") or "").strip():
            return request.redirect(
                "/job/%s?error=%s"
                % (job_id, quote_plus("The application could not be submitted."))
            )

        answers, validation_error = job.prepare_dynamic_application_answers(post)
        if validation_error:
            return request.redirect(
                "/job/%s?error=%s" % (job_id, quote_plus(validation_error))
            )

        degree_id = (post.get("type_id") or "").strip()
        degree = request.env["hr.recruitment.degree"].sudo().browse(
            int(degree_id) if degree_id.isdigit() else 0
        )
        if not degree.exists():
            return request.redirect(
                "/job/%s?error=%s"
                % (job_id, quote_plus("Please select a valid qualification."))
            )

        email = (post.get("email_from") or "").strip()
        phone = (post.get("partner_phone") or "").strip()
        Applicant = request.env["hr.applicant"]
        duplicate = Applicant.browse()
        if email and phone:
            Applicant._lock_website_application_identity(job, email, phone)
            duplicate = Applicant._find_duplicate_website_application(
                job, email, phone
            )
        if duplicate:
            message = (
                "Duplicate application detected: you have already applied to this job "
                "with the same email and phone number."
            )
            return request.redirect(
                "/job/%s?error=%s" % (job_id, quote_plus(message))
            )

        request.update_context(
            pr_dynamic_recruitment_answers=answers,
            pr_screen_existing_application_fields=job._has_core_screening_rules(),
        )
        return super().job_apply(job_id, **post)
