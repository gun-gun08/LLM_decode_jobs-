"""The paid packages of the page for companies (Job board > Packages): name, how many jobs, price. The team changes them in the backend; the plans of
/jobs/employers and the payment page /jobs/plan/<package> read them from here. Bundle of 3 and Hiring pack come with the module (data/packages.xml)."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

# the old addresses of the two packages (links already shared): /jobs/plan/bundle and /jobs/plan/pack
CODES = {'bundle': 'llmd_job_aggregator.package_bundle', 'pack': 'llmd_job_aggregator.package_pack'}


class LlmdHrPackage(models.Model):
    _name = 'llmd.hr.package'
    _description = 'Job board package'
    _order = 'sequence, amount, id'

    name = fields.Char(required=True, help='Shown on the page for companies, e.g. "Bundle of 3".')
    sequence = fields.Integer(default=10)
    limit = fields.Integer(string='Job limit', default=1, help='How many jobs the package lets the employer post (job credits added after the payment).')
    post_limited = fields.Boolean(string='Post limited', default=True,
                                  help='On: the employer gets "Job limit" job credits. Off: unlimited job posts for the account (still at most the open jobs '
                                       'allowed at once).')
    active = fields.Boolean(default=True, help='Archived packages are not offered on the website.')
    amount = fields.Monetary(required=True, currency_field='currency_id', help='The price the employer pays online (Razorpay).')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.ref('base.INR', raise_if_not_found=False))

    @api.constrains('amount', 'limit', 'post_limited')
    def _check_values(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError('The amount of a package must be more than 0.')
            if rec.post_limited and rec.limit < 1:
                raise ValidationError('A package with limited posts needs a job limit of at least 1.')

    @api.model
    def by_code(self, code):
        """The active package of /jobs/plan/<code>: "bundle" / "pack" (the first two packages) or the package ID."""
        code = (code or '').strip()
        rec = self.env.ref(CODES[code], raise_if_not_found=False) if code in CODES else (self.browse(int(code)).exists() if code.isdigit() else self)
        return rec.sudo() if rec and rec._name == self._name and rec.active else self.browse()

    def code(self):
        """The address part of /jobs/plan/<code>: the old name of the first two packages, else the ID."""
        self.ensure_one()
        xmlid = self.get_external_id().get(self.id, '')
        return next((code for code, ref in CODES.items() if ref == xmlid), str(self.id))

    def plan_values(self):
        """What the plan pages show: name, price, jobs ("unlimited" when the posts are not limited)."""
        self.ensure_one()
        price = int(self.amount) if self.amount == int(self.amount) else self.amount
        return {'name': self.name, 'price': price, 'jobs': self.limit if self.post_limited else 'unlimited', 'unlimited': not self.post_limited,
                'code': self.code(), 'currency': self.currency_id.symbol or ''}
