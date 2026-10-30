"""One record per hiring company of the job board (/companies, /companies/<slug>). The companies come from the jobs themselves: every job names its company, and
the jobs that name the same company (the same name, case and spacing aside) share ONE record - its ID is the stable key, its slug only the readable address.
Two different names that give the same slug ("Acme" and "ACME!") get two records, the later one with its ID in the slug, so a slug never opens the wrong company.
Nothing about a company is invented: no logo and no description are stored (the sources give none); the headquarters / size come from board_config when verified."""
import re

from odoo import api, fields, models

from . import board_config as C


def company_key(name):
    """The same company however a source spells the case and the spaces: 'Hevo  Data' == 'hevo data'."""
    return ' '.join((name or '').casefold().split())


def unique_slug(base, taken, record_id, reserved=(), suffix='-%d'):
    """`base` when it is free (not in `taken`, not reserved), else base + the stable record ID (suffix '-%d' or '-j%d')."""
    if base and base not in taken and base not in reserved:
        return base
    return (base or 'item') + suffix % record_id


class LlmdCompany(models.Model):
    _name = 'llmd.company'
    _description = 'Job board company'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    key = fields.Char(required=True, index=True, readonly=True, help='The name in lower case with single spaces: the jobs that name this company.')
    slug = fields.Char(required=True, index=True, readonly=True, copy=False, help='The address of its page: /companies/<slug>. Set once, then kept.')
    listing_ids = fields.One2many('llmd.job.listing', 'company_id', string='Jobs')

    _key_unique = models.Constraint('unique(key)', 'One company record per company name.')
    _slug_unique = models.Constraint('unique(slug)', 'Every company has its own address.')

    @api.model
    def ensure(self, names):
        """{name: company} for the company names of some jobs, creating the companies that do not exist yet (slug from the name, the ID added on a clash)."""
        self = self.sudo()
        keys = {}
        for name in names:
            if name and name.strip() and company_key(name) not in keys:
                keys[company_key(name)] = name.strip()
        if not keys:
            return {}
        found = {c.key: c for c in self.with_context(active_test=False).search([('key', 'in', list(keys))])}
        for key, name in keys.items():
            if key in found:
                continue
            base = C.slugify(name)[:80].strip('-') or 'company'
            rec = self.create({'name': name, 'key': key, 'slug': 'new-%s' % key.encode().hex()[:40]})
            taken = bool(self.search_count([('slug', '=', base), ('id', '!=', rec.id)]))
            rec.slug = unique_slug(base, {base} if taken else set(), rec.id)
            found[key] = rec
        return {name: found[company_key(name)] for name in names if name and name.strip()}

    def website_path(self):
        self.ensure_one()
        return '/companies/%s' % self.slug

    def hq(self):
        self.ensure_one()
        return C.company_hq(self.name)

    def size_label(self):
        self.ensure_one()
        return C.COMPANY_SIZE_LABELS.get(C.company_size(self.name), '')


SLUG_END_NUMBER = re.compile(r'(^|-)\d+$')      # an address ending in "-<number>" is how Odoo addresses its own job positions (/jobs/<name>-<id>)
