"""The applicants saved earlier by the (removed) first application form were only visible under Recruitment > Applications. They get a record in Recruitment > Job Applications too
(channel "our website", state "received by us"); the job is read from the note that was saved with each applicant. Nothing is changed on the applicants themselves."""
import html
import re

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Application = env['llmd.job.application'].with_context(mail_create_nolog=True, mail_notrack=True)
    job = env['hr.job'].with_context(active_test=False).search([('name', '=', 'Job board applications (external jobs)')], limit=1)
    if not job:
        return
    for applicant in env['hr.applicant'].with_context(active_test=False).search([('job_id', '=', job.id)]):
        if Application.with_context(active_test=False).search_count([('applicant_id', '=', applicant.id)]):
            continue
        note = str(applicant.applicant_notes or '')

        def field(label):
            m = re.search(r'<b>%s:</b>\s*(.*?)</li>' % re.escape(label), note, re.S)
            return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''

        email = (applicant.email_from or '').strip().lower()
        Application.create({
            'applicant_name': applicant.partner_name, 'email': email or False, 'phone': applicant.partner_phone or False, 'applicant_id': applicant.id,
            'job_title': field('Job') or 'External job', 'company': '' if field('Company') == '-' else field('Company'), 'source': field('Source'), 'apply_url': field('Original job link'),
            'job_key': 'legacy:%d' % applicant.id, 'identity_key': 'e:%s' % email if email else 'a:%d' % applicant.id, 'channel': 'own', 'state': 'submitted',
            'application_date': applicant.create_date, 'first_click': False})
