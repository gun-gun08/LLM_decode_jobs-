"""19.0.23.0.0: the job categories were split (Engineering -> AI & Machine Learning + IT & Software, Business & Operations -> Finance, People & HR,
Operations & Strategy): every stored job gets its category and job function again. The jobs themselves are not touched."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    jobs = Listing.search([])
    env.add_to_compute(Listing._fields['job_category'], jobs)
    env.add_to_compute(Listing._fields['job_function'], jobs)
    env.flush_all()
