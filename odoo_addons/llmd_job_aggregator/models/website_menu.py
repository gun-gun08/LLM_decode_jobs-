from urllib.parse import urlsplit

from odoo import api, models
from odoo.http import request

HIRE_URL = '/jobs/employers'
HIRE_PAGES = ('/jobs/employers', '/jobs/post', '/jobs/my', '/jobs/plan')      # the pages for companies: "Hire Talent" is the active menu there, not Jobs


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    def _is_active(self):
        """The Jobs menu stays active on every page of the job board (a search, a category, company, place or role page, one job), not only on /jobs itself;
        "Hire Talent" on the pages for companies."""
        if request and not self.child_id and not self.is_mega_menu:
            url = urlsplit(self.url or '').path.rstrip('/')
            path = request.httprequest.path
            for_companies = path.startswith(HIRE_PAGES)
            if url == HIRE_URL:
                return for_companies
            if url == '/jobs' and (path == '/jobs' or path.startswith('/jobs/')):
                return not for_companies
        return super()._is_active()

    @api.model
    def _llmd_hire_websites(self):
        """The websites that show "Hire Talent": the job board's own website(s) - a domain starting with "jobs." (jobs.llmdecode.ai), not learn.llmdecode.com.
        With no such domain (a local database with one website and no domain) every website, as before."""
        websites = self.env['website'].search([])
        def host(w):
            d = (w.domain or '').strip()
            return (urlsplit(d if '://' in d else '//' + d).hostname or '').lower()
        return websites.filtered(lambda w: host(w).startswith('jobs.')) or websites

    @api.model
    def _llmd_ensure_hire_menu(self):
        """The job board's website gets "Hire Talent" (the page for companies) right after its Jobs menu - once; the other websites (learn.llmdecode.com) have none.
        Nothing else in the menu changes."""
        hire_sites = self._llmd_hire_websites()
        self.search([('website_id', 'not in', hire_sites.ids), ('website_id', '!=', False)]).filtered(
            lambda m: urlsplit(m.url or '').path.rstrip('/') == HIRE_URL).unlink()
        for website in hire_sites:
            menus = self.search([('website_id', '=', website.id)])
            if menus.filtered(lambda m: urlsplit(m.url or '').path.rstrip('/') == HIRE_URL):
                continue
            jobs = menus.filtered(lambda m: urlsplit(m.url or '').path.rstrip('/') == '/jobs')[:1]
            if not jobs:
                continue
            later = menus.filtered(lambda m: m.parent_id == jobs.parent_id and m.sequence > jobs.sequence)
            for m in later:
                m.sequence += 1
            self.create({'name': 'Hire Talent', 'url': HIRE_URL, 'parent_id': jobs.parent_id.id, 'website_id': website.id, 'sequence': jobs.sequence + 1})
