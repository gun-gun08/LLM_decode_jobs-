"""19.0.20.0.0: the stored summaries are made again, so a line that only opens a list ("You'll thrive with us if you:") is no longer shown as a key point.
Only summary_json changes; the jobs themselves are not touched."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    jobs = Listing.search([])
    env.add_to_compute(Listing._fields['summary_json'], jobs)
    env.flush_all()
