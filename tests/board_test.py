"""Test the local job board: sources, normalization, de-duplication, the landing page (search, categories, course-matched jobs, companies, latest jobs, locations),
the results pages (/jobs?..., /jobs/category|company|location|role/<slug>) with every filter alone and together, course -> role -> jobs, View Details -> detail page ->
Apply Now -> the tracked link that saves the click in Odoo (Apply Clicks) and sends the visitor straight to the employer's application page (default), the optional application form (llmd_agg.apply_mode = form), the provider API (API key), and that no job-site name is ever visible.

  . .\\scripts\\env.ps1
  python tests\\board_test.py fetch        read every connected source and store the jobs (also done daily by the scheduled action)
  python tests\\board_test.py test         run all checks against the local website
(the adapters' own unit tests: python tests\\sources_test.py ; python tests\\facets_test.py)

The test needs jobs on the board for every course / role / work mode, and the real job sources are only connected when their keys are in .env. So it first creates TEMPORARY test jobs
(ext_id "zzds-...": two or three for every job role, remote / hybrid / on-site, in Indian cities; plus 8 "ZZFX ..." jobs with known filter answers). They are test data only; ALL of them are deleted again at the end (also when a check fails). Real jobs from connected sources are tested together with them.
"""
import base64
import datetime
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import gw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import board_config as BC  # noqa: E402  (pure Python: the courses, roles and chips of the board)
import summary as SUM  # noqa: E402  (pure Python: the Job Overview block of the detail page)
import job_facets as JF  # noqa: E402  (pure Python: the stored form of a skill)
from collections import Counter  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
if not gw.is_local():
    sys.exit('board_test.py only runs against the local instance (run  . .\\scripts\\env.ps1  first).')

COURSES = {'sell-ai': 'How to sell complex products with AI', 'genai-mastermind': '2 DAY GEN AI ENGINEERING MASTERMIND', 'claude-masterclass': 'A–Z Claude Masterclass',
           'funnel-101': 'From Leads to Sales: Funnel Building 101'}
CHIPS = ['All', 'GenAI', 'Claude', 'Python', 'AI/ML', 'Data Analytics', 'Sales', 'Digital Marketing']
EXP_LABELS = {'fresher': 'Fresher', 'internship': 'Internship', 'entry': 'Entry-level', 'mid': 'Mid-level', 'senior': 'Senior-level'}
TYPE_LABELS = {'fulltime': 'Full-time', 'parttime': 'Part-time', 'internship': 'Internship', 'contract': 'Contract'}
MODE_LABELS = {'remote': 'Remote', 'hybrid': 'Hybrid', 'onsite': 'On-site'}
PLATFORM = re.compile(r'adzuna|jsearch|jooble|indeed|naukri|himalayas|linkedin|glassdoor|rapidapi|ziprecruiter|monster\b', re.I)
RESULTS = []


def get(path):
    try:
        r = urllib.request.urlopen(urllib.request.Request(gw.site_url() + path, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40)
        return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, ''


def page_of(**params):
    """GET /jobs with filters; lists become repeated parameters."""
    return get('/jobs?' + urllib.parse.urlencode({k: v for k, v in params.items() if v not in ('', None, [])}, doseq=True))


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


def text(page):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', page, flags=re.S))))


def options(page, name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, page, re.S)
    return [(html.unescape(v), html.unescape(re.sub(r'<[^>]+>', '', t)).strip()) for v, t in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S)] if m else []


def selected(page, name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, page, re.S)
    sel = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected', m.group(1)) if m else None
    return html.unescape(sel.group(1)) if sel else None


def select_tag(page, name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>' % name, page)
    return m.group(0) if m else ''


def cards(page):
    """[{id, see, tags, text}] of the job cards (not our own positions) on a /jobs page"""
    out = []
    for part in re.split(r'(?=<article class="o_llmd_job o_llmd_card">)', page)[1:]:
        part = part.split('</article>', 1)[0]
        m = re.search(r'href="/jobs/(\d+)/[a-z0-9-]+"', part)                     # the job's own page: /jobs/<id>/<slug>
        see = re.search(r'<a[^>]*o_llmd_see[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*o_llmd_see', part)
        if not m:
            continue
        apply = re.search(r'<a\b(?=[^>]*\bo_llmd_card_apply\b)[^>]*href="([^"]+)"', part)
        out.append({'id': int(m.group(1)), 'see': html.unescape(see.group(1) or see.group(2)) if see else '', 'tags': [text(t).strip() for t in re.findall(r'class="o_llmd_tag"[^>]*>(.*?)</span>', part, re.S)], 'text': text(part),
                    'html': part, 'apply': html.unescape(apply.group(1)) if apply else ''})
    return out


def links(page, cls):
    """[(href, inner text)] of the <a> tags that have the class `cls`, whatever the order of their attributes."""
    out = []
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', page, re.S):
        attrs = m.group(1)
        c = re.search(r'\bclass="([^"]*)"', attrs)
        h = re.search(r'\bhref="([^"]*)"', attrs)
        if c and cls in c.group(1).split() and h:
            out.append((html.unescape(h.group(1)), m.group(2)))
    return out


def adv_options(page, name):
    """[(value, label, count)] of one Advanced Filter (checkboxes of the sidebar)."""
    return [(v, html.unescape(text(l)).strip(), int(n)) for v, l, n in
            re.findall(r'<input type="checkbox" class="form-check-input" name="%s" value="([^"]+)"[^>]*>\s*<span class="o_llmd_check_txt">(.*?)</span><span class="o_llmd_n">(\d+)</span>' % name, page, re.S)]


def count_of(page):
    m = re.search(r'(\d+)\s*jobs? found', text(page))
    return int(m.group(1)) if m else None


def facet(page, name, kind='checkbox'):
    """[(value, label, count, checked)] of one list of the filter panel (check boxes or radio buttons with a count)."""
    out = []
    for attrs, label, n in re.findall(r'<input type="%s" class="form-check-input" name="%s"([^>]*)>\s*<span class="o_llmd_check_txt">(.*?)</span><span class="o_llmd_n">(\d+)</span>' % (kind, name), page, re.S):
        v = re.search(r'value="([^"]*)"', attrs)
        out.append((html.unescape(v.group(1)) if v else '', html.unescape(text(label)).strip(), int(n), 'checked' in attrs))
    return out


NCR_CITIES = ('Delhi', 'Gurugram', 'Noida', 'Faridabad', 'Ghaziabad')
ZONE_SLUGS = {s for s, _n, _t, _i in JF.INDIA_ZONES}
REGION_BY_NAME = {k: s for s, n, _t, _i in JF.REGIONS + JF.INDIA_ZONES for k in (n.lower(), s.replace('-', ' '))}


def in_region(r, slug):
    return (r['india_zone'] if slug in ZONE_SLUGS else r['region']) == slug


def matches(r, f):
    """Does the stored job r pass the filters f (the URL parameters of the board)? Written from the filter rules, independently of the controller."""
    one = lambda v: v if isinstance(v, list) else [v]                       # noqa: E731
    if f.get('course') and ',%s,' % f['course'] not in (r['courses'] or ''):        # the course page (/jobs/course/<course>), not a filter
        return False
    if f.get('region') and not in_region(r, f['region']):
        return False
    if f.get('category') and r['job_category'] not in one(f['category']) or f.get('city') and r['city'] not in one(f['city']):
        return False
    if f.get('jtype') and r['job_type'] not in one(f['jtype']) or f.get('mode') and r['work_mode'] != f['mode'] or f.get('country') and r['country'] != f['country']:
        return False
    if f.get('company') and r['company'] not in one(f['company']) or f.get('function') and r['job_function'] not in one(f['function']):
        return False
    if f.get('role') and not any(',%s,' % x in (r['roles'] or '') for x in one(f['role'])):
        return False
    if f.get('skill') and not any(',%s,' % JF.skill_key(x) in (r['skill_keys'] or '') for x in one(f['skill'])):
        return False
    lo, hi = int(f.get('exp_min', 0)), int(f.get('exp_max', 25))
    if (lo > 0 or hi < 25) and not (r['exp_years_known'] and r['exp_years_max'] >= lo and (hi >= 25 or r['exp_years_min'] <= hi)):
        return False
    if f.get('posted') and not (r['posted'] and datetime.datetime.strptime(r['posted'], '%Y-%m-%d %H:%M:%S') >= datetime.datetime.utcnow() - datetime.timedelta(days=int(f['posted']))):
        return False
    place = (f.get('location') or '').strip()
    if place:
        low = place.lower()
        if low in ('india', 'in'):
            ok = r['country'] == 'India'
        elif low in ('delhi ncr', 'ncr', 'delhi-ncr'):
            ok = r['city'] in NCR_CITIES
        elif low in ('remote', 'work from home', 'wfh', 'anywhere'):
            ok = r['work_mode'] == 'remote'
        elif low in REGION_BY_NAME:
            ok = in_region(r, REGION_BY_NAME[low])
        elif JF.city_of(place) or JF.world_city_of(place):
            ok = r['city'] == (JF.city_of(place) or JF.world_city_of(place))
        else:
            ok = low in (r['location'] or '').lower()
        if not ok:
            return False
    hay = ('%s %s %s' % (r['title'], r['company'] or '', r['search_text'] or '')).lower()
    return all(w.lower() in hay for w in (f.get('q') or '').split()[:6])


def listings(domain=None, limit=50000):
    return gw.search('llmd.job.listing', domain or [['active', '=', True]], limit)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Visitor:
    """A website visitor with its own cookies (the session that the CSRF token belongs to). Redirects are NOT followed, so the test sees them.
    signed_in=True: the local test account (LLMD_TEST_USER_LOGIN / _PASSWORD of .env, scripts/local_test_user.py) is signed in first - Apply Now asks for a sign-in,
    and the site-wide switch llmd_agg.apply_login is never touched by a test (switching it off would open the gate for every visitor while the test runs)."""

    def __init__(self, signed_in=False):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())
        if signed_in:
            import json
            body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {'db': gw.os.environ['ODOO_DB'], 'login': gw.os.environ['LLMD_TEST_USER_LOGIN'],
                                                                              'password': gw.os.environ['LLMD_TEST_USER_PASSWORD']}}).encode()
            status, answer, _l = self.open('/web/session/authenticate', body, 'application/json')
            if status != 200 or not (json.loads(answer).get('result') or {}).get('uid'):
                sys.exit('the local test account could not sign in (scripts/local_test_user.py, LLMD_TEST_USER_LOGIN / LLMD_TEST_USER_PASSWORD in .env)')

    def open(self, path, body=None, content_type=None):
        req = urllib.request.Request(gw.site_url() + path, data=body, headers={'User-Agent': 'Mozilla/5.0', **({'Content-Type': content_type} if content_type else {})})
        try:
            r = self.opener.open(req, timeout=60)
            return r.status, r.read().decode('utf-8', 'replace'), ''
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode('utf-8', 'replace'), exc.headers.get('Location', '')

    def post_form(self, path, fields, files=None, csrf=True, csrf_from=None, ua=None):
        if csrf:
            fields = dict(fields, csrf_token=re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.open(csrf_from or path)[1]).group(1))
        boundary = '----llmdtest%d' % int(time.time() * 1000)
        parts = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode() for k, v in fields.items()]
        for k, (fname, data) in (files or {}).items():
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n' % (boundary, k, fname)).encode() + data + b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode())
        return self.open(path, b''.join(parts), 'multipart/form-data; boundary=' + boundary)


TEST_PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'

# temporary jobs with KNOWN answers for the filters: (key, title, company, location, countries, employment type, seniority, description)
FIXTURES = [
    ('f1', 'ZZFX Fresher Sales Executive', 'Fixture Co', 'Pune, Maharashtra', 'IN', 'Full Time', 'Fresher', '<p>Join our sales team and learn on the job every day of the week.</p>'),
    ('f2', 'ZZFX Hybrid Marketing Manager', 'Fixture Co', 'Bengaluru, Karnataka', 'IN', 'Full Time', '', '<p>Hybrid work model: three days in the office and two at home every week.</p>'),
    ('f3', 'ZZFX Remote Python Developer', 'Fixture Co', 'Remote · Hyderabad, India', 'IN', 'Contract', '', '<p>Build services in Python for our growing product team every day.</p>'),
    ('f4', 'ZZFX SEO Specialist', 'Fixture Co', 'Gurugram, Haryana', 'IN', 'Part Time', '', '<p>Own organic growth for our brands and report on results every week.</p>'),
    ('f5', 'ZZFX Marketing Intern', 'Fixture Co', 'Mumbai, Maharashtra', 'IN', 'Internship', '', '<p>Support the marketing team with research and campaigns every day.</p>'),
    ('f6', 'ZZFX Senior Data Scientist', 'Fixture Co', 'London, UK', 'GB', 'Full Time', '', '<p>Lead modelling work for our analytics group in the London office.</p>'),
    ('f7', 'ZZFX Junior Data Analyst', 'Fixture Co', 'Pune, India', 'IN', 'Full Time', '', '<p>Prepare reports and dashboards for the business teams every week.</p>'),
    ('f8', 'ZZFX Worldwide Growth Marketer', 'Fixture Co', 'Remote · Worldwide', 'Worldwide', 'Full Time', '', '<p>Run growth experiments for our global customers from anywhere.</p>'),
]
# what the filters must give for them: (filters) -> fixture keys
INDIA = {'f1', 'f2', 'f3', 'f4', 'f5', 'f7'}
FIXTURE_EXPECT = [
    ({}, {'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8'}),
    ({'country': 'India'}, INDIA), ({'location': 'India'}, INDIA), ({'loc': 'india'}, INDIA),
    ({'location': 'Remote'}, {'f3', 'f8'}), ({'loc': 'remote'}, {'f3', 'f8'}),
    ({'city': 'Pune'}, {'f1', 'f7'}), ({'location': 'Pune'}, {'f1', 'f7'}), ({'loc': 'Pune'}, {'f1', 'f7'}), ({'city': ['Pune', 'Mumbai']}, {'f1', 'f5', 'f7'}),
    ({'mode': 'remote'}, {'f3', 'f8'}), ({'mode': 'hybrid'}, {'f2'}), ({'mode': 'onsite'}, {'f1', 'f4', 'f5', 'f6', 'f7'}),
    ({'country': 'India', 'mode': 'remote'}, {'f3'}), ({'country': 'India', 'mode': 'hybrid'}, {'f2'}), ({'country': 'India', 'mode': 'onsite'}, {'f1', 'f4', 'f5', 'f7'}),
    ({'city': 'Pune', 'mode': 'onsite'}, {'f1', 'f7'}), ({'city': 'Pune', 'mode': 'remote'}, set()), ({'location': 'Remote', 'mode': 'onsite'}, set()), ({'city': 'Mumbai', 'mode': 'hybrid'}, set()),
    ({'jtype': 'contract'}, {'f3'}), ({'jtype': 'parttime'}, {'f4'}), ({'jtype': 'internship'}, {'f5'}), ({'jtype': ['parttime', 'internship'], 'country': 'India'}, {'f4', 'f5'}),
    ({'region': 'india-south-asia'}, INDIA), ({'region': 'europe'}, {'f6'}), ({'region': 'worldwide'}, {'f8'}), ({'region': 'west-india'}, {'f1', 'f5', 'f7'}),
    ({'region': 'south-india'}, {'f2', 'f3'}), ({'region': 'north-india'}, {'f4'}), ({'region': 'south-india', 'mode': 'remote'}, {'f3'}), ({'region': 'east-central-india'}, set()),
    ({'location': 'Europe'}, {'f6'}), ({'location': 'West India', 'jtype': 'internship'}, {'f5'}),
]

def make_fixtures(stamp):
    ids = {}
    for key, title, company, location, countries, kind, seniority, description in FIXTURES:
        ids[key] = gw.call('create_record', model='llmd.job.listing', values={
            'source': 'Adzuna', 'ext_id': 'zzfx-%s-%d' % (key, stamp), 'title': title, 'company': company, 'location': location, 'countries': countries, 'employment_type': kind,
            'seniority': seniority, 'description_html': description, 'full_text': False, 'short_description': 'Fixture job for the filter test.', 'via': 'naukri.com', 'also_on': 'Jooble',
            'tags': ',sales,', 'roles': ',sales_manager,', 'courses': ',sell-ai,', 'apply_url': 'https://careers.example.com/zzfx/%s/%d' % (key, stamp), 'posted': time.strftime('%Y-%m-%d %H:%M:%S')})['id']
    return ids


CITIES = ['Bengaluru, Karnataka', 'Pune, Maharashtra', 'Gurugram, Haryana', 'Hyderabad, Telangana', 'Mumbai, Maharashtra', 'Delhi', 'Chennai, Tamil Nadu', 'Noida, Uttar Pradesh']
MODE_TEXT = {'onsite': 'You will work from our office in %s and visit customers in the city.', 'hybrid': 'Hybrid work model: three days in the office and two days at home.',
             'remote': 'This is a remote position: you can work from anywhere in India.'}


def rpc(model, method, args):
    models, uid = gw._rpc()
    return models.execute_kw(gw.os.environ['ODOO_DB'], uid, gw.os.environ['ODOO_PASSWORD'], model, method, args)


def purge_dataset():
    ids = [r['id'] for r in gw.search('llmd.job.listing', [['ext_id', 'like', 'zzds-'], ['active', 'in', [True, False]]], 1000)]
    if ids:
        rpc('llmd.job.listing', 'unlink', [ids])
    return len(ids)


def make_dataset(stamp):
    """TEMPORARY test jobs, two or three for every job role of every course, as on-site / remote / hybrid jobs in Indian cities (deleted again by purge_dataset())."""
    import json
    n, ids = 0, []
    for code, label, _rx, _q, _courses in BC.ROLES:
        title = 'Claude Prompt Engineer' if code == 'prompt_engineer' else label                     # so that the "Claude" chip has jobs too
        tags = [t for t, _l, rx in BC.TRACKS if re.search(rx, title.lower())]
        courses = BC.courses_of_roles([code])
        for variant in ('onsite', 'remote', 'hybrid'):
            n += 1
            city = CITIES[n % len(CITIES)]
            location = 'Remote · India' if variant == 'remote' else city
            about = 'About the %s role: you will plan the work, report the results and work with the team every week.' % title
            ids.append(gw.call('create_record', model='llmd.job.listing', values={
                'source': ('Adzuna', 'JSearch', 'Jooble')[n % 3], 'ext_id': 'zzds-%d-%s-%d' % (stamp, code, n), 'title': title + (' (Remote)' if variant == 'remote' else ''), 'company': 'Test Company %d' % (n % 7 + 1),
                'location': location, 'countries': 'IN', 'employment_type': 'Full Time', 'description_html': '<p>%s</p><p>%s</p>' % (about, MODE_TEXT[variant] % city.split(',')[0] if variant == 'onsite' else MODE_TEXT[variant]),
                'full_text': True, 'short_description': about[:190], 'apply_url': 'https://careers.example.com/zzds/%d/%d' % (stamp, n), 'posted': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() - ((n * 37) % 71 + 1) * 3600)),               # a mix of roles on every page
                'sections_json': json.dumps({'about': about, 'duties': ['Plan the work', 'Report the results', 'Work with the team'], 'skills': ['Communication', 'Planning'], 'quals': [], 'experience': ['2 years of experience'], 'preferred': []}),
                'tags': (',' + ','.join(tags) + ',') if tags else '', 'roles': ',%s,' % code, 'courses': ',' + ','.join(courses) + ',', 'role_type': code, 'search_text': '%s Test Company Communication Planning' % title,
                'dedupe_key': 'zzds|%d' % n, 'rank': n})['id'])
    return ids


def apply_flow(rows, click0):
    print("\n=== K. Apply Now: one button -> the employer's application URL, every click saved in Odoo (Apply Clicks), no application form, no made-up applicant data, the provider API ===")
    import calendar
    import json
    jobs = [r for r in rows if r['apply_url'] and r['source'] in ('JSearch', 'Jooble', 'Adzuna') and r['company']]
    job, job2 = jobs[0], jobs[1]
    jid, stamp = job['id'], int(time.time())
    created_applicants = []

    def key_of(r):
        return 'ext:%s:%s' % (r['source'], r['ext_id'])

    def clicks(**dom):
        return gw.search('llmd.job.click', [[k, '=', v] for k, v in dom.items()] + [['id', '>', click0]], 500)

    def apps(**dom):
        return gw.search('llmd.job.application', [[k, '=', v] for k, v in dom.items()] + [['active', 'in', [True, False]]], 50)

    def apps_count():
        return len(gw.search('llmd.job.application', [['active', 'in', [True, False]]], 5000))

    def applicants_count():
        return len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000))

    def jsonrpc(params, headers=None):
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params}).encode()
        req = urllib.request.Request(gw.site_url() + '/api/llmd/applications', body, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0', **(headers or {})})
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())['result']

    n_app0, n_hr0 = apps_count(), applicants_count()
    app_id0 = max([a['id'] for a in gw.search('llmd.job.application', [['active', 'in', [True, False]]], 1)] or [0])
    tester = gw.search('res.users', [['login', '=', gw.os.environ['LLMD_TEST_USER_LOGIN']]], 1)[0]
    pid = None
    pid_form = None
    n_pos0 = len(gw.search('hr.job', [['llmd_listing_id', '!=', False], ['active', 'in', [True, False]]], 5000))
    try:
        # ---- the detail page (default): ONE Apply Now that goes straight to the employer through the tracked link - no form
        page = get('/jobs/ext/%d' % jid)[1]
        tags = re.findall(r'<a\s[^>]*o_llmd_apply[^>]*>', page)
        hrefs = [html.unescape(re.search(r'href="([^"]+)"', t).group(1)) for t in tags]
        path = '/jobs/ext/%d/apply' % jid
        region = (re.search(r'<div class="o_llmd_view">.*?</aside>', page, re.S) or [''])[0]
        check("the detail page (default): ONE 'Apply Now' - the tracked /go link of this job (new tab, noopener, nofollow) - and NO application form",
              len(re.findall(r'>\s*Apply Now', page)) == 1 and hrefs == ['/jobs/ext/%d/go' % jid] and all(x in tags[0] for x in ('target="_blank"', 'noopener', 'nofollow')) and bool(region) and '<form' not in region and path not in page, hrefs)
        check('... the original apply URL itself (and any site name) is not on the page', job['apply_url'] not in html.unescape(page) and not PLATFORM.search(text(page)))
        check('by default the form, the "I applied elsewhere" report and the confirmation page answer 404', all(get('/jobs/ext/%d/%s' % (jid, x))[0] == 404 for x in ('apply', 'report', 'applied')))

        # ---- the OPTIONAL form mode (system parameter llmd_agg.apply_mode = form)
        pid_form = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.apply_mode', 'value': 'form'})['id']
        page = get('/jobs/ext/%d' % jid)[1]
        tags = re.findall(r'<a\s[^>]*o_llmd_apply[^>]*>', page)
        hrefs = [html.unescape(re.search(r'href="([^"]+)"', t).group(1)) for t in tags]
        go_tag = (re.search(r'<a[^>]*href="/jobs/ext/%d/go"[^>]*>' % jid, page) or [''])[0]
        check("form mode: ONE 'Apply Now' (our form) and a separate 'Apply on the employer's website' link (the tracked /go link, new tab, noopener, nofollow)",
              len(re.findall(r'>\s*Apply Now', page)) == 1 and hrefs == [path] and all(x in go_tag for x in ('target="_blank"', 'noopener', 'nofollow')) and "Apply on the employer's website" in text(page), (hrefs, go_tag[:80]))

        # ---- OUR application form
        email = 'zz.test.applicant+%d@example.com' % stamp
        form = {'name': 'ZZ Test Applicant', 'email': email, 'phone': '+91 98765 43210', 'note': 'Test <b>note</b>\nsecond line', 'consent': '1'}      # a phone sent anyway is ignored
        resume = {'resume': ('ZZ Test Resume.pdf', TEST_PDF)}
        v = Visitor(signed_in=True)
        status, fpage, _ = v.open(path)
        check("our application form opens: name, email, resume (optional), message, consent - NO phone field - CSRF, file upload, link to the employer's website, no site name",
              status == 200 and job['title'] in text(fpage) and all(n in fpage for n in ('name="name"', 'name="email"', 'name="resume"', 'name="consent"', 'name="csrf_token"', 'multipart/form-data'))
              and 'name="phone"' not in fpage
              and re.search(r'name="(phone|resume)"[^>]*required', fpage) is None and '/jobs/ext/%d/go' % jid in fpage and not PLATFORM.search(text(fpage)), job['title'])
        n_hr1, n_app1 = applicants_count(), apps_count()
        status, _b, _l = v.post_form(path, form, resume, csrf=False)
        check('a post WITHOUT the CSRF token is refused and nothing is saved', status in (400, 403) and applicants_count() == n_hr1 and not apps(email=email), status)
        status, p2, _ = v.post_form(path, {})
        check('empty form: errors for name, email and consent only (phone and resume are optional), nothing saved, no confirmation',
              status == 400 and 'Please enter the full name' in text(p2) and 'valid email' in text(p2) and 'agree' in text(p2) and 'valid phone' not in text(p2) and applicants_count() == n_hr1, status)
        status, p2, _ = v.post_form(path, dict(form, email='not-an-email', phone='abc'), resume)
        check('bad email: a field error (a phone sent anyway is not checked - the form has none), the typed name is kept, nothing saved', status == 400 and 'valid email' in text(p2)
              and 'valid phone' not in text(p2) and 'value="ZZ Test Applicant"' in p2 and applicants_count() == n_hr1)
        status, p2, _ = v.post_form(path, form, {'resume': ('virus.pdf', b'MZ\x90\x00 not a pdf at all')})
        check('a program renamed to .pdf is rejected, nothing saved', status == 400 and 'does not look like a real PDF' in text(p2) and applicants_count() == n_hr1)
        status, p2, _ = v.post_form(path, form, {'resume': ('cv.exe', TEST_PDF)})
        check('an .exe is rejected, nothing saved', status == 400 and 'PDF, DOC or DOCX' in text(p2) and applicants_count() == n_hr1)
        status, p2, _ = v.post_form(path, form, {'resume': ('big.pdf', TEST_PDF + b'0' * (5 * 1024 * 1024))})
        check('a resume above 5 MB is rejected, nothing saved', status == 400 and 'larger than 5 MB' in text(p2) and applicants_count() == n_hr1)
        status, _b, loc = v.post_form(path, dict(form, company_website='http://spam.example'), resume)
        check('the hidden bot field makes the post a silent no-op', status == 303 and loc.endswith('/jobs') and applicants_count() == n_hr1 and not apps(email=email))
        no_phone = 'zz.nophone+%d@example.com' % stamp
        status, _b, loc = v.post_form(path, {'name': 'ZZ Test Minimal', 'email': no_phone, 'consent': '1'}, {})
        rec = (apps(email=no_phone) or [{}])[0]
        check('an application with only name + email + consent is saved (phone and resume are optional) and the visitor is sent to the confirmation only after saving',
              status == 303 and rec.get('state') == 'submitted' and not rec.get('phone') and re.match(r'.*/jobs/ext/%d/applied\?ref=%d&t=[0-9a-f]{32}$' % (jid, rec.get('id', 0)), loc) is not None, loc)
        if rec.get('applicant_id'):
            created_applicants.append(rec['applicant_id'][0])

        # ---- the full application: name, email, phone, message and a resume
        v2 = Visitor(signed_in=True)
        status, _b, loc = v2.post_form(path, form, resume)
        recs = apps(email=email)
        check('the full application is accepted and the visitor is redirected to the confirmation only after it was saved', status == 303 and len(recs) == 1 and recs[0]['state'] == 'submitted', loc)
        r1 = recs[0] if recs else {}
        applicant = gw.search('hr.applicant', [['id', '=', r1['applicant_id'][0]]], 1)[0] if r1.get('applicant_id') else {}
        created_applicants.append(applicant.get('id'))
        check('Odoo Recruitment has the applicant: name, email, no phone (the form has none), stage "New", active', (applicant.get('partner_name'), applicant.get('email_from'), applicant.get('partner_phone')) == ('ZZ Test Applicant', email, False)
              and applicant.get('active') and applicant['stage_id'][1] == 'New')
        position = gw.search('hr.job', [['id', '=', applicant['job_id'][0]]], 1)[0] if applicant.get('job_id') else {}
        check('... filed under the (unpublished) Odoo position created for THIS job, which points back to the listing', bool(position) and position['llmd_listing_id'][0] == jid and not position['website_published'] and job['title'][:20] in position['name'], position.get('name', '')[:60])
        atts = gw.search('ir.attachment', [['res_model', '=', 'hr.applicant'], ['res_id', '=', applicant.get('id', 0)]], 5)
        check('the resume is attached to the applicant, byte for byte', len(atts) == 1 and atts[0]['name'] == 'ZZ Test Resume.pdf' and base64.b64decode(atts[0]['datas']) == TEST_PDF)
        check('the Job Applications record has every field: applicant name, e-mail, (no phone), job title, company, external job ID, source, channel "Our website", status Received, application date, message, link to the applicant',
              (r1.get('applicant_name'), r1.get('email'), r1.get('phone'), r1.get('job_title'), r1.get('company'), r1.get('ext_id'), r1.get('source'), r1.get('channel'), r1.get('state'), r1.get('message'))
              == ('ZZ Test Applicant', email, False, job['title'], job['company'], job['ext_id'], job['source'], 'own', 'submitted', 'Test <b>note</b>\nsecond line') and bool(r1.get('application_date'))
              and r1['applicant_id'][0] == applicant.get('id') and r1['apply_url'] == job['apply_url'])
        note = applicant.get('applicant_notes') or ''
        check("the applicant's note has job, company, external ID, original link and the message (HTML-escaped)", all(x in html.unescape(note) for x in (job['title'], job['company'], job['ext_id'], job['apply_url'])) and '&lt;b&gt;note&lt;/b&gt;' in note and '<b>note</b>' not in note)
        status, cpage, _ = v2.open(loc)
        check('the confirmation says "received" with the reference and offers the employer\'s website separately (no site name)', status == 200 and 'Your application was received' in text(cpage) and '#%d' % r1.get('id', 0) in text(cpage)
              and "Go to the employer's website" in text(cpage) and not PLATFORM.search(text(cpage)))
        check('a confirmation link with a wrong token / another job / no token is a 404', v2.open(loc.split('&t=')[0] + '&t=' + '0' * 32)[0] == 404 and v2.open('/jobs/ext/%d/applied?ref=%d&t=%s' % (job2['id'], r1.get('id', 0), loc.rsplit('t=', 1)[1]))[0] == 404)
        status, _b, loc2 = v2.post_form(path, dict(form, email=email.upper()), {})
        check('applying again with the same e-mail (even in capitals) creates NO duplicate: no new applicant, no new record', status == 303 and 'again=1' in loc2 and len(apps(email=email)) == 1 and len(gw.search('hr.applicant', [['email_from', '=ilike', email]], 5)) == 1)
        v2.open('/jobs/ext/%d/go' % jid)
        check("clicking the employer link after applying is a click line and does not take the application back (status stays Received)", apps(id=r1.get('id', 0))[0]['state'] == 'submitted' and len(clicks(job_key=key_of(job))) == 1)
        v3 = Visitor(signed_in=True)
        status, _b, loc3 = v3.post_form('/jobs/ext/%d/apply' % job2['id'], form, {})
        r_other = [x for x in apps(email=email) if x['ext_id'] == job2['ext_id']]
        check('the same person can apply for a DIFFERENT job (own record, own applicant, own position)', status == 303 and len(r_other) == 1 and r_other[0]['applicant_id'] and r_other[0]['id'] != r1.get('id') and len(apps(email=email)) == 2)
        if r_other and r_other[0]['applicant_id']:
            created_applicants.append(r_other[0]['applicant_id'][0])
        shown = gw.search('llmd.job.application', [['applicant_name', 'ilike', 'zz test applicant'], ['channel', '=', 'own'], ['state', '=', 'submitted']], 5)
        check('both applications are in Recruitment > Job Applications (search by name + channel + status finds them)', len(shown) == 2)
        gw.call('delete_record', model='ir.config_parameter', res_id=pid_form)
        pid_form = None
        check('without the parameter (the default) the form is off again (404) and Apply Now is the tracked link to the employer', get(path)[0] == 404 and '/jobs/ext/%d/go' % jid in get('/jobs/ext/%d' % jid)[1])


        # ---- the click on the employer link
        for old in clicks(job_key=key_of(job)):
            rpc('llmd.job.click', 'unlink', [[old['id']]])                # the click made after applying (above) is not part of these counts
        n_app_c, n_hr_c = apps_count(), applicants_count()
        submitted_c = len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000))
        v = Visitor(signed_in=True)
        status, _b, loc = v.open('/jobs/ext/%d/go' % jid)
        cl = clicks(job_key=key_of(job))
        check("Apply Now: 303 redirect to the job's own application URL, the one stored in Odoo", status == 303 and loc == job['apply_url'], loc[:70])
        c = cl[0] if cl else {}
        check('the click is saved in Odoo before the visitor is sent on: job title, company, source, external job ID, apply URL, status "clicked", linked to the listing',
              len(cl) == 1 and (c['job_title'], c['company'], c['source'], c['ext_id'], c['apply_url'], c['status']) == (job['title'], job['company'], job['source'], job['ext_id'], job['apply_url'], 'clicked') and c['listing_id'][0] == jid, c and c['status'])
        age = time.time() - calendar.timegm(time.strptime(c['clicked_at'], '%Y-%m-%d %H:%M:%S')) if c else 9999
        check('the time stamp is the moment of the click', -5 < age < 120, '%.0f seconds ago' % age)
        mine = [a for a in apps(job_key=key_of(job)) if a['user_id'] and a['user_id'][0] == tester['id']]
        check('the click line names nobody (no name / e-mail, only the user ID for repeat clicks); the signed-in person is in Job Applications as "Redirected to External Site" - never submitted',
              bool(c) and not (c.get('applicant_name') or c.get('email')) and (c.get('user_id') or [0])[0] == tester['id'] and len(mine) == 1 and mine[0]['state'] == 'submitted'
              and mine[0]['channel'] == 'apply_now' and not mine[0]['application_date'] and not mine[0]['applicant_id'], [(a['state'], a['channel']) for a in mine])
        check('... a click creates no Recruitment applicant and no submitted application', applicants_count() == n_hr_c
              and len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000)) == submitted_c)
        v.open('/jobs/ext/%d/go' % jid)
        cl = sorted(clicks(job_key=key_of(job)), key=lambda x: x['id'])
        check('clicking again is saved as ANOTHER line (every click is saved), marked as a repeat click', len(cl) == 2 and not cl[0]['repeat'] and cl[1]['repeat'])
        Visitor(signed_in=True).open('/jobs/ext/%d/go' % jid)
        cl = sorted(clicks(job_key=key_of(job)), key=lambda x: x['id'])
        check('the same account in another browser: a third line, a repeat click of that account (two browsers = two random cookie ids)', len(cl) == 3 and cl[2]['repeat'] and len({x['visitor_key'] for x in cl}) == 2 and all(x['visitor_key'] for x in cl))
        check('... and still ONE Job Applications record for the person and the job (no duplicate)', len([a for a in apps(job_key=key_of(job)) if a['user_id'] and a['user_id'][0] == tester['id']]) == 1)
        bot = urllib.request.Request(gw.site_url() + '/jobs/ext/%d/go' % job2['id'], headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'})
        try:
            urllib.request.build_opener(_NoRedirect()).open(bot, timeout=30)
        except urllib.error.HTTPError as exc:
            bot_status, bot_loc = exc.code, exc.headers.get('Location', '')
        check('a crawler / link checker (not signed in) gets the login page and is NOT counted as a click', bot_status == 303 and '/web/login?redirect=' in bot_loc and not clicks(job_key=key_of(job2)))
        # ---- the tracked link of OUR OWN positions
        own = [j for j in gw.search('hr.job', [['website_published', '=', True]], 10) if j['apply_url']]
        if own:
            status, _b, loc6 = Visitor(signed_in=True).open('/jobs/position/%d/go' % own[0]['id'])
            oc = clicks(job_key='hr.job:%d' % own[0]['id'])
            if re.search(r'jooble\.org|adzuna\.|himalayas\.app', own[0]['apply_url']):          # direct links only: a job board page is replaced by our own Odoo form
                check('our own position whose saved link is a job board page: the tracked Apply Now link sends to OUR Odoo application form (303), ONE click line names that form (source "LLM Decode")',
                      status == 303 and '/jobs/apply/' in loc6 and 'himalayas' not in loc6 and len(oc) == 1 and oc[0]['status'] == 'clicked' and oc[0]['hr_job_id'][0] == own[0]['id']
                      and oc[0]['source'] == 'LLM Decode' and oc[0]['apply_url'].startswith('/jobs/apply/'), (status, loc6, [(c['apply_url'], c['source']) for c in oc]))
            else:
                check('our own position with an external apply URL: Apply Now goes through the tracked link too: 303 to its URL and ONE click line linked to the position (source "LLM Decode")',
                      status == 303 and loc6 == own[0]['apply_url'] and len(oc) == 1 and oc[0]['status'] == 'clicked' and oc[0]['hr_job_id'][0] == own[0]['id'] and oc[0]['source'] == 'LLM Decode' and oc[0]['apply_url'] == own[0]['apply_url'])
        # ---- Odoo's own form of our positions (stock website_hr_recruitment) is tracked as an application we received
        stock = [j for j in gw.search('hr.job', [['website_published', '=', True]], 10) if not j['apply_url']]
        if stock:
            v6 = Visitor()
            stock_mail = 'zz.stock+%d@example.com' % stamp
            status, body, _l = v6.post_form('/website/form/hr.applicant', {'partner_name': 'ZZ Stock Form', 'email_from': stock_mail, 'partner_phone': '+91 98765 43210', 'job_id': str(stock[0]['id'])}, {}, csrf_from='/web/login')                  # the token of this browser session (the stock form adds its own with JavaScript)
            sa = gw.search('hr.applicant', [['email_from', '=', stock_mail], ['active', 'in', [True, False]]], 3)
            tr = apps(email=stock_mail)
            created_applicants += [x['id'] for x in sa]
            check("Odoo's own application form of one of OUR positions still works: the applicant is saved by Odoo and a Job Applications record \"Received by us\" is linked to it and to the position",
                  len(sa) == 1 and len(tr) == 1 and tr[0]['state'] == 'submitted' and tr[0]['channel'] == 'own' and tr[0]['applicant_id'][0] == sa[0]['id'] and tr[0]['hr_job_id'][0] == stock[0]['id'] and tr[0]['job_key'] == 'hr.job:%d' % stock[0]['id'], (status, body[:80]))
            r0 = tr[0] if tr else {}
            check('the new application shows in Recruitment > Job Applications by itself, from what the person typed: name, e-mail (no phone), job title, company, external job ID, channel "Our website", status Received, date',
                  (r0.get('applicant_name'), r0.get('email'), r0.get('phone'), r0.get('job_title'), r0.get('ext_id'), r0.get('channel'), r0.get('state')) == ('ZZ Stock Form', stock_mail, False, stock[0]['name'], str(stock[0]['id']), 'own', 'submitted')
                  and bool(r0.get('application_date')) and r0.get('company') is not None)
            seen = gw.search('llmd.job.application', [['applicant_name', 'ilike', 'zz stock'], ['channel', '=', 'own'], ['state', '=', 'submitted']], 5)
            check('... and the list (search by name + channel + status, newest first) finds it', len(seen) == 1 and seen[0]['id'] == r0.get('id'))
            v7 = Visitor()
            status7, body7, _l7 = v7.post_form('/website/form/hr.applicant', {'partner_name': 'ZZ Stock Form', 'email_from': stock_mail.upper(), 'partner_phone': '+91 98765 43210', 'job_id': str(stock[0]['id'])}, {}, csrf_from='/web/login')
            sa2 = gw.search('hr.applicant', [['email_from', '=ilike', stock_mail], ['active', 'in', [True, False]]], 5)
            created_applicants += [x['id'] for x in sa2]
            check('the same person sending the form again (e-mail in capitals): Odoo keeps both applicants, the list still has ONE record for the person and the job (no duplicate)', status7 == 200 and len(sa2) == 2 and len(apps(email=stock_mail)) == 1, (status7, len(sa2)))
            rid = r0.get('id')
            rpc('llmd.job.application', 'action_confirm', [[rid]])
            st1 = apps(id=rid)[0]['state']
            rpc('llmd.job.application', 'action_withdraw', [[rid]])
            st2 = apps(id=rid)[0]['state']
            rpc('llmd.job.application', 'action_receive', [[rid]])
            check('status updates from the list / form buttons: Confirm -> Confirmed, Withdraw -> Withdrawn, Back to Received -> Received', (st1, st2, apps(id=rid)[0]['state']) == ('confirmed', 'withdrawn', 'submitted'))

        # ---- the JSON API: applicant data ONLY from an authorized provider integration
        ref = {'source': job2['source'], 'ext_id': job2['ext_id']}
        api_mail = 'zz.api+%d@example.com' % stamp
        body = {'action': 'applicant', 'job': ref, 'name': 'ZZ Api Person', 'email': api_mail, 'provider_ref': 'zz-ref-1'}
        n_app1, n_hr1 = apps_count(), applicants_count()
        check('API without a key: refused and nothing is stored - the old public actions "submit" and "report" and "confirm" too',
              all(jsonrpc(dict(body, action=a))['error'] == 'unauthorized' for a in ('applicant', 'confirm', 'submit', 'report')) and apps_count() == n_app1 and not apps(email=api_mail))
        key = 'zz-test-key-%d' % stamp
        pid = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.application_api_key', 'value': key})['id']
        check('API with a WRONG key: refused', jsonrpc(body, {'X-Api-Key': 'wrong'})['error'] == 'unauthorized' and not apps(email=api_mail))
        hdr = {'X-Api-Key': key}
        r = jsonrpc(dict(body, name='', email='bad'), hdr)
        check('API with the key: invalid data -> {ok: false, error: validation, fields: ...}, nothing saved (a consent flag is not asked: the provider answers for its applicants)',
              r['ok'] is False and r['error'] == 'validation' and {'name', 'email'} <= set(r['fields']) and 'consent' not in r['fields'], r.get('fields'))
        check('API with the key: an unknown job is refused, and so is an unknown action (the public "submit" does not exist any more)',
              jsonrpc(dict(body, job={'source': 'Nope', 'ext_id': '0'}), hdr)['error'] == 'job_not_found' and jsonrpc(dict(body, action='submit'), hdr)['error'] == 'unknown_action')
        r = jsonrpc(body, hdr)
        ar = apps(email=api_mail)
        check('API with the key: the applicant is saved exactly as the provider sent it - confirmed, channel "provider", name, e-mail, provider reference, job snapshot, date received; no phone is kept',
              r['ok'] and r['status'] == 'created' and len(ar) == 1 and (ar[0]['state'], ar[0]['channel'], ar[0]['applicant_name'], ar[0]['email'], ar[0]['provider_ref'], ar[0]['job_title'], ar[0]['ext_id'], ar[0]['apply_url'], ar[0]['confirmed_via'])
              == ('confirmed', 'provider', 'ZZ Api Person', api_mail, 'zz-ref-1', job2['title'], job2['ext_id'], job2['apply_url'], 'api') and not ar[0]['phone'] and ar[0]['application_date'], r)
        check('... it creates no Odoo applicant and no click line', bool(ar) and not ar[0]['applicant_id'] and applicants_count() == n_hr1 and not clicks(job_key=key_of(job2)))
        r = jsonrpc(dict(body, phone='+91 98765 43210', name='ZZ Api Person Two'), hdr)
        check('the same person and job again: the record is UPDATED with what is new, never duplicated', r['status'] == 'updated' and len(apps(email=api_mail)) == 1 and apps(email=api_mail)[0]['applicant_name'] == 'ZZ Api Person Two' and not apps(email=api_mail)[0]['phone'] and apps_count() == n_app1 + 1)

        # ---- the back office
        views = rpc('llmd.job.click', 'get_views', [[[False, 'list'], [False, 'form'], [False, 'search'], [False, 'pivot'], [False, 'graph']]])
        check('Odoo backend: Recruitment > Apply Clicks has list, form, search, pivot and graph views', all(k in views['views'] for k in ('list', 'form', 'search', 'pivot', 'graph')))
        menu = gw.search('ir.ui.menu', [['name', '=', 'Apply Clicks']], 3)
        check('Odoo backend: the menu "Apply Clicks" is under Recruitment (recruiters only)', len(menu) == 1 and menu[0]['parent_id'] and menu[0]['parent_id'][1].startswith('Recruitment'), menu and menu[0]['complete_name'])
        check('Odoo backend: searching by job title, company, source, external job ID, status and date finds the clicks',
              len(gw.search('llmd.job.click', [['job_title', 'ilike', job['title'][:10]], ['company', '=', job['company']], ['source', '=', job['source']], ['ext_id', '=', job['ext_id']], ['status', '=', 'clicked'],
                                                ['clicked_at', '>=', time.strftime('%Y-%m-%d', time.gmtime(stamp - 86400))]], 10)) >= 3)
        groups = rpc('llmd.job.click', 'read_group', [[['id', '>', click0]], ['status'], ['status']])
        check('Odoo backend: grouping the clicks by status works (pivot / graph)', 'clicked' in {g['status'] for g in groups} and sum(g['status_count'] for g in groups) >= 4, {g['status']: g['status_count'] for g in groups})
        views = rpc('llmd.job.application', 'get_views', [[[False, 'list'], [False, 'form'], [False, 'search'], [False, 'kanban'], [False, 'pivot'], [False, 'graph']]])
        check('Odoo backend: Recruitment > Job Applications (applicants sent by a provider or by Odoo\'s own form) has list, form, search, kanban, pivot and graph views', all(k in views['views'] for k in ('list', 'form', 'search', 'kanban', 'pivot', 'graph')))
        menu = gw.search('ir.ui.menu', [['name', '=', 'Job Applications']], 3)
        check('Odoo backend: the menu "Job Applications" is under Recruitment', len(menu) == 1 and menu[0]['parent_id'] and menu[0]['parent_id'][1].startswith('Recruitment'), menu and menu[0]['complete_name'])
        check('Odoo backend: searching Job Applications by applicant / e-mail, status, job and channel finds the provider applicant',
              len(gw.search('llmd.job.application', [['applicant_name', 'ilike', 'zz api'], ['state', '=', 'confirmed'], ['channel', '=', 'provider'], ['job_title', 'ilike', job2['title'][:10]]], 10)) == 1)
    finally:
        if pid:
            gw.call('delete_record', model='ir.config_parameter', res_id=pid)
        if pid_form:
            gw.call('delete_record', model='ir.config_parameter', res_id=pid_form)
        for c in gw.search('llmd.job.application', [['id', '>', app_id0], ['channel', '=', 'apply_now'], ['active', 'in', [True, False]]], 500):
            gw.call('delete_record', model='llmd.job.application', res_id=c['id'])          # the test account's Apply Now records of this run
        for aid in {x for x in created_applicants if x}:
            gw.call('delete_record', model='hr.applicant', res_id=aid)
        for c in gw.search('llmd.job.application', [['email', 'like', 'zz.'], ['active', 'in', [True, False]]], 100) + gw.search('llmd.job.application', [['applicant_name', 'like', 'ZZ '], ['active', 'in', [True, False]]], 100):
            try:
                gw.call('delete_record', model='llmd.job.application', res_id=c['id'])
            except Exception:
                pass
        for pos in gw.search('hr.job', [['llmd_listing_id', 'in', [jid, job2['id']]], ['active', 'in', [True, False]]], 10):
            gw.call('delete_record', model='hr.job', res_id=pos['id'])
        left = gw.search('hr.applicant', [['partner_name', 'like', 'ZZ '], ['active', 'in', [True, False]]], 5) + gw.search('llmd.job.application', [['applicant_name', 'like', 'ZZ ']], 5)
        check('cleanup: the test applicants, resumes, records and test positions are removed again', not left and applicants_count() == n_hr0 and apps_count() == n_app0 and len(gw.search('hr.job', [['llmd_listing_id', '!=', False], ['active', 'in', [True, False]]], 5000)) == n_pos0, '%d applicants (were %d), %d records (were %d)' % (applicants_count(), n_hr0, apps_count(), n_app0))


def category_checks():
    """N. The pages of one category, company, place or role: /jobs/category|company|location|role/<slug>, their filters (counted from the stored jobs), companies, pages, Apply Now."""
    print('\n=== N. category, company, location and role pages: counts, filters, companies, pages, Apply Now ===')
    rows = listings()
    by_id = {r['id']: r for r in rows}
    cats = [(slug, label) for slug, label, _d, _i in BC.JOB_CATEGORIES]
    in_cat = {slug: [r for r in rows if r['job_category'] == slug] for slug, _l in cats}

    def all_pages(base):
        seen, p = set(), 1
        while p < 300:                                                  # past the last page Odoo shows the last page again: stop when nothing new comes
            ids = {c['id'] for c in cards(get('%s%s' % (base, '' if p == 1 else '/page/%d' % p))[1])}
            if not ids - seen:
                break
            seen |= ids
            p += 1
        return seen, p - 1

    check('every visible job is in exactly one category (none left out)', rows and all(r['job_category'] in dict(cats) for r in rows), [r['title'] for r in rows if r['job_category'] not in dict(cats)][:5])
    for slug, label in cats:
        want = {r['id'] for r in in_cat[slug]}
        if not want:
            continue
        status, pg = get('/jobs/category/%s' % slug)
        seen, pages = all_pages('/jobs/category/%s' % slug)
        check('/jobs/category/%-20s %3d jobs = database; every result page together = exactly the jobs of this category' % (slug, len(want)),
              status == 200 and count_of(pg) == len(want) and seen == want and label in html.unescape(pg) and 'Categories' in text(pg), '%d pages' % pages)
    status, _b, loc = Visitor().open('/jobs/category/engineering?mode=onsite')
    check('an old category link (/jobs/category/engineering) moves permanently to its new page and keeps the filters', status == 301 and loc.endswith('/jobs/category/it-software?mode=onsite'), (status, loc))
    check('an unknown category is a 404, bad filter values do not break a category page', get('/jobs/category/nope')[0] == 404
          and get('/jobs/category/sales?exp_min=abc&exp_max=-4&posted=99&jtype=freelance&function=zz&role=%3Cx%3E')[0] == 200)

    slug = max(in_cat, key=lambda s: len(in_cat[s]))
    rows_c = in_cat[slug]
    base = '/jobs/category/%s' % slug
    pg = get(base)[1]
    strip = [(html.unescape(n), int(c)) for n, c in re.findall(r'<span class="o_llmd_co_name">(.*?)</span>\s*<span class="o_llmd_n">(\d+)</span>', pg)]
    want = sorted(Counter(r['company'] for r in rows_c if r['company']).items(), key=lambda kv: (-kv[1], kv[0].lower()))
    check('%s: "Companies hiring" shows only companies with jobs in this category (the 14 biggest), with their counts; the Company filter lists all of them' % slug,
          strip == want[:14] and sorted((v, n) for v, _l, n, _c in facet(pg, 'company')) == sorted(want), '%d companies' % len(want))
    href = links(pg, 'o_llmd_co_chip')[0][0]
    pg2 = get(href)[1]
    cs = cards(pg2)
    check('clicking a company narrows the category to that company (the category stays)', href.startswith(base + '?company=') and count_of(pg2) == want[0][1] and cs
          and all(by_id[c['id']]['company'] == want[0][0] and by_id[c['id']]['job_category'] == slug for c in cs), '%s -> %s' % (href, count_of(pg2)))
    check('... clicking it again takes the company off (the chip is a toggle)', re.search(r'class="o_llmd_co_chip active"', pg2) and any(h == base for h, _t in links(pg2, 'o_llmd_co_chip')))
    pg_m = get(base + '?mode=onsite')[1]
    check('... and a company chip keeps the other filters too', all('mode=onsite' in h for h, _t in links(pg_m, 'o_llmd_co_chip')))
    text_pg = text(pg)
    check('%s: filters Location (country, city), Experience 0-25+ slider, Work mode, Job Type, Time Posted, Department, Role, Skills, Company and Region; no Category list (the page IS one category); no course control; no Salary, no Freelance' % slug,
          all(x in pg for x in ('name="region"', 'name="country"', 'name="city"', 'name="exp_min"', 'name="exp_max"', 'name="mode"', 'name="jtype"', 'name="posted"', 'name="function"', 'name="role"', 'name="skill"', 'name="company"'))
          and 'name="course"' not in pg and 'name="category"' not in pg and 'name="salary"' not in pg and 'Freelance' not in text_pg and 'Industry' not in text_pg)
    jt = facet(pg, 'jtype')
    check('%s: the Job Type counts are the real numbers of this category' % slug, [(v, n) for v, _l, n, _c in jt] == [(k, len([r for r in rows_c if r['job_type'] == k])) for k in TYPE_LABELS], jt)
    form = re.search(r'<form[^>]*id="o_llmd_board_form"[^>]*>', pg).group(0)
    check('%s: the filter form stays on the category page and tells the live count which category it is' % slug, 'action="%s"' % base in form and 'data-scope="category"' in form and 'data-scope-value="%s"' % slug in form)

    top_role = Counter(c for r in rows_c for c in (r['roles'] or '').strip(',').split(',') if c).most_common(1)
    top_skill = Counter(k for r in rows_c for k in (r['skill_keys'] or '').strip(',').split(',') if k).most_common(1)
    top_fn = Counter(r['job_function'] for r in rows_c if r['job_function']).most_common(1)
    top_city = Counter(r['city'] for r in rows_c if r['city']).most_common(2)
    combos = [{'jtype': ['fulltime'], 'mode': 'onsite'}, {'city': [c for c, _n in top_city], 'exp_min': 3, 'exp_max': 8}, {'exp_min': 10}, {'posted': '7'},
              {'country': 'India', 'jtype': ['fulltime', 'contract'], 'exp_max': 6}, {'q': 'manager'}, {'location': 'Bengaluru', 'region': 'south-india'}, {'region': 'north-india', 'mode': 'onsite'}]
    combos += [{'role': [top_role[0][0]]}] if top_role else []
    combos += [{'skill': [top_skill[0][0]], 'mode': 'remote'}] if top_skill else []
    combos += [{'function': [top_fn[0][0]], 'jtype': ['fulltime']}] if top_fn else []
    for f in combos:
        query = urllib.parse.urlencode(f, doseq=True)
        st, pg = get(base + '?' + query)
        expect = [r for r in rows_c if matches(r, f)]
        cs = cards(pg)
        live = json.loads(get('/jobs/results-count?scope=category&scope_value=%s&%s' % (slug, query))[1])['count']
        check('%s + %s: count = database = live count; every card in the category and matching' % (slug, query), st == 200 and count_of(pg) == len(expect) == live
              and all(c['id'] in {r['id'] for r in expect} for c in cs), '%d jobs' % len(expect))

    f = {'jtype': ['fulltime']}
    pg = get(base + '?' + urllib.parse.urlencode(f, doseq=True))[1]
    n_full = len([r for r in rows_c if matches(r, f)])
    if n_full > 12:
        nxt = re.search(r'href="(%s/page/2\?[^"]*)"' % re.escape(base), pg)
        p2 = cards(get(html.unescape(nxt.group(1)))[1]) if nxt else []
        check('%s pagination keeps the filters (page 2 of Full-time: other jobs, all Full-time, same category)' % slug, nxt and 'jtype=fulltime' in nxt.group(1) and p2
              and not {c['id'] for c in p2} & {c['id'] for c in cards(pg)} and all(by_id[c['id']]['job_type'] == 'fulltime' and by_id[c['id']]['job_category'] == slug for c in p2))
    pg = get(base + '?sort=newest')[1]
    posted = [by_id[c['id']]['posted'] for c in cards(pg)]
    check('%s: Sort "Most recent" + the sort links keep the filters' % slug, posted == sorted(posted, reverse=True) and re.search(r'href="%s\?[^"]*jtype=fulltime[^"]*sort=newest' % re.escape(base),
                                                                                                                        html.unescape(get(base + '?jtype=fulltime')[1])))
    chip = re.search(r'<a class="o_llmd_fchip" href="([^"]+)" aria-label="Remove filter: Full-time"', get(base + '?jtype=fulltime&mode=onsite')[1])
    check('%s: a chip removes only its own filter; "Clear all filters" goes back to the category' % slug, chip and 'jtype' not in html.unescape(chip.group(1)) and 'mode=onsite' in html.unescape(chip.group(1))
          and [h for h, _t in links(get(base + '?jtype=fulltime')[1], 'o_llmd_clear')] == [base])

    pg = get(base)[1]
    applies = re.findall(r'<a\b(?=[^>]*\bo_llmd_card_apply\b)(?=[^>]*target="_blank")(?=[^>]*rel="noopener noreferrer nofollow")[^>]*href="([^"]+)"', pg)
    cs = cards(pg)
    with_link = [c for c in cs if by_id[c['id']]['apply_url']]
    check('category results: every card with a link has Apply Now = the tracked link of that job (new tab, noopener), as on the detail page', applies and applies == ['/jobs/ext/%d/go' % c['id'] for c in with_link], applies[:2])
    job = by_id[with_link[0]['id']]
    before = len(gw.search('llmd.job.click', [['listing_id', '=', job['id']]], 1000))
    n_submitted = len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000))
    anon_status, _b, anon_location = Visitor().open('/jobs/ext/%d/go' % job['id'])
    check('Apply Now from a card, not signed in: the login page, back to the same Apply Now afterwards', anon_status == 303 and anon_location.endswith('/web/login?redirect=%%2Fjobs%%2Fext%%2F%d%%2Fgo' % job['id']), anon_location[:80])
    status, _b, location = Visitor(signed_in=True).open('/jobs/ext/%d/go' % job['id'])
    after = gw.search('llmd.job.click', [['listing_id', '=', job['id']]], 1000)
    newest = max(after, key=lambda c: c['id']) if after else {}
    check('Apply Now from a card, signed in: the click is saved (source, external ID, original URL kept), the visitor goes to the original application page, and NO submitted application is created',
          status == 303 and location == job['apply_url'] and len(after) == before + 1 and newest.get('ext_id') == job['ext_id'] and newest.get('source') == job['source']
          and newest.get('apply_url') == job['apply_url'] and newest.get('status') == 'clicked'
          and len(gw.search('llmd.job.application', [['state', 'in', ['submitted', 'confirmed']], ['channel', '!=', 'apply_now'], ['active', 'in', [True, False]]], 5000)) == n_submitted,
          '%s -> %s' % (job['ext_id'], location[:60]))

    # ---- company pages
    co_n = Counter(r['company'] for r in rows if r['company'])
    for name, n in sorted(co_n.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:3]:
        base = '/jobs/company/%s' % BC.slugify(name)
        status, pg = get(base)
        seen, _p = all_pages(base)
        check('%-46s %3d jobs = database, heading "Jobs at ...", breadcrumb Companies, no company strip' % (base, n), status == 200 and count_of(pg) == n and seen == {r['id'] for r in rows if r['company'] == name}
              and 'Jobs at %s' % name in html.unescape(pg) and 'class="o_llmd_co_strip"' not in pg and 'name="company"' not in pg)
        f = {'mode': 'onsite'}
        live = json.loads(get('/jobs/results-count?scope=company&scope_value=%s&mode=onsite' % urllib.parse.quote(name))[1])['count']
        check('  ... + On-site: count = database = live count', count_of(get(base + '?mode=onsite')[1]) == len([r for r in rows if r['company'] == name and matches(r, f)]) == live)
    check('an unknown company is a 404', get('/jobs/company/zz-no-such-company')[0] == 404)

    # ---- location pages
    NCR = ('Delhi', 'Gurugram', 'Noida', 'Faridabad', 'Ghaziabad')
    city_n = Counter(r['city'] for r in rows if r['city'])
    top_city = city_n.most_common(1)[0][0]
    for slug, pred, label in (('delhi-ncr', lambda r: r['city'] in NCR, 'Jobs in Delhi NCR'), ('remote', lambda r: r['work_mode'] == 'remote', 'Remote jobs'),
                              ('india', lambda r: r['country'] == 'India', 'Jobs in India'), (BC.slugify(top_city), lambda r: r['city'] == top_city, 'Jobs in %s' % top_city)):
        base = '/jobs/location/%s' % slug
        status, pg = get(base)
        want = [r for r in rows if pred(r)]
        live = json.loads(get('/jobs/results-count?scope=location&scope_value=%s&jtype=fulltime' % slug)[1])['count']
        check('%-30s %3d jobs = database, heading "%s"; + Full-time: page = database = live count' % (base, len(want), label), status == 200 and count_of(pg) == len(want) and label in html.unescape(pg)
              and count_of(get(base + '?jtype=fulltime')[1]) == len([r for r in want if r['job_type'] == 'fulltime']) == live)
    pg = get('/jobs/location/delhi-ncr')[1]
    check('the Delhi NCR page lists its cities in the City filter (and nothing outside the region)', {v for v, _l, _n, _c in facet(pg, 'city')} <= set(NCR) and facet(pg, 'city'))
    check('an unknown place is a 404', get('/jobs/location/atlantis')[0] == 404)

    # ---- region pages
    region_n = Counter(r['region'] for r in rows if r['region'])
    zone_n = Counter(r['india_zone'] for r in rows if r['india_zone'])
    for slug, n in [(sl, region_n[sl]) for sl, _n, _t, _i in JF.REGIONS if region_n[sl]] + [(sl, zone_n[sl]) for sl, _n, _t, _i in JF.INDIA_ZONES if zone_n[sl]]:
        base = '/jobs/region/%s' % slug
        st, pg = get(base)
        on = len([r for r in rows if in_region(r, slug) and r['work_mode'] == 'onsite'])
        live = json.loads(get('/jobs/results-count?scope=region&scope_value=%s&mode=onsite' % slug)[1])['count']
        check('%-34s %4d jobs = database, heading, breadcrumb Regions; + On-site: page = database = live count' % (base, n), st == 200 and count_of(pg) == n
              and JF.REGION_LABELS[slug] in html.unescape(pg) and 'Regions' in text((re.search(r'<nav class="o_llmd_crumbs".*?</nav>', pg, re.S) or [''])[0])
              and count_of(get(base + '?mode=onsite')[1]) == on == live and 'name="region"' not in pg)
    walk = min([sl for sl, n in zone_n.items() if n > 24] or list(zone_n), key=zone_n.get)
    seen, pages = all_pages('/jobs/region/%s' % walk)
    check('/jobs/region/%s: every result page together = exactly the jobs of that region, each once' % walk, seen == {r['id'] for r in rows if r['india_zone'] == walk}, '%d pages' % pages)
    empty = next((sl for sl, _n, _t, _i in JF.REGIONS if not region_n[sl]), None)
    if empty:
        st, pg = get('/jobs/region/%s' % empty)
        check('a region without jobs (%s) is not in the region directory, and its page answers honestly with 0 jobs' % empty, st == 200 and count_of(pg) == 0
              and 'No jobs match these filters.' in text(pg) and '/jobs/region/%s"' % empty not in get('/jobs/regions')[1])
    check('an unknown region is a 404', get('/jobs/region/atlantis')[0] == 404)

    # ---- role pages
    role_n = Counter(c for r in rows for c in (r['roles'] or '').strip(',').split(',') if c in BC.ROLE_LABELS)
    code, n = role_n.most_common(1)[0]
    base = '/jobs/role/%s' % code.replace('_', '-')
    pg = get(base)[1]
    check('%s: %d jobs = database, heading "%s jobs", no Role list (the page IS one role)' % (base, n, BC.ROLE_LABELS[code]), count_of(pg) == n and '%s jobs' % BC.ROLE_LABELS[code] in html.unescape(pg)
          and 'name="role"' not in pg)
    check('an unknown role is a 404', get('/jobs/role/zz-nope')[0] == 404)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'test'
    if mode == 'fetch':
        print('reading every connected source (about a minute) ...')
        print(gw.call('call_method', model='llmd.job.listing', ids=None, method='fetch_now'))
        return
    purge_dataset()                                                               # leftovers of an earlier run that was interrupted
    made = make_dataset(int(time.time()))
    print('%d temporary test jobs created (remote / hybrid / on-site for every job role); they are deleted at the end' % len(made))
    try:
        run_all()
    finally:
        removed = purge_dataset()
        check('cleanup: the %d temporary test jobs are removed again' % removed, removed >= len(made) and not gw.search('llmd.job.listing', [['ext_id', 'like', 'zzds-'], ['active', 'in', [True, False]]], 3))
    print('\nRESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))


def run_all():
    click0 = max([0] + [c['id'] for c in gw.search('llmd.job.click', [], 20000)])                # the clicks of this run are removed again at the end
    rows = listings()
    by_id = {r['id']: r for r in rows}

    print('\n=== A. job sources: honest status ===')
    srcs = gw.search('llmd.job.source', [], 20)
    names = [s['name'] for s in srcs]
    check('the sources are Adzuna, JSearch, the company job boards (no key), Jooble, Indeed, Naukri.com and - as the temporary keyless fallback - Himalayas', names == ['Adzuna', 'JSearch', 'Company job boards', 'Jooble', 'Indeed', 'Naukri.com', 'Himalayas'], names)
    for s in srcs:
        check('%s is only "Working" when it really returned jobs (status: %s, jobs: %s)' % (s['name'], s['last_status'], s['last_count']), s['last_status'] != 'ok' or s['last_count'] > 0, (s['last_message'] or '')[:70])
    st = {s['name']: s for s in srcs}
    off = [n for n in ('Adzuna', 'Jooble', 'Himalayas') if st[n]['last_status'] == 'skipped' and (st[n]['last_message'] or '').startswith('Off')]
    check('direct links only (default): Adzuna, Jooble and Himalayas - their Apply Now opens their own page first - are switched off ("Off") and not asked',
          off == ['Adzuna', 'Jooble', 'Himalayas'], [(n, st[n]['last_status']) for n in ('Adzuna', 'Jooble', 'Himalayas')])
    keyed = [n for n in ('Adzuna', 'JSearch', 'Company job boards', 'Jooble') if st[n]['last_status'] == 'ok']
    check('Himalayas is only the fallback: it is read while no keyed source delivers enough jobs, otherwise it says "Not needed"',
          (st['Himalayas']['last_status'] == 'ok' and st['Himalayas']['last_count'] > 0) if not keyed else st['Himalayas']['last_status'] in ('skipped', 'ok'),
          (st['Himalayas']['last_status'], st['Himalayas']['last_count'], 'keyed sources working: %s' % keyed))

    print('\n=== B. normalized data ===')
    check('jobs are on the board (the temporary test jobs, plus the real ones once a source is connected)', len(rows) >= 60, '%d active listings' % len(rows))
    check('every job has source, source job id, title', all(r['source'] and r['ext_id'] and r['title'] for r in rows))
    check('(source, source job id) is unique', len({(r['source'], r['ext_id']) for r in rows}) == len(rows))
    check('no duplicate jobs (same title + company + place)', len({r['dedupe_key'] for r in rows}) == len(rows))
    check('every application URL is a valid http(s) link or empty', all((not r['apply_url']) or re.match(r'https?://[^\s]+\.[^\s]+$', r['apply_url']) for r in rows))
    check('no two jobs share an application URL', len({r['apply_url'] for r in rows if r['apply_url']}) == len([r for r in rows if r['apply_url']]))
    check('short description present on nearly every job', sum(1 for r in rows if r['short_description']) >= 0.9 * len(rows), '%d/%d' % (sum(1 for r in rows if r['short_description']), len(rows)))
    check('every job fits a course role, a course track or one of the job categories', all((r['roles'] or r['tags'] or r['job_category']) for r in rows))
    check('every stored job that has a location has a work mode (remote / hybrid / on-site) and an India flag', all(r['work_mode'] in MODE_LABELS for r in rows if r['location']) and all(r['work_mode'] in ('', *MODE_LABELS) for r in rows),
          {m: len([r for r in rows if r['work_mode'] == m]) for m in ('remote', 'hybrid', 'onsite')})
    check('the board holds Remote, Hybrid AND On-site jobs - not only remote ones', all(len([r for r in rows if r['work_mode'] == m]) >= 1 for m in MODE_LABELS), {m: len([r for r in rows if r['work_mode'] == m]) for m in MODE_LABELS})
    check('Indian jobs are among them', len([r for r in rows if r['india']]) >= 10, len([r for r in rows if r['india']]))
    abroad = Counter(r['country'] for r in rows if not r['india'] and r['country'])
    check('... and jobs outside India, in several countries (a worldwide board, not India only)', len(abroad) >= 3 and sum(abroad.values()) >= 50, abroad.most_common(5))
    check('Indian and international companies (by verified headquarters)', len({r['company'] for r in rows if r['company_hq'] == 'India'}) >= 3
          and len({r['company'] for r in rows if r['company_hq'] and r['company_hq'] != 'India'}) >= 3)
    check('the original application URL of every job is stored', all(r['apply_url'] for r in rows), sum(1 for r in rows if not r['apply_url']))
    board_links = [r['id'] for r in rows if re.search(r'jooble\.org|adzuna\.|himalayas\.app', r['apply_url'] or '')]
    check('no visible job opens a job board page first (Jooble / Adzuna / Himalayas): Apply Now goes straight to the employer', not board_links, board_links[:5])

    print('\n=== C. the landing page /jobs: hero search, popular searches, categories, course matches, companies, latest jobs, locations, why + FAQ ===')
    status, page = get('/jobs')
    t = text(page)
    n_companies = len({r['company'] for r in rows if r['company']})
    hero = re.search(r'<form action="/jobs" method="get" class="o_llmd_bigsearch".*?</form>', page, re.S)
    check('landing: heading "Turn your learning into real opportunities", the real numbers of jobs and companies, ONE search (keyword + city/country -> /jobs, "Search Jobs")',
          status == 200 and 'Turn your learning into real opportunities' in t and 'Search %d open jobs from %d companies' % (len(rows), n_companies) in t
          and bool(hero) and 'name="q"' in hero.group(0) and 'name="location"' in hero.group(0) and 'Search Jobs' in text(hero.group(0)), '%d jobs, %d companies' % (len(rows), n_companies))
    status, pg = get('/jobs?q=&location=')
    check('an empty search is not the landing page again: it shows all jobs', status == 200 and count_of(pg) == len(rows), count_of(pg))
    role_n = Counter(c for r in rows for c in (r['roles'] or '').strip(',').split(',') if c in BC.ROLE_LABELS)
    pops = [(h, int(re.search(r'o_llmd_n">(\d+)<', inner).group(1))) for h, inner in links(page, 'o_llmd_pop')]
    ranked = [n for _c, n in role_n.most_common()]
    check('popular searches: the roles with the most jobs (real counts), each a /jobs/role/<role> page',
          len(pops) == min(6, len(role_n)) and [n for _h, n in pops] == ranked[:len(pops)] and all(role_n[h.rsplit('/', 1)[-1].replace('-', '_')] == n for h, n in pops), pops)
    check('... a popular search opens its role page with the same number of jobs', bool(pops) and count_of(get(pops[0][0])[1]) == pops[0][1], pops[:1])
    in_cat = Counter(r['job_category'] for r in rows if r['job_category'])
    shown = [(h.rsplit('/', 1)[-1], int(re.search(r'(\d+) open jobs?', text(inner)).group(1))) for h, inner in links(page, 'o_llmd_catcard')]
    all_cats = sorted([(sl, in_cat[sl]) for sl, _l, _d, _i in BC.JOB_CATEGORIES if in_cat[sl]], key=lambda c: -c[1])
    check('"Explore by job category": the 8 categories with the most jobs, real counts, each a /jobs/category/<slug> page; "Explore all %d categories"' % len(all_cats),
          shown == all_cats[:8] and 'href="/jobs/categories"' in page and 'Explore all %d categories' % len(all_cats) in t, shown)
    status, dpg = get('/jobs/categories')
    dshown = [(h.rsplit('/', 1)[-1], int(re.search(r'(\d+) open jobs?', text(inner)).group(1))) for h, inner in links(dpg, 'o_llmd_catcard')]
    co_in_cat = Counter(c for c, _co in {(r['job_category'], r['company']) for r in rows if r['job_category'] and r['company']})
    check('/jobs/categories: EVERY category that has jobs (no empty one), most jobs first, with its jobs and companies, searchable', status == 200 and dshown == all_cats
          and all('%d %s' % (co_in_cat[sl], 'company' if co_in_cat[sl] == 1 else 'companies') in text(inner) for (h, inner), (sl, _n) in zip(links(dpg, 'o_llmd_catcard'), dshown))
          and 'o_llmd_dir_filter' in dpg, '%d categories' % len(dshown))
    bad = [(sl, n) for sl, n in dshown[-3:] if count_of(get('/jobs/category/%s' % sl)[1]) != n]
    check('... a category of the directory opens its results page with the same number of jobs', not bad, bad)

    catalog = gw.call('call_method', model='llmd.course.catalog', ids=None, method='courses')
    pills = re.findall(r'<button\b[^>]*name="rec"[^>]*value="([^"]+)"[^>]*>.*?<span class="o_llmd_cpill_name">(.*?)</span><span class="o_llmd_n">(\d+)</span>', page, re.S)
    in_course = {c['code']: [r for r in rows if ',%s,' % c['code'] in (r['courses'] or '')] for c in catalog}
    check('"Learn with LLM Decode, Discover Your Career Opportunities": one button per course of the catalog (same names, same order), each with its real number of matching jobs',
          [(v, html.unescape(n)) for v, n, _c in pills] == [(c['code'], c['name']) for c in catalog] and all(int(n) == len(in_course[v]) for v, _n, n in pills), [(v, n) for v, _x, n in pills])
    check('(this database has no eLearning module, so the catalog is the built-in fallback = the four LLM Decode courses, with the words each course teaches from its own page)',
          [c['name'] for c in catalog] == list(COURSES.values()) and not any(c['dynamic'] for c in catalog) and all(c.get('terms') for c in catalog), [(c['code'], len(c.get('terms') or [])) for c in catalog])

    def course_block(pg, code):
        """(cards, 'View all' href, its number, the 'Matches your course' labels of every card) of the course-matched block."""
        block = (re.search(r'<div class="o_llmd_cm" data-course="%s">.*' % re.escape(code), pg, re.S) or [''])[0]
        block = block.split('id="latest"', 1)[0]
        view = re.search(r'href="(/jobs/course/[^"]+)"[^>]*>View all (\d+) course-matched jobs', block)
        matched = [[x.strip() for x in html.unescape(m).split(',')] for m in re.findall(r'Matches your course: ([^<]*)</p>', block)]
        return cards(block), (html.unescape(view.group(1)) if view else ''), (int(view.group(2)) if view else None), matched

    def overlap(r, course):
        return len(set(course['terms']) & set((r.get('term_keys') or '').strip(',').split(',')))
    for course in catalog:
        code = course['code']
        status, pg = get('/jobs/course-matches?course=%s' % code)
        cs, view, n, matched = course_block(pg, code)
        want = in_course[code]
        best = max([overlap(r, course) for r in want] or [0])
        ov = [overlap(by_id[c['id']], course) for c in cs if c['id'] in by_id]
        labels = {BC.COURSE_TERM_LABELS[k] for k in course['terms']}
        check('%-40s %d matching jobs: up to 6 shown, the closest to what the course teaches first, "View all %d" = the results page' % (course['name'][:40], len(want), len(want)),
              status == 200 and n == len(want) and view == '/jobs/course/%s' % code and len(cs) == min(6, len(want)) and all(c['id'] in {r['id'] for r in want} for c in cs)
              and ov == sorted(ov, reverse=True) and (not ov or ov[0] == best) and all(set(m) <= labels for m in matched) and count_of(get(view)[1]) == len(want), (ov, n))
    check('an unknown course for the course-matched block is a 404', get('/jobs/course-matches?course=nope')[0] == 404)
    cs, view, n, _m = course_block(page, catalog[0]['code'])
    check('the landing page opens with the first course selected and its matched jobs in place', bool(cs) and n == len(in_course[catalog[0]['code']]) and re.search(r'aria-selected="true"[^>]*data-course="%s"' % catalog[0]['code'], page))
    pg = get('/jobs?rec=%s' % catalog[2]['code'])[1]
    check('without JavaScript the course buttons reload the page with that course (?rec=...) - the same block', re.search(r'aria-selected="true"[^>]*data-course="%s"' % catalog[2]['code'], pg)
          and course_block(pg, catalog[2]['code'])[2] == len(in_course[catalog[2]['code']]))

    co_n = Counter(r['company'] for r in rows if r['company'])
    hq_of = {r['company']: (r['company_region'] or 'not-verified') for r in rows if r['company']}
    want_tabs = [sl for sl, _n, _t, _i in JF.REGIONS if sl in hq_of.values()] + (['not-verified'] if 'not-verified' in hq_of.values() else [])
    tabs = re.findall(r'<a\b[^>]*class="o_llmd_hq_tab[^"]*"[^>]*data-tab="([^"]+)"', page)
    check('"Companies by region": one tab per headquarters region that has companies (and "Headquarters not verified" for the others), in order', tabs == want_tabs, tabs)
    bad = []
    for sl in want_tabs:
        seg = page.split('id="hq-%s"' % sl, 1)[1].split('id="hq-', 1)[0].split('id="countries"', 1)[0]
        got = [(html.unescape(re.search(r'<strong>(.*?)</strong>', inner).group(1)), int(re.search(r'(\d+) open jobs?', text(inner)).group(1))) for _h, inner in links(seg, 'o_llmd_cocard')]
        want = sorted([(c, n) for c, n in co_n.items() if hq_of[c] == sl], key=lambda kv: (-kv[1], kv[0].lower()))
        if got != want:
            bad.append((sl, got[:3], want[:3]))
    check('... each region lists ALL its companies (the biggest 12 first, the rest behind "Show all"), each with its real number of jobs', not bad, bad[:2])
    check('... Indian and foreign companies side by side, and the headquarters are not where the jobs are (an American company hiring in India stays under North America)',
          'india-south-asia' in want_tabs and len(want_tabs) >= 3 and any(hq_of.get(r['company']) == 'north-america' and r['india'] for r in rows))
    first = links(page.split('id="hq-%s"' % want_tabs[0], 1)[1], 'o_llmd_cocard')[0][0]
    name = next(c for c in co_n if '/jobs/company/%s' % BC.slugify(c) == first)
    pg = get(first)[1]
    cs = cards(pg)
    check('... a company card opens the results of that company only (same count, India and abroad)', bool(cs) and count_of(pg) == co_n[name] and all(by_id[c['id']]['company'] == name for c in cs if c['id'] in by_id)
          and 'Jobs at %s' % name in html.unescape(pg), '%s: %s' % (name, count_of(pg)))
    check('"Explore all regions" opens the worldwide region directory', 'href="/jobs/regions"' in page)

    def newest(rs):
        return sorted(rs, key=lambda r: (r['posted'] or '', r['id']), reverse=True)
    def mixed(rs):
        rs = newest(rs)
        home, away = [r['id'] for r in rs if r['india']], [r['id'] for r in rs if not r['india']]
        return [i for pair in zip(home, away) for i in pair] + home[len(away):] + away[len(home):]
    check('the landing page has no "Browse all jobs" listing any more (Latest Jobs shows the newest jobs), and no filter panel',
          'id="jobs"' not in page and 'Browse all jobs' not in text(page) and 'id="o_llmd_board_form"' not in page)
    check('... Latest Jobs links to the full search with its filters ("Search all jobs with filters" -> /jobs?view=all)',
          [h for h, _t in links(page.split('id="latest"', 1)[1].split('id="companies"', 1)[0], 'o_llmd_latest_all')] == ['/jobs?view=all'])
    listing = cards(get('/jobs?view=all')[1])
    check('... the full search with its filters stays at /jobs?view=all: 12 jobs, the newest in India and the newest abroad one after the other, each with View Details and Apply Now',
          [c['id'] for c in listing] == mixed(rows)[:12]
          and all(c['apply'] == ('/jobs/ext/%d/go' % c['id'] if by_id[c['id']]['apply_url'] else '') for c in listing), [c['id'] for c in listing][:3])

    # ---- Latest Jobs: the newest by posting date, the last sync, category shortcuts, page numbers
    def latest_ids(html_part):
        return [int(i) for i in re.findall(r'class="o_llmd_lcard_title"><a href="/jobs/(\d+)/[a-z0-9-]+"', html_part)]
    by_date = [r['id'] for r in newest(rows)]
    sec = page.split('id="latest"', 1)[1].split('id="companies"', 1)[0]
    ids = latest_ids(sec)
    check('"Latest Jobs": heading, "Fresh opportunities from companies worldwide", the 12 newest jobs by their posting date, each card with View Details',
          'Latest Jobs' in text(sec) and 'Fresh opportunities from companies worldwide' in text(sec) and ids == by_date[:12]
          and all('href="/jobs/%d/' % i in sec for i in ids) and text(sec).count('View Details') == len(ids), ids[:3])
    syncs = [x for x in gw.search('llmd.job.sync', [['finished', '!=', False], ['state', 'in', ['ok', 'partial']]], 5000) if x['created'] or x['updated']]
    last = max((x['finished'] for x in syncs), default=None)
    check('... "Updated ... ago" = the end of the last sync that brought jobs (the sync log), exact time in its tooltip', bool(last) and 'title="Last sync: %s UTC"' % last in sec and 'Updated ' in text(sec), last)
    now = datetime.datetime.utcnow()
    fresh = {r['id'] for r in rows if r['posted'] and datetime.datetime.strptime(r['posted'], '%Y-%m-%d %H:%M:%S') >= now - datetime.timedelta(days=3)}
    cells = re.split(r'(?=<div class="o_llmd_lcell)', sec)[1:]
    check('... "New" only on jobs really posted in the last 3 days, and a job without a posting date says so (no made-up date)',
          all(('o_llmd_newbadge' in c) == (int(re.search(r'/jobs/(?:ext/)?(\d+)', c).group(1)) in fresh) for c in cells)
          and all('No posting date' in c for c in cells if not by_id[int(re.search(r'/jobs/(?:ext/)?(\d+)', c).group(1))]['posted']))
    chips = [(h, int(re.findall(r'\d+', text(inner))[-1])) for h, inner in links(sec, 'o_llmd_lchip')]
    want = [('/jobs#latest', len(rows))] + [('/jobs?latest_cat=%s#latest' % sl, n) for sl, n in all_cats[:8]]
    check('... category shortcuts: "All jobs" and the 8 biggest categories, with their real counts', chips == want, chips[:4])
    st, b1 = get('/jobs/latest?page=1')
    st2, b2 = get('/jobs/latest?page=2')
    p1, p2 = latest_ids(b1), latest_ids(b2)
    check('page 2 (/jobs/latest?page=2, the "2" of the page numbers): the next 12 jobs by date, none of page 1, and it says there are more', st == st2 == 200 and p1 == ids and p2 == by_date[12:24]
          and not set(p1) & set(p2) and 'data-more="1"' in b2 and 'href="/jobs?latest=2#latest"' in sec, p2[:3])
    last_page = -(-len(rows) // 12)
    bl = get('/jobs/latest?page=%d' % last_page)[1]
    check('... the last page says there is nothing more (Next is off)', 'data-more="0"' in bl and latest_ids(bl) == by_date[(last_page - 1) * 12:])
    cat = all_cats[2][0]
    in_this = [r['id'] for r in newest([r for r in rows if r['job_category'] == cat])]
    bc = get('/jobs/latest?category=%s&page=1' % cat)[1]
    check('... a category shortcut (%s) loads that category only, newest first, with its own total' % cat, latest_ids(bc) == in_this[:12] and 'data-total="%d"' % len(in_this) in bc)
    nojs = get('/jobs?latest=2&latest_cat=%s' % cat)[1].split('id="latest"', 1)[1].split('id="companies"', 1)[0]
    check('... without JavaScript the page numbers reload the landing page on that page (/jobs?latest=2&latest_cat=...)', latest_ids(nojs) == in_this[12:24] and 'active' in (re.search(r'<a[^>]*latest_cat=%s#latest"[^>]*>' % cat, nojs) or [''])[0])

    # ---- Top 10 countries hiring, and the directory of all countries
    country_n = sorted(Counter(r['country'] for r in rows if r['country']).items(), key=lambda kv: (-kv[1], kv[0]))
    sec = page.split('id="countries"', 1)[1].split('id="why"', 1)[0]
    shown = [(h, html.unescape(re.search(r'<strong>(.*?)</strong>', inner).group(1)), int(re.search(r'(\d+) jobs?', text(inner)).group(1))) for h, inner in links(sec, 'o_llmd_countrycard')]
    check('"Top 10 Countries Hiring": the 10 countries with the most jobs (every work mode), real counts, a flag each, each opening /jobs/location/<country>',
          'Top 10 Countries Hiring' in text(sec) and [(c, n) for _h, c, n in shown] == country_n[:10] and all(h == '/jobs/location/%s' % BC.slugify(c) for h, c, _n in shown)
          and sec.count('class="o_llmd_flag"') == len(shown) and 'Noto+Color+Emoji' in sec, shown[:3])
    bad = [(h, n) for h, _c, n in shown[:4] if count_of(get(h)[1]) != n]
    check('... a country card opens the results of that country (same count)', not bad, bad)
    check('... "Explore All Countries (%d)" opens /jobs/countries' % len(country_n), 'href="/jobs/countries"' in sec and 'Explore All Countries (%d)' % len(country_n) in text(sec))
    st, cpg = get('/jobs/countries')
    dshown = sorted((html.unescape(re.search(r'<strong>(.*?)</strong>', inner).group(1)), int(re.search(r'(\d+) jobs?', text(inner)).group(1))) for _h, inner in links(cpg, 'o_llmd_countrycard'))
    check('/jobs/countries: EVERY country that has jobs (%d), each with its real number of jobs, grouped by region, searchable' % len(country_n), st == 200 and dshown == sorted(country_n)
          and 'o_llmd_dir_filter' in cpg and all(nm in text(cpg) for sl, nm, _t, _i in JF.REGIONS if any(r['region'] == sl and r['country'] for r in rows)))
    remote_n = Counter(r['country'] for r in rows if r['country'] and r['work_mode'] == 'remote')
    st, rpg2 = get('/jobs/countries?mode=remote')
    rshown = sorted((html.unescape(re.search(r'<strong>(.*?)</strong>', inner).group(1)), int(re.search(r'(\d+) jobs?', text(inner)).group(1)), h) for h, inner in links(rpg2, 'o_llmd_countrycard'))
    check('... "Remote only" counts the remote jobs on their own (and its cards open the country with the remote filter)', st == 200 and [(c, n) for c, n, _h in rshown] == sorted(remote_n.items())
          and all(h.endswith('?mode=remote') for _c, _n, h in rshown), rshown[:3])

    # ---- the visible name of the board is "Jobs Explorer" (a label only: every route stays /jobs...)
    ex_pages = {'/jobs?view=all': get('/jobs?view=all')[1], '/jobs/categories': get('/jobs/categories')[1], '/jobs/regions': get('/jobs/regions')[1],
                '/jobs/countries': get('/jobs/countries')[1], '/jobs/ext/%d' % rows[0]['id']: get('/jobs/ext/%d' % rows[0]['id'])[1]}
    crumbs_ok = all(re.search(r'<a href="/jobs" class="o_llmd_crumb_(?:link|back)">(?:<i[^>]*></i>\s*)?Jobs Explorer</a>', pg) for pg in ex_pages.values())
    check('"Jobs Explorer": the browser title and the badge of the landing page, the breadcrumb of every board page (results, directories, job details), all still linking /jobs',
          '<title>Jobs Explorer | ' in page and 'LLM Decode Jobs Explorer' in text(page) and crumbs_ok, [u for u, pg in ex_pages.items() if 'Jobs Explorer' not in pg])
    menu_link = re.search(r'<a role="menuitem" href="/jobs" class="nav-link[^"]*">\s*<span>([^<]*)</span>', page)
    check('... the website menu says "Jobs Explorer" (and still opens /jobs); no board page shows the old label "Job Board"',
          bool(menu_link) and menu_link.group(1) == 'Jobs Explorer' and not any('Job Board' in text(pg) for pg in [page] + list(ex_pages.values())),     # "company job boards" (where the jobs come from) is no label
          menu_link.group(1) if menu_link else 'no /jobs menu link')

    # ---- v19.0.28: China & Hong Kong, the languages of a job, the dark theme
    cn_rows = [r for r in rows if r['region'] == 'china']
    check('"China & Hong Kong" is a region of its own: its jobs are in China, Hong Kong or Macau, and /jobs/region/china shows exactly them (%d)' % len(cn_rows),
          all(r['country'] in ('China', 'Hong Kong', 'Macau') for r in cn_rows) and not any(r['country'] in ('China', 'Hong Kong') and r['region'] != 'china' for r in rows)
          and (not cn_rows or count_of(get('/jobs/region/china')[1]) == len(cn_rows)), len(cn_rows))
    cn_hq = sorted({r['company'] for r in rows if r['company_region'] == 'china'})
    check('... companies headquartered in China / Hong Kong get their own "China & Hong Kong" tab in "Companies by region" (%s)' % ', '.join(cn_hq[:6]),
          not cn_hq or ('data-tab="china"' in page and all(html.escape(c) in page.split('id="hq-china"', 1)[1].split('id="hq-', 1)[0] for c in cn_hq[:12])), cn_hq[:6])
    zh = [r for r in rows if r['source_lang']]
    if zh:
        z = zh[0]
        dz = get('/jobs/ext/%d' % z['id'])[1]
        note = {'zh-title': 'in Chinese only; the description below', 'zh-en': 'in Chinese and English'}.get(z['source_lang'], 'published this job in Chinese')
        check('a listing in Chinese (%d of them) is shown as the employer wrote it, marked as such - no made-up English version' % len(zh),
              html.escape(z['title']) in dz and note in text(dz) and (('lang="zh"' in re.search(r'<h1 class="o_llmd_title"[^>]*>', dz).group(0)) == bool(re.search('[一-鿿]', z['title']))), (z['id'], z['source_lang']))
    else:
        check('no listing in Chinese is stored right now (nothing to mark)', True)
    lg = [r for r in rows if r['languages'] and any(x.split(':')[0] != 'English' for x in r['languages'].split(','))]
    if lg:
        r0 = lg[0]
        want = [x.split(':') for x in r0['languages'].split(',')]
        dl = get('/jobs/ext/%d' % r0['id'])[1]
        sec = (re.search(r'class="o_llmd_langs">.*?</div>', dl, re.S) or [''])[0]
        check('a job whose text asks for a language (%d jobs) lists it on its page, required or a plus: %s' % (len(lg), r0['languages']),
              all(name in text(sec) for name, _k in want) and text(sec).count('a plus') == sum(1 for _n, k in want if k == 'plus'), (r0['id'], text(sec)[:120]))
    bundle28 = re.search(r'<link[^>]+href="(/web/assets/[^"]*web\.assets_frontend[^"]*\.css)"', page)
    css28 = get(bundle28.group(1))[1] if bundle28 else ''
    check('the light theme of learn.llmdecode.com: light tokens and color-scheme on the board, its header and footer on the board pages only, motion off with reduced motion',
          '--bg:#ffffff' in css28.replace(' ', '') and '--grad:linear-gradient(135deg,#2563eb0%,#7c3aed100%)' in css28.replace(' ', '') and 'color-scheme:light' in css28.replace(' ', '')
          and 'body:has(#wrap.o_llmd_board)' in css28 and 'prefers-reduced-motion' in css28 and 'o_llmd_rv_on' in css28 and '#090c17' not in css28)
    st_home, home = get('/')
    check('... other pages of the site keep their own theme (the home page has no board on it)', st_home == 200 and 'o_llmd_board' not in home)

    region_n = Counter(r['region'] for r in rows if r['region'])
    zone_n = Counter(r['india_zone'] for r in rows if r['india_zone'])
    region_want = [(sl, region_n[sl]) for sl, _n, _t, _i in JF.REGIONS if region_n[sl]] + [(sl, zone_n[sl]) for sl, _n, _t, _i in JF.INDIA_ZONES if zone_n[sl]]
    status, rpg = get('/jobs/regions')
    rows_shown = [(h.rsplit('/', 1)[-1], int(re.search(r'<strong>(\d+)</strong>', inner).group(1))) for h, inner in links(rpg, 'o_llmd_regionrow_head')]
    check('/jobs/regions: every world region that has jobs (by where the JOBS are), in order, with its real number of jobs', status == 200
          and rows_shown == [(sl, region_n[sl]) for sl, _n, _t, _i in JF.REGIONS if region_n[sl]] and len(rows_shown) >= 2, rows_shown)
    bad = []
    for sl, n in rows_shown:
        seg = rpg.split('o_llmd_region_%s"' % sl, 1)[1].split('<article', 1)[0]
        cn = sorted(Counter(r['country'] for r in rows if r['region'] == sl and r['country']).items(), key=lambda kv: (-kv[1], kv[0]))
        got = [(html.unescape(text(inner)).strip().rsplit(' ', 1)[0].strip(), int(text(inner).strip().rsplit(' ', 1)[1])) for h, inner in links(seg, 'o_llmd_cat_pill') if h.startswith('/jobs/location/')]
        n_co = len({r['company'] for r in rows if r['region'] == sl and r['company']})
        if got != cn or '%d compan' % n_co not in text(seg):
            bad.append((sl, got[:3], cn[:3], n_co))
    check('... each region lists its countries (with their jobs) and how many companies hire there; India & South Asia also its regions of India', not bad
          and all('/jobs/region/%s"' % z in rpg for z, n in zone_n.items() if n), bad[:2])
    bad = [(sl, n, c) for sl, n in rows_shown + [(z, zone_n[z]) for z in zone_n] for c in [count_of(get('/jobs/region/%s' % sl)[1])] if c != n]
    check('... every region opens /jobs/region/<region> with exactly that number of jobs', not bad, bad)
    no_region = len(rows) - sum(region_n.values())
    note = text((re.search(r'<p class="o_llmd_region_note">.*?</p>', rpg, re.S) or [''])[0])
    check('the directory says how many jobs are in no region (%d name no country or region) and which regions have none - nothing is guessed' % no_region,
          (not no_region or '%d of the %d jobs name no country' % (no_region, len(rows)) in note)
          and all(nm in note for sl, nm, _t, _i in JF.REGIONS if not region_n[sl]), note[:160])
    top_country = Counter(r['country'] for r in rows if r['country'] and r['country'] != 'India').most_common(1)
    if top_country:
        c, n = top_country[0]
        check('a country of the directory opens its page: /jobs/location/%s = %d jobs' % (BC.slugify(c), n), count_of(get('/jobs/location/%s' % BC.slugify(c))[1]) == n)
    why = (re.search(r'id="why">.*?</section>', page, re.S) or [''])[0]
    check('"Why search jobs on LLM Decode" and 5 questions, with no made-up numbers (no digit in that part of the page)', 'Why search jobs on LLM Decode' in t and why.count('class="o_llmd_faq_item"') == 5
          and not re.search(r'\d', text(why)))
    bundle = re.search(r'<link[^>]+href="(/web/assets/[^"]*web\.assets_frontend[^"]*\.css)"', page)
    css = get(bundle.group(1))[1] if bundle else ''
    check('the fonts of learn.llmdecode.com: Inter and Inter Tight are loaded (once, for the whole site), no Manrope any more, and no rule of the board uses Fraunces or Caveat',
          page.count('family=Inter:') == 1 and 'family=Inter+Tight:' in page and 'Manrope' not in page and 'Fraunces' not in page and 'Caveat' not in page
          and bool(css) and not re.search(r'\.o_llmd_[\w-]+[^{}]*\{[^}]*(Fraunces|Caveat)', css))
    check('the Jobs menu of the website is marked active on the board pages', all(re.search(r'<a role="menuitem" href="/jobs" class="nav-link active"', get(p)[1]) for p in ('/jobs', '/jobs?view=all', '/jobs/category/sales')))

    print('\n=== C2. the results page: filters on the left (a drawer on small screens), results on the right ===')
    status, page = get('/jobs?view=all')
    t = text(page)
    check('all jobs: "%d jobs found", breadcrumb Jobs / All jobs, the search bar keeps the other filters' % len(rows), status == 200 and count_of(page) == len(rows)
          and 'class="o_llmd_crumbs"' in page and 'name="view" value="all"' in page)
    side = (re.search(r'<aside class="o_llmd_side".*?</aside>', page, re.S) or [''])[0]
    check('no course in the general filters: no course select, no course chip, no course words in the panel (the course has its own section and page)',
          bool(side) and 'name="course"' not in page and 'o_llmd_fchip_course' not in page and not re.search(r'(?i)llm decode course|any course|select your course|\bcourse\b', text(side)))
    reg = re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)\((\d+)\)</option>', (re.search(r'<select id="llmd_region".*?</select>', page, re.S) or [''])[0])
    check('Region filter: the world regions and the regions of India that have jobs, each with its count', [(v, int(n)) for v, _l, n in reg] == region_want, reg)
    check('filters: Location (country, city), Experience 0-25+ (two handles, Reset), Work mode, Job Type, Time Posted, Category, Department, Role, Skills, Company; no Salary, no Freelance',
          all(x in page for x in ('name="region"', 'name="country"', 'name="city"', 'name="exp_min"', 'name="exp_max"', 'name="mode"', 'name="jtype"', 'name="posted"', 'name="category"', 'name="function"', 'name="role"', 'name="skill"', 'name="company"'))
          and 'name="salary"' not in page and 'Freelance' not in t and 'Salary' not in t and 'class="o_llmd_range_reset"' in page
          and re.findall(r'<div class="o_llmd_range_scale"[^>]*>(.*?)</div>', page, re.S) and text(re.findall(r'<div class="o_llmd_range_scale"[^>]*>(.*?)</div>', page, re.S)[0]).split() == ['0', '5', '10', '15', '20', '25+'])
    check('Role, Skills and Company lists can be searched (a search box above each list)', page.count('class="form-control o_llmd_listfilter"') == 3)
    check('Company size is a filter (approximate bands, the note says so); Industry is not in the panel at all (no source gives it)',
          'name="size"' in page and 'Company size' in t and 'Approximate employee count' in t and 'Industry' not in t and 'name="industry"' not in page)
    modes = re.findall(r'<label class="btn btn-outline-primary"[^>]*>(.*?)</label>', page, re.S)
    check('Work mode: All Jobs, Remote, Hybrid, On-site', [text(m).strip() for m in modes] == ['All Jobs', 'Remote', 'Hybrid', 'On-site'], [text(m).strip() for m in modes])
    jt = facet(page, 'jtype')
    check('Job Type: Full-time, Part-time, Internship, Contract, each with its real number of jobs', [(v, l, n) for v, l, n, _c in jt] == [(k, TYPE_LABELS[k], len([r for r in rows if r['job_type'] == k])) for k in TYPE_LABELS], jt)
    now = datetime.datetime.utcnow()
    po = facet(page, 'posted', 'radio')
    check('Time Posted: Any time, Last 24 hours, Last 7 days, Last 30 days, with real counts', [l for _v, l, _n, _c in po] == ['Any time', 'Last 24 hours', 'Last 7 days', 'Last 30 days']
          and [n for _v, _l, n, _c in po] == [len(rows)] + [len([r for r in rows if r['posted'] and datetime.datetime.strptime(r['posted'], '%Y-%m-%d %H:%M:%S') >= now - datetime.timedelta(days=d)]) for d in (1, 7, 30)], po)
    cats_f = facet(page, 'category')
    check('Category: every category with jobs and its count', sorted((v, n) for v, _l, n, _c in cats_f) == sorted((s, n) for s, n in in_cat.items()), cats_f[:3])
    check('Apply Filters shows how many jobs the filters give (here: all), and Clear All', re.search(r'Apply Filters · <span class="o_llmd_live_n">%d</span>' % len(rows), page) and 'Clear All' in t
          and json.loads(get('/jobs/results-count')[1])['count'] == len(rows))
    check('the panel is a drawer on small screens: Filters button, close button, backdrop', all(x in page for x in ('class="o_llmd_side"', 'id="o_llmd_board_form"', 'class="o_llmd_filter_btn"', 'class="o_llmd_drawer_close"', 'class="o_llmd_backdrop"')))
    menu = (re.search(r'<div class="o_llmd_sort_menu".*?</div>', page, re.S) or [''])[0]
    check('sorting: Most relevant / Most recent', [text(a).strip() for a in re.findall(r'<a\b[^>]*>(.*?)</a>', menu, re.S)] == ['Most relevant', 'Most recent'])
    cs = cards(page)
    check('every job card: View Details (the detail page) and Apply Now (the tracked link that opens the original application page)', bool(cs)
          and all(c['see'] == by_id[c['id']]['page_url'] and c['apply'] == ('/jobs/ext/%d/go' % c['id'] if by_id[c['id']]['apply_url'] else '') for c in cs if c['id'] in by_id), '%d cards' % len(cs))
    check('a job card links its company page and its category page', all(re.search(r'href="/jobs/company/%s"' % re.escape(BC.slugify(by_id[c['id']]['company'])), c['html']) for c in cs if by_id.get(c['id'], {}).get('company'))
          and all('href="/jobs/category/%s"' % by_id[c['id']]['job_category'] in c['html'] for c in cs if by_id.get(c['id'], {}).get('job_category')))

    print('\n=== D. course -> matching real jobs -> View Details -> Apply Now ===')
    flow_ok, total_checked = True, 0
    for course in catalog:
        code, label = course['code'], course['name']
        status, page = get('/jobs/course/%s' % code)
        want = {r['id'] for r in in_course[code]}
        cs = cards(page)
        check('/jobs/course/%-18s %3d jobs = database, every card matches the course, heading "Jobs matched to ...", no course control' % (code, len(want)), status == 200
              and count_of(page) == len(want) and cs and all(c['id'] in want for c in cs) and 'Jobs matched to %s' % label in html.unescape(page) and 'name="course"' not in page)
        roles = facet(page, 'role')
        for role, role_label, n, _c in roles:
            pg = get('/jobs/course/%s?role=%s' % (code, role))[1]
            exp = [r for r in in_course[code] if ',%s,' % role in (r['roles'] or '')]
            cs = cards(pg)
            ok = n == len(exp) == count_of(pg) and all(c['id'] in {r['id'] for r in exp} for c in cs)
            for c in cs[:2]:
                r = by_id[c['id']]
                dstatus, dpage = get(c['see'])
                hrefs = [html.unescape(a or b) for a, b in re.findall(r'<a[^>]*class="[^"]*o_llmd_apply[^"]*"[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*class="[^"]*o_llmd_apply[^"]*"', dpage)]
                ok = ok and dstatus == 200 and r['title'] in text(dpage) and len(re.findall(r'>\s*Apply Now', dpage)) == 1 and hrefs == (['/jobs/ext/%d/go' % r['id']] if r['apply_url'] else [])
                total_checked += 1
            flow_ok = flow_ok and ok
            check('  %s / %-36s %3d jobs' % (code.split('-')[0], role_label[:36], n), ok)
    check('whole flow course -> role -> jobs -> View Details -> Apply Now (straight to the employer through the tracked link)', flow_ok, '%d detail pages checked' % total_checked)
    pg = get('/jobs/course/sell-ai?jtype=fulltime')[1]
    check('the course page: "Clear all filters" stays on it, no course chip, "Choose another course" leads back to the course selector, the terms it teaches are shown',
          [h for h, _t in links(pg, 'o_llmd_clear')] == ['/jobs/course/sell-ai'] and 'o_llmd_fchip_course' not in pg and 'href="/jobs?rec=sell-ai#courses"' in pg and 'What it teaches' in text(pg))
    status, _b, loc = Visitor().open('/jobs?course=sell-ai&mode=hybrid')
    check('old links /jobs?course=... move permanently (301) to the course page and keep the other filters', status == 301 and loc.endswith('/jobs/course/sell-ai?mode=hybrid'), (status, loc))
    check('an unknown course page is a 404', get('/jobs/course/nope')[0] == 404)

    print('\n=== E. search, every filter alone and together, sort, pages, chips ===')
    top_city = [c for c, _n in Counter(r['city'] for r in rows if r['city']).most_common(2)]
    top_skill = Counter(k for r in rows for k in (r['skill_keys'] or '').strip(',').split(',') if k).most_common(1)
    top_fn = Counter(r['job_function'] for r in rows if r['job_function']).most_common(1)
    combos = [{'q': 'python'}, {'q': 'account executive'}, {'jtype': ['fulltime', 'contract']}, {'mode': 'hybrid'}, {'exp_min': 3, 'exp_max': 8}, {'exp_min': 10}, {'posted': '7'},
              {'country': 'India', 'mode': 'onsite'}, {'city': top_city}, {'category': ['sales', 'marketing']}, {'company': [co_n.most_common(1)[0][0]]}, {'location': 'Bengaluru'}, {'location': 'Remote'},
              {'location': 'Delhi NCR'}, {'location': 'India', 'jtype': ['fulltime'], 'exp_max': 6}, {'course': 'sell-ai', 'mode': 'onsite', 'jtype': ['fulltime']},
              {'course': 'genai-mastermind', 'q': 'python'}, {'category': ['ai-machine-learning'], 'city': top_city[:1], 'exp_min': 2},
              {'region': 'south-india', 'mode': 'onsite'}, {'region': 'india-south-asia', 'jtype': ['fulltime'], 'exp_min': 2}, {'region': 'north-india', 'category': ['sales']},
              {'region': 'west-india', 'q': 'manager', 'sort': 'newest'}, {'location': 'South India'}, {'course': 'sell-ai', 'region': 'south-india'}]
    combos += [{'skill': [top_skill[0][0]]}] if top_skill else []
    abroad_top = Counter(r['country'] for r in rows if r['country'] and r['country'] != 'India').most_common(1)
    combos += [{'country': abroad_top[0][0], 'mode': 'remote'}, {'region': JF.COUNTRY_REGION.get(abroad_top[0][0], 'europe'), 'jtype': ['fulltime']}] if abroad_top else []
    world_city = Counter(r['city'] for r in rows if r['city'] and not r['india']).most_common(1)
    combos += [{'location': world_city[0][0]}] if world_city else []
    combos += [{'function': [top_fn[0][0]], 'jtype': ['fulltime']}] if top_fn else []
    for f in combos:
        query = urllib.parse.urlencode({k: v for k, v in f.items() if k != 'course'}, doseq=True)
        path = '/jobs/course/%s' % f['course'] if f.get('course') else '/jobs'
        st, pg = get(path + '?' + query)
        expect = {r['id'] for r in rows if matches(r, f)}
        cs = cards(pg)
        live = json.loads(get('/jobs/results-count?' + query + ('&scope=course&scope_value=%s' % f['course'] if f.get('course') else ''))[1])['count']
        check('%-62s count = database = the live count of Apply Filters; every card matches' % (path + '?' + query)[:62], st == 200 and count_of(pg) == len(expect) == live
              and all(c['id'] in expect for c in cs), '%d jobs' % len(expect))
    check('the pager form ?jtype=fulltime,contract (one value with commas) gives the same jobs as two values', count_of(get('/jobs?jtype=fulltime,contract')[1]) == len([r for r in rows if r['job_type'] in ('fulltime', 'contract')]))
    check('made-up filter values do not crash and are ignored', get('/jobs?course=%3Cscript%3E&role=zzz&track=%27&exp_min=zz&exp_max=-3&jtype=x&mode=zz&posted=99&sort=zz&category=zz&function=zz')[0] == 200
          and count_of(get('/jobs?jtype=x&mode=zz&posted=99&exp_min=zz&category=zz&sort=zz')[1]) == len(rows))
    pg = page_of(jtype='fulltime', mode='onsite')[1]
    nxt = re.search(r'href="(/jobs/page/2\?[^"]*)"', pg)
    p2 = cards(get(html.unescape(nxt.group(1)))[1]) if nxt else []
    check('the pager keeps the filters (page 2: other jobs, all Full-time + On-site)', nxt and 'jtype=fulltime' in nxt.group(1) and 'mode=onsite' in nxt.group(1) and p2
          and not {c['id'] for c in p2} & {c['id'] for c in cards(pg)} and all(by_id[c['id']]['job_type'] == 'fulltime' and by_id[c['id']]['work_mode'] == 'onsite' for c in p2 if c['id'] in by_id))
    check('the sort links keep the filters', re.search(r'href="/jobs\?[^"]*jtype=fulltime[^"]*sort=newest"', html.unescape(pg)) and re.search(r'href="/jobs\?mode=onsite&jtype=fulltime"', html.unescape(pg)))
    ft = dict((label, html.unescape(h)) for h, label in re.findall(r'<a class="o_llmd_fchip" href="([^"]+)" aria-label="Remove filter: ([^"]+)"', pg))
    check('chips: "Full-time" removes only the job type, "On-site" only the work mode; "Clear all filters" goes back to all jobs', ft.get('Full-time') == '/jobs?mode=onsite' and ft.get('On-site') == '/jobs?jtype=fulltime'
          and [h for h, _t in links(pg, 'o_llmd_clear')] == ['/jobs?view=all'], ft)
    pg = page_of(sort='newest', view='all')[1]
    posted = [by_id[c['id']]['posted'] or '' for c in cards(pg) if c['id'] in by_id]
    check('Sort "Most recent": the newest first', posted == sorted(posted, reverse=True) and 'Most recent' in text(pg), posted[:3])
    ranked = cards(page_of(q='sales')[1])
    check('Sort "Most relevant" with a keyword: jobs that have it in the TITLE come before those that only mention it', ranked and all('sales' in by_id[c['id']]['title'].lower() for c in ranked[:3]),
          [by_id[c['id']]['title'] for c in ranked[:3]])
    status, pg = page_of(q='zzzqqqxxx')
    check('a search without result: a friendly empty state with "Clear all filters", not an error', status == 200 and 'No jobs match these filters.' in text(pg) and count_of(pg) == 0)
    p1, p2 = cards(page_of(view='all')[1]), cards(get('/jobs/page/2?view=all')[1])
    check('page 1 is a mix of categories and page 2 shows other jobs', len({by_id[c['id']]['job_category'] for c in p1 if c['id'] in by_id}) >= 3 and p2 and not {c['id'] for c in p1} & {c['id'] for c in p2})
    check('stock Odoo list still reachable (/jobs?stock=1)', get('/jobs?stock=1')[0] == 200)

    print('\n=== L. Location and Work mode filters (known answers: 8 temporary jobs "ZZFX ...") ===')
    stamp = int(time.time())
    fx = make_fixtures(stamp)
    key_of = {v: k for k, v in fx.items()}
    try:
        got = {r['id']: r for r in gw.search('llmd.job.listing', [['id', 'in', list(fx.values())]], 20)}
        want = {'f1': ('fresher', 'fulltime', 'onsite', True, 'Pune'), 'f2': ('mid', 'fulltime', 'hybrid', True, 'Bengaluru'), 'f3': ('', 'contract', 'remote', True, 'Hyderabad'),
                'f4': ('', 'parttime', 'onsite', True, 'Gurugram'), 'f5': ('internship', 'internship', 'onsite', True, 'Mumbai'), 'f6': ('senior', 'fulltime', 'onsite', False, 'London'),
                'f7': ('entry', 'fulltime', 'onsite', True, 'Pune'), 'f8': ('', 'fulltime', 'remote', False, '')}
        bad = {k: (got[fx[k]]['exp_level'], got[fx[k]]['job_type'], got[fx[k]]['work_mode'], got[fx[k]]['india'], got[fx[k]]['city']) for k in want
               if (got[fx[k]]['exp_level'], got[fx[k]]['job_type'], got[fx[k]]['work_mode'], got[fx[k]]['india'], got[fx[k]]['city']) != want[k]}
        check('the stored filter values of the 8 temporary jobs are right (experience, type, work mode, India, city)', not bad, bad)
        for filters, expect in FIXTURE_EXPECT:
            status, page = page_of(q='ZZFX', **filters)
            cs = cards(page)
            found = {key_of[c['id']] for c in cs if c['id'] in key_of}
            label = ', '.join('%s=%s' % (k, '+'.join(v) if isinstance(v, list) else v) for k, v in filters.items()) or '(no filter: every place)'
            check('filter %-44s -> %s' % (label, ', '.join(sorted(expect)) or 'no job + friendly message'), status == 200 and found == expect and len(cs) == len(expect) and count_of(page) == len(expect)
                  and (bool(expect) or 'No jobs match these filters.' in text(page)), sorted(found))
        status, page = page_of(q='ZZFX')
        check('the city filter lists the cities that have jobs, each under its country', {'Pune', 'Bengaluru', 'Hyderabad', 'Gurugram', 'Mumbai'} <= {v for v, _l, _n, _c in facet(page, 'city')}
              and re.search(r'data-country="India"[^>]*>\s*<input type="checkbox" class="form-check-input" name="city" value="Pune"', page))
        status, page = page_of(q='ZZFX', city='Pune', mode='onsite')
        check('every control keeps its state after the page reloads (city ticked, work mode chosen)', [v for v, _l, _n, c in facet(page, 'city') if c] == ['Pune']
              and re.search(r'value="onsite"[^>]*checked', page) is not None and not re.search(r'id="llmd_mode_all" value=""[^>]*checked', page))
        check('"Clear all filters" appears when a filter is active, and not on the plain results', 'Clear all filters' in text(page) and not links(get('/jobs?view=all')[1], 'o_llmd_clear'))
        # the default order ("Most relevant" without a keyword or course): the newest first, Indian and international jobs mixed
        flags = [by_id[c['id']]['india'] if c['id'] in by_id else key_of.get(c['id']) not in ('f6', 'f8') for c in cards(get('/jobs?view=all')[1])]
        check('the default order mixes the jobs: one in India, one abroad, the newest of each first (no India-first any more: a worldwide board)', flags[:8] == [True, False] * 4, flags)
        status, page2 = get('/jobs/page/2?' + urllib.parse.urlencode({'mode': 'onsite'}))
        check('the pager keeps the filters (page 2 of On-site)', status == 200 and re.search(r'value="onsite"[^>]*checked', page2) is not None and bool(cards(page2)))
        pg = page_of(mode='hybrid', country='India')[1]
        sort_link = re.search(r'href="(/jobs\?[^"]*sort=newest[^"]*)"', pg)
        chip = re.search(r'<a class="o_llmd_fchip" href="([^"]+)" aria-label="Remove filter: Hybrid"', pg)
        check('the sort menu and the chips keep the other filters (a chip removes only its own filter)', sort_link and 'mode=hybrid' in html.unescape(sort_link.group(1)) and 'country=India' in html.unescape(sort_link.group(1))
              and chip and 'mode=' not in html.unescape(chip.group(1)) and 'country=India' in html.unescape(chip.group(1)), chip and chip.group(1))
    finally:
        for lid in fx.values():
            gw.call('delete_record', model='llmd.job.listing', res_id=lid)
    check('cleanup: the temporary jobs are removed', not gw.search('llmd.job.listing', [['title', 'like', 'ZZFX']], 5))
    # real data: the header count of a filter equals what the database says
    for filters, pred, label in (({'view': 'all'}, lambda r: True, 'all jobs'), ({'country': 'India'}, lambda r: r['country'] == 'India', 'country India'),
                                 ({'mode': 'remote'}, lambda r: r['work_mode'] == 'remote', 'remote'), ({'mode': 'hybrid'}, lambda r: r['work_mode'] == 'hybrid', 'hybrid'),
                                 ({'mode': 'onsite'}, lambda r: r['work_mode'] == 'onsite', 'on-site'), ({'location': 'Remote'}, lambda r: r['work_mode'] == 'remote', 'location "Remote"'),
                                 ({'course': 'genai-mastermind', 'mode': 'hybrid'}, lambda r: ',genai-mastermind,' in (r['courses'] or '') and r['work_mode'] == 'hybrid', 'course + hybrid'),
                                 ({'course': 'sell-ai', 'country': 'India', 'mode': 'remote'}, lambda r: ',sell-ai,' in (r['courses'] or '') and r['country'] == 'India' and r['work_mode'] == 'remote', 'course + India + remote')):
        status, page = page_of(**filters)
        check('real + test jobs: %-30s header count = database' % label, status == 200 and count_of(page) == len([r for r in rows if pred(r)]), count_of(page))
        if filters.get('mode'):
            shown = cards(page)
            check('  ... and every card shown is really a %s job' % filters['mode'], bool(shown) and all(by_id[c['id']]['work_mode'] == filters['mode'] for c in shown if c['id'] in by_id), '%d cards' % len(shown))

    print('\n=== F. safety: invalid links, missing description ===')
    victim = cards(page_of(course='sell-ai', loc='all')[1])[0]['id']
    old = by_id[victim]['apply_url']
    for bad in ('javascript:alert(1)', 'data:text/html;base64,PHNjcmlwdD4=', 'ftp://example.com/x', '//evil.example.com', 'not a url', ''):
        gw.call('update_record', model='llmd.job.listing', res_id=victim, values={'apply_url': bad})
        dpage = get('/jobs/ext/%d' % victim)[1]
        n_nolink = len(gw.search('llmd.job.click', [['listing_id', '=', victim], ['status', '=', 'no_link'], ['id', '>', click0]], 50))
        go = Visitor().open('/jobs/ext/%d/go' % victim)
        saved = gw.search('llmd.job.click', [['listing_id', '=', victim], ['status', '=', 'no_link'], ['id', '>', click0]], 50)
        check('apply_url %-34r -> no employer link, the URL is not on the page, a disabled Apply Now, /go sends the visitor back to the job and saves the click as "no_link"' % bad,
              '/jobs/ext/%d/go' % victim not in dpage and (not bad or bad not in dpage) and 'valid application link is not available' in text(dpage) and go[0] == 303 and go[2].endswith(by_id[victim]['page_url'])
              and len(saved) == n_nolink + 1 and not saved[-1]['apply_url'])
    gw.call('update_record', model='llmd.job.listing', res_id=victim, values={'apply_url': old})
    tmp = gw.call('create_record', model='llmd.job.listing', values={'source': 'test', 'ext_id': 'no-description-test-%d' % int(time.time()), 'title': 'Listing without a description', 'company': 'Test Co',
                                                                    'location': 'Remote', 'tags': ',python,', 'roles': ',python_dev,', 'courses': ',genai-mastermind,', 'apply_url': 'https://example.com/jobs/1'})['id']
    status, page = get('/jobs/ext/%d' % tmp)
    check('missing description: page opens with a clear message and Apply Now', status == 200 and 'No description is available' in text(page) and 'Apply Now' in text(page))
    gw.call('update_record', model='llmd.job.listing', res_id=tmp, values={'active': False})
    check('an archived listing gives 404', get('/jobs/ext/%d' % tmp)[0] == 404)
    gw.call('delete_record', model='llmd.job.listing', res_id=tmp)
    check('bad id gives 404', get('/jobs/ext/99999999')[0] == 404)

    print('\n=== G. combining sources: normalization + duplicate removal (dry run, nothing stored) ===')
    same = {'title': 'Sales Manager', 'company': 'Acme Corp', 'location': 'Gurugram, Haryana', 'apply_url': 'https://example.com/a', 'posted': None, 'full_text': False, 'position': 0}
    cand = [dict(same, source='Adzuna', ext_id='a1', html='<p>Short snippet from one source.</p>', apply_url='https://example.com/a'),
            dict(same, source='Jooble', ext_id='j1', html='<p>A somewhat longer snippet from the second source about leading a sales team.</p>', apply_url='https://example.com/j'),
            dict(same, source='JSearch', ext_id='s1', full_text=True, html='<h3>Responsibilities</h3><ul><li>Lead the regional team and own the quota</li><li>Run weekly pipeline reviews</li><li>Coach sales reps</li></ul>', apply_url='https://example.com/h'),
            dict(same, source='Jooble', ext_id='j2', location='Mumbai, Maharashtra', html='<p>Same title and company in another city is a different job.</p>', apply_url='https://example.com/j2'),
            dict(same, title='Underwater Welder', source='Adzuna', ext_id='a9', html='<p>Not related to any course.</p>', apply_url='https://example.com/w')]
    uid = gw._rpc()[1]                                                            # the candidates go in as the method's argument (XML-RPC)
    merged = gw._rpc()[0].execute_kw(gw.os.environ['ODOO_DB'], uid, gw.os.environ['ODOO_PASSWORD'], 'llmd.job.listing', 'preview_merge', [cand])
    check('the same job from three sources is stored once (3 -> 1), another city stays separate, unrelated jobs are dropped', len(merged) == 2, [(m['source'], m['also_on']) for m in merged])
    keeper = [m for m in merged if 'Mumbai' not in str(m)][0]
    check('the full-text source wins and the others are named as "also on" (internally)', keeper['source'] == 'JSearch' and set(keeper['also_on'].split(', ')) == {'Adzuna', 'Jooble'} and keeper['full_text'], keeper)
    check('the kept job keeps ITS OWN application URL and is tagged with its course and role', keeper['apply_url'] == 'https://example.com/h' and ',sell-ai,' in keeper['courses'] and ',sales_manager,' in keeper['roles'])

    print('\n=== H. a failing source must not break the board (only the Indeed source is run: no real job API is called by this test) ===')
    indeed = gw.search('llmd.job.source', [['code', '=', 'indeed']], 1)[0]
    others_before = {s['name']: (s['last_status'], s['last_run'], s['requests_used']) for s in gw.search('llmd.job.source', [['code', '!=', 'indeed']], 20)}
    param = gw.search('ir.config_parameter', [['key', '=', 'llmd_agg.indeed_feed_url']], 1)
    pid = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.indeed_feed_url', 'value': 'http://127.0.0.1:9/indeed.xml'})['id'] if not param else param[0]['id']
    found = rpc('llmd.job.source', 'run', [[indeed['id']], []])
    srcs = {s['name']: s for s in gw.search('llmd.job.source', [], 20)}
    check('Indeed with an unreachable feed -> status "error" with a clear message and no jobs', found == [] and srcs['Indeed']['last_status'] == 'error' and 'unreachable' in (srcs['Indeed']['last_message'] or ''), srcs['Indeed']['last_message'])
    check('the other sources and the board are not touched by it', {n: (s['last_status'], s['last_run'], s['requests_used']) for n, s in srcs.items() if n != 'Indeed'} == others_before and get('/jobs')[0] == 200 and bool(cards(page_of(loc='all')[1])))
    gw.call('delete_record', model='ir.config_parameter', res_id=pid)
    rpc('llmd.job.source', 'run', [[indeed['id']], []])
    check('after removing it, Indeed is honestly "not connected" again', {s['name']: s for s in gw.search('llmd.job.source', [], 20)}['Indeed']['last_status'] == 'not_configured')

    print('\n=== J. detail page format: concise, same layout everywhere, no job site name ===')
    STRUCTURE = ['o_llmd_view', 'o_llmd_wrap', 'o_llmd_head', 'o_llmd_title', 'o_llmd_meta', 'o_llmd_card', 'o_llmd_apply_card', 'o_llmd_apply_btn']
    with_salary = [r for r in rows if r['salary']][:3]
    sample_j = [c['id'] for c in p1[:6]] + [r['id'] for r in with_salary]
    for jid in sample_j:
        r = by_id[jid]
        dpage = get('/jobs/ext/%d' % jid)[1]
        dtext = text(dpage)
        head = re.search(r'<header class="o_llmd_head">(.*?)</header>', dpage, re.S)
        head_text = text(head.group(1)) if head else ''
        aside = re.search(r'<aside class="o_llmd_apply_card">(.*?)</aside>', dpage, re.S)
        resp = re.search(r'<h2>Key Responsibilities</h2>\s*<ul>(.*?)</ul>', dpage, re.S)
        about = re.search(r'<h2>Job Overview</h2>\s*<p>(.*?)</p>', dpage, re.S)
        heads = re.findall(r'<h2>(.*?)</h2>', dpage)
        n_resp = len(re.findall(r'<li', resp.group(1))) if resp else 0
        n_skill = dpage.count('class="o_llmd_skill"')
        ok = (head and r['title'] in head_text and ((r['company'] or '') in head_text) and ((r['location'] or '') in head_text)
              and (not r['job_type'] or TYPE_LABELS[r['job_type']] in head_text) and (not r['exp_level'] or EXP_LABELS[r['exp_level']] in head_text) and (not r['work_mode'] or MODE_LABELS[r['work_mode']] in head_text)
              and ((r['salary'] in head_text) if r['salary'] else ('fa-money' not in head.group(1)))
              and n_resp <= 6 and n_skill <= 8 and bool(about) and len(text(about.group(1)).split()) <= 70
              and 'Job Overview' in heads and not ({'Key Responsibilities', 'Required Skills &amp; Qualifications', 'Experience Level', 'About the Role'} & set(heads)) and 'Not specified' not in dtext
              and len(re.findall(r'<li', (re.search(r'<h2>Job Overview</h2>(.*?)</section>', dpage, re.S) or [0, ''])[1])) <= 8
              and 'Read Full Description' not in dtext and 'o_llmd_more' not in dpage
              and all(c in dpage for c in STRUCTURE) and len(re.findall(r'>\s*Apply Now', dpage)) == 1
              and not PLATFORM.search(head_text) and not (aside and PLATFORM.search(text(aside.group(1)))) and 'Source:' not in dtext and 'Original listing' not in dtext and 'original posting' not in dtext)
        check('#%-5d header %s | ONE Job Overview card (overview, <= 8 points, %d skills, facts) | no site name' % (jid, '+salary' if r['salary'] else 'no salary', n_skill), ok, '%s | %s' % (r['company'], r['salary'] or '-'))
    jid = sample_j[0]
    dpage = get('/jobs/ext/%d' % jid)[1]
    region = (re.search(r'<div class="o_llmd_view">.*', dpage, re.S) or [''])[0]
    bundle = re.search(r'<link[^>]+href="(/web/assets/[^"]*web\.assets_frontend[^"]*\.css)"', dpage)
    css = get(bundle.group(1))[1] if bundle else ''
    check('detail page design: breadcrumb back to all jobs, header card with the company initial, the "Interested in this role?" Apply card; styled by the site stylesheet (no inline <style>)',
          'class="o_llmd_crumbs"' in dpage and '<a href="/jobs" class="o_llmd_crumb_back">' in dpage and 'o_llmd_head_logo' in dpage and 'Interested in this role?' in dpage
          and '<style' not in region and '.o_llmd_view .o_llmd_apply_card' in css and re.search(r'\.o_llmd_view \.o_llmd_head\s*\{', css), bundle.group(1).rsplit('/', 1)[-1] if bundle else 'no stylesheet')
    def timeline(page):
        """(numbers, [(bold lead, rest)], headings, timeline html) of the Key points of a detail page."""
        tl = re.search(r'<div class="o_llmd_timeline">(.*?)</div>', page, re.S)
        body = tl.group(1) if tl else ''
        nums = re.findall(r'<span class="o_llmd_tl_no" aria-hidden="true">(.*?)</span>', body)
        parts = [(html.unescape(a), html.unescape(b)) for a, b in re.findall(r'<p class="o_llmd_tl_txt"><strong>(.*?)</strong>(.*?)</p>', body, re.S)]
        heads = [html.unescape(h) for h in re.findall(r'<h4 class="o_llmd_tl_head">(.*?)</h4>', body)]
        return nums, parts, heads, body

    nums, parts, heads, body = timeline(dpage)
    block = SUM.display(json.loads(by_id[jid]['summary_json'])) if by_id[jid].get('summary_json') else {'points': [], 'point_groups': []}
    check('Key points timeline: numbered 1, 2, 3 ... in purple badges (no leading zero, no tick icon), bold opening phrase, the stored points in their own order, text unchanged',
          body and nums == [str(i) for i in range(1, len(block['points']) + 1)] and [a + b for a, b in parts] == block['points'] and all(a for a, _b in parts)
          and 'fa-check' not in body and '<i ' not in body and 'o_llmd_keypoints' not in dpage, '#%d, %d points' % (jid, len(nums)))
    headed = next((r for r in rows if r.get('summary_json') and any(g['heading'] for g in SUM.display(json.loads(r['summary_json']))['point_groups'])), None)
    if headed:
        block = SUM.display(json.loads(headed['summary_json']))
        nums, parts, heads, body = timeline(get('/jobs/ext/%d' % headed['id'])[1])
        check('a heading of the job ("What You Will Do?") heads its points instead of being numbered; numbering still runs 1, 2, 3 ...',
              heads == [g['heading'] for g in block['point_groups'] if g['heading']] and not any(SUM.is_heading_point(a + b) for a, b in parts)
              and [a + b for a, b in parts] == block['points'] and nums == [str(i) for i in range(1, len(block['points']) + 1)], '#%d: %s' % (headed['id'], heads))
    sim = re.search(r'<section class="o_llmd_similar o_llmd_board">(.*?)</section>', dpage, re.S)
    sim_ids = list(dict.fromkeys(int(x) for x in re.findall(r'href="/jobs/(\d+)/[a-z0-9-]+"', sim.group(1)))) if sim else []

    def keys(row):
        return (set((row.get('roles') or '').split(',')) | set((row.get('tags') or '').split(','))) - {''}
    if not keys(by_id[jid]):                                             # a job with no role and no course track has nothing to be similar to: no made-up matches
        check('Similar jobs: a job with no role or course track shows none (nothing is made up)', not sim_ids, '#%d -> %s' % (jid, sim_ids))
    else:
        check('Similar jobs: 1-3 real visible jobs (not this one) that share its role or course track, as compact cards with View Details (no description, no second Apply Now on the page)',
          sim and 1 <= len(sim_ids) <= 3 and jid not in sim_ids and all(i in by_id and keys(by_id[i]) & keys(by_id[jid]) for i in sim_ids)
          and 'View Details' in sim.group(1) and 'Apply Now' not in text(sim.group(1)) and 'o_llmd_job_desc' not in sim.group(1), '#%d -> %s' % (jid, sim_ids))
    r = by_id[jid]
    head_crumbs = (re.search(r'<nav class="o_llmd_crumbs".*?</nav>', dpage, re.S) or [''])[0]
    check('detail page: breadcrumb Jobs / <its category> / title, and the company name opens the company page', ('href="/jobs/category/%s"' % r['job_category'] in head_crumbs if r['job_category'] else True)
          and (not r['company'] or 'href="/jobs/company/%s"' % BC.slugify(r['company']) in dpage), head_crumbs[:120])
    leadin = gw.search('llmd.job.listing', ['|', ['summary_json', 'ilike', 'if you."'], ['summary_json', 'ilike', 'if you:"']], 50)
    check('no key point is only the opening line of a list ("You\'ll thrive with us if you:")', not leadin, '%d jobs' % len(leadin))
    own_jobs =gw.search('hr.job', [['website_published', '=', True]], 10)
    if own_jobs:
        own_page = get(own_jobs[0]['website_url'])[1]
        own_text = text(own_page)
        n_resp = len(re.findall(r'<li', (re.search(r'<h2>Key Responsibilities</h2>\s*<ul>(.*?)</ul>', own_page, re.S) or [0, ''])[1]))
        check('our own position uses the SAME layout (all structure classes)', all(c in own_page for c in STRUCTURE), own_jobs[0]['name'])
        check('our own position: the same format (<= 6 responsibilities), one Apply Now, no site name, no salary of another employer', n_resp <= 6 and len(re.findall(r'>\s*Apply Now', own_page)) == 1 and 'fa-money' not in own_page
              and not re.search(r'based on a real|Source:', own_text))
    tmp1 = gw.call('create_record', model='llmd.job.listing', values={'source': 'test', 'ext_id': 'snippet-test-%d' % int(time.time()), 'title': 'Snippet only job', 'company': 'Snippet Co', 'location': 'Pune, India',
                                                                     'tags': ',sales,', 'roles': ',sales_manager,', 'courses': ',sell-ai,', 'full_text': False, 'description_html': '<p>A short summary that the source provides about leading a regional sales team.</p>',
                                                                     'sections_json': '{"about": "A short summary that the source provides about leading a regional sales team.", "skills": ["CRM"]}', 'apply_url': 'https://example.com/snippet'})['id']
    tmp2 = gw.call('create_record', model='llmd.job.listing', values={'source': 'test', 'ext_id': 'bare-test-%d' % int(time.time()), 'title': 'Title only job', 'tags': ',sales,', 'roles': ',sales_manager,', 'courses': ',sell-ai,'})['id']
    pg = get('/jobs/ext/%d' % tmp1)[1]
    check('snippet-only source: a clear note (no site name), still one Apply Now', 'Only a short summary of this job is available' in text(pg) and len(re.findall(r'>\s*Apply Now', pg)) == 1)
    pg = get('/jobs/ext/%d' % tmp2)[1]
    head = re.search(r'<header class="o_llmd_head">(.*?)</header>', pg, re.S)
    check('missing fields: header shows only what exists (no empty company / salary / type lines), a disabled Apply Now (no link to send anybody to), friendly message',
          head and 'Title only job' in text(head.group(1)) and not re.search(r'fa-(building-o|map-marker|money|briefcase)', head.group(1)) and '/go' not in pg and 'valid application link is not available' in text(pg) and 'No description is available' in text(pg))
    for t_id in (tmp1, tmp2):
        gw.call('delete_record', model='llmd.job.listing', res_id=t_id)

    print('\n=== M. no job-site name is visible anywhere on the pages (a job that came from Adzuna, "via naukri.com", also on Jooble) ===')
    fx = make_fixtures(stamp + 1)
    try:
        shown = [('/jobs?q=ZZFX&loc=all', 'the board with the job card')] + [('/jobs/ext/%d' % fx['f1'], 'detail page'), ('/jobs?q=zzzqqqxxx', 'the board without any job (all page chrome)'),
                                                                              ('/jobs?course=sell-ai&loc=all&mode=hybrid', 'the board with filters and a course')]
        for path, label in shown:
            status, pg = get(path)
            visible = text(re.sub(r'<head>.*?</head>', '', pg, flags=re.S))
            if 'q=ZZFX' in path or path.startswith('/jobs/ext/'):
                hits = PLATFORM.findall(visible.replace('LinkedIn profile', ''))
            else:                                                     # real jobs may name an employer such as "Indeed": only the page chrome and the chips are checked
                chrome = re.sub(r'<article.*?</article>', '', pg, flags=re.S)
                hits = PLATFORM.findall(text(re.sub(r'<head>.*?</head>', '', chrome, flags=re.S)))
            check('%-44s no site name' % label, status == 200 and not hits and 'Source:' not in visible and 'Original listing' not in visible, hits)
    finally:
        for lid in fx.values():
            gw.call('delete_record', model='llmd.job.listing', res_id=lid)

    print('\n=== I. our own positions are untouched and listed on the landing page ===')
    own = gw.search('hr.job', [['website_published', '=', True]], 10)
    made_pos = None
    if not own:                                                           # this database has none: a TEMPORARY published position, deleted right after
        made_pos = gw.call('create_record', model='hr.job', values={'name': 'ZZ Test Position %d' % int(time.time()), 'is_published': True})['id']
        own = gw.search('hr.job', [['id', '=', made_pos]], 1)
    try:
        landing = get('/jobs')[1]
        block = (re.search(r'id="positions">.*?</section>', landing, re.S) or [''])[0]
        check('own position page still opens: %s' % own[0]['website_url'], get(own[0]['website_url'])[0] == 200)
        check('our own positions are listed on the landing page ("Open positions at LLM Decode") with View Details -> their own page', 'Open positions at LLM Decode' in text(landing)
              and own[0]['name'] in text(block) and 'href="%s"' % own[0]['website_url'] in block and 'View Details' in text(block))
    finally:
        if made_pos:
            gw.call('delete_record', model='hr.job', res_id=made_pos)
    sample = next((r for r in rows if r['apply_url']), None)
    if sample:
        status, _b, loc = Visitor().open('/jobs/ext/%d/go' % sample['id'])
        check('default: an anonymous Apply Now goes to the login page first (the signed-in flow itself: tests/apply_login_test.py)',
              status == 303 and loc.endswith('/web/login?redirect=%%2Fjobs%%2Fext%%2F%d%%2Fgo' % sample['id']), loc[:80])
    app_id0 = max([a['id'] for a in gw.search('llmd.job.application', [['active', 'in', [True, False]]], 1)] or [0])
    try:
        category_checks()
        apply_flow(rows, click0)
    finally:
        for c in gw.search('llmd.job.application', [['id', '>', app_id0], ['channel', '=', 'apply_now'], ['active', 'in', [True, False]]], 500):
            gw.call('delete_record', model='llmd.job.application', res_id=c['id'])          # the test account's Apply Now records (signed-in cards)
        ids = [c['id'] for c in gw.search('llmd.job.click', [['id', '>', click0]], 20000)]
        if ids:
            rpc('llmd.job.click', 'unlink', [ids])
        check('cleanup: the %d click lines of this test run are removed again (earlier real clicks stay)' % len(ids), not gw.search('llmd.job.click', [['id', '>', click0]], 3))


if __name__ == '__main__':
    main()
