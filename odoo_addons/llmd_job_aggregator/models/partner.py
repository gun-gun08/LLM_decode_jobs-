"""Who a website account is on the job board: a job seeker (applicant) or somebody hiring (employer / HR) - asked at the sign-up (the window of Apply Now /
Post a job, and Odoo's own /web/signup page), or once after a sign-in when it is not known yet. A hirer also gives the company, their designation and,
optionally, the company website and a phone number; all of it is kept on the person's contact (res.partner), in Odoo's own fields where there is one
(company_name, function, website, phone). Recruitment > Job board > Employers lists the hirers."""
import re

from odoo import api, fields, models

ROLES = [('applicant', 'Job seeker'), ('hirer', 'Employer / HR')]


def clean_phone(value):
    """A phone number typed in a form -> the number with single spaces, or '' when it does not look like one."""
    phone = ' '.join((value or '').split())[:30]
    return phone if re.fullmatch(r'\+?[\d\s()-]{7,20}', phone) else ''


def clean_hirer(form, prefix='llmd_', required=True):
    """The hirer details of a form -> (values for res.partner, error text or ''). Only these fields are read. `required=False`: none given is fine
    (the sign-up only asks the role; the Post a job form asks the details)."""
    def text(name, limit):
        return ' '.join((form.get(prefix + name) or '').split())[:limit]
    company, designation, website, phone = text('company', 120), text('designation', 80), text('website', 200), text('phone', 30)
    if not required and not (company or designation or website or phone):
        return {}, ''
    if len(company) < 2 or len(designation) < 2:
        return {}, 'Please enter your company name and your designation.'
    if website and not re.match(r'^https?://', website, re.I):
        website = 'https://' + website
    if website and not re.fullmatch(r'https?://[\w.-]+\.[a-z]{2,}(/\S*)?', website, re.I):
        return {}, 'Please enter a valid company website (or leave it empty).'
    if phone and not re.fullmatch(r'\+?[\d\s()-]{7,20}', phone):
        return {}, 'Please enter a valid phone number (or leave it empty).'
    vals = {'company_name': company, 'function': designation}
    if website:
        vals['website'] = website
    if phone:
        vals['phone'] = phone
    return vals, ''


class ResPartner(models.Model):
    _inherit = 'res.partner'

    llmd_role = fields.Selection(ROLES, string='Job board role', index=True, copy=False,
                                 help='Chosen by the person on the LLM Decode job board: looking for a job, or hiring (can post jobs).')
    llmd_role_date = fields.Datetime(string='Role chosen on', copy=False, readonly=True)
    llmd_linkedin = fields.Char(string='Company LinkedIn')
    llmd_post_count = fields.Integer(string='Jobs posted', compute='_compute_llmd_post_count')

    def _compute_llmd_post_count(self):
        Listing = self.env['llmd.job.listing'].sudo().with_context(active_test=False)
        users = self.env['res.users'].sudo().with_context(active_test=False).search([('partner_id', 'in', self.ids)])
        counts = dict(Listing._read_group([('poster_id', 'in', users.ids), ('post_kind', '=', 'employer')], ['poster_id'], ['__count']))
        by_partner = {u.partner_id.id: counts.get(u, 0) for u in users}
        for rec in self:
            rec.llmd_post_count = by_partner.get(rec.id, 0)

    @api.model
    def llmd_set_role(self, partner, role, hirer_vals=None):
        """Save the role (and a hirer's details) on the person's contact."""
        if role not in dict(ROLES):
            return False
        vals = dict(hirer_vals or {}) if role == 'hirer' else {}
        vals.update(llmd_role=role, llmd_role_date=fields.Datetime.now())
        partner.sudo().write(vals)
        return True

    def action_llmd_posts(self):
        self.ensure_one()
        users = self.env['res.users'].sudo().with_context(active_test=False).search([('partner_id', '=', self.id)])
        action = self.env['ir.actions.act_window']._for_xml_id('llmd_job_aggregator.llmd_job_post_employer_action')
        action['domain'] = [('post_kind', '=', 'employer'), ('poster_id', 'in', users.ids)]
        action['context'] = {'active_test': False, 'create': False}
        return action
