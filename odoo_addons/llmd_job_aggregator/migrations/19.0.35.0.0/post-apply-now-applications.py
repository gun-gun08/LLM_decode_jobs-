"""19.0.35.0.0: the signed-in person of an Apply Now is kept in Job Applications (status "Redirected to External Site" / "Apply Clicked"), no longer in Apply Clicks.
The Apply Clicks lines that 19.0.33 saved with a user, name or e-mail get their Job Applications record (one per person and job, the time of their last click,
the number of clicks). Nothing is deleted or changed in Apply Clicks: those lines and their old columns stay as they are, only no longer shown there."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

SNAPSHOT = ('listing_id', 'hr_job_id', 'job_title', 'company', 'location', 'source', 'ext_id', 'apply_url', 'job_key', 'posted_type')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    App = env['llmd.job.application'].with_context(active_test=False, mail_create_nolog=True, tracking_disable=True)
    clicks = env['llmd.job.click'].search(['|', ('user_id', '!=', False), ('email', '!=', False)], order='clicked_at, id')
    made = updated = 0
    for click in clicks:
        user = click.user_id
        email = (click.email or user.email or '').strip().lower()
        identity = 'e:%s' % email if '@' in email else ('u:%d' % user.id if user else '')
        if not identity:
            continue
        info = {k: (click[k].id if k in ('listing_id', 'hr_job_id') else click[k]) or False for k in SNAPSHOT}
        external = click.status == 'clicked' and (click.apply_url or '').startswith(('https://', 'http://'))
        rec = App.search([('job_key', '=', info['job_key']), ('identity_key', '=', identity)], limit=1)
        if rec:
            vals = {'clicked_at': click.clicked_at, 'click_count': rec.click_count + 1}
            if not rec.user_id and user:
                vals['user_id'] = user.id
            if rec.state == 'clicked' and external:
                vals['state'] = 'redirected'
            rec.write(vals)
            updated += 1
            continue
        App.create(dict(info, identity_key=identity, applicant_name=click.applicant_name or user.partner_id.name or user.name or False, email=email or False,
                        user_id=user.id or False, channel='apply_now', state='redirected' if external else 'clicked', clicked_at=click.clicked_at, click_count=1))
        made += 1
    _logger.info('19.0.35: %d signed-in Apply Clicks lines -> %d new Job Applications records ("Redirected to External Site" / "Apply Clicked"), %d updated',
                 len(clicks), made, updated)
