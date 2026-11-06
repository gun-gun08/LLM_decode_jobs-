"""The jobs posted on the website itself (models/post.py):
/jobs/post        an employer / HR posts a job for free (sign-in first, in the same window as Apply Now) -> Pending review
/jobs/my          the employer's own jobs: status, applicants (with the resume), close / reopen
/jobs/llmdecode   every live job of "Posted by LLM Decode"
An employer only ever reads their OWN posts and the applications sent for them (every query below filters on the signed-in account)."""
import base64
import logging
import re
import time

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.payment.controllers.post_processing import PaymentPostProcessing

from urllib.parse import quote

from ..models import apply_utils as A
from ..models import world_points as WP
from ..models import job_facets as F
from ..models import post as PO
from ..models import plan_request as PR

_logger = logging.getLogger(__name__)

FEED_ORDER = 'pinned desc, posted desc, id desc'


class LlmdJobPosts(http.Controller):

    @staticmethod
    def _llmd_employer():
        """The signed-in account, or None for a visitor."""
        user = request.env.user
        return None if not user or user._is_public() else user

    @staticmethod
    def _llmd_own_post(post_id, user):
        post = request.env['llmd.job.listing'].sudo().with_context(active_test=False).search(
            [('id', '=', post_id), ('poster_id', '=', user.id), ('post_kind', '=', 'employer')], limit=1)
        if not post:
            raise NotFound()
        return post

    def _llmd_form_values(self, user, vals=None, errors=None):
        partner = user.partner_id
        if vals is None:                                                # what the account already knows is filled in
            vals = {'company': partner.company_name or '', 'designation': partner.function or '', 'company_site': partner.website or '', 'phone': partner.phone or '',
                    'linkedin': partner.llmd_linkedin or ''}
        return {'vals': vals, 'errors': errors or {}, 'user_name': user.name, 'user_email': user.email or user.login, 'max_mb': A.MAX_RESUME // (1024 * 1024), 'open_n': request.env['llmd.job.listing'].sudo().open_posts_of(user), 'max_open': PO.MAX_OPEN_POSTS,
                'modes': F.WORK_MODES, 'types': list(PO.POST_JOB_TYPES.items()), 'levels': list(PO.POST_LEVELS.items()), 'departments': PO.POST_DEPARTMENTS, 'post_days': PO.POST_DAYS,
                'free_post': request.env['llmd.job.listing'].sudo().free_post_left(user), 'credits': partner.llmd_job_credits}

    @http.route('/jobs/post', type='http', auth='public', website=True, methods=['GET', 'POST'], sitemap=False)
    def llmd_post(self, **post):
        user = self._llmd_employer()
        if not user:                                                    # sign in / sign up first, in the window over the page, then back here
            if request.httprequest.method == 'POST':
                return request.redirect('/jobs/post')
            return self._llmd_employers_page(None)
        if request.httprequest.method != 'POST':
            request.env['payment.transaction'].sudo().llmd_sync_partner(user.partner_id)      # credits of a plan whose webhook did not reach us yet
            return request.render('llmd_job_aggregator.post_form', self._llmd_form_values(user))
        if post.get('company_website'):                                 # hidden field that only bots fill in
            return request.redirect('/jobs')
        upload = request.httprequest.files.get('jd_pdf')
        pdf = upload.read(A.MAX_RESUME + 1) if upload else b''
        vals, errors = PO.validate_post(post, has_pdf=bool(pdf))
        pdf_name = ''
        if pdf:
            pdf_error, ext, _mime, pdf_name = A.check_resume(upload.filename, pdf)
            if pdf_error or ext != 'pdf':
                errors['jd_pdf'] = 'Attach the job posting as a real PDF file of up to %d MB.' % (A.MAX_RESUME // (1024 * 1024))
        site, site_error = PO.clean_site(post.get('company_site'))
        if site_error or not site:
            errors['company_site'] = site_error or 'Enter your company website.'
        phone = ' '.join((post.get('phone') or '').split())[:30]
        if not re.fullmatch(r'\+?[\d\s()-]{7,20}', phone):
            errors['phone'] = 'Enter a phone number we can reach you on.'
        designation = ' '.join((post.get('designation') or '').split())[:80]
        if len(designation) < 2:
            errors['designation'] = 'Enter your designation.'
        linkedin, linkedin_error = PO.clean_site(post.get('linkedin'))
        if linkedin_error:
            errors['linkedin'] = 'Enter the full link of your company LinkedIn page (or leave it empty).'
        if not errors:
            try:
                with request.env.cr.savepoint():
                    rec = request.env['llmd.job.listing'].sudo().employer_post(user, vals)
                    partner = user.partner_id.sudo()
                    if partner.llmd_role != 'hirer':                    # posting a job makes the account a hirer (its company kept on the contact)
                        request.env['res.partner'].llmd_set_role(partner, 'hirer', {} if partner.company_name else {'company_name': vals['company']})
                    contact = {'phone': phone, 'website': site, 'function': designation, 'company_name': vals['company']}
                    if linkedin:
                        contact['llmd_linkedin'] = linkedin
                    partner.write(contact)                              # the contact details of the company, kept up to date
                    company = rec.company_id.sudo()
                    if company:                                         # the company page shows them too (only where nothing is set yet)
                        company.write({k: v for k, v in (('website', site), ('linkedin', linkedin)) if v and not company[k]})
                    if pdf:
                        att = request.env['ir.attachment'].sudo().create({'name': pdf_name, 'datas': base64.b64encode(pdf), 'mimetype': 'application/pdf',
                                                                          'res_model': 'llmd.job.listing', 'res_id': rec.id, 'type': 'binary'})
                        rec.jd_attachment_id = att
                return request.redirect('/jobs/my?posted=%d' % rec.id)
            except UserError as exc:
                errors['form'] = exc.args[0]
            except Exception:
                _logger.exception('job post could not be saved (user %s)', user.id)
                errors['form'] = 'Sorry, your job could not be saved right now. Please try again in a few minutes.'
        shown = dict(vals, company_site=post.get('company_site') or '', designation=post.get('designation') or '', phone=post.get('phone') or '', linkedin=post.get('linkedin') or '',
                     jd_url=post.get('jd_url') or '', skills=post.get('skills') or '', description=post.get('description') or '', apply_url=post.get('apply_url') or '')
        response = request.render('llmd_job_aggregator.post_form', self._llmd_form_values(user, shown, errors))
        response.status_code = 400
        return response

    def _llmd_employers_page(self, user):
        Listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        return request.render('llmd_job_aggregator.employers_page', {
            'signed_in': bool(user), 'is_hirer': bool(user and user.partner_id.llmd_role == 'hirer'),
            'open_jobs': Listing.search_count(active), 'company_total': len(Listing._read_group(active + [('company', '!=', False)], ['company'], [])),
            'category_total': len(Listing._read_group(active + [('job_category', '!=', False)], ['job_category'], [])),
            'max_open': PO.MAX_OPEN_POSTS, 'post_days': PO.POST_DAYS, **self._llmd_map_pins(Listing, active)})

    @staticmethod
    def _llmd_map_pins(Listing, active, limit=6):
        """The pins of the map on the page for companies: the countries with the most open jobs (counted live), placed at their centre on
        static/src/img/world_map.svg; a pin that would sit under the card in the middle or on another pin is left out."""
        iso = {name: ('GB' if code == 'uk' else code.upper()) for code, name in F.COUNTRY_OF_CODE.items()}
        rows = sorted(Listing._read_group(active + [('country', '!=', False)], ['country'], ['__count']), key=lambda r: -r[1])
        pins = []
        for name, n in rows[:25]:
            code = iso.get(name)
            point = WP.POINTS.get(code) if code else None
            if point:                                                   # the map is drawn 108% wide from -4%, 6% down, at 1000:470 in a 1000:560 box
                point = (round(-4 + 1.08 * point[0], 1), round(6 + 0.906 * point[1], 1))
            if not point or (28 <= point[0] <= 68 and 18 <= point[1] <= 84) or any(abs(point[0] - p['x']) < 9 and abs(point[1] - p['y']) < 12 for p in pins):
                continue
            pins.append({'x': point[0], 'y': point[1], 'name': name, 'n': n, 'flag': ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code)})
            if len(pins) >= limit:
                break
        flags = ''.join(p['flag'] for p in pins)
        return {'map_pins': pins, 'map_flag_font': 'https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=swap&text=%s' % quote(flags) if flags else ''}

    @http.route('/jobs/employers', type='http', auth='public', website=True, sitemap=True)
    def llmd_employers(self, **kwargs):
        """The page for companies (Post a job, how it works, the plan, questions)."""
        return self._llmd_employers_page(self._llmd_employer())

    @http.route('/jobs/plan/<string:plan_code>', type='http', auth='public', website=True, methods=['GET', 'POST'], sitemap=False)
    def llmd_plan_request(self, plan_code, **post):
        """The request page of a paid plan: a short contact form; our team gets in touch about the payment (nothing is paid on the website)."""
        plan = PR.PLANS.get(plan_code)
        if not plan:
            raise NotFound()
        user = self._llmd_employer()
        if user and request.httprequest.method != 'POST':                # a plan paid on Razorpay whose webhook did not reach us yet
            request.env['payment.transaction'].sudo().llmd_sync_partner(user.partner_id)
        values = {'plan_code': plan_code, 'plan': plan, 'errors': {}, 'sent': False, 'post_days': PO.POST_DAYS, 'signed_in': bool(user),
                  'credits': user.partner_id.llmd_job_credits if user else 0}
        if request.httprequest.method != 'POST':
            vals = {}
            if user:                                                    # what the account already knows is filled in
                partner = user.partner_id
                first, _sp, last = (partner.name or '').partition(' ')
                vals = {'first_name': first, 'last_name': last, 'email': user.email or user.login or '', 'phone': partner.phone or '',
                        'company': partner.company_name or '', 'company_site': partner.website or '', 'linkedin': partner.llmd_linkedin or ''}
            return request.render('llmd_job_aggregator.plan_request_page', dict(values, vals=vals, sent=bool(post.get('sent'))))
        if post.get('company_website'):                                 # hidden field that only bots fill in
            return request.redirect('/jobs/employers')
        if not user:                                                    # the credits go to an account: sign in first (the window over the page)
            return request.redirect('/jobs/plan/%s' % plan_code)
        vals, errors = PR.validate_request(post)
        if not errors:
            try:
                with request.env.cr.savepoint():
                    inr = request.env.ref('base.INR').sudo()
                    if not inr.active:                                  # Razorpay takes Indian rupees
                        inr.active = True
                    rec = request.env['llmd.plan.request'].sudo().create(dict(vals, plan=plan_code, user_id=user.id, amount=plan['price'], currency_id=inr.id, jobs=plan['jobs']))
                    partner = user.partner_id.sudo()
                    partner.write({k: v for k, v in (('phone', vals['phone']), ('website', vals['company_site']), ('company_name', vals['company']),
                                                     ('llmd_linkedin', vals['linkedin'])) if v and not partner[k]})
                    rec._notify_team()
                    url = rec.payment_url()
                return request.redirect(url)
            except Exception:
                _logger.exception('plan request could not be saved')
                errors['form'] = 'Sorry, your request could not be sent right now. Please try again in a few minutes.'
        shown = dict(vals, company_site=post.get('company_site') or '', linkedin=post.get('linkedin') or '')
        response = request.render('llmd_job_aggregator.plan_request_page', dict(values, vals=shown, errors=errors))
        response.status_code = 400
        return response

    @http.route('/jobs/my', type='http', auth='public', website=True, sitemap=False)
    def llmd_my_jobs(self, posted=None, **kwargs):
        user = self._llmd_employer()
        if not user:
            return request.redirect('/web/login?redirect=/jobs/my')
        posts = request.env['llmd.job.listing'].sudo().with_context(active_test=False).search([('poster_id', '=', user.id), ('post_kind', '=', 'employer')], order='id desc')
        counts = {p.id: len(p.employer_applications()) for p in posts}
        just = posts.filtered(lambda p: str(p.id) == (posted or ''))
        return request.render('llmd_job_aggregator.my_jobs', {'posts': posts, 'counts': counts, 'just_posted': just[:1], 'max_open': PO.MAX_OPEN_POSTS,
                                                              'states': dict(PO.POST_STATES)})

    @http.route('/jobs/my/<int:post_id>/applicants', type='http', auth='public', website=True, sitemap=False)
    def llmd_my_applicants(self, post_id, **kwargs):
        user = self._llmd_employer()
        if not user:
            return request.redirect('/web/login?redirect=/jobs/my')
        post = self._llmd_own_post(post_id, user)
        apps = post.employer_applications()
        resumes = {}
        for app in apps:
            att = request.env['ir.attachment'].sudo().search([('res_model', '=', 'hr.applicant'), ('res_id', '=', app.applicant_id.id)], order='id', limit=1)
            resumes[app.id] = bool(att)
        return request.render('llmd_job_aggregator.my_applicants', {'post': post, 'apps': apps, 'resumes': resumes})

    @http.route('/jobs/my/<int:post_id>/resume/<int:app_id>', type='http', auth='public', website=True, sitemap=False)
    def llmd_my_resume(self, post_id, app_id, **kwargs):
        user = self._llmd_employer()
        if not user:
            raise NotFound()
        post = self._llmd_own_post(post_id, user)
        app = post.employer_applications().filtered(lambda a: a.id == app_id)
        if not app:
            raise NotFound()
        att = request.env['ir.attachment'].sudo().search([('res_model', '=', 'hr.applicant'), ('res_id', '=', app.applicant_id.id)], order='id', limit=1)
        if not att:
            raise NotFound()
        response = request.env['ir.binary']._get_stream_from(att).get_response(as_attachment=True)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @http.route(['/jobs/my/<int:post_id>/close', '/jobs/my/<int:post_id>/reopen'], type='http', auth='user', website=True, methods=['POST'], sitemap=False)
    def llmd_my_toggle(self, post_id, **kwargs):
        post = self._llmd_own_post(post_id, request.env.user)
        if request.httprequest.path.endswith('/close'):
            post.action_close()
        else:
            post.action_reopen()
        return request.redirect('/jobs/my')

    @http.route('/jobs/jd/<int:listing_id>', type='http', auth='public', website=True, sitemap=False)
    def llmd_job_pdf(self, listing_id, **kwargs):
        """The PDF an employer attached to their job: for everybody while the job is live, and for that employer always."""
        job = request.env['llmd.job.listing'].sudo().with_context(active_test=False).browse(listing_id).exists()
        user = self._llmd_employer()
        if not job or not job.jd_attachment_id or not (job.active or (user and job.poster_id == user)):
            raise NotFound()
        return request.env['ir.binary']._get_stream_from(job.jd_attachment_id.sudo()).get_response()

    @http.route('/jobs/llmdecode', type='http', auth='public', website=True, sitemap=False)
    def llmd_feed(self, **kwargs):
        posts = request.env['llmd.job.listing'].sudo().search([('post_kind', '=', 'llmdecode'), ('active', '=', True)], order=FEED_ORDER, limit=120)
        return request.render('llmd_job_aggregator.llmd_feed', {'posts': posts, 'card_cols': 'col-md-6 col-xl-4'})


class LlmdPaymentStatus(PaymentPostProcessing):
    """Odoo's payment status page asks every few seconds whether the payment is done. For a plan paid on Razorpay it also asks Razorpay itself
    (at most every 10 seconds): without that the page waits for Razorpay's webhook, which never arrives on a local Odoo or when it is missed."""

    @http.route()
    def poll_status(self, **kwargs):
        tx = self._get_monitored_transaction()
        if tx and tx.provider_code == 'razorpay' and tx.state in ('draft', 'pending', 'authorized') and (tx.reference or '').startswith(PR.REF_PREFIX):
            now = time.time()
            if now - request.session.get('llmd_rzp_poll', 0) >= 10:
                request.session['llmd_rzp_poll'] = now
                tx._llmd_razorpay_sync()
        return super().poll_status(**kwargs)
