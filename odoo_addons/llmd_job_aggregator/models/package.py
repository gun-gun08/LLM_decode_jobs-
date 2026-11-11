"""The paid packages of the page for companies (Job board > Packages): name, how many jobs, price. The team changes them in the backend; the plans of
/jobs/employers and the payment page /jobs/plan/<package> read them from here. Bundle of 3 and Hiring pack come with the module (data/packages.xml)."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from . import post as PO

# the old addresses of the two packages (links already shared): /jobs/plan/bundle and /jobs/plan/pack
CODES = {'bundle': 'llmd_job_aggregator.package_bundle', 'pack': 'llmd_job_aggregator.package_pack'}


class LlmdHrPackage(models.Model):
    _name = 'llmd.hr.package'
    _description = 'Job board package'
    _order = 'sequence, amount, id'

    name = fields.Char(required=True, help='Shown on the page for companies, e.g. "Bundle of 3".')
    sequence = fields.Integer(default=10)
    limit = fields.Integer(string='Job limit', default=1, help='How many jobs the package lets the employer post (job credits added after the payment).')
    post_limited = fields.Integer(string='Post limit', default=PO.MAX_OPEN_POSTS,
                                  help='How many jobs the employer may have open (pending + live) at the same time after buying this package.')
    active = fields.Boolean(default=True, help='Archived packages are not offered on the website.')
    amount = fields.Monetary(required=True, currency_field='currency_id', help='The price the employer pays online (Razorpay).')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.ref('base.INR', raise_if_not_found=False))
    product_id = fields.Many2one('product.product', string='Product', ondelete='restrict', copy=False,
                                 help='The service product of this package (for invoices and accounting). Made with the package; its name and price follow the package.')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._llmd_sync_products()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'name', 'amount', 'product_id', 'active'} & set(vals):
            self._llmd_sync_products()
        return res

    def _llmd_sync_products(self):
        """Every package has its service product: made when missing, its name, price and Active kept like the package's."""
        Product = self.env['product.product'].sudo()
        for rec in self.with_context(active_test=False):
            vals = {'name': rec.name, 'list_price': rec.amount, 'active': rec.active}
            if not rec.product_id:
                product = Product.create(dict(vals, type='service', sale_ok=True, purchase_ok=False, default_code='LLMD-PKG-%d' % rec.id))
                super(LlmdHrPackage, rec).write({'product_id': product.id})
            elif any(rec.product_id[k] != v for k, v in vals.items()):
                rec.product_id.sudo().write(vals)

    @api.model
    def _llmd_ensure_products(self):
        """Every module update: the packages without a product get one (the packages made before the Product field)."""
        self.with_context(active_test=False).search([])._llmd_sync_products()

    @api.constrains('amount', 'limit', 'post_limited')
    def _check_values(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError('The amount of a package cannot be below 0 (0 = the free package).')
            if rec.limit < 1:
                raise ValidationError('The job limit of a package must be at least 1.')
            if rec.post_limited < 1:
                raise ValidationError('The post limit of a package must be at least 1 (jobs open at the same time).')

    @api.model
    def by_code(self, code):
        """The active package of /jobs/plan/<code>: "bundle" / "pack" (the first two packages) or the package ID."""
        code = (code or '').strip()
        rec = self.env.ref(CODES[code], raise_if_not_found=False) if code in CODES else (self.browse(int(code)).exists() if code.isdigit() else self)
        return rec.sudo() if rec and rec._name == self._name and rec.active and rec.amount > 0 else self.browse()      # the free package is not bought

    @api.model
    def free_package(self):
        """The Free package (amount 0): how many jobs a new account posts for free and how many it may have open; empty when archived."""
        rec = self.env.ref('llmd_job_aggregator.package_free', raise_if_not_found=False)
        return rec.sudo() if rec and rec.sudo().active else self.browse()

    def code(self):
        """The address part of /jobs/plan/<code>: the old name of the first two packages, else the ID."""
        self.ensure_one()
        xmlid = self.get_external_id().get(self.id, '')
        return next((code for code, ref in CODES.items() if ref == xmlid), str(self.id))

    def plan_values(self):
        """What the plan pages show: name, price, jobs, how many can be open at once."""
        self.ensure_one()
        price = int(self.amount) if self.amount == int(self.amount) else self.amount
        return {'name': self.name, 'price': price, 'jobs': self.limit, 'post_limit': self.post_limited,
                'code': self.code(), 'currency': self.currency_id.symbol or ''}
