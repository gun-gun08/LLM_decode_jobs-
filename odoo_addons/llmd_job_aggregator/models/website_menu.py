from urllib.parse import urlsplit

from odoo import models
from odoo.http import request


class WebsiteMenu(models.Model):
    _inherit = 'website.menu'

    def _is_active(self):
        """The Jobs menu stays active on every page of the job board (a search, a category, company, place or role page, one job), not only on /jobs itself."""
        if request and not self.child_id and not self.is_mega_menu and urlsplit(self.url or '').path.rstrip('/') == '/jobs':
            path = request.httprequest.path
            if path == '/jobs' or path.startswith('/jobs/'):
                return True
        return super()._is_active()
