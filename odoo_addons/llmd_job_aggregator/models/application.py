"""Job applications (Recruitment > Job Applications).

An APPLICATION is something we really know about:
Each record keeps the name and e-mail and (through the Odoo applicant) the resume - no phone number (switched off again in 19.0.36).
* an applicant that an authorized provider integration sent to our API (X-Api-Key) - state `confirmed`, channel `provider`. A job provider that does not send applicants never
  produces a record here: names and e-mails are never made up and never taken from a click;
* an applicant of Odoo's own application form of one of OUR positions (website_hr_recruitment) - state `submitted`, channel `own`;
* a SIGNED-IN visitor who clicked Apply Now - channel `apply_now` ("Apply Now (signed in)"), state `submitted` ("Received", like every application that reaches us).
  Name, e-mail and user ID come from their own account. The channel and the Application Type ("External Apply Click") tell it apart from an application sent through a
  form: whether they finished the application on the employer's site is not known - a recruiter or an authorized provider makes it "Confirmed";
* records of the earlier versions of this module (our own form, "I applied" reports) stay as they were.

Every click on "Apply Now" is also a line of `llmd.job.click` (Apply Clicks: the job and the time only, no name or e-mail).

One record per job and person (SQL unique on job_key + identity_key, the identity is the e-mail).
"""
import base64
import logging
import os
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import consteq
from odoo.tools.misc import hmac

from . import apply_utils as A
from . import board_config as C
from . import job_facets as F

_logger = logging.getLogger(__name__)

STATES = [('clicked', 'Apply Clicked'), ('redirected', 'Redirected to External Site'), ('submitted', 'Received'), ('reported', 'Applicant said they applied (earlier version, not verified)'), ('confirmed', 'Confirmed'), ('withdrawn', 'Withdrawn')]
CHANNELS = [('own', 'Our website (Odoo form)'), ('recruiter', 'Added in Odoo / by e-mail'), ('provider', 'Job provider (API)'), ('external', "Applicant's own report (old)"), ('apply_now', 'Apply Now (signed in)')]
CLICK_WINDOW = 30                                    # seconds: the same account's Apply Now twice in a row (a redirect to our own form, a double click) is one event

HOURLY_LIMIT = 30                                    # applications one browser can send per hour
# the fields of the form whose row is hidden when the record has no value for them (empty, False, 0 or only spaces) - see llmd_blank
FORM_FIELDS = ('applicant_name', 'email', 'resume_count', 'application_type', 'channel', 'application_date', 'clicked_at', 'click_count', 'confirmed_date', 'confirmed_via', 'provider_ref', 'job_title', 'company', 'department', 'job_type', 'experience_required', 'location', 'posted_type', 'internal_job_id', 'ext_id', 'source', 'apply_url', 'message')


class HrJob(models.Model):
    _inherit = 'hr.job'

    llmd_listing_id = fields.Many2one('llmd.job.listing', string='Job board listing', ondelete='set null', index=True, copy=False, readonly=True,
                                      help='The externally fetched job this position was created for: the applications that arrive through our application form are filed under it.')


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    llmd_application_ids = fields.One2many('llmd.job.application', 'applicant_id', string='Job application tracking')

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('llmd_skip_track') and {'partner_name', 'email_from', 'job_id'} & set(vals):
            for applicant in self:
                try:
                    with self.env.cr.savepoint():
                        self.env['llmd.job.application'].sudo()._sync_stock_applicant(applicant)
                except Exception:                                   # never break the recruiter's edit because of the tracking
                    _logger.exception('job application tracking: applicant %s could not be synchronized', applicant.id)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        applicants = super().create(vals_list)
        if not self.env.context.get('llmd_skip_track'):
            for applicant in applicants:
                try:
                    with self.env.cr.savepoint():
                        self.env['llmd.job.application'].sudo()._track_stock_applicant(applicant)
                except Exception:                                   # never break Odoo's own application form because of the tracking
                    _logger.exception('job application tracking: applicant %s could not be tracked', applicant.id)
        return applicants


class LlmdJobApplication(models.Model):
    _name = 'llmd.job.application'
    _description = 'Job application'
    _inherit = ['mail.thread']
    _order = 'activity_date desc nulls last, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    applicant_name = fields.Char(string='Applicant Name', tracking=True)
    email = fields.Char(string='Email', index=True, tracking=True)
    phone = fields.Char(string='Phone', help='Not collected any more (19.0.36): kept only so that values saved by 19.0.34 are not lost. Not shown, not filled.')
    user_id = fields.Many2one('res.users', string='User', ondelete='set null', index=True, readonly=True, help='The signed-in website account that clicked Apply Now.')
    clicked_at = fields.Datetime(string='Apply Clicked At', readonly=True, help='The last time this account clicked Apply Now for this job.')
    click_count = fields.Integer(string='Apply Clicks', readonly=True, default=0)
    internal_job_id = fields.Integer(string='Internal Job ID', compute='_compute_internal_job_id', store=True,
                                     help='The ID of the job in Odoo: the job board listing (/jobs/ext/<id>), else our own position.')
    activity_date = fields.Datetime(string='Date', compute='_compute_activity_date', store=True, index=True, help='Application date, else the Apply Now click.')
    # the job: links + a snapshot (so that the history stays complete when a listing is hidden or removed)
    listing_id = fields.Many2one('llmd.job.listing', string='Job board listing', ondelete='set null', index=True)
    hr_job_id = fields.Many2one('hr.job', string='Job position', ondelete='set null', index=True)
    applicant_id = fields.Many2one('hr.applicant', string='Odoo applicant', ondelete='set null', index=True, copy=False)
    job_title = fields.Char(string='Job Title', required=True)
    company = fields.Char(string='Company')
    location = fields.Char()
    source = fields.Char(string='Source', help='Internal only: never shown on the website.')
    ext_id = fields.Char(string='External Job ID', index=True)
    apply_url = fields.Char(string='Original apply URL')
    department = fields.Char(string='Department', help="The team the company files the job under, as the job gives it.")
    job_type = fields.Char(string='Job Type', help='Full-time, Part-time, Internship, Contract - as the job gives it.')
    experience_required = fields.Char(string='Experience Required',
                                      help='As the job gives it: the years its text asks for ("3–5 yrs"), else the provider\'s own label; empty when the job states none.')
    posted_type = fields.Selection(C.POSTED_TYPES, string='Posted Type', help='Fetched: an external API / provider job. Public User: a job a public user posted.')
    application_type = fields.Selection(C.APPLICATION_TYPES, string='Application Type', compute='_compute_application_type', store=True, index=True,
                                        help='Website Form: the person sent our website\'s application form. A click on an external Apply Now is never an application (see Apply Clicks).')
    job_key = fields.Char(required=True, index=True, copy=False)
    identity_key = fields.Char(required=True, index=True, copy=False, help='e:<e-mail> (or a:<applicant id> when there is no e-mail).')
    channel = fields.Selection(CHANNELS, string='Channel', default='provider', required=True, tracking=True)
    state = fields.Selection(STATES, string='Application Status', default='confirmed', required=True, tracking=True, index=True)
    application_date = fields.Datetime(string='Application Date', help='When the application reached us (from the provider integration, or Odoo\'s own form).')
    confirmed_date = fields.Datetime(readonly=True)
    confirmed_via = fields.Char(readonly=True)
    visitor_key = fields.Char(index=True, copy=False, help='Random browser id of the application form (cookie llmd_vid): it only limits how many applications one browser can send.')
    provider_ref = fields.Char(string='Provider reference', help="The provider's own id of this application, as they sent it.")
    active = fields.Boolean(default=True)
    message = fields.Text()
    resume_count = fields.Integer(compute='_compute_resume_count', string='Resumes')
    job_type_label = fields.Char(string='Job Type', compute='_compute_job_type_label',
                                 help='The job type as the job gives it (Full-time, Contract ...), "Not specified" when it gives none. Shown only: the stored Job Type stays as it is.')
    experience_label = fields.Char(string='Experience Required', compute='_compute_experience_label',
                                   help='The experience as the job gives it ("3–5 yrs"), "Not specified" when it gives none. Shown only: the stored Experience Required stays as it is.')
    llmd_blank = fields.Char(compute='_compute_llmd_blank', string='Empty fields', help='Technical, for the form: ",name,name," of the fields this record has no value for. Not stored.')

    _job_identity_uniq = models.Constraint('unique(job_key, identity_key)', 'This person has already been recorded for this job.')

    def write(self, vals):
        """An apply link changed by hand must be a full http(s) link (or empty)."""
        from .click import check_apply_url
        check_apply_url(vals)
        return super().write(vals)

    @api.depends('channel', 'apply_url')
    def _compute_application_type(self):
        for rec in self:
            external = rec.channel == 'apply_now' and (rec.apply_url or '').startswith(('https://', 'http://'))
            rec.application_type = 'website_form' if rec.channel == 'own' else 'external_apply_click' if external else False

    @api.depends('listing_id', 'hr_job_id')
    def _compute_internal_job_id(self):
        for rec in self:
            rec.internal_job_id = rec.listing_id.id or rec.hr_job_id.id or 0

    @api.depends('application_date', 'clicked_at')
    def _compute_activity_date(self):
        for rec in self:
            rec.activity_date = rec.application_date or rec.clicked_at

    @api.depends('applicant_name', 'job_title')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s - %s' % (rec.applicant_name or 'Applicant', rec.job_title or '')

    @api.depends('job_type')
    def _compute_job_type_label(self):
        for rec in self:
            rec.job_type_label = (rec.job_type or '').strip() or 'Not specified'

    @api.depends('experience_required')
    def _compute_experience_label(self):
        for rec in self:
            rec.experience_label = (rec.experience_required or '').strip() or 'Not specified'

    @api.depends(*[f for f in FORM_FIELDS if f != 'resume_count'])
    def _compute_llmd_blank(self):
        """The form hides the row of every field listed here (invisible="',job_type,' in llmd_blank"): no value, False, 0 or only spaces. Nothing is filled in."""
        for rec in self:
            empty = []
            for name in FORM_FIELDS:
                value = rec[name]
                if isinstance(value, models.BaseModel):
                    value = value.ids
                if isinstance(value, str):
                    value = value.strip()
                if not value:
                    empty.append(name)
            rec.llmd_blank = ',%s,' % ','.join(empty)

    def _compute_resume_count(self):
        for rec in self:
            rec.resume_count = self.env['ir.attachment'].sudo().search_count([('res_model', '=', 'hr.applicant'), ('res_id', '=', rec.applicant_id.id)]) if rec.applicant_id else 0

    # ------------------------------------------------------------------ the job of a record or of a click
    @api.model
    def job_info(self, listing=None, job=None):
        """The link + snapshot values for an externally fetched listing, for the position made for one, or for one of our own positions (hr.job)."""
        listing = listing or (job.llmd_listing_id if job else None)
        if listing:
            return {'listing_id': listing.id, 'hr_job_id': job.id if job else False, 'job_title': listing.title, 'company': listing.company or '', 'location': listing.location or '', 'source': listing.source,
                    'ext_id': listing.ext_id, 'apply_url': listing.safe_apply_url(), 'job_key': 'ext:%s:%s' % (listing.source, listing.ext_id), 'posted_type': listing.posted_type or False}
        from .listing import valid_url
        return {'listing_id': False, 'hr_job_id': job.id, 'job_title': job.name, 'company': job.company_id.name or '', 'location': job.sudo().address_id.city or '', 'source': 'LLM Decode',
                'ext_id': str(job.id), 'apply_url': valid_url(job.apply_url), 'job_key': 'hr.job:%d' % job.id, 'posted_type': job.sudo().llmd_posted_type or False}

    @api.model
    def job_details(self, listing=None, job=None):
        """Department, Job Type and Experience Required of a job, as the job itself gives them (an application keeps them; a click does not need them)."""
        listing = listing or (job.llmd_listing_id if job else None)
        if listing:
            raw = (listing.categories or '').strip()                    # a company board's own department name; other sources send a list of tags there
            return {'department': (raw if raw and ',' not in raw and len(raw) <= 60 else '') or listing.function_label or False,
                    'job_type': F.TYPE_LABELS.get(listing.job_type) or (listing.employment_type or '').strip() or False,
                    'experience_required': listing.experience_required() or False}
        if not job:
            return {}
        job = job.sudo()
        contract = job.contract_type_id.name if 'contract_type_id' in job._fields and job.contract_type_id else False
        return {'department': job.department_id.name or False, 'job_type': contract, 'experience_required': False}

    # ------------------------------------------------------------------ finding / creating the one record of a person and a job
    @api.model
    def _find(self, job_key, identities):
        return self.sudo().with_context(active_test=False).search([('job_key', '=', job_key), ('identity_key', 'in', identities)], order='id', limit=1)

    @api.model
    def _get_or_create(self, info, identity, vals):
        """The record of this identity for this job, created when missing. Two requests at the same moment cannot make two records (unique constraint -> use the first one)."""
        rec = self._find(info['job_key'], [identity])
        if rec:
            return rec, False
        try:
            details = self.job_details(listing=self.env['llmd.job.listing'].sudo().browse(info.get('listing_id') or []) or None,
                                       job=self.env['hr.job'].sudo().browse(info.get('hr_job_id') or []) or None)
            with self.env.cr.savepoint():
                return self.sudo().with_context(mail_create_nolog=True).create(dict(info, identity_key=identity, **dict(details, **vals))), True
        except Exception:
            rec = self._find(info['job_key'], [identity])
            if not rec:
                raise
            return rec, False

    # ------------------------------------------------------------------ a signed-in visitor clicked Apply Now: one record per account and job, never "submitted"
    @api.model
    def record_apply_now(self, info, user, external):
        """The one Job Applications record of this signed-in account for this job, made by its first Apply Now: name, e-mail and user ID from the account itself,
        the job from `info` (job_info), status "Received" (every application that reaches us is), channel "Apply Now (signed in)". A later click only updates the time
        and the count - the status stays as it is (a recruiter's Confirmed or Withdrawn too). `external`: kept for the callers (the type follows the apply URL).
        Returns the record."""
        self = self.sudo()
        partner = user.partner_id
        email = (user.email or partner.email or '').strip().lower()
        identity = 'e:%s' % email if A.valid_email(email) else 'u:%d' % user.id
        now = fields.Datetime.now()
        state = 'submitted'
        rec, created = self._get_or_create(info, identity, {'applicant_name': partner.name or user.name, 'email': email if A.valid_email(email) else False, 'user_id': user.id,
                                                            'channel': 'apply_now', 'state': state, 'clicked_at': now, 'click_count': 1})
        if not created:
            vals = {} if rec.clicked_at and (now - rec.clicked_at).total_seconds() < CLICK_WINDOW else {'click_count': rec.click_count + 1}
            vals['clicked_at'] = now
            if not rec.user_id:
                vals['user_id'] = user.id
            rec.write(vals)
        _logger.info('apply now saved in Job Applications: record %s (%s), %s', rec.id, rec.state, info['job_key'])
        return rec

    # ------------------------------------------------------------------ OUR application form of a job: saved in Odoo (applicant + resume + this record) before "received" is shown
    @api.model
    def _too_many(self, visitor):
        since = fields.Datetime.now() - timedelta(hours=1)
        return bool(visitor) and self.sudo().with_context(active_test=False).search_count([('visitor_key', '=', visitor), ('application_date', '>', since)]) >= HOURLY_LIMIT

    @api.model
    def _source_record(self, name):
        Source = self.env['utm.source'].sudo()
        return Source.search([('name', '=', name)], limit=1) or Source.create({'name': name})

    @api.model
    def submit_own(self, listing, vals, resume_name, resume_mimetype, resume_data, visitor=None):
        """-> (record, 'created' | 'duplicate'). `vals` = the validated form (apply_utils.validate). The applicant (Recruitment > Applications, filed under the position of the job), the resume and
        the record of Job Applications are saved in ONE savepoint: when anything fails nothing is saved and the error goes to the caller, who must NOT show a success message then."""
        self = self.sudo()
        info = self.job_info(listing=listing)
        email = (vals['email'] or '').strip().lower()
        identity = 'e:%s' % email
        duplicate = self._find(info['job_key'], [identity])
        # already received through a form (an Apply Now record - Received, but no applicant yet - gets the application, the applicant and the resume now)
        if duplicate and (duplicate.applicant_id or (duplicate.state in ('submitted', 'confirmed') and duplicate.channel != 'apply_now')):
            return duplicate, 'duplicate'
        with self.env.cr.savepoint():
            hr_job = listing.ensure_job()
            twin = self.env['hr.applicant'].sudo().with_context(active_test=False).search([('job_id', '=', hr_job.id), ('email_from', '=ilike', email)], limit=1)
            if twin:                                          # the same person is already an applicant of this job: only link it
                rec = duplicate or self._get_or_create(info, identity, {'channel': 'own', 'state': 'submitted'})[0]
                rec.write({'applicant_id': twin.id, 'state': 'submitted', 'channel': 'own', 'application_date': rec.application_date or fields.Datetime.now()})
                return rec, 'duplicate'
            note = Markup('<p><b>Application sent through the LLM Decode website.</b></p><ul><li><b>Job:</b> %s</li><li><b>Company:</b> %s</li><li><b>External job ID:</b> %s</li>') % (
                info['job_title'], info['company'] or '-', info['ext_id'])
            if info['apply_url']:
                note += Markup('<li><b>Original job link:</b> <a href="%s" target="_blank" rel="noopener noreferrer nofollow">%s</a></li>') % (info['apply_url'], info['apply_url'])
            note += Markup('</ul>')
            if vals.get('note'):
                note += Markup('<p><b>Message from the applicant:</b></p><p>%s</p>') % Markup('<br/>').join(vals['note'].split('\n'))
            applicant = self.env['hr.applicant'].sudo().with_context(llmd_skip_track=True, mail_create_nolog=True, mail_create_nosubscribe=True, mail_notrack=True).create({
                'partner_name': vals['name'], 'email_from': email, 'job_id': hr_job.id,
                'source_id': self._source_record(info['source']).id, 'applicant_notes': note})
            if resume_data:
                self.env['ir.attachment'].sudo().create({'name': resume_name, 'datas': base64.b64encode(resume_data), 'mimetype': resume_mimetype, 'res_model': 'hr.applicant', 'res_id': applicant.id, 'type': 'binary'})
            values = {'state': 'submitted', 'channel': 'own', 'applicant_id': applicant.id, 'hr_job_id': hr_job.id, 'application_date': fields.Datetime.now(), 'applicant_name': vals['name'],
                      'message': vals.get('note') or False, 'visitor_key': visitor or False}
            if duplicate:
                rec = duplicate
                rec.write(values)
            else:
                rec, new = self._get_or_create(info, identity, dict(values, email=email))
                if not new:
                    rec.write(values)
        _logger.info('job application saved: record %s, applicant %s, job %s', rec.id, applicant.id, info['job_key'])
        return rec, 'created'

    # ------------------------------------------------------------------ the confirmation link of the website (only for a record that is really saved)
    @api.model
    def token(self, record_id):
        return hmac(self.env(su=True), 'llmd_applied', int(record_id))[:32]

    @api.model
    def token_ok(self, record_id, token):
        return bool(token) and consteq(self.token(record_id), str(token))

    # ------------------------------------------------------------------ an Odoo applicant (website form of one of our positions, a recruiter, an incoming e-mail) -> one record here
    @api.model
    def _applicant_channel(self):
        """'own' when the applicant is created by a website form (the person applied on our site), otherwise 'recruiter' (typed in the backend or created from an e-mail)."""
        try:
            return 'own' if request.httprequest.path.startswith('/website/form') else 'recruiter'
        except Exception:                                           # no web request: the ORM, a scheduled action or the mail gateway
            return 'recruiter'

    @api.model
    def _track_stock_applicant(self, applicant):
        job = applicant.job_id
        if not job:
            return
        info = self.job_info(job=job)
        email = (applicant.email_from or '').strip().lower()
        identity = 'e:%s' % email if email else 'a:%d' % applicant.id
        rec = self._find(info['job_key'], [identity])
        values = {'state': 'submitted', 'channel': self._applicant_channel(), 'applicant_id': applicant.id, 'application_date': fields.Datetime.now(), 'applicant_name': applicant.partner_name, 'email': email or False,
                  'hr_job_id': job.id}
        if rec:
            if rec.state not in ('confirmed',):
                rec.write(values)
        else:
            self._get_or_create(info, identity, values)

    @api.model
    def _sync_stock_applicant(self, applicant):
        """The recruiter changed the name or e-mail of an applicant (or gave it a job): the record follows, so the list stays right. A new e-mail that another record of the
        same job already uses is not taken over (that would be a duplicate)."""
        recs = self.sudo().with_context(active_test=False).search([('applicant_id', '=', applicant.id)])
        if not recs:
            return self._track_stock_applicant(applicant)
        email = (applicant.email_from or '').strip().lower()
        for rec in recs:
            values = {'applicant_name': applicant.partner_name}
            if email and email != (rec.email or ''):
                if not self._find(rec.job_key, ['e:%s' % email]):
                    values.update(email=email, identity_key='e:%s' % email)
            rec.write(values)

    # ------------------------------------------------------------------ the people in the back office
    def action_confirm(self):
        for rec in self:
            if rec.state == 'withdrawn':
                raise UserError('A withdrawn application cannot be confirmed.')
            rec.write({'state': 'confirmed', 'confirmed_date': fields.Datetime.now(), 'confirmed_via': 'recruiter', 'application_date': rec.application_date or fields.Datetime.now()})       # a recruiter knows it was submitted
        return True

    def action_withdraw(self):
        self.write({'state': 'withdrawn'})
        return True

    def action_receive(self):
        """Back to "Received" (for example a withdrawn application the person sent again)."""
        self.write({'state': 'submitted'})
        return True

    def action_open_applicant(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.applicant', 'res_id': self.applicant_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_open_listing(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'llmd.job.listing', 'res_id': self.listing_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_open_job(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.job', 'res_id': self.hr_job_id.id, 'view_mode': 'form', 'target': 'current'}

    # ------------------------------------------------------------------ the JSON API of an authorized provider integration
    @api.model
    def api_key_ok(self, key):
        expected = (os.environ.get('LLMD_APPLICATION_API_KEY') or self.env['ir.config_parameter'].sudo().get_param('llmd_agg.application_api_key') or '').strip()
        return bool(expected) and bool(key) and consteq(expected, str(key))

    @api.model
    def _resolve_job(self, ref):
        """{'listing_id': 1} | {'source': 'Jooble', 'ext_id': '123'} | {'hr_job_id': 2} -> (listing, hr.job) or raises ValueError('job_not_found')."""
        Listing, Job = self.env['llmd.job.listing'].sudo(), self.env['hr.job'].sudo()
        if not isinstance(ref, dict):
            raise ValueError('job_not_found')
        listing = job = None
        try:
            if ref.get('listing_id'):
                listing = Listing.search([('id', '=', int(ref['listing_id'])), ('active', '=', True)], limit=1)
            elif ref.get('source') and ref.get('ext_id'):
                listing = Listing.search([('source', '=', str(ref['source'])[:80]), ('ext_id', '=', str(ref['ext_id'])[:200]), ('active', '=', True)], limit=1)
            elif ref.get('hr_job_id'):
                job = Job.search([('id', '=', int(ref['hr_job_id'])), ('website_published', '=', True)], limit=1)
        except (TypeError, ValueError):
            raise ValueError('job_not_found')
        if not (listing or job):
            raise ValueError('job_not_found')
        return listing or None, job or None

    @api.model
    def process_api(self, payload, authorized=False):
        """The one entry point behind POST /api/llmd/applications. Returns a plain dict {ok, status, ...}; problems are an answer, not an exception.
        Only a caller with the API key can add applicant data: the job provider tells us "this person applied to this job" (`applicant`, the older name `confirm` means the same).
        Whatever the provider did not send stays empty: nothing about the applicant is guessed. A phone it sends is not kept."""
        if not authorized:
            return {'ok': False, 'error': 'unauthorized', 'message': 'A valid API key is required: applicant data is only accepted from an authorized provider integration.'}
        action = str(payload.get('action') or 'applicant').lower()
        if action not in ('applicant', 'confirm'):
            return {'ok': False, 'error': 'unknown_action', 'message': 'action must be applicant'}
        try:
            listing, job = self._resolve_job(payload.get('job'))
        except ValueError:
            return {'ok': False, 'error': 'job_not_found', 'message': 'No active job matches this reference.'}
        vals, errors = A.validate(payload, consent_required=False)
        if errors:
            return {'ok': False, 'error': 'validation', 'fields': errors}
        info = self.job_info(listing=listing, job=job)
        now = fields.Datetime.now()
        rec = self._find(info['job_key'], ['e:%s' % vals['email']])
        if rec and rec.state == 'withdrawn':
            return {'ok': False, 'error': 'withdrawn', 'message': 'This application was withdrawn.'}
        values = {'applicant_name': vals['name'], 'message': vals['note'] or False, 'provider_ref': A.one_line(payload.get('provider_ref'), 120) or False}
        if rec:
            values = {k: v for k, v in values.items() if v}
            if rec.state != 'confirmed':
                values.update(state='confirmed', confirmed_date=now, confirmed_via='api', application_date=rec.application_date or now)
            rec.write(values)
            return {'ok': True, 'status': 'updated', 'id': rec.id, 'state': rec.state}
        rec, _new = self._get_or_create(info, 'e:%s' % vals['email'], dict(values, email=vals['email'], channel='provider', state='confirmed', application_date=now, confirmed_date=now, confirmed_via='api'))
        return {'ok': True, 'status': 'created', 'id': rec.id, 'state': rec.state}
