"""19.0.29.0.0: Apply Clicks hold job data only, and an application is a name + an e-mail. The personal columns that 19.0.28 added to the click lines (the
logged-in user, name, e-mail, phone) and the phone of the Job Applications are dropped from the database, so that no old personal data stays behind; the
phone of the Recruitment applicants that belong to these applications is emptied. Every click line and every application record stays."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    for table, columns in (('llmd_job_click', ('user_id', 'applicant_name', 'email', 'phone', 'logged_in')), ('llmd_job_application', ('phone',))):
        for column in columns:
            cr.execute('ALTER TABLE %s DROP COLUMN IF EXISTS %s' % (table, column))
    cr.execute("""UPDATE hr_applicant SET partner_phone = NULL
                   WHERE partner_phone IS NOT NULL AND id IN (SELECT applicant_id FROM llmd_job_application WHERE applicant_id IS NOT NULL)""")
    _logger.info('19.0.29: personal columns of Apply Clicks and the phone of Job Applications removed; %d applicant phones emptied', cr.rowcount)
