"""One record per hiring company of the job board (/companies, /companies/<slug>). The companies come from the jobs themselves: every job names its company, and
the jobs that name the same company (the same name, case and spacing aside) share ONE record - its ID is the stable key, its slug only the readable address.
Two different names that give the same slug ("Acme" and "ACME!") get two records, the later one with its ID in the slug, so a slug never opens the wrong company.
Nothing about a company is invented: the sources give no logo, description, website or LinkedIn - those are typed in by the team (Recruitment > Job board >
Companies) or come from the company's own employer account (Post a job); the headquarters / size come from board_config when verified."""
import logging
import re
from urllib.parse import quote_plus

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import board_config as C
from . import company_info as CI


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
    industry = fields.Char(help='Shown on the company page, e.g. "IT Services & Consulting". Empty: the category with the most of its jobs.')
    description = fields.Text(help='A few sentences about the company, shown on its page. Only facts you know (from the company itself).')
    website = fields.Char(help='The company website, https://...')
    linkedin = fields.Char(string='LinkedIn', help='The company LinkedIn page, https://www.linkedin.com/company/...')
    job_count = fields.Integer(string='Open jobs', compute='_compute_job_count')

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
            rec = self.create(dict({'name': name, 'key': key, 'slug': 'new-%s' % key.encode().hex()[:40]}, **self._known_values(name)))
            taken = bool(self.search_count([('slug', '=', base), ('id', '!=', rec.id)]))
            rec.slug = unique_slug(base, {base} if taken else set(), rec.id)
            found[key] = rec
        return {name: found[company_key(name)] for name in names if name and name.strip()}

    def write(self, vals):
        if vals.get('linkedin'):                                        # a pasted link of any page of it (posts, about ...) -> the company page itself
            vals['linkedin'] = linkedin_of(vals['linkedin']) or vals['linkedin'].strip()
        return super().write(vals)

    @api.constrains('website', 'linkedin')
    def _check_links(self):
        for rec in self:
            for name in ('website', 'linkedin'):
                if rec[name] and not re.fullmatch(r'https?://[\w.-]+\.[a-z]{2,}(/\S*)?', rec[name].strip(), re.I):
                    raise ValidationError('%s must be a full link, e.g. https://www.example.com' % rec._fields[name].string)

    def _compute_job_count(self):
        counts = dict(self.env['llmd.job.listing'].sudo()._read_group([('active', '=', True), ('company_id', 'in', self.ids)], ['company_id'], ['__count']))
        for rec in self:
            rec.job_count = counts.get(rec, 0)

    def action_find_linkedin(self):
        """For each company with a website: read its home page and take the LinkedIn company page the company itself links to. A site that cannot be read,
        or that links to no LinkedIn page, changes nothing."""
        found = 0
        for rec in self.filtered('website'):
            try:
                answer = requests.get(rec.website.strip(), timeout=12, headers={'User-Agent': 'Mozilla/5.0 (compatible; LLMDecodeJobs/1.0)'})
                link = linkedin_of(answer.text[:2000000]) if answer.ok else ''
            except requests.RequestException:
                _logger.info('company %s: website %s could not be read', rec.id, rec.website)
                link = ''
            if link:
                rec.linkedin = link
                found += 1
        if len(self) == 1 and not found:
            raise UserError('No LinkedIn company page was found on %s. Open the website, find its LinkedIn link and paste it here.' % (self.website or 'the website'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success' if found else 'warning', 'message': 'LinkedIn page found for %d of %d companies.' % (found, len(self.filtered('website')))}}

    def linkedin_search(self):
        """Until the LinkedIn page is known: LinkedIn's own company search for this name (always right, never a guessed address)."""
        self.ensure_one()
        return 'https://www.linkedin.com/search/results/companies/?keywords=%s' % quote_plus(self.name)

    @api.model
    def _known_values(self, name, have=None):
        """Website, one line about it and LinkedIn of a company listed in company_info.py - only for the fields that are still empty (`have`)."""
        known = {company_key(k): v for k, v in CI.COMPANY_INFO.items()}.get(company_key(name))
        linkedin = {company_key(k): v for k, v in CI.COMPANY_LINKEDIN.items()}.get(company_key(name))
        vals = {}
        if known:
            vals.update({k: v for k, v in (('website', known[0]), ('description', known[1])) if v})
        if linkedin:
            vals['linkedin'] = linkedin
        return {k: v for k, v in vals.items() if not (have or {}).get(k)}

    @api.model
    def _llmd_fill_known(self):
        """Every module update: the companies of company_info.py get their website, line and LinkedIn where nothing is set yet (typed values stay)."""
        for rec in self.sudo().search([]):
            vals = self._known_values(rec.name, {'website': rec.website, 'description': rec.description, 'linkedin': rec.linkedin})
            if vals:
                rec.write(vals)

    def website_path(self):
        self.ensure_one()
        return '/companies/%s' % self.slug

    def hq(self):
        self.ensure_one()
        return C.company_hq(self.name)

    def size_label(self):
        self.ensure_one()
        return C.COMPANY_SIZE_LABELS.get(C.company_size(self.name), '')


_logger = logging.getLogger(__name__)
LINKEDIN_PAGE = re.compile(r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([A-Za-z0-9_%.-]+)', re.I)


def linkedin_of(html):
    """The LinkedIn company page a website links to (its header / footer), or ''. Only linkedin.com/company/<name> links count."""
    names = [m.group(1).strip('/').rstrip('.') for m in LINKEDIN_PAGE.finditer(html or '')]
    names = [n for n in names if n and n.lower() not in ('linkedin', 'share')]
    return 'https://www.linkedin.com/company/%s/' % max(set(names), key=names.count) if names else ''


SLUG_END_NUMBER = re.compile(r'(^|-)\d+$')      # an address ending in "-<number>" is how Odoo addresses its own job positions (/jobs/<name>-<id>)
