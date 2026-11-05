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
    def _llmd_ensure_hire_menu(self):
        """Every website whose menu has the Jobs page gets "Hire Talent" (the page for companies) right after it - once; nothing else in the menu changes."""
        for website in self.env['website'].search([]):
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
