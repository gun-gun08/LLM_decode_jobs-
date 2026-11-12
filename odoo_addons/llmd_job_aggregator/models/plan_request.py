"""A paid plan of the page for companies (/jobs/plan/<plan>): the signed-in employer fills in the company details, pays online (Odoo's payment page -
Razorpay, set up under Website/Invoicing > Payment Providers) and gets job credits on the account. The first job of an account is free; every later
post uses one credit (given back when we reject the job). Requests are kept under Job board > Subscribers."""
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
    _description = 'Job board subscriber'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Contact', compute='_compute_name', store=True)
    plan = fields.Selection([(code, plan_label(code)) for code in PLANS], help='The plan of the first requests (before Job board > Packages).')
    package_id = fields.Many2one('llmd.hr.package', string='Package', ondelete='set null', index=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False,
                                 help='The customer invoice of this plan: made in draft when the employer goes to the payment page, posted and paid by the '
                                      'online payment (or posted by "Paid (add credits)").')
    invoice_state = fields.Selection(related='invoice_id.state', string='Invoice status')
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', string='Invoice paid')
    payment_status = fields.Char(string='Online payment', compute='_compute_payment_status',
                                 help='The last Razorpay payment of this plan (LLMDPLAN-<id>): not started, waiting, done, cancelled or an error.')
    post_limit = fields.Integer(string='Post limit', help='The jobs the account may have open at the same time once this package is paid (from the package).')
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

    def _llmd_transactions(self):
        self.ensure_one()
        if not self.id:
            return self.env['payment.transaction']
        return self.env['payment.transaction'].sudo().search(['|', ('reference', '=', '%s%d' % (REF_PREFIX, self.id)),
                                                              ('reference', '=like', '%s%d-%%' % (REF_PREFIX, self.id))], order='id desc')

    def _compute_payment_status(self):
        labels = {'draft': 'Started, not paid', 'pending': 'Waiting for Razorpay', 'authorized': 'Authorized', 'done': 'Done',
                  'cancel': 'Cancelled', 'error': 'Error'}
        for rec in self:
            tx = rec._llmd_transactions()[:1]
            rec.payment_status = ('%s (%s)' % (labels.get(tx.state, tx.state), tx.reference)) if tx else 'Not started'

    def action_open_invoice(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.invoice_id.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'context': {'default_move_type': 'out_invoice'}}

    def action_open_payments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Online payments', 'res_model': 'payment.transaction', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._llmd_transactions().ids)]}

    @api.depends('paid_count')
    def _compute_paid_twice(self):
        for rec in self:
            rec.paid_twice = rec.paid_count > 1

    def action_contacted(self):
        self.write({'state': 'contacted'})

    def action_paid(self):
        """Paid outside the website (bank transfer, a payment link...): the credits are added once, as for an online payment, and the invoice is made
        (posted; finance registers the payment on it)."""
        for rec in self:
            rec._llmd_credit()
            invoice = rec._llmd_open_invoice()
            if invoice.state == 'draft':
                invoice.action_post()
        return True

    def _llmd_open_invoice(self, tx=None):
        """The invoice to pay: the draft made on the payment page, else a new one (none yet, or the old one was cancelled). A posted invoice is
        already paid or waiting for finance: nothing new is made (a second payment of the same plan gets no second invoice)."""
        self.ensure_one()
        invoice = self.invoice_id.sudo()
        if invoice and invoice.state != 'cancel':
            return invoice
        return self._llmd_make_invoice(tx)

    def _llmd_make_invoice(self, tx=None):
        """The customer invoice of this plan, in draft: the employer's account, one line with the package's product (its name, price and GST taxes -
        Odoo maps them by the customer's fiscal position: CGST + SGST in Haryana, IGST elsewhere). An error is logged and never stops the payment."""
        self.ensure_one()
        partner = self.user_id.partner_id.sudo()
        if not partner:
            return self.env['account.move']
        try:
            with self.env.cr.savepoint():
                package = self.package_id.sudo()
                product = package.product_id
                line = {'quantity': 1, 'price_unit': package.amount if package else self.amount}
                if product:
                    line['product_id'] = product.id
                else:
                    line['name'] = package.name or dict(self._fields['plan'].selection).get(self.plan) or 'Job board plan'
                invoice = self.env['account.move'].sudo().with_company(self.env.company).create({
                    'move_type': 'out_invoice', 'partner_id': partner.id, 'currency_id': self.currency_id.id,
                    'invoice_origin': tx.reference if tx else '%s%d' % (REF_PREFIX, self.id), 'invoice_line_ids': [(0, 0, line)]})
                if tx and abs(invoice.amount_total - tx.amount) > 0.01:
                    _logger.warning('plan request %s: invoice total %s differs from the payment %s', self.id, invoice.amount_total, tx.amount)
                self.invoice_id = invoice
                invoice.message_post(body=Markup('Job board plan <b>%s</b> (%s, %s jobs) - subscriber %s%d. %s') % (
                    package.name or self.plan or '', self.company or '', self.jobs or 0, REF_PREFIX, self.id,
                    'Paid online: %s' % tx.reference if tx else 'Waiting for the online payment (Razorpay); it is posted and paid by itself.'))
                return invoice
        except Exception:
            _logger.warning('plan request %s: the invoice could not be made', self.id, exc_info=True)
        return self.env['account.move']

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
            partner.llmd_job_credits = (partner.llmd_job_credits or 0) + (self.jobs or PLANS.get(self.plan or '', {}).get('jobs', 0))
            if self.post_limit > (partner.llmd_max_open or 0):          # the package's post limit, when higher than the account's
                partner.llmd_max_open = self.post_limit
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
        drafts = self.invoice_id.sudo().filtered(lambda m: m.state == 'draft')
        if drafts:
            drafts.button_cancel()

    def _notify_team(self):
        """One e-mail to our team (the company address of the website) about a new request; it never stops the request."""
        self.ensure_one()
        to = self.env.company.email
        if not to:
            return
        body = Markup('<p>New subscriber: <b>%s</b></p><p>%s %s, %s<br/>%s · %s<br/>%s</p><p>%s</p>') % (
            self.package_id.name or dict(self._fields['plan'].selection).get(self.plan) or '', self.first_name, self.last_name, self.company, self.email, self.phone,
            self.company_site or '', self.note or '')
        try:
            with self.env.cr.savepoint():
                self.env['mail.mail'].sudo().create({'subject': 'New subscriber: %s' % self.company, 'email_to': to, 'body_html': str(body), 'auto_delete': True,
                                                     'reply_to': self.email, 'email_from': self.env.company.email_formatted or False})
        except Exception:
            _logger.warning('plan request %s: the e-mail to the team could not be queued', self.id, exc_info=True)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    llmd_job_credits = fields.Integer(string='Job credits', default=0, help='Paid jobs this employer can still post on the job board (the first job is free).')
    llmd_max_open = fields.Integer(string='Open jobs allowed', help='Jobs this employer may have open (pending + live) at once, from the packages bought. Empty: the default (5).')


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
        """A done payment of a plan request (reference LLMDPLAN-<id>) adds the plan's job credits - when the amount and currency are the ones asked.
        Before Odoo's own post-processing, the plan's invoice is made and linked to the payment: Odoo then posts it and reconciles the payment with it."""
        Request = self.env['llmd.plan.request'].sudo()
        for tx in self.filtered(lambda t: t.state == 'done' and (t.reference or '').startswith(REF_PREFIX) and not t.invoice_ids):
            match = re.match(r'%s(\d+)' % REF_PREFIX, tx.reference)
            req = Request.browse(int(match.group(1))).exists() if match else Request
            if req and tx.currency_id == req.currency_id and tx.amount + 0.001 >= req.amount:
                invoice = req._llmd_open_invoice(tx)
                if invoice.state == 'draft':
                    if abs(invoice.amount_total - tx.amount) > 0.01:
                        _logger.warning('plan request %s: invoice total %s differs from the payment %s', req.id, invoice.amount_total, tx.amount)
                    invoice.invoice_origin = tx.reference
                    tx.sudo().invoice_ids = [(4, invoice.id)]
        super()._post_process()
        for tx in self.filtered(lambda t: t.state == 'done' and (t.reference or '').startswith(REF_PREFIX)):
            match = re.match(r'%s(\d+)' % REF_PREFIX, tx.reference)
            req = Request.browse(int(match.group(1))).exists() if match else Request
            if not req:
                continue
            if tx.currency_id != req.currency_id or tx.amount + 0.001 < req.amount:
                _logger.warning('plan request %s: payment %s does not match (%s %s)', req.id, tx.reference, tx.amount, tx.currency_id.name)
                continue
            req._llmd_credit(tx)
