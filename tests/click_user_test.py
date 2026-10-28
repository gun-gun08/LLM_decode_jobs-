r"""Apply Now of a LOGGED-IN website user, against the LOCAL instance:

  1. the test account (scripts/local_test_user.py, login + password from .env) logs in on the website;
  2. it clicks Apply Now of a real job: it is sent to the employer's original application page, and Recruitment > Apply Clicks gets ONE line with the job only -
     title, company, source, external job ID, original apply URL, click time, status - and NO user, name, e-mail or phone (also not of a logged-in user);
  3. an anonymous click of the same job is the same kind of line;
  4. a click is never an application: Job Applications and Recruitment applicants do not change;
  5. with our own application form switched on (llmd_agg.apply_mode = form, only during this test), the logged-in user sees the form (name + e-mail, no phone) filled
     from the profile and sends it: ONE real application is saved (Job Applications + Recruitment applicant) with the details that were sent.

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

    def post_form(self, path, fields):
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.open(path)[1]).group(1)
        boundary = '----llmdclick%d' % int(time.time() * 1000)
        parts = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode() for k, v in dict(fields, csrf_token=token).items()]
        parts.append(('--%s--\r\n' % boundary).encode())
        return self.open(path, b''.join(parts), 'multipart/form-data; boundary=' + boundary)


def counts():
    return (len(gw.search('llmd.job.application', [['active', 'in', [True, False]]], 5000)), len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000)))


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
status, page, _ = me.open('/jobs/ext/%d' % job['id'])
check('the job page opens for the logged-in user, with ONE Apply Now (the tracked /go link)', status == 200 and page.count('href="/jobs/ext/%d/go"' % job['id']) == 1, status)

print('\n=== 2. Apply Now of the logged-in user ===')
before = max([c['id'] for c in gw.search('llmd.job.click', [], 1)] or [0])
status, _b, location = me.open('/jobs/ext/%d/go' % job['id'])
check('Apply Now sends the user straight on to the employer\'s original application page (external redirect kept)', status in (302, 303) and location == job['apply_url'], (status, location[:80]))
mine = gw.search('llmd.job.click', [['id', '>', before]], 5)
c = mine[0] if mine else {}
check('ONE click line', len(mine) == 1, len(mine))
check('... with NO personal data: no user, name, e-mail or phone column, and nothing of the profile anywhere in the line',
      bool(c) and not ({'user_id', 'applicant_name', 'email', 'phone', 'logged_in'} & set(c)) and not any(str(v) in (partner['name'], LOGIN, partner['phone']) for v in c.values() if v),
      sorted(set(c) & {'user_id', 'applicant_name', 'email', 'phone', 'logged_in'}))
check('... and the job: title, company, external job ID, original apply URL, click time, status "Clicked"',
      (c.get('job_title'), c.get('company'), c.get('ext_id'), c.get('apply_url'), c.get('status')) == (job['title'], job['company'], job['ext_id'], job['apply_url'], 'clicked') and bool(c.get('clicked_at')),
      (c.get('job_title'), c.get('ext_id'), c.get('clicked_at')))
status, _b, _l = me.open('/jobs/ext/%d/go?name=Someone+Else&email=fake%%40example.com' % job['id'])
lines = gw.search('llmd.job.click', [['id', '>', before]], 5)
check('names or e-mails put in the address are not stored either', status in (302, 303) and not any('fake@example.com' in str(v) or 'Someone' in str(v) for l in lines for v in l.values() if v))
rpc('llmd.job.click', 'unlink', [[l['id'] for l in lines]])                # the test's own click lines are no use to anybody

print('\n=== 3. an anonymous click ===')
anon = Browser()
before_anon = max([c['id'] for c in gw.search('llmd.job.click', [], 1)] or [0])
status, _b, location = anon.open('/jobs/ext/%d/go' % job['id'])
a = (gw.search('llmd.job.click', [['id', '>', before_anon]], 1) or [{}])[0]
check('an anonymous visitor is sent on too, with the same kind of line (the job only)', status in (302, 303) and location == job['apply_url'] and a and a.get('job_title') == job['title']
      and not ({'user_id', 'applicant_name', 'email', 'phone'} & set(a)), a.get('id'))
if a:
    rpc('llmd.job.click', 'unlink', [[a['id']]])                     # the anonymous test click is no use to anybody

print('\n=== 4. a click is not an application ===')
check('Job Applications and Recruitment applicants are unchanged by the clicks (%d / %d)' % apps0, counts() == apps0, counts())

print('\n=== 5. our own application form (switched on only for this test) ===')
param = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.apply_mode', 'value': 'form'})['id']
try:
    status, form, _ = me.open('/jobs/ext/%d/apply' % job['id'])
    check('the form opens for the logged-in user, filled from the profile (name, e-mail) - and it has NO phone field', status == 200 and 'value="%s"' % partner['name'] in form
          and 'value="%s"' % LOGIN in form and 'name="phone"' not in form, status)
    status, _b, location = me.post_form('/jobs/ext/%d/apply' % job['id'], {'name': partner['name'], 'email': LOGIN,
                                                                          'note': 'Test application of the LLMD test account (local), sent without a phone number.', 'consent': 'on'})
    check('sending it saves the application and shows the confirmation page', status == 303 and '/applied?ref=' in location, (status, location[:80]))
    app = (gw.search('llmd.job.application', [['email', '=', LOGIN], ['ext_id', '=', job['ext_id']]], 2) or [{}])[0]
    check('Job Applications: ONE real record without a phone - name, e-mail, job title, company, external job ID, original apply URL, application date, channel "Our website", status Received',
          (app.get('applicant_name'), app.get('email'), 'phone' in app, app.get('job_title'), app.get('company'), app.get('ext_id'), app.get('apply_url'), app.get('channel'), app.get('state'))
          == (partner['name'], LOGIN, False, job['title'], job['company'], job['ext_id'], job['apply_url'], 'own', 'submitted') and bool(app.get('application_date')), app.get('id'))
    hr = gw.search('hr.applicant', [['email_from', '=', LOGIN]], 3)
    check('... and ONE Recruitment applicant linked to it', len(hr) == 1 and app.get('applicant_id') and app['applicant_id'][0] == hr[0]['id'], len(hr))
finally:
    gw.call('delete_record', model='ir.config_parameter', res_id=param)
check('the form is switched off again afterwards (the default: Apply Now goes to the employer)', me.open('/jobs/ext/%d/apply' % job['id'])[0] == 404)

print('\nRESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
print('Look in Odoo: Recruitment > Apply Clicks (filter "Logged-in users") and Recruitment > Job Applications. Remove the test records: python tests\\click_user_test.py --cleanup')
