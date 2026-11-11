"""A paid plan of the page for companies (/jobs/plan/<plan>): the signed-in employer fills in the company details, pays online (Odoo's payment page -
Razorpay, set up under Website/Invoicing > Payment Providers) and gets job credits on the account. The first job of an account is free; every later
post uses one credit (given back when we reject the job). Requests are kept under Job board > Plan requests."""
import logging
import re

from markupsafe import Markup

from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.payment import utils as payment_utils

from . import post as PO

_logger = logging.getLogger(__name__)

REF_PREFIX = 'LLMDPLAN-'                               # payment references of plan requests: LLMDPLAN-<request id>[-n]

PLANS = {
    'bundle': {'name': 'Bundle of 3', 'price': 1000, 'jobs': 3},
    'pack': {'name': 'Hiring pack', 'price': 5000, 'jobs': PO.MAX_OPEN_POSTS},
}


def plan_label(code):
    plan = PLANS[code]
    return '%s - Rs %s' % (plan['name'], '{:,}'.format(plan['price']))


def validate_request(form):
    """The /jobs/plan form -> (clean values, errors by field)."""
    def text(key, size):
        return ' '.join((form.get(key) or '').split())[:size]
    vals, errors = {'first_name': text('first_name', 60), 'last_name': text('last_name', 60), 'email': text('email', 120).lower(),
                    'phone': text('phone', 30), 'company': text('company', 120), 'note': (form.get('note') or '').strip()[:1000]}, {}
    for key, label in (('first_name', 'your first name'), ('last_name', 'your last name'), ('company', 'your company name')):
        if len(vals[key]) < 2:
            errors[key] = 'Enter %s.' % label
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', vals['email']):
        errors['email'] = 'Enter a valid e-mail address.'
    if not re.fullmatch(r'\+?[\d\s()-]{7,20}', vals['phone']):
        errors['phone'] = 'Enter a phone number we can reach you on.'
    site, site_error = PO.clean_site(form.get('company_site'))
    if site_error or not site:
        errors['company_site'] = site_error or 'Enter your company website.'
    linkedin, linkedin_error = PO.clean_site(form.get('linkedin'))
    if linkedin_error:
        errors['linkedin'] = 'Enter the full link of your company LinkedIn page (or leave it empty).'
    vals.update(company_site=site, linkedin=linkedin)
    return vals, errors


class LlmdPlanRequest(models.Model):
    _name = 'llmd.plan.request'
    _description = 'Job board plan request'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Contact', compute='_compute_name', store=True)
    plan = fields.Selection([(code, plan_label(code)) for code in PLANS], help='The plan of the first requests (before Job board > Packages).')
    package_id = fields.Many2one('llmd.hr.package', string='Package', ondelete='set null', index=True)
    unlimited = fields.Boolean(string='Unlimited posts', help='The package has no job limit: once paid, the account posts without using credits.')
    state = fields.Selection([('new', 'Waiting for payment'), ('contacted', 'Contacted'), ('paid', 'Paid'), ('cancel', 'Cancelled')], default='new', required=True, index=True)
    amount = fields.Float(string='Amount', digits=(12, 2))
    currency_id = fields.Many2one('res.currency', string='Currency')
    jobs = fields.Integer(string='Job credits', help='The job credits this plan adds to the account once it is paid.')
    credited = fields.Boolean(string='Credits added', readonly=True, copy=False)
    transaction_id = fields.Many2one('payment.transaction', string='Payment', readonly=True, copy=False)
    credits_left = fields.Integer(related='user_id.partner_id.llmd_job_credits', string='Credits left on the account')
    paid_count = fields.Integer(string='Payments received', readonly=True, copy=False,
                                help='How many times this plan was paid. More than one: the employer paid twice (e.g. paid again while the first payment was '
                                     'still being confirmed) - every payment added its credits; refund one in Razorpay and take the credits back if needed.')
    paid_twice = fields.Boolean(string='Paid more than once', compute='_compute_paid_twice', store=True)
    first_name = fields.Char(required=True)
    last_name = fields.Char(required=True)
    email = fields.Char(required=True)
    phone = fields.Char(required=True)
    company = fields.Char(required=True)
    company_site = fields.Char(string='Company website')
    linkedin = fields.Char(string='Company LinkedIn')
    note = fields.Text(string='Message')
    user_id = fields.Many2one('res.users', string='Account', ondelete='set null', help='The signed-in account that sent the request, if any.')

    @api.depends('first_name', 'last_name', 'company')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s (%s)' % (rec.first_name or '', rec.last_name or '', rec.company or '')

    @api.depends('paid_count')
    def _compute_paid_twice(self):
        for rec in self:
            rec.paid_twice = rec.paid_count > 1

    def action_contacted(self):
        self.write({'state': 'contacted'})

    def action_paid(self):
        """Paid outside the website (bank transfer, a payment link...): the credits are added once, as for an online payment."""
        for rec in self:
            rec._llmd_credit()
        return True

    def _llmd_credit(self, tx=None):
        """A payment of the plan is done: its job credits go to the account and the request is marked Paid. Every payment counts once (an online
        payment is remembered on its transaction): an employer who paid twice gets the credits of both payments, and the request shows "Paid more
        than once" for our team. A payment marked by hand ("Paid", no transaction) counts only when the request has no payment yet."""
        self.ensure_one()
        tx = tx.sudo() if tx else tx
        if (tx and tx.llmd_credited) or (not tx and self.credited):
            return
        partner = self.user_id.partner_id.sudo()
        if partner:
            if self.unlimited:
                partner.llmd_unlimited_posts = True
            else:
                partner.llmd_job_credits = (partner.llmd_job_credits or 0) + (self.jobs or PLANS.get(self.plan or '', {}).get('jobs', 0))
        if tx:
            tx.llmd_credited = True
        self.write({'state': 'paid', 'credited': bool(partner), 'paid_count': (self.paid_count or 0) + 1,
                    'transaction_id': self.transaction_id.id or (tx.id if tx else False)})
        if self.paid_count > 1:
            _logger.warning('plan request %s was paid %d times (last payment %s)', self.id, self.paid_count, tx.reference if tx else 'by hand')

    def payment_url(self):
        """Odoo's payment page for this request (amount, currency and partner signed by an access token, so they cannot be changed in the link)."""
        self.ensure_one()
        partner = self.user_id.partner_id
        token = payment_utils.generate_access_token(partner.id, self.amount, self.currency_id.id, env=self.env)
        return '/payment/pay?reference=%s%d&amount=%s&currency_id=%d&partner_id=%d&company_id=%d&access_token=%s' % (
            REF_PREFIX, self.id, self.amount, self.currency_id.id, partner.id, self.env.company.id, token)

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def _notify_team(self):
        """One e-mail to our team (the company address of the website) about a new request; it never stops the request."""
        self.ensure_one()
        to = self.env.company.email
        if not to:
            return
        body = Markup('<p>New plan request: <b>%s</b></p><p>%s %s, %s<br/>%s · %s<br/>%s</p><p>%s</p>') % (
            dict(self._fields['plan'].selection)[self.plan], self.first_name, self.last_name, self.company, self.email, self.phone,
            self.company_site or '', self.note or '')
        try:
            with self.env.cr.savepoint():
                self.env['mail.mail'].sudo().create({'subject': 'Plan request: %s' % self.company, 'email_to': to, 'body_html': str(body), 'auto_delete': True,
                                                     'reply_to': self.email, 'email_from': self.env.company.email_formatted or False})
        except Exception:
            _logger.warning('plan request %s: the e-mail to the team could not be queued', self.id, exc_info=True)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    llmd_job_credits = fields.Integer(string='Job credits', default=0, help='Paid jobs this employer can still post on the job board (the first job is free).')
    llmd_unlimited_posts = fields.Boolean(string='Unlimited job posts', help='Bought a package without a job limit: posts use no credits (still at most the open jobs allowed at once).')


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    llmd_credited = fields.Boolean(string='Plan credits added', readonly=True, copy=False, help='The job credits of this plan payment were added to the account.')
    llmd_razorpay_order_id = fields.Char(string='Razorpay order (plan)', readonly=True, copy=False,
                                         help='The Razorpay order of a plan payment, kept so that the backup check can ask Razorpay what happened to it.')

    def _get_specific_processing_values(self, processing_values):
        """Keep the Razorpay order of a plan payment (Odoo does not store it) for the backup check below."""
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code == 'razorpay' and (self.reference or '').startswith(REF_PREFIX) and res.get('razorpay_order_id'):
            self.sudo().llmd_razorpay_order_id = res['razorpay_order_id']
        return res

    def _llmd_razorpay_sync(self):
        """Backup for a missed webhook: ask Razorpay about the order of each open plan payment and, when it was paid, process it exactly as Odoo
        processes Razorpay's webhook (which then adds the job credits). Nothing happens for an order that was not paid; an error only goes to the log."""
        for tx in self.sudo().filtered(lambda t: t.provider_code == 'razorpay' and t.state in ('draft', 'pending', 'authorized')
                                       and t.llmd_razorpay_order_id and (t.reference or '').startswith(REF_PREFIX)):
            try:
                with self.env.cr.savepoint():
                    data = tx.provider_id._send_api_request('GET', 'orders/%s/payments' % tx.llmd_razorpay_order_id)
                    paid = [p for p in (data or {}).get('items', []) if p.get('status') in ('captured', 'authorized')]
                    if paid:
                        tx._process('razorpay', paid[0])
                        if tx.state == 'done' and not tx.is_post_processed:
                            tx._post_process()
            except Exception:
                _logger.warning('plan payment %s: the check with Razorpay failed', tx.reference, exc_info=True)

    @api.model
    def _cron_llmd_razorpay_sync(self):
        """Every 10 minutes: the plan payments of the last 3 days that Razorpay has not confirmed to Odoo yet."""
        since = fields.Datetime.now() - timedelta(days=3)
        self.sudo().search([('provider_code', '=', 'razorpay'), ('state', 'in', ('draft', 'pending', 'authorized')), ('reference', '=like', REF_PREFIX + '%'),
                            ('llmd_razorpay_order_id', '!=', False), ('create_date', '>=', since)], limit=50)._llmd_razorpay_sync()

    @api.model
    def llmd_sync_partner(self, partner):
        """The open plan payments of one employer (the plan page and Post a job check them when the employer opens them)."""
        since = fields.Datetime.now() - timedelta(days=3)
        self.sudo().search([('partner_id', '=', partner.id), ('provider_code', '=', 'razorpay'), ('state', 'in', ('draft', 'pending', 'authorized')),
                            ('reference', '=like', REF_PREFIX + '%'), ('llmd_razorpay_order_id', '!=', False), ('create_date', '>=', since)], limit=5)._llmd_razorpay_sync()

    def _post_process(self):
        """A done payment of a plan request (reference LLMDPLAN-<id>) adds the plan's job credits - when the amount and currency are the ones asked."""
        super()._post_process()
        Request = self.env['llmd.plan.request'].sudo()
        for tx in self.filtered(lambda t: t.state == 'done' and (t.reference or '').startswith(REF_PREFIX)):
            match = re.match(r'%s(\d+)' % REF_PREFIX, tx.reference)
            req = Request.browse(int(match.group(1))).exists() if match else Request
            if not req:
                continue
            if tx.currency_id != req.currency_id or tx.amount + 0.001 < req.amount:
                _logger.warning('plan request %s: payment %s does not match (%s %s)', req.id, tx.reference, tx.amount, tx.currency_id.name)
                continue
            req._llmd_credit(tx)
