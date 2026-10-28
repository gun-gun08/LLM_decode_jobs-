r"""Lists (and with --delete removes) the test records that earlier versions of the end-to-end test left in the local database:
the test applicants "E2E ..." (Recruitment > Applications), their Job Applications records, and the unpublished position the old application form made for the test job.

  . .\scripts\env.ps1
  python tests\e2e_leftovers.py            list
  python tests\e2e_leftovers.py --delete   delete them
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gw  # noqa: E402

DELETE = '--delete' in sys.argv

applicants = gw.search('hr.applicant', [['partner_name', 'like', 'E2E'], ['active', 'in', [True, False]]], 100)
apps = gw.search('llmd.job.application', [['applicant_name', 'like', 'E2E']], 100)
print('hr.applicant:', len(applicants))
for r in applicants:
    print('  ', r['id'], r['partner_name'], r['email_from'], r['job_id'], r['create_date'])
print('llmd.job.application:', len(apps))
for r in apps:
    print('  ', r['id'], r['applicant_name'], r['email'], r['state'], r['listing_id'], r['create_date'])
positions = sorted({r['job_id'][0] for r in applicants if r['job_id']})
positions = [p for p in gw.search('hr.job', [['id', 'in', positions], ['website_published', '=', False]], 50)]
print('unpublished positions of those applicants:', [(p['id'], p['name']) for p in positions])
if DELETE:
    for r in applicants:
        gw.call('delete_record', model='hr.applicant', res_id=r['id'])
    for r in apps:
        gw.call('delete_record', model='llmd.job.application', res_id=r['id'])
    for p in positions:
        gw.call('delete_record', model='hr.job', res_id=p['id'])
    print('deleted', len(applicants), 'applicants,', len(apps), 'application records and', len(positions), 'positions')
