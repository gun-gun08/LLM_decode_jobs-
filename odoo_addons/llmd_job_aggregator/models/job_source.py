import logging
import os
import re

from odoo import api, fields, models

from . import board_config as C
from . import job_facets as F
from . import sources as S

_logger = logging.getLogger(__name__)


class LlmdJobSource(models.Model):
    """One row per job source with its honest status: connected and working, not configured (what is missing), or failing (why)."""
    _name = 'llmd.job.source'
    _description = 'Job source (API / feed)'
    _order = 'sequence, id'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    kind = fields.Selection([('api', 'Official API'), ('feed', 'Authorized job feed')], default='api')
    home_url = fields.Char()
    sequence = fields.Integer(default=10)
    enabled = fields.Boolean(default=True)
    howto = fields.Text(string='How to connect it')
    last_run = fields.Datetime(readonly=True)
    last_status = fields.Selection([('ok', 'Working'), ('not_configured', 'Not connected'), ('error', 'Error'), ('skipped', 'Off / not needed')], readonly=True, default='not_configured')
    last_message = fields.Char(readonly=True)
    last_count = fields.Integer(string='Jobs in last run', readonly=True)
    requests_used = fields.Integer(string='API requests used', readonly=True)
    budget_period = fields.Char(string='Request counter period', readonly=True, help='For plans that count requests per month: the month the counter belongs to.')

    _code_uniq = models.Constraint('unique(code)', 'This source already exists.')

    @api.model
    def _ensure_sources(self):
        """Create the sources of board_config.SOURCES that are missing and remove the ones that are no longer part of the integration (Himalayas was removed)."""
        known = {s.code: s for s in self.search([])}
        for i, (code, name, kind, home, howto) in enumerate(C.SOURCES):
            if code not in known:
                self.create({'code': code, 'name': name, 'kind': kind, 'home_url': home, 'howto': howto, 'sequence': (i + 1) * 10})
            else:
                known[code].write({'howto': howto, 'sequence': (i + 1) * 10})
        self.search([('code', 'not in', [c[0] for c in C.SOURCES])]).unlink()
        return self.search([])

    # ------------------------------------------------------------------ credentials: environment variables first, then system parameters (never code, never the page)
    def _secret(self, env_name):
        icp = self.env['ir.config_parameter'].sudo()
        return (os.environ.get(env_name) or icp.get_param('llmd_agg.' + env_name.lower()) or '').strip()

    def _credentials(self):
        """-> dict of what the source needs, or None when something is missing."""
        self.ensure_one()
        if self.code == 'adzuna':
            a, k = self._secret('ADZUNA_APP_ID'), self._secret('ADZUNA_APP_KEY')
            return {'app_id': a, 'app_key': k} if a and k else None
        if self.code == 'jooble':
            k = self._secret('JOOBLE_API_KEY')
            return {'key': k} if k else None
        if self.code == 'jsearch':
            k = self._secret('JSEARCH_API_KEY')
            return {'key': k, 'base_url': self._secret('JSEARCH_BASE_URL')} if k else None
        if self.code in ('indeed', 'naukri'):
            url = self._secret(self.code.upper() + '_FEED_URL')
            return {'url': url, 'token': self._secret(self.code.upper() + '_FEED_TOKEN')} if url else None
        if self.code == 'himalayas':
            return {}                                                        # no key needed
        if self.code == 'company':
            value = (self.env['ir.config_parameter'].sudo().get_param('llmd_agg.company_boards') or '').strip()
            boards = S.parse_boards(C.COMPANY_BOARDS if not value else value)                # "off" (or any text without a board) switches the source off
            return {'boards': boards} if boards else None
        return None

    def is_configured(self):
        self.ensure_one()
        return self._credentials() is not None

    # ------------------------------------------------------------------ request budgets (the free plans are small: stop before they are used up)
    def _count_request(self):
        """Count one API request; False when this source's budget is used up. Jooble: 500 requests in total per key. JSearch: counted per calendar month."""
        default, period = C.REQUEST_BUDGET.get(self.code, (0, 'total'))
        if not default:
            return True
        budget = int(self.env['ir.config_parameter'].sudo().get_param('llmd_agg.%s_budget' % self.code) or default)
        if period == 'month':
            stamp = fields.Date.today().strftime('%Y-%m')
            if self.budget_period != stamp:
                self.sudo().write({'budget_period': stamp, 'requests_used': 0})
        if self.requests_used >= budget:
            return False
        self.sudo().write({'requests_used': self.requests_used + 1})
        return True

    def _queries_for_run(self, queries):
        """All queries, or - for the small plans - the next few: the window moves on every day, so every query is used within a few days."""
        per_run = int(self.env['ir.config_parameter'].sudo().get_param('llmd_agg.%s_per_run' % self.code) or C.QUERIES_PER_RUN.get(self.code, 0))
        if not per_run or per_run >= len(queries):
            return list(queries)
        start = (fields.Date.today().toordinal() * per_run) % len(queries)
        return [queries[(start + i) % len(queries)] for i in range(per_run)]

    # ------------------------------------------------------------------ fetch (never raises: a broken source only changes its own status)
    def run(self, queries):
        self.ensure_one()
        now = fields.Datetime.now()
        creds = self._credentials()
        if creds is None:
            self.write({'last_run': now, 'last_status': 'not_configured', 'last_count': 0, 'last_message': (self.howto or 'Not connected')[:250]})
            return []
        queries = self._queries_for_run(queries)
        try:
            if self.code == 'adzuna':
                jobs = S.fetch_adzuna(creds['app_id'], creds['app_key'], queries, 'in')
            elif self.code == 'jooble':
                jobs = S.fetch_jooble(creds['key'], queries, 'India', self._count_request)
            elif self.code == 'jsearch':
                jobs = S.fetch_jsearch(creds['key'], queries, creds['base_url'], 'in', self._count_request)
            elif self.code in ('indeed', 'naukri'):
                jobs = S.fetch_feed(creds['url'], creds['token'], self.name)
            elif self.code == 'himalayas':
                jobs = S.fetch_himalayas(queries, 'IN')
            elif self.code == 'company':
                icp = self.env['ir.config_parameter'].sudo()
                per_board = int(icp.get_param('llmd_agg.company_boards_per_board') or C.COMPANY_PER_BOARD)
                per_world = int(icp.get_param('llmd_agg.company_boards_per_board_world') or C.COMPANY_PER_BOARD_WORLD)
                boards = creds['boards']
                part = self.env.context.get('llmd_board_slice')                  # a batch of the scheduled sync: (first, last + 1)
                if part:
                    boards = boards[part[0]:part[1]]
                jobs = S.fetch_company_boards(boards, self._company_keep, keep_place=lambda loc: F.is_india(loc), per_board=per_board, country='in',
                                              listed=self.env.context.get('llmd_listed'), per_board_world=per_world)      # fetch_now hides the jobs the companies closed
            else:
                raise S.SourceError('this source is not part of the integration')
        except S.SourceError as exc:
            self.write({'last_run': now, 'last_status': 'error', 'last_count': 0, 'last_message': str(exc)[:250]})
            return []
        except Exception:                                                    # a broken source must never break the board
            _logger.warning('job source %s failed', self.code, exc_info=True)       # a warning: handled here (an ERROR log trips Odoo's "Run Manually")
            self.write({'last_run': now, 'last_status': 'error', 'last_count': 0, 'last_message': 'unexpected error - see the Odoo log'})
            return []
        self.write({'last_run': now, 'last_status': 'ok', 'last_count': len(jobs), 'last_message': ''})
        return jobs

    @staticmethod
    def _company_keep(title, location, department=''):
        """A company board lists all of a company's jobs, in India and abroad: keep the ones that fit a course role or one of the job categories (where the job
        is decides only how many of them are taken per company: per_board in India, per_board_world elsewhere)."""
        return C.board_relevant(title, department)

    def mark_skipped(self, message):
        self.write({'last_run': fields.Datetime.now(), 'last_status': 'skipped', 'last_count': 0, 'last_message': message[:250]})

    def action_fetch_all(self):
        self.env['llmd.job.listing'].fetch_now()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
