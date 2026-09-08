import logging

from lxml import html

from odoo import api, fields, models

try:
    from googletrans import Translator
except ImportError:  # Keep Careers available even if the optional library is missing.
    Translator = None


_logger = logging.getLogger(__name__)


def _translated_text(translator, value):
    if not value or not value.strip():
        return value
    result = translator.translate(value, src="en", dest="ar")
    return result.text if result and getattr(result, "text", False) else value


def _translated_html(translator, value):
    """Translate visible text nodes without sending or replacing HTML tags."""
    if not value or not value.strip():
        return value

    wrapper = html.fragment_fromstring(value, create_parent="div")
    text_slots = []
    if wrapper.text and wrapper.text.strip():
        text_slots.append((wrapper, "text", wrapper.text))
    for node in wrapper.iterdescendants():
        if node.tag not in ("script", "style") and node.text and node.text.strip():
            text_slots.append((node, "text", node.text))
        if node.tail and node.tail.strip():
            text_slots.append((node, "tail", node.tail))

    for node, attribute, source in text_slots:
        leading = source[:len(source) - len(source.lstrip())]
        trailing = source[len(source.rstrip()):]
        translated = _translated_text(translator, source.strip())
        setattr(node, attribute, "%s%s%s" % (leading, translated, trailing))

    return (wrapper.text or "") + "".join(
        html.tostring(child, encoding="unicode") for child in wrapper
    )


class HrJob(models.Model):
    _inherit = "hr.job"

    # Make website job content use Odoo's per-language JSON translations.
    # Existing source values remain the fallback when a translation is empty.
    name = fields.Char(translate=True)
    pr_career_description_ar = fields.Html(
        string="Automatically Translated Arabic Job Description",
        copy=False,
        readonly=True,
    )
    pr_career_company_name = fields.Char(
        string="Careers Company Name",
        translate=True,
        copy=False,
        readonly=True,
    )
    pr_career_location = fields.Char(
        string="Careers Location",
        translate=True,
        copy=False,
        readonly=True,
    )
    pr_arabic_auto_translated = fields.Boolean(
        string="Arabic Careers Content Generated",
        default=False,
        copy=False,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        jobs._auto_translate_careers_arabic(vals_list)
        return jobs

    def write(self, vals):
        vals = dict(vals)
        if (
            not self.env.context.get("pr_skip_careers_auto_translation")
            and {"name", "description"}.intersection(vals)
        ):
            vals["pr_arabic_auto_translated"] = False
        result = super().write(vals)
        if not self.env.context.get("pr_skip_careers_auto_translation"):
            self._auto_translate_careers_arabic([vals] * len(self))
        return result

    def _auto_translate_careers_arabic(self, vals_list=None):
        if self.env.context.get("pr_skip_careers_auto_translation"):
            return
        lang_code = self.env.context.get("lang") or self.env.user.lang or ""
        if lang_code.lower().startswith("ar"):
            return
        if Translator is None:
            _logger.warning("googletrans is unavailable; Careers Arabic auto-translation was skipped.")
            return

        vals_list = vals_list or [{} for job in self]
        translator = Translator()
        for job, vals in zip(self, vals_list):
            translated_vals = {}
            try:
                company_name = (job.company_id.name or "").strip()
                location = (
                    (job.address_id.city or "").strip()
                    if job.address_id else ""
                )
                job.with_context(
                    lang="en_US",
                    pr_skip_careers_auto_translation=True,
                ).write({
                    "pr_career_company_name": company_name,
                    "pr_career_location": location,
                })
                if "name" in vals and job.name:
                    translated_vals["name"] = _translated_text(translator, job.name)
                if "description" in vals and job.description:
                    translated_vals["pr_career_description_ar"] = _translated_html(
                        translator, job.description
                    )
                if company_name:
                    translated_vals["pr_career_company_name"] = _translated_text(
                        translator, company_name
                    )
                if location:
                    translated_vals["pr_career_location"] = _translated_text(
                        translator, location
                    )
                translated_vals["pr_arabic_auto_translated"] = True
                job.with_context(
                    lang="ar_001",
                    pr_skip_careers_auto_translation=True,
                ).write(translated_vals)
            except Exception:
                # A translation outage must never prevent HR from saving a job.
                _logger.exception(
                    "Could not auto-translate Careers content for job %s.", job.id
                )

    def _ensure_careers_arabic_translation(self):
        """Generate translations for jobs that existed before this feature."""
        english_jobs = self.with_context(lang="en_US")
        pending = english_jobs.filtered(
            lambda job: (
                not job.pr_arabic_auto_translated
                or (job.description and not job.pr_career_description_ar)
                or job.pr_career_company_name != (job.company_id.name or "").strip()
                or job.pr_career_location
                != ((job.address_id.city or "").strip() if job.address_id else "")
            )
        )
        if not pending:
            return
        vals_list = [
            {"name": job.name, "description": job.description}
            for job in pending
        ]
        pending._auto_translate_careers_arabic(vals_list)


class HrDepartment(models.Model):
    _inherit = "hr.department"

    name = fields.Char(translate=True)


class HrRecruitmentDegree(models.Model):
    _inherit = "hr.recruitment.degree"

    name = fields.Char(translate=True)


class HrJobShift(models.Model):
    _inherit = "hr.job.shift"

    name = fields.Char(translate=True)


class HrCareerLevel(models.Model):
    _inherit = "hr.career.level"

    name = fields.Char(translate=True)


class HrSkill(models.Model):
    _inherit = "hr.skill"

    name = fields.Char(translate=True)


class HrSkillType(models.Model):
    _inherit = "hr.skill.type"

    name = fields.Char(translate=True)
