"""Jobs posted on the website itself, next to the synced ones:
- by the LLM Decode team (Recruitment > Job board > Our posts): live at once, shown in "Posted by LLM Decode" (/jobs and /jobs/llmdecode);
- by an employer / HR (/jobs/post, free, after a sign-in): "Pending review" until a Recruitment manager approves it, then live with "Posted by employer".
They are llmd.job.listing records like every other job (same cards, detail page, filters, Apply Now), with source 'llmdecode' / 'employer' (listing.OWN_SOURCES:
no sync ever hides or changes them). A post closes itself POST_DAYS days after it went live (_cron_expire_posts)."""
import logging
import re
import secrets
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import board_config as C
from . import job_facets as F
from .listing import valid_url

_logger = logging.getLogger(__name__)

POST_KINDS = [('llmdecode', 'LLM Decode'), ('employer', 'Employer')]
POST_STATES = [('pending', 'Pending review'), ('live', 'Live'), ('rejected', 'Rejected'), ('closed', 'Closed')]
POST_DAYS = 30                                          # a post is open this long after it went live
MAX_OPEN_POSTS = 5                                      # pending + live posts one employer account may have at once (free posting, no spam)
POST_FIELDS = ('title', 'company', 'location', 'description_html')
POST_DEPARTMENTS = [(key, label) for key, label, _rx in C.JOB_FUNCTIONS]       # the Department of a post = a Job Function of the board       # a change of these works out the categories, roles and summary again


def text_to_html(text):
    """Plain text an employer typed -> safe HTML paragraphs (a line starting with "-" or "•" becomes a list item)."""
    out, items = [], []
    for line in (text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if line[:1] in ('-', '•', '*'):
            items.append(Markup('<li>%s</li>') % line.lstrip('-•* ').strip())
            continue
        if items:
            out.append(Markup('<ul>%s</ul>') % Markup('').join(items))
            items = []
        if line:
            out.append(Markup('<p>%s</p>') % line)
    if items:
        out.append(Markup('<ul>%s</ul>') % Markup('').join(items))
    return str(Markup('').join(out))


class LlmdJobPost(models.Model):
    _inherit = 'llmd.job.listing'

    post_paid = fields.Boolean(string='Paid with a job credit', copy=False, readonly=True)
    # what the employer typed in the form (to fill the form again when the job is edited)
    post_description = fields.Text(string='Description as typed', copy=False)
    post_experience = fields.Char(string='Experience as typed', copy=False)
    post_skills = fields.Char(string='Skills as typed', copy=False)
    post_kind = fields.Selection(POST_KINDS, string='Posted by', index=True, readonly=True, copy=False,
                                 help='Empty for a job of the sync. LLM Decode: our team posted it. Employer: an employer posted it on the website (/jobs/post).')
    post_state = fields.Selection(POST_STATES, string='Post status', index=True, copy=False, readonly=True)
    poster_id = fields.Many2one('res.users', string='Posted by (account)', index=True, ondelete='set null', readonly=True, copy=False)
    contact_email = fields.Char(string='Employer e-mail', help='Where the employer is told about the review and about new applications.')
    pinned = fields.Boolean(string='Pinned', help='Stays at the top of "Posted by LLM Decode".')
    apply_how = fields.Selection([('form', 'LLM Decode application form'), ('link', "Employer's own application link")], string='How people apply', default='form')
    expires_on = fields.Date(string='Open until', copy=False, help='The post closes itself after this day.')
    reject_reason = fields.Char(string='Reason (rejected)')
    post_department = fields.Selection(POST_DEPARTMENTS, string='Department', help='The team the job is in: the Department filter and pages (/departments/...) of the board.')
    jd_attachment_id = fields.Many2one('ir.attachment', string='Job description (PDF)', ondelete='set null', copy=False, readonly=True)
    jd_url = fields.Char(string='Job posting link', help="The employer's own page of this job (shown on the job page as Original job posting).")

    # ------------------------------------------------------------------ create / write
    @api.model_create_multi
    def create(self, vals_list):
        """A post (post_kind set) gets its own source and ID, the categories / roles / summary worked out from its text like a synced job, and its status:
        an LLM Decode post is live at once, an employer's post waits for the review (hidden until then)."""
        today = fields.Date.context_today(self)
        for vals in vals_list:
            kind = vals.get('post_kind') or self.env.context.get('default_post_kind')
            if not kind:
                continue
            vals['post_kind'] = kind
            vals.setdefault('source', kind)
            vals.setdefault('ext_id', 'post-%s' % secrets.token_hex(6))
            vals.setdefault('posted', fields.Datetime.now())
            vals.setdefault('fetched_at', fields.Datetime.now())
            vals['full_text'] = True
            live = kind == 'llmdecode'
            vals.setdefault('post_state', 'live' if live else 'pending')
            vals['active'] = vals['post_state'] == 'live'
            if live:
                vals.setdefault('expires_on', today + timedelta(days=POST_DAYS))
            for key, value in self._post_derived(vals).items():
                vals.setdefault(key, value)
            if vals.get('post_department'):
                vals['categories'] = dict(POST_DEPARTMENTS).get(vals['post_department'], '')
        records = super().create(vals_list)
        posts = records.filtered('post_kind')
        if posts:
            posts._post_place()
            posts._post_skills()
        return records

    @api.model
    def _llmd_fix_post_places(self):
        """Module update: the posts saved before v19.0.74 get their city too."""
        self.with_context(active_test=False).search([('post_kind', '!=', False)])._post_place()

    def _post_place(self):
        """The city / India of a post from its location ("Gurugram, India"), like a synced job. A post's form gives its work mode, job type and level, and
        Odoo then skips the rest of that computation - so the place is worked out here (the Location, City, Region pages and filters need it)."""
        for rec in self:
            facets = F.facets(rec.title, rec.location, rec.countries, rec.employment_type, rec.seniority, '')
            vals = {k: facets[k] for k in ('city', 'india') if facets[k] and facets[k] != rec[k]}
            if vals:
                super(LlmdJobPost, rec.with_context(llmd_sync=True)).write(vals)

    def write(self, vals):
        if 'post_department' in vals:
            vals['categories'] = dict(POST_DEPARTMENTS).get(vals['post_department'], '') if vals['post_department'] else ''
        # an edit of a post's text (e.g. by our team in the backend) re-runs the work mode / job type / level guess from the text: keep what the
        # employer chose in the form instead (only a field that is not written here and has a value)
        keep = {}
        if {'description_html', 'title', 'location', 'countries', 'employment_type', 'seniority'} & set(vals) and not self.env.context.get('llmd_sync'):
            for rec in self.filtered('post_kind'):
                kept = {f: rec[f] for f in ('work_mode', 'job_type', 'exp_level') if f not in vals and rec[f]}
                if kept:
                    keep[rec.id] = kept
        res = super().write(vals)
        for rec_id, kept in keep.items():
            rec = self.browse(rec_id)
            changed = {f: v for f, v in kept.items() if rec[f] != v}
            if changed:
                super(LlmdJobPost, rec.with_context(llmd_sync=True)).write(changed)
        if 'location' in vals and not self.env.context.get('llmd_post_derived'):
            self.filtered('post_kind')._post_place()
        if not self.env.context.get('llmd_post_derived') and set(POST_FIELDS) & set(vals):
            for rec in self.filtered('post_kind'):
                rec.with_context(llmd_post_derived=True, llmd_sync=True).write(self._post_derived({f: rec[f] for f in POST_FIELDS}))
            self.filtered('post_kind')._post_skills()
        return res

    @api.model
    def _post_derived(self, vals):
        """What the sync works out for a job (category chips, roles, courses, sections, short text, search text) - for a post, from what was typed."""
        job = {'source': 'post', 'ext_id': 'post', 'title': vals.get('title') or '', 'company': vals.get('company') or '', 'location': vals.get('location') or '',
               'html': vals.get('description_html') or '', 'full_text': True}
        prepared = self._prepare(job, keep=True) or {}
        keys = ('tags', 'roles', 'courses', 'role_type', 'sections_json', 'short_description', 'search_text', 'dedupe_key')
        return {k: prepared[k] for k in keys if k in prepared}

    def _post_skills(self):
        try:
            with self.env.cr.savepoint():
                self.link_odoo_skills()
        except Exception:                                               # the skills never stop a post from being saved
            _logger.warning('job posts %s: the skills could not be linked', self.ids, exc_info=True)

    @api.depends('source', 'post_kind')
    def _compute_posted_type(self):
        for rec in self:
            rec.posted_type = {'employer': 'public_user', 'llmdecode': 'llmdecode'}.get(rec.post_kind) or ('fetched' if rec.source else False)

    def apply_mode(self):
        """A post whose people apply on our form (or that has no valid link) always opens OUR application form; every other job follows llmd_agg.apply_mode."""
        if len(self) == 1 and self.post_kind and (self.apply_how == 'form' or not self.safe_apply_url()):
            return 'form'
        return super().apply_mode()

    def post_badge(self):
        """(label, css class) of the badge of a post on its card and its page, ('', '') for a synced job."""
        self.ensure_one()
        return {'llmdecode': ('LLM Decode pick', 'o_llmd_pick'), 'employer': ('Posted by employer', 'o_llmd_employer')}.get(self.post_kind, ('', ''))

    def detail_vals(self):
        vals = super().detail_vals()
        vals['post_badge'] = self.post_badge()
        vals['jd_pdf'] = '/jobs/jd/%d' % self.id if self.jd_attachment_id else ''
        vals['jd_url'] = valid_url(self.jd_url) if self.post_kind else ''
        return vals

    # ------------------------------------------------------------------ the review (Recruitment managers) and the employer's own buttons
    def action_approve(self):
        today = fields.Date.context_today(self)
        for rec in self.filtered(lambda r: r.post_kind and r.post_state in ('pending', 'rejected')):
            rec.write({'post_state': 'live', 'active': True, 'posted': fields.Datetime.now(), 'reject_reason': False, 'expires_on': today + timedelta(days=POST_DAYS)})
            rec._post_mail('Your job is live: %s' % rec.title,
                           Markup('<p>Your job <b>%s</b> was approved and is now live on the LLM Decode job board.</p><p>It stays open until %s. You see its applicants under My jobs.</p>') % (
                               rec.title, rec.expires_on))
        return True

    def action_reject(self):
        for rec in self.filtered(lambda r: r.post_kind == 'employer' and r.post_state in ('pending', 'live')):
            rec.write({'post_state': 'rejected', 'active': False})
            if rec.post_paid and rec.poster_id:                         # a paid post we do not publish: its credit goes back to the account
                partner = rec.poster_id.partner_id.sudo()
                partner.llmd_job_credits = (partner.llmd_job_credits or 0) + 1
                rec.post_paid = False
            reason = Markup('<p>Reason: %s</p>') % rec.reject_reason if rec.reject_reason else Markup('')
            rec._post_mail('Your job was not published: %s' % rec.title, Markup('<p>Your job <b>%s</b> was not published on the LLM Decode job board.</p>%s') % (rec.title, reason))
        return True

    def action_close(self):
        self.filtered(lambda r: r.post_kind and r.post_state == 'live').write({'post_state': 'closed', 'active': False})
        return True

    def action_reopen(self):
        """A closed post goes live again (for another POST_DAYS days) - an employer's post only when it was approved before (closed, never rejected)."""
        today = fields.Date.context_today(self)
        self.filtered(lambda r: r.post_kind and r.post_state == 'closed').write({'post_state': 'live', 'active': True, 'expires_on': today + timedelta(days=POST_DAYS)})
        return True

    @api.model
    def _cron_expire_posts(self):
        """Every day: a live post whose "Open until" has passed is closed (hidden; kept with its applicants)."""
        expired = self.search([('post_kind', '!=', False), ('post_state', '=', 'live'), ('expires_on', '<', fields.Date.context_today(self))])
        expired.write({'post_state': 'closed', 'active': False})
        return len(expired)

    # ------------------------------------------------------------------ the employer's side (/jobs/post, /jobs/my)
    @api.model
    def open_posts_of(self, user):
        return self.with_context(active_test=False).search_count([('poster_id', '=', user.id), ('post_kind', '=', 'employer'), ('post_state', 'in', ('pending', 'live'))])

    @api.model
    def max_open_of(self, user):
        """How many jobs this employer may have open (pending + live) at once: the post limit of the packages bought, else the default."""
        return max(MAX_OPEN_POSTS, user.partner_id.sudo().llmd_max_open or 0)

    @api.model
    def free_post_left(self, user):
        """The first job of an account is free (a rejected one does not count)."""
        return not self.with_context(active_test=False).search_count([('poster_id', '=', user.id), ('post_kind', '=', 'employer'), ('post_state', '!=', 'rejected')])

    @api.model
    def employer_post(self, user, form):
        """An employer's job from the /jobs/post form (already checked by validate_post) -> the new post, Pending review. The first job is free; a later one
        uses one job credit of the account (bought on the For companies page)."""
        if self.open_posts_of(user) >= self.max_open_of(user):
            raise UserError('You already have %d open jobs. Close one under My jobs before you post another.' % self.max_open_of(user))
        free = self.free_post_left(user)
        partner = user.partner_id.sudo()
        if not free and (partner.llmd_job_credits or 0) < 1:
            raise UserError('Your free job is used. Buy a plan on the For companies page to post more jobs.')
        vals = dict(self._post_form_vals(form), post_kind='employer', poster_id=user.id, contact_email=user.email or user.login)
        if not free:
            vals['post_paid'] = True
            partner.llmd_job_credits -= 1
        return self.sudo().create(vals)

    @api.model
    def employer_update(self, user, post, form):
        """The employer's edit of their own job (form already checked by validate_post). A pending or live job goes back to Pending review (hidden until
        our team approves it again - so nothing unchecked is shown); a rejected job is sent again, which counts like a new job (free job or a credit)."""
        post = post.sudo()
        if post.post_kind != 'employer' or post.poster_id != user or post.post_state not in ('pending', 'live', 'rejected'):
            raise UserError('This job cannot be edited. A closed job can be reopened from My jobs.')
        vals = self._post_form_vals(form, update=True)
        if post.post_state == 'rejected':
            if self.open_posts_of(user) >= self.max_open_of(user):
                raise UserError('You already have %d open jobs. Close one under My jobs before you send this one again.' % self.max_open_of(user))
            partner = user.partner_id.sudo()
            if not self.free_post_left(user):
                if (partner.llmd_job_credits or 0) < 1:
                    raise UserError('Sending this job again uses a job credit. Buy a plan on the For companies page.')
                partner.llmd_job_credits -= 1
                vals['post_paid'] = True
        vals.update(post_state='pending', active=False, reject_reason=False)
        post.write(vals)
        return post

    @api.model
    def _post_form_vals(self, form, update=False):
        """The listing values of a checked Post a job form (a new job, or an edit when `update`)."""
        html = text_to_html(form['description']) or str(Markup('<p>%s</p>') % (
            'The full description of this job is in the attached PDF.' if form.get('has_pdf') else 'The full description of this job is on the original job posting.'))
        if form.get('experience'):
            exp = form['experience'].strip()
            if re.fullmatch(r'\d{1,2}\s*(?:(?:-|–|to)\s*\d{1,2})?\s*\+?', exp):      # the form's field is in years: "0-2" -> "0-2 years"
                exp += ' years'
            html += str(Markup('<p>Experience: %s.</p>') % exp)
        if form.get('skills'):
            html += str(Markup('<h3>Skills</h3><ul>%s</ul>') % Markup('').join(Markup('<li>%s</li>') % s for s in form['skills']))
        vals = {'title': form['title'], 'company': form['company'],
                'location': form['location'], 'salary': form.get('salary') or '', 'description_html': html, 'apply_how': form['apply_how'],
                'apply_url': form.get('apply_url') or False, 'employment_type': F.TYPE_LABELS.get(form.get('job_type'), ''),
                'jd_url': form.get('jd_url') or False, 'source_url': form.get('jd_url') or False,
                'post_description': form.get('description') or False, 'post_experience': (form.get('experience') or '').strip() or False,
                'post_skills': ', '.join(form.get('skills') or []) or False}
        if form.get('department') in dict(POST_DEPARTMENTS):
            vals['post_department'] = form['department']
        for name in ('work_mode', 'job_type', 'exp_level'):
            if form.get(name):
                vals[name] = form[name]
            elif update:
                vals[name] = False
        return vals

    def employer_applications(self):
        """The applications people SENT for this post (our form), newest first - what the employer sees under My jobs."""
        self.ensure_one()
        return self.env['llmd.job.application'].sudo().with_context(active_test=False).search(
            [('listing_id', '=', self.id), ('state', 'in', ('submitted', 'confirmed')), ('applicant_id', '!=', False)], order='application_date desc, id desc')

    def notify_application(self, application):
        """Tell the employer of this post that somebody applied (name and e-mail; the resume is on My jobs)."""
        self.ensure_one()
        if self.post_kind != 'employer':
            return
        self._post_mail('New application: %s' % self.title, Markup('<p><b>%s</b> (%s) applied for your job <b>%s</b>.</p><p>See the application and the resume under My jobs on the LLM Decode job board.</p>') % (
            application.applicant_name or 'Someone', application.email or '-', self.title))

    def _post_mail(self, subject, body):
        """One e-mail to the employer of a post (queued; Odoo's mail queue sends it). Our own posts have nobody to tell."""
        self.ensure_one()
        to = self.contact_email or (self.poster_id.email if self.poster_id else '')
        if self.post_kind != 'employer' or not to:
            return
        try:
            with self.env.cr.savepoint():
                self.env['mail.mail'].sudo().create({'subject': subject, 'email_to': to, 'body_html': str(body), 'auto_delete': True,
                                                     'email_from': self.env.company.email_formatted or self.env.user.email_formatted or False})
        except Exception:                                               # an e-mail never stops the review
            _logger.warning('job post %s: the e-mail to the employer could not be queued', self.id, exc_info=True)


def clean_site(value):
    """An optional company website typed in the form -> (full link or '', error text or '')."""
    value = ' '.join((value or '').split())[:200]
    if not value:
        return '', ''
    if not re.match(r'^https?://', value, re.I):
        value = 'https://' + value
    return (value, '') if valid_url(value) else ('', 'Enter a valid website (or leave it empty).')


def validate_post(form, has_pdf=False):
    """The /jobs/post form -> (clean values, errors by field). Only what is listed here is read. The description is a PDF (`has_pdf`), a link to the
    posting or a typed text - at least one; typed alone it needs a few sentences."""
    def text(name, limit):
        return ' '.join((form.get(name) or '').split())[:limit]
    vals = {'title': text('title', 120), 'company': text('company', 120), 'location': text('location', 120), 'salary': text('salary', 80), 'experience': text('experience', 60),
            'description': (form.get('description') or '').strip()[:8000], 'work_mode': form.get('work_mode') or '', 'job_type': form.get('job_type') or '',
            'exp_level': form.get('exp_level') or '', 'department': form.get('department') or '', 'apply_how': 'link' if form.get('apply_how') == 'link' else 'form', 'apply_url': (form.get('apply_url') or '').strip(),
            'skills': [s for s in dict.fromkeys(' '.join(x.split())[:40] for x in (form.get('skills') or '').split(',')) if s][:15],
            'jd_url': (form.get('jd_url') or '').strip(), 'has_pdf': bool(has_pdf)}
    errors = {}
    for name, label in (('title', 'job title'), ('company', 'company name'), ('location', 'location')):
        if len(vals[name]) < 2:
            errors[name] = 'Enter the %s.' % label
    if vals['jd_url']:
        vals['jd_url'] = valid_url(vals['jd_url'])
        if not vals['jd_url']:
            errors['jd_url'] = 'Enter the full link of your job posting (https://...).'
    if not has_pdf and not vals['jd_url'] and len(vals['description']) < 80:
        errors['description'] = 'Attach a PDF, give the link of your job posting, or describe the job in a few sentences (at least 80 characters).'
    if vals['work_mode'] not in F.MODE_LABELS:
        errors['work_mode'] = 'Choose on-site, hybrid or remote.'
    if vals['job_type'] not in POST_JOB_TYPES:
        errors['job_type'] = 'Choose the job type.'
    if vals['exp_level'] and vals['exp_level'] not in POST_LEVELS:
        vals['exp_level'] = ''
    if vals['department'] not in dict(POST_DEPARTMENTS):
        errors['department'] = 'Choose the department of the job.'
    if vals['apply_how'] == 'link':
        vals['apply_url'] = valid_url(vals['apply_url'])
        if not vals['apply_url']:
            errors['apply_url'] = 'Enter the full link of your application page (https://...).'
    else:
        vals['apply_url'] = ''
    return vals, errors


POST_JOB_TYPES = {'fulltime': 'Full-time', 'parttime': 'Part-time', 'internship': 'Internship'}        # what an employer can choose (no freelance)
POST_LEVELS = {k: F.EXP_LABELS[k] for k in ('fresher', 'entry', 'mid', 'senior') if k in F.EXP_LABELS}
