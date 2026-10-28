"""19.0.25.0.0: "Explore jobs by region". The country of a job now also comes from short forms and big cities ("London, UK"), and every stored job gets its
world region and region of India. The jobs themselves are not touched."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    jobs = Listing.search([])
    env.add_to_compute(Listing._fields['country'], jobs)
    env.flush_all()
    for name in ('region', 'india_zone', 'region_label', 'india_zone_label'):
        env.add_to_compute(Listing._fields[name], jobs)
    env.flush_all()
