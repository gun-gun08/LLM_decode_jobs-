r"""Apply Now of a LOGGED-IN website user, against the LOCAL instance:

  1. the test account (scripts/local_test_user.py, login + password from .env) logs in on the website;
  2. it clicks Apply Now of a real job: it is sent to the employer's original application page; Recruitment > Apply Clicks gets ONE line with the job -
     title, company, source, external job ID, original apply URL, click time, status - and no name or e-mail; Recruitment > Job Applications gets ONE record
     with the account's name, e-mail and user ID and the status "Redirected to External Site";
  3. an anonymous visitor is sent to the login page first (back to the same Apply Now afterwards) and nothing is saved;
  4. a click is never an application: nothing is submitted, no Recruitment applicant is made;
  5. with our own application form switched on (llmd_agg.apply_mode = form, only during this test), the logged-in user sees the form (name + e-mail, no phone) filled
     from the profile and sends it with a resume: ONE real application is saved (Job Applications + Recruitment applicant + resume) with the details
     that were sent; sending it again makes no duplicate.

The test application stays, so that it can be seen in Job Applications (use --cleanup to remove it again); the test's click lines are removed at the end.
Nothing is printed from .env.

  . .\scripts\env.ps1
  python tests\click_user_test.py            run, keep the records to look at in Odoo
  python tests\click_user_test.py --cleanup  remove this test account's application and applicant
"""
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gw  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
if not gw.is_local():
    sys.exit('click_user_test.py runs against the LOCAL instance only.')
LOGIN, PASSWORD = os.environ.get('LLMD_TEST_USER_LOGIN'), os.environ.get('LLMD_TEST_USER_PASSWORD')
if not LOGIN or not PASSWORD:
    sys.exit('LLMD_TEST_USER_LOGIN / LLMD_TEST_USER_PASSWORD are not set (.env, see scripts/local_test_user.py).')
RESULTS = []
TEST_PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'


def rpc(model, method, args):
    models, uid = gw._rpc()
    return models.execute_kw(os.environ['ODOO_DB'], uid, os.environ['ODOO_PASSWORD'], model, method, args)


def check(label, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', label, ('' if ok else ' - %s' % (detail,))))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    """One website visitor with its own cookies; redirects are not followed, so the test sees where Apply Now sends it."""

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())

    def open(self, path, body=None, content_type=None):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36'}
        if content_type:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(gw.site_url() + path, data=body, headers=headers)
        try:
            r = self.opener.open(req, timeout=60)
            return r.status, r.read().decode('utf-8', 'replace'), ''
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode('utf-8', 'replace'), exc.headers.get('Location', '')

    def login(self):
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {'db': os.environ.get('ODOO_DB') or 'llmd_local', 'login': LOGIN, 'password': PASSWORD}}).encode()
        status, text, _ = self.open('/web/session/authenticate', body, 'application/json')
        data = json.loads(text) if status == 200 else {}
        return bool((data.get('result') or {}).get('uid'))

    def post_form(self, path, fields, files=None):
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.open(path)[1]).group(1)
        boundary = '----llmdclick%d' % int(time.time() * 1000)
        parts = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode() for k, v in dict(fields, csrf_token=token).items()]
        for k, (fname, data) in (files or {}).items():
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: application/pdf\r\n\r\n' % (boundary, k, fname)).encode() + data + b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode())
        return self.open(path, b''.join(parts), 'multipart/form-data; boundary=' + boundary)


def counts():
    """(submitted / confirmed applications, Recruitment applicants): what a click must never change."""
    return (len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000)),
            len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000)))


user = gw.search('res.users', [['login', '=', LOGIN]], 1)
if not user:
    sys.exit('The test account does not exist yet: run scripts/local_test_user.py first.')
user = user[0]
partner = gw.search('res.partner', [['id', '=', user['partner_id'][0]]], 1)[0]

if '--cleanup' in sys.argv:
    apps = gw.search('llmd.job.application', [['email', '=', LOGIN], ['active', 'in', [True, False]]], 100)
    applicants = gw.search('hr.applicant', [['email_from', '=', LOGIN], ['active', 'in', [True, False]]], 100)
    for model, recs in (('llmd.job.application', apps), ('hr.applicant', applicants)):
        if recs:
            rpc(model, 'unlink', [[r['id'] for r in recs]])
    print('removed: %d applications, %d applicants of the test account' % (len(apps), len(applicants)))
    sys.exit(0)

print('=== %s | test account "%s" (user %d) ===' % (gw.target_name(), partner['name'], user['id']))
job = gw.search('llmd.job.listing', [['active', '=', True], ['apply_url', '=like', 'https://%']], 1)[0]
apps0 = counts()

print('\n=== 1. log in ===')
me = Browser()
check('the test account logs in on the website (Odoo session)', me.login())
status, page, _ = me.open(job['page_url'])                               # the job's own page /jobs/<id>/<slug>
check('the job page opens for the logged-in user, with ONE Apply Now (the tracked /go link)', status == 200 and page.count('href="/jobs/ext/%d/go"' % job['id']) == 1, status)

print('\n=== 2. Apply Now of the logged-in user ===')
before = max([c['id'] for c in gw.search('llmd.job.click', [], 1)] or [0])
status, _b, location = me.open('/jobs/ext/%d/go' % job['id'])
check('Apply Now sends the user straight on to the employer\'s original application page (external redirect kept)', status in (302, 303) and location == job['apply_url'], (status, location[:80]))
mine = gw.search('llmd.job.click', [['id', '>', before]], 5)
c = mine[0] if mine else {}
check('ONE click line', len(mine) == 1, len(mine))
check('... without name or e-mail (only the user ID, for repeat clicks)', bool(c) and not c.get('applicant_name') and not c.get('email') and (c.get('user_id') or [0])[0] == user['id'],
      (c.get('applicant_name'), c.get('email')))
key = 'ext:%s:%s' % (job['source'], job['ext_id'])
rec = gw.search('llmd.job.application', [['job_key', '=', key], ['email', '=', LOGIN.lower()], ['active', 'in', [True, False]]], 5)
r = rec[0] if rec else {}
check('Job Applications: ONE record - name, e-mail, user ID, job title, company, internal + external job ID, click time, status "Redirected to External Site" (not submitted)',
      len(rec) == 1 and (r.get('applicant_name'), r.get('email'), (r.get('user_id') or [0])[0], r.get('job_title'), r.get('company'), r.get('internal_job_id'), r.get('ext_id'), r.get('state'))
      == (partner['name'], LOGIN.lower(), user['id'], job['title'], job['company'], job['id'], job['ext_id'], 'submitted') and r.get('channel') == 'apply_now' and bool(r.get('clicked_at')) and not r.get('application_date'),
      (len(rec), r.get('state'), r.get('applicant_name')))
check('... and the job: title, company, external job ID, original apply URL, click time, status "Clicked"',
      (c.get('job_title'), c.get('company'), c.get('ext_id'), c.get('apply_url'), c.get('status')) == (job['title'], job['company'], job['ext_id'], job['apply_url'], 'clicked') and bool(c.get('clicked_at')),
      (c.get('job_title'), c.get('ext_id'), c.get('clicked_at')))
status, _b, _l = me.open('/jobs/ext/%d/go?name=Someone+Else&email=fake%%40example.com' % job['id'])
lines = gw.search('llmd.job.click', [['id', '>', before]], 5)
check('names or e-mails put in the address are never stored (only those of the account)', status in (302, 303) and not any('fake@example.com' in str(v) or 'Someone' in str(v) for l in lines for v in l.values() if v)
      and not gw.search('llmd.job.application', [['email', '=', 'fake@example.com']], 1) and len(gw.search('llmd.job.application', [['job_key', '=', key], ['email', '=', LOGIN.lower()]], 5)) == 1)
rpc('llmd.job.click', 'unlink', [[l['id'] for l in lines]])                # the test's own click lines are no use to anybody

print('\n=== 3. an anonymous click ===')
anon = Browser()
before_anon = max([c['id'] for c in gw.search('llmd.job.click', [], 1)] or [0])
status, _b, location = anon.open('/jobs/ext/%d/go' % job['id'])
a = gw.search('llmd.job.click', [['id', '>', before_anon]], 1)
check('an anonymous visitor is sent to the login page, back to the same Apply Now afterwards - and nothing is saved before the sign-in',
      status in (302, 303) and location.endswith('/web/login?redirect=%%2Fjobs%%2Fext%%2F%d%%2Fgo' % job['id']) and not a, (status, location[:80], len(a)))

print('\n=== 4. a click is not an application ===')
check('nothing is submitted by the clicks, no Recruitment applicant is made (%d submitted / %d applicants)' % apps0, counts() == apps0, counts())

print('\n=== 5. our own application form (switched on only for this test) ===')
param = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.apply_mode', 'value': 'form'})['id']
try:
    status, form, _ = me.open('/jobs/ext/%d/apply' % job['id'])
    check('the form opens for the logged-in user, filled from the profile (name, e-mail) - and it has NO phone field', status == 200 and 'value="%s"' % partner['name'] in form
          and 'value="%s"' % LOGIN in form and 'name="phone"' not in form, status)
    status, _b, location = me.post_form('/jobs/ext/%d/apply' % job['id'], {'name': partner['name'], 'email': LOGIN, 'phone': partner['phone'],
                                                                          'note': 'Test application of the LLMD test account (local).', 'consent': 'on'},
                                        {'resume': ('LLMD Test Resume.pdf', TEST_PDF)})
    check('sending it saves the application and shows the confirmation page', status == 303 and '/applied?ref=' in location, (status, location[:80]))
    check('... the Apply Now record of this person and job BECAME the application (still one record, now Received)',
          [x['id'] for x in gw.search('llmd.job.application', [['job_key', '=', key], ['email', '=', LOGIN.lower()]], 5)] == [r.get('id')], r.get('id'))
    found = gw.search('llmd.job.application', [['email', '=', LOGIN], ['ext_id', '=', job['ext_id']]], 2)
    app = (found or [{}])[0]
    check('Job Applications: ONE real record without a phone (one sent anyway is ignored) - name, e-mail, job title, company, external job ID, original apply URL, application date, channel "Our website", status Received',
          len(found) == 1 and (app.get('applicant_name'), app.get('email'), app.get('phone'), app.get('job_title'), app.get('company'), app.get('ext_id'), app.get('apply_url'), app.get('channel'), app.get('state'))
          == (partner['name'], LOGIN, False, job['title'], job['company'], job['ext_id'], job['apply_url'], 'own', 'submitted') and bool(app.get('application_date')), app.get('id'))
    hr = gw.search('hr.applicant', [['email_from', '=', LOGIN]], 3)
    check('... and ONE Recruitment applicant linked to it, without a phone', len(hr) == 1 and app.get('applicant_id') and app['applicant_id'][0] == hr[0]['id'] and not hr[0]['partner_phone'], len(hr))
    atts = gw.search('ir.attachment', [['res_model', '=', 'hr.applicant'], ['res_id', '=', hr[0]['id'] if hr else 0]], 3)
    check('... the resume is attached to the applicant (Resumes = 1 in Job Applications)', len(atts) == 1 and atts[0]['name'] == 'LLMD Test Resume.pdf' and app.get('resume_count') == 1, len(atts))
    status, _b, location = me.post_form('/jobs/ext/%d/apply' % job['id'], {'name': partner['name'], 'email': LOGIN, 'consent': 'on'})
    check('sending the same application again creates NO duplicate record', status == 303 and 'again=1' in location
          and len(gw.search('llmd.job.application', [['email', '=', LOGIN], ['ext_id', '=', job['ext_id']]], 5)) == 1, location[:80])
finally:
    gw.call('delete_record', model='ir.config_parameter', res_id=param)
check('the form is switched off again afterwards (the default: Apply Now goes to the employer)', me.open('/jobs/ext/%d/apply' % job['id'])[0] == 404)

print('\nRESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
print('Look in Odoo: Recruitment > Apply Clicks (filter "Signed-in users") and Recruitment > Job Applications. Remove the test records: python tests\\click_user_test.py --cleanup')
