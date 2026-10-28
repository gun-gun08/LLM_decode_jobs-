"""19.0.14.0.0: direct links only (default). The visible jobs whose Apply Now opens a job board's own page (Adzuna, Jooble, Himalayas) are hidden - kept in the
database, never deleted - unless the system parameter llmd_agg.direct_links_only is 0."""
from odoo import SUPERUSER_ID, api

from odoo.addons.llmd_job_aggregator.models.listing import direct_links_only, is_board_link
from odoo.addons.llmd_job_aggregator.models import board_config as C


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if not direct_links_only(env):
        return
    names = [C.SOURCE_NAMES[c] for c in C.BOARD_LINK_SOURCES]
    board = env['llmd.job.listing'].search([('active', '=', True), ('source', '!=', 'test')]).filtered(lambda r: r.source in names or is_board_link(r.apply_url))
    board.write({'active': False})
