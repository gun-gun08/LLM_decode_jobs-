r"""Sign in before Apply Now - every Apply Now of the site, end to end in a browser-like client against the LOCAL instance:

  1. every Apply Now on the site leads to one of the gated routes (job cards of the landing page, search results, category pages, Latest Jobs, detail pages);
     a logged-out visitor is sent to the login page with the same Apply Now as `redirect`; nothing is saved yet;
  2. sign in with the login FORM: back to that job's Apply Now and on to its original application URL (never the homepage) - for a job card AND for a detail page
     of a different job; Job Applications gets ONE record per job with name, e-mail, user ID, job title, company, internal + external job ID, click time and the
     status "Redirected to External Site" (NOT submitted); Apply Clicks gets the click line without name / e-mail;
  3. a signed-in user skips the login page; a repeat click updates the same record (no duplicate);
  4. a NEW visitor creates an account with the sign-up form: the same flow, the record has the new account;
  5. a sign-in that lost its `redirect` still returns to the pending job (session);
  6. secure redirects (no other site), CSRF, nothing marked as submitted by clicks;
  7. our own positions (/jobs/position/<id>/go, Odoo's /jobs/apply/<position>) and our form (llmd_agg.apply_mode = form, only during this test): the same sign-in;
     opening our form is "Apply Clicked", sending it makes the SAME record "Received" (submitted).

Everything the test creates (clicks, records, the sign-up account, the test application) is removed at the end. Nothing is printed from .env.

  . .\scripts\env.ps1
  python tests\apply_login_test.py
"""
import http.cookiejar
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gw  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
if not gw.is_local():
    sys.exit('apply_login_test.py runs against the LOCAL instance only.')
LOGIN, PASSWORD = os.environ.get('LLMD_TEST_USER_LOGIN'), os.environ.get('LLMD_TEST_USER_PASSWORD')
if not LOGIN or not PASSWORD:
    sys.exit('LLMD_TEST_USER_LOGIN / LLMD_TEST_USER_PASSWORD are not set (.env, see scripts/local_test_user.py).')
RESULTS = []
GATED = re.compile(r'^/jobs/(?:ext/\d+/(?:go|apply)|position/\d+/go|apply/[\w-]+)$')
TEST_PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'


def rpc(model, method, args, kw=None):
    models, uid = gw._rpc()
    return models.execute_kw(os.environ['ODOO_DB'], uid, os.environ['ODOO_PASSWORD'], model, method, args, kw or {})


def check(label, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', label, ('' if ok else ' - %s' % (detail,))))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    """One visitor with its own cookies. Redirects are followed by hand (`follow`), so the test sees every step."""

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())

    def open(self, path, form=None, body=None, content_type=None):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36'}
        if form is not None:
            body, content_type = urlencode(form).encode(), 'application/x-www-form-urlencoded'
        if content_type:
            headers['Content-Type'] = content_type
        url = path if path.startswith('http') else gw.site_url() + path
        try:
            r = self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=60)
            return r.status, r.read().decode('utf-8', 'replace'), ''
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode('utf-8', 'replace'), exc.headers.get('Location', '')

    def follow(self, path, form=None):
        """[(status, location)] of every hop until a page is shown or the visitor leaves our site (an external address is not opened)."""
        hops = []
        status, page, location = self.open(path, form)
        while status in (301, 302, 303, 307) and len(hops) < 10:
            hops.append((status, location))
            if not (location.startswith('/') or location.startswith(gw.site_url())):
                return hops, ''
            status, page, location = self.open(location)
        hops.append((status, ''))
        return hops, page

    def csrf(self, path):
        found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.open(path)[1])
        return found.group(1) if found else ''

    def login(self, go):
        """The login FORM, after Apply Now sent the visitor to it: -> the locations it was sent to."""
        token = self.csrf('/web/login?' + urlencode({'redirect': go}))
        hops, _p = self.follow('/web/login', {'login': LOGIN, 'password': PASSWORD, 'redirect': go, 'csrf_token': token})
        return [l for _s, l in hops if l]

    def post_multipart(self, path, fields, files):
        token = self.csrf(path)
        boundary = '----llmdlogin%d' % int(time.time() * 1000)
        parts = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode() for k, v in dict(fields, csrf_token=token).items()]
        for k, (fname, data) in files.items():
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: application/pdf\r\n\r\n' % (boundary, k, fname)).encode() + data + b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode())
        return self.open(path, body=b''.join(parts), content_type='multipart/form-data; boundary=' + boundary)


def last_id(model):
    return max([r['id'] for r in gw.search(model, [['active', 'in', [True, False]]] if model == 'llmd.job.application' else [], 1)] or [0])


def new_clicks(before):
    return gw.search('llmd.job.click', [['id', '>', before]], 50)


def records(job_key, login=LOGIN):
    return gw.search('llmd.job.application', [['job_key', '=', job_key], ['email', '=', login.lower()], ['active', 'in', [True, False]]], 10)


def submitted_count():
    """Applications sent through a form or a provider (an Apply Now record is "Received" too, but its channel says it came from Apply Now)."""
    return len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000))


def apply_links(page):
    """The targets of every Apply Now button / link of a page."""
    return [m for m in re.findall(r'<a\b[^>]*\bclass="[^"]*(?:o_llmd_card_apply|o_llmd_apply)[^"]*"[^>]*href="([^"]+)"', page)] + \
           [m for m in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*\bclass="[^"]*(?:o_llmd_card_apply|o_llmd_apply)[^"]*"', page)]


def key_of(job):
    return 'ext:%s:%s' % (job['source'], job['ext_id'])


user = gw.search('res.users', [['login', '=', LOGIN]], 1)
if not user:
    sys.exit('The test account does not exist yet: run scripts/local_test_user.py first.')
user = user[0]
partner = gw.search('res.partner', [['id', '=', user['partner_id'][0]]], 1)[0]
taken = {a['job_key'] for a in gw.search('llmd.job.application', [['email', '=', LOGIN.lower()], ['active', 'in', [True, False]]], 500)}   # e.g. click_user_test keeps its application
jobs = [j for j in gw.search('llmd.job.listing', [['active', '=', True], ['apply_url', '=like', 'https://%']], 40) if 'ext:%s:%s' % (j['source'], j['ext_id']) not in taken][:3]
job, job_b = jobs[0], jobs[1]
go, go_b = '/jobs/ext/%d/go' % job['id'], '/jobs/ext/%d/go' % job_b['id']
start_click, start_app = last_id('llmd.job.click'), last_id('llmd.job.application')
start_position = max([p['id'] for p in gw.search('hr.job', [['active', 'in', [True, False]]], 1000)] or [0])
submitted0 = submitted_count()
signup_login = 'llmd.signup.%d@example.com' % int(time.time())
print('=== %s | job A %d "%s" at %s | job B %d "%s" at %s ===' % (gw.target_name(), job['id'], job['title'][:50], job['company'], job_b['id'], job_b['title'][:50], job_b['company']))

try:
    print('\n=== 1. every Apply Now on the site -> the same gated routes; logged out -> login page ===')
    anon = Browser()
    pages = {'landing (course matches)': ('/jobs', True), 'search results': ('/jobs/search/engineer', True), 'all jobs': ('/jobs/all', True),
             'a company page': ('/companies/%s' % rpc('llmd.company', 'search_read', [[('key', '=', ' '.join(job['company'].casefold().split()))]], {'fields': ['slug']})[0]['slug'], True),
             'a category page': ('/categories/it-software', True), 'detail page A': (job['page_url'], True),
             'Latest Jobs batch (View Details only)': ('/jobs/latest?page=1', False)}
    for name, (path, has_apply) in pages.items():
        status, page, _l = anon.open(path)
        links = apply_links(page)
        check('%-38s %2d Apply Now - none of them bypasses the gated routes' % (name + ':', len(links)), status == 200 and (bool(links) or not has_apply) and all(GATED.match(l) for l in links),
              [l for l in links if not GATED.match(l)][:3] or status)
    for target in (go, go_b, '/jobs/ext/%d/go' % jobs[2]['id']):
        status, _b, location = anon.open(target)
        check('logged out, %s -> the login page with the same Apply Now as redirect' % target, status == 303 and location.endswith('/web/login?' + urlencode({'redirect': target})), (status, location))
    check('... and nothing is saved before the sign-in (no click line, no record)', not new_clicks(start_click) and last_id('llmd.job.application') == start_app)
    status, page, _l = anon.open('/web/login?' + urlencode({'redirect': go}))
    check('the existing login page offers the existing sign-up with the same redirect', status == 200 and ('/web/signup?redirect=%s' % quote(go, safe='')) in page.replace('&amp;', '&'), status)
    status, page, _l = anon.open(job['page_url'])
    check('the detail page tells a logged-out visitor that a sign-in comes first', 'Sign in or create an account first' in page)

    print('\n=== 2. log in from a JOB CARD (job A) -> back to job A -> its application URL ===')
    before = last_id('llmd.job.click')
    locations = anon.login(go)
    check('after the login the visitor comes back to the same Apply Now (not the homepage)', bool(locations) and locations[0].endswith(go), locations[:2])
    check('... and is sent on to job A\'s original application URL', bool(locations) and locations[-1] == job['apply_url'], locations[-1:])
    recs = records(key_of(job))
    r = recs[0] if recs else {}
    check('Job Applications: ONE record - name, e-mail, user ID of the account',
          len(recs) == 1 and (r.get('applicant_name'), r.get('email'), (r.get('user_id') or [0])[0]) == (partner['name'], LOGIN.lower(), user['id']), (len(recs), r.get('applicant_name'), r.get('email')))
    check('... job title, company, internal job ID, external job ID, click time',
          (r.get('job_title'), r.get('company'), r.get('internal_job_id'), r.get('ext_id')) == (job['title'], job['company'], job['id'], job['ext_id']) and bool(r.get('clicked_at')),
          (r.get('job_title'), r.get('internal_job_id'), r.get('ext_id')))
    check('... status "Received", channel "Apply Now (signed in)", type "External Apply Click" - and no Recruitment applicant (nothing was sent through a form)',
          (r.get('state'), r.get('channel'), r.get('application_type'), r.get('applicant_id')) == ('submitted', 'apply_now', 'external_apply_click', False), (r.get('state'), r.get('channel')))
    lines = new_clicks(before)
    c = lines[0] if lines else {}
    check('Apply Clicks: ONE line with the job and the time - and NO name or e-mail',
          len(lines) == 1 and (c.get('job_title'), c.get('ext_id'), c.get('status')) == (job['title'], job['ext_id'], 'clicked') and not c.get('applicant_name') and not c.get('email'), len(lines))

    print('\n=== 3. already logged in -> straight on; a DETAIL page of another job (job B) ===')
    status, page, _l = anon.open(job_b['page_url'])
    check('the detail page of job B no longer asks a logged-in user to sign in, its Apply Now is the gated route', status == 200 and 'Sign in or create an account first' not in page and go_b in apply_links(page))
    status, _b, location = anon.open(go_b)
    check('a logged-in user skips the login page and goes straight to job B\'s application URL', status == 303 and location == job_b['apply_url'], (status, location[:80]))
    rb = records(key_of(job_b))
    check('... job B gets its OWN record (job B title / company / IDs, "Received")', len(rb) == 1 and (rb[0]['job_title'], rb[0]['ext_id'], rb[0]['state']) == (job_b['title'], job_b['ext_id'], 'submitted'), len(rb))
    anon.open(go)
    anon.open(go)
    recs = records(key_of(job))
    check('clicking job A again: still ONE record (time updated, no duplicate)', len(recs) == 1 and recs[0]['state'] == 'submitted' and recs[0]['click_count'] >= 1, len(recs))

    print('\n=== 4. sign up with a NEW account from a job card -> back to the job -> its application URL ===')
    new = Browser()
    new.open(go_b)
    token = new.csrf('/web/signup?' + urlencode({'redirect': go_b}))
    check('the existing sign-up page opens with the redirect', bool(token))
    pw = 'Local-only-%d' % int(time.time())
    hops, page = new.follow('/web/signup', {'login': signup_login, 'name': 'LLMD Signup Test', 'password': pw, 'confirm_password': pw, 'redirect': go_b, 'csrf_token': token})
    locations = [l for _s, l in hops if l]
    check('after the sign-up the new user comes back to the same Apply Now', bool(locations) and locations[0].endswith(go_b), (locations[:2], re.findall(r'alert-danger[^>]*>([^<]+)', page or '')[:1]))
    check('... and is sent on to job B\'s application URL', bool(locations) and locations[-1] == job_b['apply_url'], locations[-1:])
    rn = records(key_of(job_b), signup_login)
    check('Job Applications: ONE record with the new account\'s name, e-mail and user ID, "Received"',
          len(rn) == 1 and rn[0]['applicant_name'] == 'LLMD Signup Test' and rn[0]['user_id'] and rn[0]['state'] == 'submitted', len(rn))

    print('\n=== 5. a login that lost its redirect ===')
    lost = Browser()
    lost.open(go)
    token = lost.csrf('/web/login')
    hops, _p = lost.follow('/web/login', {'login': LOGIN, 'password': PASSWORD, 'csrf_token': token})
    locations = [l for _s, l in hops if l]
    check('the login without redirect still returns to the pending Apply Now, then the application URL', bool(locations) and locations[0].endswith(go) and locations[-1] == job['apply_url'], locations[:3])
    plain = Browser()
    token = plain.csrf('/web/login')
    hops, _p = plain.follow('/web/login', {'login': LOGIN, 'password': PASSWORD, 'csrf_token': token})
    locations = [l for _s, l in hops if l]
    check('a normal login (no Apply Now pending) keeps Odoo\'s usual page', bool(locations) and '/jobs/' not in locations[0], locations[:1])

    print('\n=== 6. secure redirects, CSRF, no false submissions, no duplicates ===')
    evil = Browser()
    token = evil.csrf('/web/login')
    status, _b, location = evil.open('/web/login', {'login': LOGIN, 'password': PASSWORD, 'redirect': 'https://evil.example.com/steal', 'csrf_token': token})
    check('a redirect to another site is turned into a local path (no open redirect)', status in (302, 303) and (location.startswith('/') or location.startswith(gw.site_url() + '/')), location)
    status, _b, _l = Browser().open('/web/login', {'login': LOGIN, 'password': PASSWORD, 'redirect': go})
    check('a login POST without CSRF token is refused', status in (400, 403), status)
    check('external clicks create no form / provider application and no Recruitment applicant (%d before, %d now)' % (submitted0, submitted_count()), submitted_count() == submitted0)
    mine = gw.search('llmd.job.application', [['id', '>', start_app], ['active', 'in', [True, False]]], 100)
    pairs = [(a['job_key'], a['identity_key']) for a in mine]
    check('no duplicate records: one per person and job (%d records)' % len(mine), len(pairs) == len(set(pairs)), pairs)

    print('\n=== 7. our own positions, Odoo\'s position form and our own form ===')
    position = gw.search('hr.job', [['website_published', '=', True]], 5)
    if position:
        with_link = [p for p in position if p['apply_url']]
        if with_link:
            path = '/jobs/position/%d/go' % with_link[0]['id']
            status, _b, location = Browser().open(path)
            check('Apply Now of our own position asks for the login too', status == 303 and location.endswith('/web/login?' + urlencode({'redirect': path})), (status, location))
        page = Browser().open(position[0]['website_url'])[1]
        stock_links = sorted(set(re.findall(r'href="(/jobs/apply/[^"]+)"', page)))
        if stock_links:
            status, _b, location = Browser().open(stock_links[0])
            check("Odoo's own \"Apply Now!\" of a position (%s) asks for the login too" % stock_links[0], status == 303 and location.endswith('/web/login?' + urlencode({'redirect': stock_links[0]})), (status, location))
            locations = Browser().login(stock_links[0])
            check('... and comes back to that form after the login', bool(locations) and locations[0].endswith(stock_links[0]), locations[:2])
        else:
            print('  (no stock "Apply Now!" on %s: skipped)' % position[0]['website_url'])
    else:
        print('  (no published position: skipped)')
    param = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.apply_mode', 'value': 'form'})['id']
    try:
        form = '/jobs/ext/%d/apply' % jobs[2]['id']
        status, _b, location = Browser().open(form)
        check('form mode: logged out -> the login page, back to the form afterwards', status in (302, 303) and location.endswith('/web/login?' + urlencode({'redirect': form})), (status, location))
        before = last_id('llmd.job.click')
        status, page, _l = anon.open(form)
        rf = records(key_of(jobs[2]))
        check('form mode: the logged-in user sees the form filled from the account; Job Applications: "Received" from Apply Now, no applicant yet; no click line',
              status == 200 and 'value="%s"' % LOGIN in page and len(rf) == 1 and rf[0]['state'] == 'submitted' and rf[0]['channel'] == 'apply_now' and not rf[0]['applicant_id'] and not new_clicks(before),
              (status, [(x['state'], x['channel']) for x in rf]))
        status, _b, location = anon.post_multipart(form, {'name': partner['name'], 'email': LOGIN, 'phone': partner.get('phone') or '', 'consent': '1', 'note': 'apply_login_test'},
                                                   {'resume': ('Login Test CV.pdf', TEST_PDF)})
        rf = records(key_of(jobs[2]))
        check('sending the form makes the SAME record "Received" (submitted) with an application date and the Odoo applicant - only now it is an application',
              status == 303 and '/applied?ref=' in location and len(rf) == 1 and rf[0]['state'] == 'submitted' and rf[0]['application_date'] and rf[0]['applicant_id'], (status, location[:60]))
    finally:
        gw.call('delete_record', model='ir.config_parameter', res_id=param)
finally:
    lines = new_clicks(start_click)
    if lines:
        rpc('llmd.job.click', 'unlink', [[l['id'] for l in lines]])
    made = gw.search('llmd.job.application', [['id', '>', start_app], ['active', 'in', [True, False]]], 200)
    applicants = [a['applicant_id'][0] for a in made if a['applicant_id']]
    if made:
        rpc('llmd.job.application', 'unlink', [[a['id'] for a in made]])
    if applicants:
        rpc('hr.applicant', 'unlink', [applicants])
    positions = gw.search('hr.job', [['id', '>', start_position], ['llmd_listing_id', '!=', False], ['active', 'in', [True, False]]], 20)
    if positions:
        rpc('hr.job', 'unlink', [[p['id'] for p in positions]])              # the unpublished position our form makes for a job
    created = gw.search('res.users', [['login', '=', signup_login], ['active', 'in', [True, False]]], 1)
    if created:
        try:
            rpc('res.users', 'unlink', [[created[0]['id']]])
        except Exception:
            rpc('res.users', 'write', [[created[0]['id']], {'active': False}])
    print('\ncleanup: %d click lines, %d Job Applications records, %d applicants%s removed' % (len(lines), len(made), len(applicants), ', the sign-up account' if created else ''))

print('\nRESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
