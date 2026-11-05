"""A paid plan of the page for companies (/jobs/plan/<plan>): the signed-in employer fills in the company details, pays online (Odoo's payment page -
Razorpay, set up under Website/Invoicing > Payment Providers) and gets job credits on the account. The first job of an account is free; every later
post uses one credit (given back when we reject the job). Requests are kept under Job board > Plan requests."""
import logging
import re

from markupsafe import Markup

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
    plan = fields.Selection([(code, plan_label(code)) for code in PLANS], required=True)
    state = fields.Selection([('new', 'Waiting for payment'), ('contacted', 'Contacted'), ('paid', 'Paid'), ('cancel', 'Cancelled')], default='new', required=True, index=True)
    amount = fields.Float(string='Amount', digits=(12, 2))
    currency_id = fields.Many2one('res.currency', string='Currency')
    jobs = fields.Integer(string='Job credits', help='The job credits this plan adds to the account once it is paid.')
    credited = fields.Boolean(string='Credits added', readonly=True, copy=False)
    transaction_id = fields.Many2one('payment.transaction', string='Payment', readonly=True, copy=False)
    credits_left = fields.Integer(related='user_id.partner_id.llmd_job_credits', string='Credits left on the account')
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

    def action_contacted(self):
        self.write({'state': 'contacted'})

    def action_paid(self):
        """Paid outside the website (bank transfer, a payment link...): the credits are added once, as for an online payment."""
        for rec in self:
            rec._llmd_credit()
        return True

    def _llmd_credit(self, tx=None):
        """The plan is paid: its job credits go to the account (only once), the request is marked Paid."""
        self.ensure_one()
        if self.credited:
            return
        partner = self.user_id.partner_id.sudo()
        if partner:
            partner.llmd_job_credits = (partner.llmd_job_credits or 0) + (self.jobs or PLANS.get(self.plan, {}).get('jobs', 0))
        self.write({'state': 'paid', 'credited': bool(partner), 'transaction_id': tx.id if tx else self.transaction_id.id})

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


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

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
