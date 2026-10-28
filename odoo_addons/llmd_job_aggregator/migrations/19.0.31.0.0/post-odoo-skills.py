"""19.0.31.0.0: the skills of the stored jobs go into Odoo's skill system (llmd.job.listing.skill_ids): Technical Skills (a skill type of its own, made
from the first one a job mentions), Odoo's Languages and Soft Skills matched by name. Only job listings get skills - no applicant, no employee. Nothing
is deleted; Odoo's own skills are only linked, never changed."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    jobs = env['llmd.job.listing'].with_context(active_test=False).search([])
    changed = jobs.link_odoo_skills()
    env.flush_all()
    _logger.info('19.0.31: %d of %d jobs linked to Odoo skills', changed, len(jobs))
