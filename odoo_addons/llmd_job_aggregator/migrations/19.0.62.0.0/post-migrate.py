"""v19.0.62: every job gets its address /jobs/<slug> (the company records of /companies are filled by the stored compute of company_id)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    jobs = env['llmd.job.listing'].with_context(active_test=False).search([('url_slug', '=', False)], order='id')
    jobs.assign_slugs()
