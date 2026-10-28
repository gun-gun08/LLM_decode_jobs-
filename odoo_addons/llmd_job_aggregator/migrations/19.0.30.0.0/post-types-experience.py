"""19.0.30.0.0: Posted Type (Fetched / Public User) on jobs, Application Type (Website Form / External Apply Click) and the job's Department, Job Type and
Experience Required on Job Applications. The stored records get these values from the job they belong to; a record whose job is gone keeps them empty.
No record is created or deleted."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Listing = env['llmd.job.listing'].with_context(active_test=False)
    env.add_to_compute(Listing._fields['posted_type'], Listing.search([]))
    Job = env['hr.job'].with_context(active_test=False)
    env.add_to_compute(Job._fields['llmd_posted_type'], Job.search([]))
    env.flush_all()
    Application = env['llmd.job.application'].with_context(active_test=False)
    for rec in Application.search([]):
        info = Application.job_details(listing=rec.listing_id or None, job=rec.hr_job_id or None)
        info['posted_type'] = (rec.listing_id.posted_type if rec.listing_id else rec.hr_job_id.llmd_posted_type) or False
        rec.write({k: v for k, v in info.items() if v})
    Click = env['llmd.job.click'].with_context(active_test=False)
    for rec in Click.search([('posted_type', '=', False)]):
        posted = (rec.listing_id.posted_type if rec.listing_id else rec.hr_job_id.llmd_posted_type) or False
        if posted:
            rec.write({'posted_type': posted})
    env.flush_all()
