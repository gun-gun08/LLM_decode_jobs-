"""19.0.28.0.0: "China & Hong Kong" is a region of its own (it was part of Asia-Pacific), more Chinese cities are known, and the companies headquartered in China,
Hong Kong and the UAE are listed. Every stored job gets its country, region, company headquarters and its language fields (listing language, languages
asked) again. The jobs themselves are not touched."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    jobs = Listing.search([])
    for names in (('country', 'city'), ('region', 'india_zone', 'region_label', 'india_zone_label', 'company_hq', 'company_region', 'company_region_label'),
                  ('source_lang', 'languages')):
        for name in names:
            env.add_to_compute(Listing._fields[name], jobs)
        env.flush_all()
