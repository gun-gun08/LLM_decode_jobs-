"""19.0.32.0.0: Experience Required also takes the years a job's requirements state in a line without the word "experience" ("2–5 years in DevOps ...")
and "Fresher" / "Entry Level" from a title that says so. Job Applications whose Experience Required is empty get it from their job when the job states
it; a value that is already there is never changed, a job that states nothing leaves the field empty. No record is created or deleted."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    apps = env['llmd.job.application'].with_context(active_test=False).search([('experience_required', 'in', (False, '')), ('listing_id', '!=', False)])
    filled = 0
    for rec in apps:
        value = rec.listing_id.experience_required()
        if value:
            rec.write({'experience_required': value})
            filled += 1
    env.flush_all()
    _logger.info('19.0.32: Experience Required filled for %d of %d applications that had none', filled, len(apps))
