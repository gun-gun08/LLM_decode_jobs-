"""Version 19.0.10: the applications saved before the job id was kept (the removed first form) get their External Job ID back. Nothing is made up: the saved record knows the original link
of the job; the id is the one of the stored job listing with that link (a Jooble link carries the id itself, a Himalayas link IS the id). A record whose job cannot be found stays as it is."""
import re

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    for rec in env['llmd.job.application'].with_context(active_test=False).search([('ext_id', 'in', [False, '']), ('apply_url', '!=', False)]):
        url = rec.apply_url or ''
        wanted = re.search(r'/desc/(-?\d+)', url).group(1) if re.search(r'/desc/(-?\d+)', url) else url.split('?')[0]
        listing = Listing.search([('ext_id', '=', wanted), ('title', '=', rec.job_title)], limit=1) or Listing.search([('ext_id', '=', wanted)], limit=1)
        if listing:
            values = {'ext_id': listing.ext_id, 'source': listing.source}
            if not rec.listing_id:
                values['listing_id'] = listing.id
            rec.write(values)
