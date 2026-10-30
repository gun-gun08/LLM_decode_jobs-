"""Run inside `odoo shell`: editing job board listings in the backend (Recruitment > Job board > Job board listings). One transaction, rolled back at the end: nothing is stored.

  Get-Content tests\\listing_edit_test.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
"""
from odoo.exceptions import AccessError, ValidationError

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


def raises(exc, fn):
    try:
        with env.cr.savepoint():
            fn()
    except exc:
        return True
    except Exception as other:                                   # noqa: BLE001
        print('    (raised %r instead)' % other)
        return False
    return False


Listing = env['llmd.job.listing']
Users = env['res.users'].with_context(no_reset_password=True)
manager = Users.create({'name': 'Edit test manager', 'login': 'llmd-edit-test-manager', 'group_ids': [(6, 0, [env.ref('hr_recruitment.group_hr_recruitment_manager').id])]}) \
    if 'group_ids' in Users._fields else Users.create({'name': 'Edit test manager', 'login': 'llmd-edit-test-manager', 'groups_id': [(6, 0, [env.ref('hr_recruitment.group_hr_recruitment_manager').id])]})
officer = Users.create({'name': 'Edit test officer', 'login': 'llmd-edit-test-officer',
                        ('group_ids' if 'group_ids' in Users._fields else 'groups_id'): [(6, 0, [env.ref('hr_recruitment.group_hr_recruitment_user').id])]})


def listing(ext, **kw):
    return Listing.create(dict({'source': 'Adzuna', 'ext_id': ext, 'title': 'Data Analyst', 'company': 'Acme', 'location': 'Pune, Maharashtra',
                                'apply_url': 'https://careers.example.com/%s' % ext, 'description_html': '<p>Full-time role, work from office in Pune.</p>'}, **kw))


print('\n=== E1. who may edit ===')
a, b, c = listing('edit-a'), listing('edit-b'), listing('edit-c')
check('a Recruitment manager can change a job', not raises(Exception, lambda: a.with_user(manager).write({'title': 'Senior Data Analyst'})))
check('a recruiter (Officer) can read but not change a job', a.with_user(officer).read(['title']) and raises(AccessError, lambda: b.with_user(officer).write({'title': 'X'})))
check('nobody but an admin can delete a job from the backend', raises(AccessError, lambda: c.with_user(manager).unlink()))

print('\n=== E2. edits are stored ===')
a.with_user(manager).write({'location': 'Bengaluru, Karnataka', 'work_mode': 'hybrid', 'job_type': 'contract', 'apply_url': 'https://jobs.example.org/a', 'salary': 'INR 12-15 LPA'})
env.invalidate_all()
a = Listing.browse(a.id)
check('title, location, work mode, job type, salary and apply URL are saved (read again from the database)',
      (a.title, a.location, a.work_mode, a.job_type, a.apply_url, a.salary) == ('Senior Data Analyst', 'Bengaluru, Karnataka', 'hybrid', 'contract', 'https://jobs.example.org/a', 'INR 12-15 LPA'),
      (a.title, a.location, a.work_mode, a.job_type, a.apply_url))
check('the changed fields are remembered as changed by hand', set(a.manual_names()) == {'title', 'location', 'work_mode', 'job_type', 'apply_url', 'salary'}, a.manual_fields)
check('the website page shows the new values', a.detail_vals()['title'] == 'Senior Data Analyst' and a.detail_vals()['work_mode'] == 'Hybrid' and a.detail_vals()['apply_url'] == 'https://jobs.example.org/a')
(b | c).with_user(manager).write({'work_mode': 'remote'})
env.invalidate_all()
check('several jobs can be changed at once', Listing.browse([b.id, c.id]).mapped('work_mode') == ['remote', 'remote'] and all('work_mode' in r.manual_names() for r in (b | c)))

print('\n=== E3. wrong values are refused ===')
check('a work mode the filters do not know is refused', raises(ValidationError, lambda: a.write({'work_mode': 'sometimes'})))
check('a javascript: application link is refused', raises(ValidationError, lambda: a.write({'apply_url': 'javascript:alert(1)'})))
check('an empty title is refused', raises(ValidationError, lambda: a.write({'title': '  '})))

print('\n=== E4. the sync keeps the changes made by hand ===')
sync = Listing.with_context(llmd_sync=True)
d = listing('edit-d')
sync.browse(d.id).write({'title': 'From the source'})
check('a write of the sync is not counted as made by hand', not Listing.browse(d.id).manual_fields)
src = {'source': 'Adzuna', 'ext_id': 'edit-a', 'title': 'Data Analyst (source)', 'company': 'Acme Corp', 'location': 'Pune, Maharashtra', 'apply_url': 'https://careers.example.com/new',
       'html': '<p>Remote role, internship.</p>', 'full_text': True}
vals = Listing._prepare(dict(src))
if vals is None:                                                   # the title fits no board category: give the update path the values directly
    vals = {'source': 'Adzuna', 'ext_id': 'edit-a', 'title': src['title'], 'company': src['company'], 'location': src['location'], 'apply_url': src['apply_url'],
            'description_html': src['html']}
vals = {k: v for k, v in vals.items() if not k.startswith('_')}
rec = sync.browse(a.id)
manual = rec.manual_names()
kept = {f: rec[f] for f in ('work_mode', 'job_type', 'exp_level', 'india', 'city', 'country') if f in manual}
rec.write({k: v for k, v in vals.items() if k not in manual})        # the same steps as fetch_now() for a job changed by hand
if kept:
    rec.write(kept)
env.invalidate_all()
a = Listing.browse(a.id)
check('after a sync the hand-made title, location, work mode, job type and link are still there',
      (a.title, a.location, a.work_mode, a.job_type, a.apply_url) == ('Senior Data Analyst', 'Bengaluru, Karnataka', 'hybrid', 'contract', 'https://jobs.example.org/a'),
      (a.title, a.location, a.work_mode, a.job_type, a.apply_url))
check('a field not changed by hand takes the source value', a.company == 'Acme Corp' and 'Remote role' in (a.description_html or ''))

print('\n=== E5. a real sync run (fetch_now, the sources answer canned jobs) keeps the changes made by hand ===')
from unittest import mock
from odoo.addons.llmd_job_aggregator.models import board_config as BC
BC.COMPANY_BOARDS, BC.DIRECT_LINKS_ONLY = 'off', False
e = listing('edit-e', title='Sales Manager', roles=',sales_manager,', tags=',sales,')
e.with_user(manager).write({'title': 'Regional Sales Manager (edited)', 'work_mode': 'onsite', 'apply_url': 'https://jobs.example.org/e'})
canned = {'source': 'Adzuna', 'ext_id': 'edit-e', 'title': 'Sales Manager', 'company': 'Acme Synced', 'location': 'Pune, Maharashtra',
          'apply_url': 'https://careers.example.com/e2', 'html': '<p>Fully remote sales role. Remote work from anywhere in India.</p>', 'full_text': True}
with mock.patch.object(type(env['llmd.job.source']), 'run', lambda self, queries: [dict(canned)]):
    stats = Listing.fetch_now(trigger='manual')
env.invalidate_all()
e = Listing.browse(e.id)
check('the sync updated this job', stats.get('updated', 0) >= 1 and e.company == 'Acme Synced', stats)
check('the hand-made title, work mode and application link survive the sync', (e.title, e.work_mode, e.apply_url) == ('Regional Sales Manager (edited)', 'onsite', 'https://jobs.example.org/e'),
      (e.title, e.work_mode, e.apply_url))
check('the sync did not mark its own changes as made by hand', set(e.manual_names()) == {'title', 'work_mode', 'apply_url'}, e.manual_fields)

print('\n=== E6. the apply links of Apply Clicks and Job Applications can be corrected ===')
Click, App = env['llmd.job.click'], env['llmd.job.application']
k1, k2 = (Click.create({'job_title': 'Sales Manager', 'job_key': 'ext:Adzuna:edit-k%d' % i, 'apply_url': 'https://careers.example.com/old%d' % i}) for i in (1, 2))
check('a Recruitment manager can change the apply link of a click', not raises(Exception, lambda: k1.with_user(manager).write({'apply_url': 'https://jobs.example.org/fixed'})))
(k1 | k2).with_user(manager).write({'apply_url': 'https://jobs.example.org/both'})
env.invalidate_all()
check('the new link of several clicks is saved (read again from the database)', Click.browse([k1.id, k2.id]).mapped('apply_url') == ['https://jobs.example.org/both'] * 2)
check('a recruiter (Officer) cannot change a click', raises(AccessError, lambda: k1.with_user(officer).write({'apply_url': 'https://jobs.example.org/x'})))
check('a javascript: link is refused on a click', raises(ValidationError, lambda: k1.write({'apply_url': 'javascript:alert(1)'})))
check('the other fields of a click stay read-only in the backend', Click.fields_get(['job_title', 'clicked_at', 'apply_url'], ['readonly']) ==
      {'job_title': {'readonly': True}, 'clicked_at': {'readonly': True}, 'apply_url': {'readonly': False}})
app = App.sudo().create({'applicant_name': 'Edit Test', 'email': 'edit-test@example.com', 'job_title': 'Sales Manager', 'job_key': 'ext:Adzuna:edit-app', 'identity_key': 'e:edit-test@example.com'})
app.with_user(manager).write({'apply_url': 'https://jobs.example.org/app'})
env.invalidate_all()
check('a missing apply link of a job application can be added and is saved', App.browse(app.id).apply_url == 'https://jobs.example.org/app')
check('a javascript: link is refused on a job application', raises(ValidationError, lambda: app.write({'apply_url': 'javascript:alert(1)'})))
form = App.get_views([(False, 'form')])['views']['form']['arch']
check('the job application form always shows the apply link (also when it is empty)', 'name="apply_url"' in form and "',apply_url,' in llmd_blank" not in form)

print('\n=== E7. reset ===')
a.with_user(manager).action_reset_manual()
check('Reset to source values forgets the changes made by hand (the next sync writes them again)', not Listing.browse(a.id).manual_fields)
check('fetch_now() marks its writes as the sync\'s', 'llmd_sync=True' in open(__import__('odoo.addons.llmd_job_aggregator.models.listing', fromlist=['x']).__file__, encoding='utf-8').read())

env.cr.rollback()
print('\n%d / %d checks passed (rolled back: nothing stored)' % (sum(RESULTS), len(RESULTS)))
