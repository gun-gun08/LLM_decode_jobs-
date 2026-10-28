"""Run inside `odoo shell`: checks of the Apply Now click log, the job applications API and of the synchronization that need the ORM. One transaction, rolled back at the end: nothing is stored.

  Get-Content tests\\orm_checks_app.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'
"""
import base64
import os
import threading
from unittest import mock

import odoo
from odoo import fields
from odoo.addons.llmd_job_aggregator.models import sources as S

RESULTS = []
from odoo.addons.llmd_job_aggregator.models import board_config as _BC
_BC.COMPANY_BOARDS = 'off'          # canned answers only: the company job boards send no real request in these checks (survives the rollbacks, changes no data)
_BC.DIRECT_LINKS_ONLY = False      # these checks combine all sources (job board links included); the default "direct links only" is checked in orm_checks.py section N


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


Listing, App, Applicant, Job = env['llmd.job.listing'], env['llmd.job.application'], env['hr.applicant'], env['hr.job']


def listing(ext, title='Sales Manager', company='Acme', **kw):
    return Listing.create(dict({'source': 'Adzuna', 'ext_id': ext, 'title': title, 'company': company, 'location': 'Pune, Maharashtra', 'apply_url': 'https://careers.example.com/%s' % ext,
                                'roles': ',sales_manager,', 'courses': ',sell-ai,', 'tags': ',sales,', 'description_html': '<p>x</p>'}, **kw))


print('\n=== P. every click on Apply Now is one line of the click log (never an application, never a person) ===')
Click = env['llmd.job.click']
a, b = listing('orm-a'), listing('orm-b')
n_app, n_rec = Applicant.search_count([]), App.search_count([])
c1 = Click.record_click(listing=a, visitor='visitor-aaaaaaaaaaaaaaaa')
check('a click saves a line with time, job title, company, source, external job ID, apply URL and status "clicked"',
      (c1.job_title, c1.company, c1.source, c1.ext_id, c1.apply_url, c1.status, c1.listing_id) == ('Sales Manager', 'Acme', 'Adzuna', 'orm-a', 'https://careers.example.com/orm-a', 'clicked', a) and bool(c1.clicked_at) and c1.job_key == 'ext:Adzuna:orm-a')
check('a click carries NO personal data: the model has no user, name, e-mail or phone field, and nothing is created in Job Applications or Recruitment',
      not ({'user_id', 'applicant_name', 'email', 'phone', 'logged_in', 'applicant_id'} & set(Click._fields)) and App.search_count([]) == n_rec and Applicant.search_count([]) == n_app)
c2 = Click.record_click(listing=a, visitor='visitor-aaaaaaaaaaaaaaaa')
check('the same browser clicking the same job again is saved as ANOTHER line (every click is saved), marked as a repeat click', c2 != c1 and c2.repeat and not c1.repeat and Click.search_count([('job_key', '=', c1.job_key)]) == 2)
c3 = Click.record_click(listing=a, visitor='visitor-bbbbbbbbbbbbbbbb')
c4 = Click.record_click(listing=b, visitor='visitor-aaaaaaaaaaaaaaaa')
check('another browser, or another job, is a first click (not a repeat)', not c3.repeat and not c4.repeat and c4.job_key == 'ext:Adzuna:orm-b')
nolink = listing('orm-nolink', apply_url=False)
c5 = Click.record_click(listing=nolink, visitor='visitor-aaaaaaaaaaaaaaaa')
check('a job without an application link: the click is saved with the status "no_link" (nobody is sent anywhere)', c5.status == 'no_link' and not c5.apply_url)
own = Job.search([('website_published', '=', True)], limit=1) or Job.with_context(llmd_skip=True).create({'name': 'ORM own position', 'website_published': True})   # rolled back
c6 = Click.record_click(job=own, visitor='visitor-aaaaaaaaaaaaaaaa')
check('a click on one of OUR positions is saved too: linked to the position, source "LLM Decode"', c6.hr_job_id == own and c6.source == 'LLM Decode' and c6.job_key == 'hr.job:%d' % own.id and c6.job_title == own.name)
c7 = Click.record_click(listing=a)
check('without a cookie (no visitor id) the click is still saved', bool(c7) and not c7.visitor_key and not c7.repeat)
before = Click.search_count([])
for i in range(120):
    Click.create({'job_title': 'x', 'job_key': 'flood:%d' % i, 'visitor_key': 'visitor-ffffffffffffffff', 'status': 'clicked'})
none = Click.record_click(listing=a, visitor='visitor-ffffffffffffffff')
check('one browser cannot add more than 120 lines an hour (the visitor would still be sent on, only the line is not saved)', not none and Click.search_count([]) == before + 120)
a.unlink()
env.invalidate_all()
check('the click log keeps its history when a listing is removed (snapshot fields stay, the link is cleared)', (c1.listing_id.id, c1.job_title, c1.apply_url) == (False, 'Sales Manager', 'https://careers.example.com/orm-a'))

print('\n=== Q. Job Applications: the stock form of our positions, the unique record per person, a failing tracking ===')
stock = Applicant.create({'partner_name': 'Stock Person', 'email_from': 'stock@example.com', 'job_id': own.id})
track = App.search([('applicant_id', '=', stock.id)])
check('an applicant created without a website request (a recruiter, an incoming e-mail, the ORM) gets a Job Applications record: Received, channel "Added in Odoo / by e-mail", linked to the position', len(track) == 1 and (track.state, track.channel, track.hr_job_id) == ('submitted', 'recruiter', own))
check('all eight columns of the list are filled from the applicant and the job: name, e-mail, job title, company, external job ID, channel, status, date',
      (track.applicant_name, track.email, track.job_title, track.company, track.ext_id, track.channel, track.state) == ('Stock Person', 'stock@example.com', own.name, own.company_id.name or '', str(own.id), 'recruiter', 'submitted') and bool(track.application_date))
fake_request = mock.MagicMock()
fake_request.httprequest.path = '/website/form/hr.applicant'
with mock.patch('odoo.addons.llmd_job_aggregator.models.application.request', new=fake_request):          # a website form posts to /website/form/<model>
    web = Applicant.create({'partner_name': 'Web Person', 'email_from': 'web@example.com', 'partner_phone': '+91 98765 43210', 'job_id': own.id})
web_rec = App.search([('applicant_id', '=', web.id)])
check('an applicant created by a website form (the person applied on our site) is channel "Our website (Odoo form)" with the name and e-mail - no phone is kept', (web_rec.channel, web_rec.applicant_name, web_rec.email) == ('own', 'Web Person', 'web@example.com')
      and 'phone' not in App._fields)
again = Applicant.create({'partner_name': 'Web Person', 'email_from': 'WEB@example.com', 'partner_phone': '+91 98765 43210', 'job_id': own.id})
check('the same person applying again for the same job (e-mail in capitals) makes NO second record: still one, now pointing to the newest applicant', App.search_count([('job_key', '=', web_rec.job_key), ('email', '=', 'web@example.com')]) == 1 and web_rec.applicant_id == again)
web.write({'partner_name': 'Web Person Renamed', 'partner_phone': '+91 90000 00000'})
again.write({'partner_name': 'Web Person Renamed', 'partner_phone': '+91 90000 00000'})
check('the recruiter edits the name of the applicant: the record in the list follows', web_rec.applicant_name == 'Web Person Renamed')
again.write({'email_from': 'Web.New@Example.com'})
check('the recruiter corrects the e-mail: the record follows (lower case) and still has exactly one record for the person', (web_rec.email, web_rec.identity_key) == ('web.new@example.com', 'e:web.new@example.com') and App.search_count([('job_key', '=', web_rec.job_key), ('email', '=', 'web.new@example.com')]) == 1)
again.write({'email_from': 'stock@example.com'})
check('an e-mail that another record of the same job already uses is NOT taken over (no duplicate, no error)', web_rec.email == 'web.new@example.com' and App.search_count([('job_key', '=', web_rec.job_key), ('email', '=', 'stock@example.com')]) == 1)
web_rec.action_confirm()
st1 = web_rec.state
web_rec.action_withdraw()
st2 = web_rec.state
web_rec.action_receive()
check('status updates: Confirm -> confirmed, Withdraw -> withdrawn, Back to Received -> received (also on several selected records at once)', (st1, st2, web_rec.state) == ('confirmed', 'withdrawn', 'submitted') and (web_rec | track).action_confirm() and {web_rec.state, track.state} == {'confirmed'})
web_rec.application_date = '2030-01-01 00:00:00'
track.application_date = '2029-01-01 00:00:00'
old_row = App.create(dict(App.job_info(job=own), identity_key='e:undated@example.com', job_title='undated', applicant_name='Undated', channel='recruiter', state='submitted', application_date=False))
ordered = App.search([('id', 'in', (web_rec | track | old_row).ids)])
check('the list shows the newest application first and the ones without a date last', ordered.ids == [web_rec.id, track.id, old_row.id], ordered.mapped('applicant_name'))
labels = {k: v['string'] for k, v in App.fields_get(['applicant_name', 'email', 'job_title', 'company', 'ext_id', 'channel', 'state', 'application_date'], ['string']).items()}
check('the column names are Applicant Name, Email, Job Title, Company, External Job ID, Channel, Application Status, Application Date', labels == {'applicant_name': 'Applicant Name', 'email': 'Email', 'job_title': 'Job Title', 'company': 'Company', 'ext_id': 'External Job ID',
                                                                                                                                            'channel': 'Channel', 'state': 'Application Status', 'application_date': 'Application Date'}, labels)
import re as _re
arch = App.get_views([(False, 'list')])['views']['list']['arch']
shown = [f for f, attrs in _re.findall(r'<field name="(\w+)"([^>]*)/?>', arch) if 'optional="hide"' not in attrs]
check('the list view shows exactly these columns, in this order (name, e-mail, the job with its department, job type and experience, how it was applied for, who posted the job; no phone), and Confirm / Withdraw / Back to Received for the selected rows',
      shown == ['applicant_name', 'email', 'job_title', 'company', 'department', 'job_type', 'experience_required', 'ext_id', 'application_type', 'posted_type', 'state', 'application_date'] and all(b in arch for b in ('action_confirm', 'action_withdraw', 'action_receive')), shown)
with mock.patch.object(type(App), '_track_stock_applicant', side_effect=RuntimeError('boom')):
    ok = Applicant.create({'partner_name': 'Stock Two', 'email_from': 'stock2@example.com', 'job_id': own.id})
check('if the tracking itself fails, Odoo\'s own application form still works (the applicant is saved)', bool(ok) and ok.exists())
try:
    with env.cr.savepoint():
        App.create(dict(App.job_info(job=own), identity_key='e:stock@example.com', job_title='x'))
    unique_ok = False
except Exception:
    unique_ok = True
check('the database itself refuses a second record for the same job and person (unique constraint), even by a direct create', unique_ok)
check('there is no "I applied elsewhere" report any more and no token / click helper on the application model', not any(hasattr(App, name) for name in ('report_external', 'track_click', '_adopt')))

print('\n=== Q2. OUR application form: the applicant, the resume and the record are saved together ===')
fl = listing('orm-form', 'Data Analyst', 'Form Co')
vals_form = {'name': 'Asha Verma', 'email': 'asha.form@example.com', 'phone': '+91 98765 43210', 'note': 'Hello <b>there</b>\nsecond line', 'consent': True}
PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF'
n_hr, n_rec = Applicant.search_count([]), App.search_count([])
rec, status = App.submit_own(fl, vals_form, 'Asha CV.pdf', 'application/pdf', PDF, 'visitor-gggggggggggggggg')
ap = rec.applicant_id
att = env['ir.attachment'].search([('res_model', '=', 'hr.applicant'), ('res_id', '=', ap.id)])
check('a submission saves an Odoo applicant (name, e-mail - a phone sent anyway is not kept) filed under an unpublished position made for the job that points back to the listing',
      status == 'created' and (ap.partner_name, ap.email_from, ap.partner_phone) == ('Asha Verma', 'asha.form@example.com', False) and ap.job_id.llmd_listing_id == fl and not ap.job_id.website_published
      and Applicant.search_count([]) == n_hr + 1 and App.search_count([]) == n_rec + 1)
check('... with the resume attached byte for byte, and the message, job, company, external job ID and original link in the applicant\'s note (HTML-escaped)',
      len(att) == 1 and att.name == 'Asha CV.pdf' and base64.b64decode(att.datas) == PDF and all(x in str(ap.applicant_notes) for x in ('Data Analyst', 'Form Co', 'orm-form', 'https://careers.example.com/orm-form'))
      and '&lt;b&gt;there&lt;/b&gt;' in str(ap.applicant_notes) and '<b>there</b>' not in str(ap.applicant_notes))
check('the Job Applications record has every field: name, e-mail, job title, company, external job ID, source (internal), channel "Our website", status Received, application date, resume count, message',
      (rec.applicant_name, rec.email, rec.job_title, rec.company, rec.ext_id, rec.source, rec.channel, rec.state, rec.resume_count, rec.message) ==
      ('Asha Verma', 'asha.form@example.com', 'Data Analyst', 'Form Co', 'orm-form', 'Adzuna', 'own', 'submitted', 1, 'Hello <b>there</b>\nsecond line') and bool(rec.application_date) and rec.listing_id == fl)
check('the applicant\'s recruitment source is the (internal) job source, never shown on the site', ap.source_id.name == 'Adzuna')
dup, status = App.submit_own(fl, dict(vals_form, email='ASHA.Form@Example.com'), '', '', b'', None)
check('applying again (e-mail in capitals) is a duplicate: no second applicant, no second record', status == 'duplicate' and dup == rec and Applicant.search_count([]) == n_hr + 1 and App.search_count([('job_key', '=', rec.job_key), ('email', '=', 'asha.form@example.com')]) == 1)
fl2 = listing('orm-form2', 'Data Analyst', 'Form Co')
r2, status = App.submit_own(fl2, dict(vals_form, email='other@example.com'), '', '', b'', None)
check('two jobs with the same title and company get TWO positions (Odoo wants unique names); a person without a resume is saved with that field empty',
      fl.ensure_job() != fl2.ensure_job() and fl.ensure_job().name != fl2.ensure_job().name and fl.ensure_job() == ap.job_id and not r2.resume_count)
r3, _s = App.submit_own(fl2, {'name': 'Name Only', 'email': 'nameonly@example.com', 'note': '', 'consent': True}, '', '', b'', None)
check('a name and an e-mail are all it takes: the application is saved, the applicant has no phone', r3.state == 'submitted' and r3.applicant_name == 'Name Only' and not r3.applicant_id.partner_phone)
n_hr, n_rec = Applicant.search_count([]), App.search_count([])
with mock.patch.object(type(env['ir.attachment']), 'create', side_effect=RuntimeError('disk full')):
    try:
        App.submit_own(fl, {'name': 'Fail Case', 'email': 'fail@example.com', 'phone': '', 'note': '', 'consent': True}, 'cv.pdf', 'application/pdf', PDF, 'visitor-hhhhhhhhhhhhhhhh')
        raised = False
    except RuntimeError:
        raised = True
check('if the resume cannot be saved, the error reaches the caller (no "received" is shown) and NOTHING of that application is left', raised and Applicant.search_count([]) == n_hr and App.search_count([]) == n_rec)
for i in range(30):
    App.create(dict(App.job_info(listing=fl2), identity_key='e:flood%d@example.com' % i, visitor_key='visitor-ffffffffffffffff', state='submitted', application_date=fields.Datetime.now(), job_key='flood:%d' % i, applicant_name='Flood'))
check('one browser cannot send more than 30 applications per hour', App._too_many('visitor-ffffffffffffffff') and not App._too_many('visitor-zzzzzzzzzzzzzzzz') and not App._too_many(None))
check('the confirmation link is signed: only the right token opens a record', App.token_ok(rec.id, App.token(rec.id)) and not App.token_ok(rec.id, '0' * 32) and not App.token_ok(rec.id, None) and App.token(rec.id) != App.token(r2.id))
check('by default Apply Now goes straight to the employer (the tracked /go link) and there is no form link', fl2.apply_mode() == 'redirect' and fl2.detail_vals()['apply_form_href'] == '' and fl2.detail_vals()['go_href'].endswith('/go'))
env['ir.config_parameter'].sudo().set_param('llmd_agg.apply_mode', 'form')
check('... the system parameter llmd_agg.apply_mode = form switches our form on (Apply Now -> /apply, the employer link stays)', fl2.apply_mode() == 'form' and fl2.detail_vals()['apply_form_href'] == '/jobs/ext/%d/apply' % fl2.id and fl2.detail_vals()['go_href'].endswith('/go'))
env['ir.config_parameter'].sudo().set_param('llmd_agg.apply_mode', False)

print('\n=== R. the JSON API: applicant data only from an authorized provider integration ===')
nb = listing('orm-api')
ref = {'source': 'Adzuna', 'ext_id': 'orm-api'}
good = {'action': 'applicant', 'job': ref, 'name': 'Asha Verma', 'email': 'Asha@Example.com', 'phone': '', 'provider_ref': 'prov-123', 'note': 'Applied through the provider.'}
n_rec = App.search_count([])
for bad_action in ('applicant', 'confirm', 'submit', 'report'):
    r = App.process_api(dict(good, action=bad_action), authorized=False)
    check('no API key: "%s" is refused and nothing is stored' % bad_action, r['error'] == 'unauthorized' and App.search_count([]) == n_rec)
check('an unknown action is refused even with the key (the old public "submit" and "report" do not exist any more)', App.process_api(dict(good, action='submit'), authorized=True)['error'] == 'unknown_action' and App.process_api(dict(good, action='report'), authorized=True)['error'] == 'unknown_action')
check('unknown job -> job_not_found', App.process_api(dict(good, job={'source': 'x', 'ext_id': 'y'}), authorized=True)['error'] == 'job_not_found')
r = App.process_api(dict(good, name='', email='bad'), authorized=True)
check('invalid data is answered with the field errors and nothing is saved', r['error'] == 'validation' and {'name', 'email'} <= set(r['fields']) and 'consent' not in r['fields'] and App.search_count([]) == n_rec)
r = App.process_api(good, authorized=True)
rec = App.browse(r['id'])
check('with the key: the applicant is saved as the provider sent it - confirmed, channel provider, e-mail in lower case, provider reference, date received, "api"; no phone is kept',
      r['ok'] and r['status'] == 'created' and (rec.state, rec.channel, rec.email, rec.applicant_name, rec.provider_ref, rec.confirmed_via) == ('confirmed', 'provider', 'asha@example.com', 'Asha Verma', 'prov-123', 'api')
      and bool(rec.application_date) and (rec.job_title, rec.company, rec.source, rec.ext_id, rec.apply_url) == ('Sales Manager', 'Acme', 'Adzuna', 'orm-api', 'https://careers.example.com/orm-api'), (r, rec.state))
check('... it does not create an Odoo applicant and no click line', not rec.applicant_id and Click.search_count([('job_key', '=', rec.job_key)]) == 0)
r2 = App.process_api(dict(good, name='Asha V. Verma', phone='+91 98765 43210'), authorized=True)
check('the same person for the same job again: the record is UPDATED with what is new, never duplicated', r2['status'] == 'updated' and r2['id'] == rec.id and rec.applicant_name == 'Asha V. Verma' and App.search_count([('job_key', '=', rec.job_key)]) == 1)
check('job given as listing_id, as source + ext_id and as hr_job_id all resolve', all(App.process_api({'job': j, 'name': 'Zed Zed', 'email': 'zed%d@example.com' % i}, authorized=True)['ok'] for i, j in enumerate(({'listing_id': nb.id}, ref, {'hr_job_id': own.id}))))
rec.action_withdraw()
check('a withdrawn application cannot be confirmed again - neither by a recruiter nor by the API', App.process_api(good, authorized=True)['error'] == 'withdrawn' and rec.state == 'withdrawn')
try:
    rec.action_confirm()
    blocked = False
except Exception:
    blocked = True
check('... (confirming a withdrawn application is refused)', blocked)
rec2 = App.browse(App.process_api(dict(good, email='second@example.com'), authorized=True)['id'])
rec2.write({'state': 'submitted'})
rec2.action_confirm()
check('a recruiter confirms: state "confirmed", date and "recruiter" are stored', (rec2.state, rec2.confirmed_via, bool(rec2.confirmed_date)) == ('confirmed', 'recruiter', True))
check('the API key is read from the environment / a system parameter and compared in constant time; an empty key is never valid', not App.api_key_ok('') and not App.api_key_ok(None) and not App.api_key_ok('anything'))
with mock.patch.dict(os.environ, {'LLMD_APPLICATION_API_KEY': 'k-secret-123'}):
    check('with a key configured only that key opens the API', App.api_key_ok('k-secret-123') and not App.api_key_ok('k-secret-124') and not App.api_key_ok(''))

print('\n=== T. a direct application link wins over a job board page ===')
from odoo.addons.llmd_job_aggregator.models.listing import is_board_link
base = {'dedupe_key': 'bdr|othor ai|bangalore', 'tags': ',genai,', 'roles': ',ai_engineer,', 'courses': ',genai-mastermind,', 'rank': 1}
jooble = dict(base, source='Jooble', ext_id='j1', full_text=False, _plain_len=400, apply_url='https://in.jooble.org/desc/-2529696625599924113?ckey=ai')
jsearch = dict(base, source='JSearch', ext_id='s1', full_text=False, _plain_len=120, apply_url='https://www.foundit.in/job/bdr-ai-agents-othor-ai-bangalore-12345')
kept = Listing._dedupe([dict(jooble), dict(jsearch)])
check('the same job from Jooble (link to the Jooble page) and JSearch (direct foundit link): the direct link is kept even with a shorter description',
      len(kept) == 1 and kept[0]['apply_url'].startswith('https://www.foundit.in/') and kept[0]['also_on'] == 'Jooble', [(k['source'], k['apply_url'][:40]) for k in kept])
kept = Listing._dedupe([dict(jsearch), dict(jooble)])
check('... also when the Jooble version comes first', len(kept) == 1 and kept[0]['source'] == 'JSearch')
check('job-board pages are recognised (Jooble, Adzuna, Himalayas); employer and portal links are not',
      all(is_board_link(u) for u in ('https://in.jooble.org/desc/1', 'https://www.adzuna.in/land/ad/1', 'https://himalayas.app/companies/x/jobs/y'))
      and not any(is_board_link(u) for u in ('https://www.foundit.in/job/1', 'https://www.naukri.com/job-listings-1', 'https://boards.greenhouse.io/x/jobs/1', '')))

print('\n=== S. synchronization: lock, per-job safety, log ===')
env['ir.config_parameter'].sudo().set_param('llmd_agg.himalayas_mode', 'off')          # no real request in these checks
BLANK = {'JOOBLE_API_KEY': '', 'ADZUNA_APP_ID': '', 'ADZUNA_APP_KEY': '', 'JSEARCH_API_KEY': ''}
hold = threading.Event()
release = threading.Event()
got = []


def other_connection():
    """Another database connection (= another running sync) holds the sync lock."""
    with odoo.sql_db.db_connect(env.cr.dbname).cursor() as cr2:
        cr2.execute('SELECT pg_try_advisory_lock(%s)', [72940011])
        got.append(cr2.fetchone()[0])
        hold.set()
        release.wait(30)
        cr2.execute('SELECT pg_advisory_unlock(%s)', [72940011])


t = threading.Thread(target=other_connection)
t.start()
hold.wait(10)
with mock.patch.dict(os.environ, BLANK), mock.patch.object(S.requests, 'get', side_effect=AssertionError('no request')):
    locked = Listing.fetch_now()
release.set()
t.join(20)
check('while another sync holds the lock, a second one returns at once ("another sync is already running") and reads nothing', got == [True] and locked.get('skipped') and locked['created'] == 0 and not t.is_alive(), locked.get('skipped'))
n_log = env['llmd.job.sync'].search_count([])
with mock.patch.dict(os.environ, BLANK), mock.patch.object(S.requests, 'get', side_effect=AssertionError('no request')), mock.patch.object(S.requests, 'post', side_effect=AssertionError('no request')):
    stats = Listing.fetch_now(trigger='cron')
check('every sync run writes one line to the "Sync runs" log', env['llmd.job.sync'].search_count([]) == n_log + 1 and env['llmd.job.sync'].search([], limit=1).trigger == 'cron')
JOOBLE = {'jobs': [{'id': 9001, 'title': 'Sales Manager', 'company': 'Good Co', 'location': 'Pune', 'snippet': 'We need a strong sales manager for our Pune office, owning the quota every month.', 'link': 'https://in.jooble.org/desc/9001', 'updated': '2026-10-20T00:00:00.0000000'},
                   {'id': 9002, 'title': 'Account Executive', 'company': 'Bad Co', 'location': 'Delhi', 'snippet': 'We need an account executive for our Delhi office, owning the pipeline every month.', 'link': 'https://in.jooble.org/desc/9002', 'updated': '2026-10-20T00:00:00.0000000'},
                   {'id': 9003, 'title': 'Data Analyst', 'company': 'Fine Co', 'location': 'Noida', 'snippet': 'We need a data analyst for our Noida office, building the dashboards every single week.', 'link': 'https://in.jooble.org/desc/9003', 'updated': '2026-10-20T00:00:00.0000000'}]}


class Resp:
    status_code, text = 200, ''

    def json(self):
        return JOOBLE


real_create = type(Listing).create


def flaky_create(self, vals_list, *a, **k):
    if any(str(v.get('ext_id')) == '9002' for v in (vals_list if isinstance(vals_list, list) else [vals_list])):
        raise ValueError('this job cannot be saved')
    return real_create(self, vals_list, *a, **k)


with mock.patch.dict(os.environ, dict(BLANK, JOOBLE_API_KEY='k')), mock.patch.object(S.requests, 'post', return_value=Resp()), mock.patch.object(S.time, 'sleep'), \
        mock.patch.object(type(Listing), 'create', flaky_create):
    stats = Listing.fetch_now()
saved = Listing.search([('ext_id', 'in', ['9001', '9002', '9003'])])
check('one job that cannot be saved is logged and skipped - the others of the same run are saved, the run is counted as "some problems"',
      sorted(saved.mapped('ext_id')) == ['9001', '9003'] and stats['errors'] == 1 and env['llmd.job.sync'].search([], limit=1).state == 'partial' and '9002' in (env['llmd.job.sync'].search([], limit=1).details or ''), stats['errors'])
with mock.patch.dict(os.environ, dict(BLANK, JOOBLE_API_KEY='k')), mock.patch.object(S.requests, 'post', return_value=Resp()), mock.patch.object(S.time, 'sleep'):
    again = Listing.fetch_now()
check('the same jobs again: updated, never duplicated (source + external job ID), and the failed one is now saved', again['created'] == 1 and Listing.search_count([('ext_id', '=', '9001'), ('source', '=', 'Jooble')]) == 1 and Listing.search_count([('ext_id', '=', '9002')]) == 1)
check('the job data is stored in Odoo: title, company, location, description, apply URL, source, external job ID', all(saved[0][f] for f in ('title', 'company', 'location', 'description_html', 'apply_url', 'source', 'ext_id')))

# an apostrophe in a job text must come out as an apostrophe on the page, not as &#x27; (the stored HTML escapes it)
html = S._text_html(S._strip("We&amp;#x27;re hiring a Sales Manager for Pune. You&amp;amp;#x27;ll own the quota & the pipeline every month, with a strong team."))
prep = Listing._prepare({'source': 'Jooble', 'ext_id': 'entity-1', 'title': 'Sales Manager', 'company': 'Quote Co', 'location': 'Pune', 'html': html, 'apply_url': 'https://in.jooble.org/desc/1'})
shown = prep['short_description'] + ' ' + prep['sections_json'] + ' ' + prep['search_text']
check('apostrophes and ampersands in a job text are plain text in the stored summary and sections (no &#x27; / &amp;)', prep and "We're hiring" in prep['short_description'] and "You'll own" in shown and '&#' not in shown and '&amp;' not in shown, shown[:200])

print('\nSHELL RESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
env.cr.rollback()
