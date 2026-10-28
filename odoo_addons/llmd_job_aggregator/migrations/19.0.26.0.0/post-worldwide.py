"""19.0.26.0.0: a worldwide board. Countries, cities and regions are read from locations all over the world, there are more job categories, and every job gets
the headquarters of its company. Every stored job gets these values again; the jobs themselves are not touched."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    jobs = Listing.search([])
    for names in (('exp_level', 'job_type', 'work_mode', 'india', 'city'), ('country', 'job_category', 'job_function', 'category_label', 'function_label'),
                  ('region', 'india_zone', 'region_label', 'india_zone_label', 'company_hq', 'company_region', 'company_region_label')):
        for name in names:
            env.add_to_compute(Listing._fields[name], jobs)
        env.flush_all()
