"""Version 19.0.9: a click on "Apply Now" is no longer a (merged) line of Job Applications: every click is one line of Apply Clicks (llmd.job.click).

The lines the earlier version kept for clicks (state "clicked") are moved to the click log, and only what they really knew is moved: the first click and, when there was more than one
click, the last click. Clicks that were never recorded individually are not made up. The name or e-mail such a line may carry (a logged-in website user) is not kept: a click has no
applicant. Everything else (applications, reports, confirmations) stays where it is.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'llmd_job_application' AND column_name = 'click_count'")
    if not cr.fetchone():
        return
    cr.execute("""SELECT id, listing_id, hr_job_id, job_title, company, location, source, ext_id, apply_url, job_key, visitor_key, click_count, first_click, last_click, create_date
                    FROM llmd_job_application WHERE state = 'clicked' ORDER BY id""")
    rows = cr.dictfetchall()
    moved = []
    for row in rows:
        times = [(row['first_click'] or row['create_date'], False)]
        if (row['click_count'] or 0) > 1 and row['last_click'] and row['last_click'] != times[0][0]:
            times.append((row['last_click'], True))
        for when, repeat in times:
            cr.execute("""INSERT INTO llmd_job_click (create_uid, create_date, write_uid, write_date, clicked_at, status, listing_id, hr_job_id, job_title, company, location, source, ext_id,
                                                      apply_url, job_key, visitor_key, repeat)
                          VALUES (%s, now() at time zone 'utc', %s, now() at time zone 'utc', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       (SUPERUSER_ID, SUPERUSER_ID, when, 'clicked' if row['apply_url'] else 'no_link', row['listing_id'], row['hr_job_id'], row['job_title'], row['company'], row['location'],
                        row['source'], row['ext_id'], row['apply_url'], row['job_key'], row['visitor_key'], repeat))
        moved.append(row['id'])
    if moved:
        env = api.Environment(cr, SUPERUSER_ID, {})
        env['llmd.job.application'].with_context(active_test=False).browse(moved).unlink()
    _logger.info('llmd_job_aggregator 19.0.9: %d click line(s) moved to the click log', len(moved))
