"""The Apply Now click log (Recruitment > Apply Clicks).

Every time a person clicks "Apply Now" on a job, one line is saved here BEFORE they are sent on to the employer's own application page: when, which job (title, company, source,
external job ID, original apply URL) and the status - no name and no e-mail: the signed-in person's name, e-mail and user ID are kept in Job Applications
(`llmd.job.application.record_apply_now`, status "Redirected to External Site"). A click line only keeps the account's user ID (to tell repeat clicks apart).
The columns `applicant_name` / `email` of 19.0.33 stay in the table for the lines saved then; they are no longer filled or shown.
A click is only a click: we cannot know whether the person then applied on the other site, so nothing here is an application and no click ever becomes one.
Applications are `llmd.job.application` (our own form, Odoo's form of our positions, or an authorized provider integration).
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .board_config import APPLICATION_TYPES, POSTED_TYPES

_logger = logging.getLogger(__name__)

STATUSES = [('clicked', 'Clicked'), ('no_link', 'No apply link')]


def check_apply_url(vals):
    """Refuse an apply link written by hand that is not a plain http(s) link (javascript:, a relative or broken address)."""
    from .listing import valid_url
    url = (vals.get('apply_url') or '').strip() if 'apply_url' in vals else ''
    if url and not valid_url(url):
        raise ValidationError('The apply link must be a full http(s) link, e.g. https://careers.example.com/job/123.')


HOURLY_LIMIT = 120                                   # lines one browser can add per hour (a script cannot fill the table)


class LlmdJobClick(models.Model):
    _name = 'llmd.job.click'
    _description = 'Apply Now click'
    _order = 'clicked_at desc, id desc'

    clicked_at = fields.Datetime(string='Clicked at', required=True, default=fields.Datetime.now, index=True, readonly=True)
    status = fields.Selection(STATUSES, default='clicked', required=True, index=True, readonly=True)
    # the job: links + a snapshot (so that the history stays complete when a listing is hidden or removed)
    listing_id = fields.Many2one('llmd.job.listing', string='Job board listing', ondelete='set null', index=True, readonly=True)
    hr_job_id = fields.Many2one('hr.job', string='Our position', ondelete='set null', index=True, readonly=True)
    job_title = fields.Char(required=True, readonly=True)
    company = fields.Char(readonly=True)
    location = fields.Char(readonly=True)
    source = fields.Char(string='Source', readonly=True, help='Internal only: never shown on the website.')
    ext_id = fields.Char(string='External job ID', index=True, readonly=True)
    apply_url = fields.Char(string='Original apply URL', help='The application link the click opened. A Recruitment manager can correct it (a full http(s) link, or empty).')
    job_key = fields.Char(required=True, index=True, readonly=True)
    visitor_key = fields.Char(index=True, readonly=True, help='A random id in a first-party cookie. It is not a name, an e-mail or an IP address; it only shows that two clicks came from the same browser.')
    repeat = fields.Boolean(string='Repeat click', readonly=True, help='The same browser or the same account had already clicked Apply Now on this job.')
    user_id = fields.Many2one('res.users', string='User', ondelete='set null', index=True, readonly=True, help='Only to tell repeat clicks of one account apart. Name and e-mail are in Job Applications.')
    applicant_name = fields.Char(string='Name (19.0.33)', readonly=True, help='Only filled by version 19.0.33; name and e-mail are kept in Job Applications now.')
    email = fields.Char(string='Email (19.0.33)', readonly=True, help='Only filled by version 19.0.33; name and e-mail are kept in Job Applications now.')
    posted_type = fields.Selection(POSTED_TYPES, string='Posted Type', readonly=True, help='Fetched: an external API / provider job. Public User: a job a public user posted.')
    application_type = fields.Selection(APPLICATION_TYPES, string='Application Type', compute='_compute_application_type', store=True, index=True,
                                        help='External Apply Click: the person was sent on to the original application page. This is a click, never an application.')

    def write(self, vals):
        """A link changed by hand must be a full http(s) link (or empty), the same rule as the job board listings."""
        check_apply_url(vals)
        return super().write(vals)

    @api.depends('apply_url', 'status')
    def _compute_application_type(self):
        for rec in self:
            external = (rec.apply_url or '').startswith(('https://', 'http://'))
            rec.application_type = 'external_apply_click' if rec.status == 'clicked' and external else False

    @api.depends('job_title', 'company', 'clicked_at')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.job_title or '', rec.company or '') if rec.company else (rec.job_title or '')

    @api.model
    def record_click(self, listing=None, job=None, visitor=None, url=None, user=None):
        """Save one click on "Apply Now" of an externally fetched `listing` or of one of our own positions (`job`); `url` = where the visitor is really sent when that
        is not the saved apply URL (our own form); `user` = the signed-in account: only its user ID is kept on the line (repeat clicks; the person is in Job Applications).
        Returns the new line, or an empty recordset when this browser has reached the hourly limit (the visitor is sent on all the same: counting never blocks anybody)."""
        self = self.sudo()
        info = self.env['llmd.job.application'].job_info(listing=listing, job=job)
        if url:
            info['apply_url'] = url
        now = fields.Datetime.now()
        repeat = False
        if visitor:
            if self.search_count([('visitor_key', '=', visitor), ('clicked_at', '>', now - timedelta(hours=1))]) >= HOURLY_LIMIT:
                _logger.warning('apply clicks: one browser reached %d clicks in an hour, this one is not saved', HOURLY_LIMIT)
                return self.browse()
            repeat = bool(self.search([('visitor_key', '=', visitor), ('job_key', '=', info['job_key'])], limit=1))
        person = {}
        if user and not user._is_public():
            person = {'user_id': user.id}
            repeat = repeat or bool(self.search([('user_id', '=', user.id), ('job_key', '=', info['job_key'])], limit=1))      # the same person, also from another browser
        rec = self.create(dict(info, clicked_at=now, status='clicked' if info['apply_url'] else 'no_link', visitor_key=visitor or False, repeat=repeat, **person))
        _logger.info('apply click saved: %s (%s)', rec.job_key, rec.status)
        return rec
