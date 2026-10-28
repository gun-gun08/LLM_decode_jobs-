import json
import logging
import os
import re

import requests
from urllib.parse import urlparse

from odoo import api, fields, models

from . import board_config as C
from . import parsers as P
from . import sources as S
from . import view_helpers as V
from . import summary as SUM
from .listing import direct_links_only, is_board_link, valid_url

_logger = logging.getLogger(__name__)

TIMEOUT = 20
MARK = 'As an employee of our company'          # Odoo's generic default paragraph
ROLE_NOUNS = {'engineer', 'developer', 'manager', 'analyst', 'designer', 'scientist', 'architect', 'consultant', 'specialist', 'executive', 'writer', 'editor',
              'recruiter', 'accountant', 'administrator', 'coordinator', 'assistant', 'tester', 'officer', 'marketer', 'representative'}


class HrJob(models.Model):
    _inherit = 'hr.job'

    apply_url = fields.Char(string='Application URL', copy=False,
                            help='Where Apply Now sends the visitor (LinkedIn, Naukri, the careers page ...). Filled from the job API listing when empty.')
    agg_source = fields.Char(string='Content source', readonly=True, copy=False)
    llmd_posted_type = fields.Selection(C.POSTED_TYPES, string='Posted Type', compute='_compute_llmd_posted_type', store=True,
                                        help='Public User: the position was created by a portal / public website user. Empty for positions our own team created.')

    @api.depends('create_uid')
    def _compute_llmd_posted_type(self):
        for job in self:
            job.llmd_posted_type = 'public_user' if job.sudo().create_uid.share else False         # share = a portal / public user, not our team
    agg_title = fields.Char(string='Matched listing', readonly=True, copy=False)
    agg_company = fields.Char(string='Listing company', readonly=True, copy=False)
    agg_url = fields.Char(string='Listing link', readonly=True, copy=False)
    agg_snippet = fields.Text(string='About the role (fetched)', readonly=True, copy=False)
    agg_json = fields.Text(string='Fetched sections (JSON)', readonly=True, copy=False)
    agg_fetched = fields.Datetime(string='Fetched on', readonly=True, copy=False)
    agg_status = fields.Char(string='Fetch status', readonly=True, copy=False)

    # ------------------------------------------------------------------ hooks: created / published / title or location changed
    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        if not self.env.context.get('llmd_skip'):
            jobs._llmd_refresh()
        return jobs

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('llmd_skip'):
            if 'name' in vals or 'address_id' in vals:
                self._llmd_refresh()
            elif vals.get('website_published'):
                self.filtered(lambda j: not j.agg_fetched)._llmd_refresh()
        return res

    def llmd_refetch(self):
        """Fetch again from the job APIs (XML-RPC / scheduled action)."""
        self._llmd_refresh()
        return True

    # ------------------------------------------------------------------ what the page template shows
    def llmd_content(self):
        """The data of the shared detail layout for one of OUR positions (same keys as llmd.job.listing.detail_vals()).
        'on' is False for a page somebody wrote by hand: that page is then shown exactly as it is."""
        self.ensure_one()
        desc = str(self.website_description or '')
        if desc.strip() and MARK not in desc and 'o_llmd_' not in desc:
            return {'on': False}
        try:
            data = json.loads(self.agg_json) if self.agg_json else {}
        except ValueError:
            data = {}
        rec = self.sudo()                                               # the visitor (public user) may not read partners or companies
        address = rec.address_id
        icp = self.env['ir.config_parameter'].sudo()
        apply_url = valid_url(self.apply_url)
        internal = (icp.get_param('llmd_agg.fallback_apply') or '') in ('1', 'true', 'yes')
        if apply_url and is_board_link(apply_url) and direct_links_only(self.env):
            apply_url, internal = '', True                                  # a job board's page is no direct link: our own position is applied for on our own Odoo form
        source = data.get('source', '')
        location = ', '.join(p for p in (address.city or '', address.country_id.name or '') if p)
        sm = SUM.build(self.name, rec.company_id.name or '', location, '', rec.contract_type_id.name or '', '', '', '', True,
                       {k: data.get(k) or ([] if k != 'about' else '') for k in ('about', 'duties', 'skills', 'quals', 'experience', 'preferred')})
        block = SUM.display(sm)
        return {
            'on': True, 'has_data': bool(data), 'title': self.name, 'company': rec.company_id.name or '',
            'location': ', '.join(p for p in (address.city or '', address.country_id.name or '') if p),
            'salary': '', 'job_type': rec.contract_type_id.name or '', 'posted': '', 'badge': None, 'labels': [],
            'overview': block['overview'] if data else '', 'points': block['points'], 'point_groups': block['point_groups'], 'skills': block['skills'], 'facts': block['facts'], 'from_text': sm['from_text'],
            'notice': '', 'apply_url': apply_url, 'go_href': ('/jobs/position/%d/go' % self.id) if apply_url else '',
            'internal_href': ('/jobs/apply/%s' % self.env['ir.http']._slug(self)) if (internal and not apply_url) else '',
            'source_text': '', 'source': source, 'internal_apply': internal,
        }

    # ------------------------------------------------------------------ keys (never stored in code: environment or system parameters)
    def _llmd_keys(self):
        icp = self.env['ir.config_parameter'].sudo()

        def get(env_name, param):
            return (os.environ.get(env_name) or icp.get_param(param) or '').strip()

        return {'adzuna_id': get('ADZUNA_APP_ID', 'llmd_agg.adzuna_app_id'), 'adzuna_key': get('ADZUNA_APP_KEY', 'llmd_agg.adzuna_app_key'),
                'jooble': get('JOOBLE_API_KEY', 'llmd_agg.jooble_api_key') or icp.get_param('llmd_agg.jooble_key') or '',      # same parameter name as the job board uses (the older name still works)
                'jsearch': get('JSEARCH_API_KEY', 'llmd_agg.jsearch_api_key'),
                'jsearch_url': get('JSEARCH_BASE_URL', 'llmd_agg.jsearch_base_url')}

    # ------------------------------------------------------------------ the job APIs (each returns (candidates, note))
    @api.model
    def _llmd_himalayas(self, queries, country):
        """Himalayas (no key, TEMPORARY fallback, switched off by llmd_agg.himalayas_mode = off): the FULL listing text and the listing link of remote jobs open to `country`."""
        if (self.env['ir.config_parameter'].sudo().get_param('llmd_agg.himalayas_mode') or 'fallback').strip() == 'off':
            return [], ''
        try:
            jobs = S.fetch_himalayas(queries, (country or 'IN').upper())
        except S.SourceError as exc:
            return [], 'Himalayas: %s' % exc
        return [{'source': 'Himalayas', 'title': j['title'], 'company': j['company'], 'html': j['html'], 'url': j['apply_url']} for j in jobs], 'Himalayas: %d listings' % len(jobs)

    @api.model
    def _llmd_jsearch(self, keys, what):
        """JSearch: needs a key; returns the full job text and the apply link. Its requests are counted in the same monthly budget as the job board's."""
        if not keys['jsearch']:
            return [], ''
        counter = self.env['llmd.job.source'].sudo().search([('code', '=', 'jsearch')], limit=1)
        try:
            jobs = S.fetch_jsearch(keys['jsearch'], [what], keys['jsearch_url'], 'in', counter._count_request if counter else None)
        except S.SourceError as exc:
            return [], 'JSearch: %s' % exc
        return [{'source': 'JSearch', 'title': j['title'], 'company': j['company'], 'html': j['html'], 'url': j['apply_url']} for j in jobs], 'JSearch: %d' % len(jobs)

    @api.model
    def _llmd_adzuna(self, keys, what, city, country):
        """Adzuna: needs a key; returns only a snippet of the description."""
        if not (keys['adzuna_id'] and keys['adzuna_key']):
            return [], ''
        url = 'https://api.adzuna.com/v1/api/jobs/%s/search/1' % (country or 'in')
        found = []
        for where in ([city, ''] if city else ['']):
            params = {'app_id': keys['adzuna_id'], 'app_key': keys['adzuna_key'], 'what': what, 'results_per_page': 10, 'content-type': 'application/json'}
            if where:
                params['where'] = where
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code != 200:
                return [], 'Adzuna: HTTP %s' % resp.status_code
            for j in resp.json().get('results', []):
                found.append({'source': 'Adzuna', 'title': j.get('title'), 'company': (j.get('company') or {}).get('display_name'), 'text': j.get('description'), 'url': j.get('redirect_url')})
            if found:
                break
        return found, 'Adzuna: %d' % len(found)

    @api.model
    def _llmd_jooble(self, keys, what, where):
        """Jooble: needs a key; returns only a snippet of the description."""
        if not keys['jooble']:
            return [], ''
        resp = requests.post('https://jooble.org/api/%s' % keys['jooble'], json={'keywords': what, 'location': where or ''}, timeout=TIMEOUT)
        if resp.status_code != 200:
            return [], 'Jooble: HTTP %s' % resp.status_code
        found = [{'source': 'Jooble', 'title': j.get('title'), 'company': j.get('company'), 'text': j.get('snippet'), 'url': j.get('link')} for j in resp.json().get('jobs', [])]
        return found, 'Jooble: %d' % len(found)

    # ------------------------------------------------------------------ choosing the listing
    @api.model
    def _llmd_choose(self, title, candidates):
        """The listing whose title fits the job best and whose text gives the richest page. -> (candidate, parsed) or (None, None)."""
        best = None
        for c in candidates:
            ts = P.title_score(title, c.get('title'))
            if ts < 0.6 or not c.get('url'):
                continue
            if c.get('html'):
                parsed = P.parse_listing(c['html'], c.get('company'), c.get('title'))
                if not P.usable(parsed):
                    continue
            else:
                parsed = P.parse_snippet(P.clean_snippet(c.get('text')), c.get('company'), c.get('title'))
                if len(parsed['about']) < 80:
                    continue
            score = (5 if ts >= 0.99 else 0) + ts * 3 + P.richness(parsed) + (0.5 if c.get('html') else 0)       # the exact title wins unless it is a thin listing; a full text beats a snippet
            if best is None or score > best[0]:
                best = (score, c, parsed)
        return (best[1], best[2]) if best else (None, None)

    # ------------------------------------------------------------------ the whole job
    def _llmd_refresh(self):
        keys = self._llmd_keys()
        for job in self:
            try:
                job._llmd_refresh_one(keys)
            except Exception:                                       # never block creating / renaming a job
                _logger.exception('llmd job content: job %s', job.id)

    def _llmd_refresh_one(self, keys):
        self.ensure_one()
        title = (self.name or '').strip()
        city = self.address_id.city or ''
        country = self.address_id.country_id
        where = ', '.join(p for p in (city, country.name) if p)
        fixed = P.fix_title(title)
        queries = [title]
        if fixed and fixed.lower() != title.lower():
            queries.append(fixed)
        if fixed and fixed.split()[-1] not in ROLE_NOUNS:             # "Mern Stack" -> also search "mern stack developer"
            queries.append(fixed + ' developer')
        candidates, notes = [], []
        for fetch in (lambda: self._llmd_himalayas(queries, country.code or 'IN'),
                      lambda: self._llmd_adzuna(keys, fixed or title, city, (country.code or 'IN').lower()),
                      lambda: self._llmd_jsearch(keys, (fixed or title) + ((' ' + where) if where else '')),
                      lambda: self._llmd_jooble(keys, fixed or title, where)):
            try:
                found, note = fetch()
            except requests.RequestException as exc:
                found, note = [], 'request failed: %s' % exc.__class__.__name__
            candidates += found
            if note:
                notes.append(note)
        pick, parsed = self._llmd_choose(title, candidates)
        vals = {'agg_fetched': fields.Datetime.now()}
        if pick:
            content = dict(parsed, source=pick['source'])
            vals.update(agg_source=pick['source'], agg_title=re.sub(r'<[^>]+>', '', pick.get('title') or ''), agg_company=pick.get('company') or '', agg_url=pick['url'],
                        agg_snippet=parsed['about'], agg_json=json.dumps(content, ensure_ascii=False), agg_status='; '.join(notes + ['matched'])[:250])
            if not self.apply_url or self.apply_url == self.agg_url:       # never over a link somebody typed in
                vals['apply_url'] = pick['url']
        else:
            vals.update(agg_source=False, agg_title=False, agg_company=False, agg_snippet=False, agg_json=False, agg_status='; '.join(notes + ['no usable listing'])[:250])
            if self.apply_url and self.apply_url == self.agg_url:
                vals['apply_url'] = False
            vals['agg_url'] = False
        self.with_context(llmd_skip=True).write(vals)
