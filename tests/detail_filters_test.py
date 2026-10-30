r"""The facts of a job detail page are filter links, against the LOCAL instance:

  1. every fact a job has (track badges, work mode, department, location, region, salary, employment type, experience level, years, posted date, company)
     is a link to the list of that filter - every filter a part of the path (/jobs/remote, /locations/delhi, /companies/harvey/remote/full-time ...) -
     built from the job's own values;
  2. every such link opens a listing whose number of jobs is exactly the number of stored jobs matching that filter (counted in Odoo), every job of its
     first page really matches, and the job itself matches;
  3. filters combine (company + mode + type + level), in our own words and in other names (work_mode, employment_type, department, experience_level,
     posted=today ...), which move to their one path (301); pages keep the filters;
  4. a fact the job does NOT have gives no link: no salary band, no experience level, an old posting date - nothing is made up.

  . .\scripts\env.ps1
  python tests\detail_filters_test.py
"""
import html
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gw  # noqa: E402
from board_test import count_of, get  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
if not gw.is_local():
    sys.exit('detail_filters_test.py runs against the LOCAL instance only.')
RESULTS = []


def rpc(model, method, args, kw=None):
    models, uid = gw._rpc()
    return models.execute_kw(os.environ['ODOO_DB'], uid, os.environ['ODOO_PASSWORD'], model, method, args, kw or {})


def count(dom):
    return rpc('llmd.job.listing', 'search_count', [dom])


def check(label, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' - %s' % (detail,)))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def head(path):
    """(status, location) without following a redirect."""
    try:
        r = urllib.request.build_opener(_NoRedirect()).open(urllib.request.Request(gw.site_url() + path, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60)
        return r.status, ''
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get('Location', '')


EXP_MAX = 25


TYPE_SLUGS = {'full-time': 'fulltime', 'part-time': 'parttime', 'internship': 'internship', 'contract': 'contract'}
POSTED_SLUGS = {'posted-24-hours': '1', 'posted-7-days': '7', 'posted-30-days': '30'}
_CACHE = {}


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')


def _values(field):
    """{slug: value} of a field of the open jobs (country, city)."""
    if field not in _CACHE:
        rows = rpc('llmd.job.listing', 'read_group', [[['active', '=', True], [field, '!=', False]], [field], [field]], {'lazy': False})
        _CACHE[field] = {_slug(r[field]): r[field] for r in rows}
    return _CACHE[field]


def _companies():
    if 'co' not in _CACHE:
        _CACHE['co'] = {c['slug']: c for c in rpc('llmd.company', 'search_read', [[]], {'fields': ['name', 'slug']})}
    return _CACHE['co']


def _salary_parts():
    """{path part: band} - salary-usd-150-200k, salary-inr-10-25-lpa, salary-usd-250k-plus (models/urls.py SALARY_PARTS)."""
    out = {}
    for code in ['inr-0-10', 'inr-10-25', 'inr-25-50', 'inr-50'] + ['%s-%s' % (c, b) for c in ('usd', 'eur', 'gbp') for b in ('0-100', '100-150', '150-200', '200-250', '250')]:
        cur, rest = code.split('-', 1)
        unit = '-lpa' if cur == 'inr' else 'k'
        out['salary-%s-%s' % (cur, rest + unit if '-' in rest else rest + unit + '-plus')] = code
    return out


def to_query(href):
    """(extra domain, {filter: [values]}) of a list address: the scope (/companies/<slug>, /categories/<slug>, /locations/<slug> ...) and every part of the path."""
    url = urllib.parse.urlparse(href)
    q = {k: list(v) for k, v in urllib.parse.parse_qs(url.query).items()}
    dom = []
    parts = [urllib.parse.unquote(x) for x in url.path.split('/') if x]
    scope, rest = parts[:1], parts[1:]
    if scope == ['companies']:
        dom.append(['company_id', '=', _companies()[rest[0]]['id']])
        rest = rest[1:]
    elif scope == ['categories']:
        q.setdefault('category', []).append(rest[0])
        rest = rest[1:]
    elif scope == ['departments']:
        q.setdefault('function', []).append(rest[0])
        rest = rest[1:]
    elif scope == ['locations']:
        if rest[0] in _values('country'):
            q['country'] = [_values('country')[rest[0]]]
        else:
            q.setdefault('city', []).append(_values('city')[rest[0]])
        rest = rest[1:]
    elif scope == ['regions']:
        q['region'] = [rest[0]]
        rest = rest[1:]
    elif rest[:1] == ['all']:
        rest = rest[1:]
    if len(rest) >= 2 and rest[-2] == 'page':
        rest = rest[:-2]
    salaries = _salary_parts()
    i = 0
    while i < len(rest):
        part = rest[i].rstrip('~')
        i += 1
        add = lambda k, v: q.setdefault(k, []).append(v)                          # noqa: E731
        years = re.fullmatch(r'(\d+)-(\d+|plus)-years-experience', part)
        if part == 'search':
            q['q'] = [rest[i].replace('-', ' ')]
            i += 1
        elif part == 'newest':
            pass
        elif part in ('remote', 'hybrid', 'onsite'):
            q['mode'] = [part]
        elif part in TYPE_SLUGS:
            add('jtype', TYPE_SLUGS[part])
        elif part.endswith('-level'):
            add('level', part[:-6])
        elif years:
            q['exp_min'] = [years.group(1)]
            if years.group(2) != 'plus':
                q['exp_max'] = [years.group(2)]
        elif part.startswith('in-'):
            slug = part[3:]
            if slug.endswith('-city'):
                add('city', _values('city')[slug[:-5]])
            elif slug in _values('country'):
                q['country'] = [_values('country')[slug]]
            else:
                add('city', _values('city')[slug])
        elif part.startswith('region-'):
            q['region'] = [part[7:]]
        elif part.startswith('category-'):
            add('category', part[9:])
        elif part.startswith('department-'):
            add('function', part[11:])
        elif part.startswith('company-'):
            add('company', _companies()[part[8:]]['name'])
        elif part in POSTED_SLUGS:
            q['posted'] = [POSTED_SLUGS[part]]
        elif part in salaries:
            add('salary', salaries[part])
        elif part.startswith('track-'):
            q['track'] = [part[6:]]
        else:
            raise ValueError('unknown part %r in %s' % (part, href))
    return dom, q


def kinds_of(href):
    dom, q = to_query(href)
    return (['company'] if dom else []) + sorted(q)


def domain_of(href):
    """The stored-job condition a filter link means (the same rules as the controller), as an Odoo domain."""
    extra, q = to_query(href)
    dom = [['active', '=', True]] + extra
    for key, vals in q.items():
        v = vals[0]
        if key == 'track':
            dom.append(['tags', 'ilike', ',%s,' % v])
        elif key == 'category':
            dom.append(['job_category', 'in', vals])
        elif key == 'mode':
            dom.append(['work_mode', '=', v])
        elif key == 'function':
            dom.append(['job_function', 'in', vals])
        elif key == 'city':
            dom.append(['city', 'in', vals])
        elif key == 'country':
            dom.append(['country', '=', v])
        elif key == 'region':
            dom.append(['india_zone' if v.endswith('-india') else 'region', '=', v])
        elif key == 'salary':
            dom.append(['salary_band', 'in', vals])
        elif key == 'jtype':
            dom.append(['job_type', 'in', vals])
        elif key == 'level':
            dom.append(['exp_level', 'in', vals])
        elif key == 'company':
            dom.append(['company', 'in', vals])
        elif key == 'q':
            for term in v.split()[:6]:
                dom += ['|', '|', ['title', 'ilike', term], ['company', 'ilike', term], ['search_text', 'ilike', term]]
        elif key == 'posted':
            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=int(v))
            dom.append(['posted', '>=', since.strftime('%Y-%m-%d %H:%M:%S')])
        elif key == 'exp_min':
            dom += [['exp_years_known', '=', True], ['exp_years_max', '>=', int(v)]]
            if 'exp_max' in q and int(q['exp_max'][0]) < EXP_MAX:
                dom.append(['exp_years_min', '<=', int(q['exp_max'][0])])
    return dom


def fact_links(page):
    """[(label, href)] of the filter links of a detail page header (badges, work mode, the facts, the company)."""
    header = (re.search(r'<header class="o_llmd_head">(.*?)</header>', page, re.S) or [None, ''])[1]
    out = []
    for attrs, inner in re.findall(r'<a\b([^>]*)>(.*?)</a>', header, re.S):
        h = re.search(r'href="([^"]+)"', attrs)
        if h and re.search(r'o_llmd_(tag_link|meta_link)', attrs):
            out.append((re.sub(r'<[^>]+>', '', html.unescape(inner)).strip(), html.unescape(h.group(1))))
    return out


def job_ids(page):
    """The job IDs of the cards of a list (from their Apply Now: the job pages are /jobs/<slug>)."""
    return [int(i) for i in re.findall(r'<article class="o_llmd_job o_llmd_card">.*?/jobs/ext/(\d+)/', page, re.S)]


def ids_matching(dom, ids):
    found = set(rpc('llmd.job.listing', 'search', [dom + [['id', 'in', ids]]]))
    return [i for i in ids if i not in found]


print('=== %s ===' % gw.target_name())
harvey = gw.search('llmd.job.listing', [['id', '=', 16882], ['active', '=', True]], 1) or gw.search('llmd.job.listing', [['active', '=', True], ['company', '=', 'Harvey']], 1)
rich = gw.search('llmd.job.listing', [['active', '=', True], ['salary_band', '!=', False], ['exp_level', '!=', ''], ['exp_years_known', '=', True], ['job_function', '!=', False]], 1)
inr = gw.search('llmd.job.listing', [['active', '=', True], ['salary_band', '=like', 'inr-%']], 1)
india = gw.search('llmd.job.listing', [['active', '=', True], ['india_zone', '!=', False], ['city', '!=', False]], 1)
samples = [j for j in (harvey + rich + inr + india) if j]
seen = set()
for job in samples:
    if job['id'] in seen:
        continue
    seen.add(job['id'])
    print('\n=== job %d: %s at %s (%s) ===' % (job['id'], job['title'][:60], job['company'], job['page_url']))
    status, page = get(job['page_url'])
    links = fact_links(page)
    kinds = sorted({k for _l, h in links for k in kinds_of(h)[:1]})
    check('the detail page opens and its facts are filter links: %s' % ', '.join(kinds), status == 200 and len(links) >= 5, links)
    for label, href in links:
        dom = domain_of(href)
        expected = count(dom)
        st, lp = get(href)
        shown = count_of(lp)
        ids = job_ids(lp)
        wrong = ids_matching(dom, ids)
        own = bool(count(dom + [['id', '=', job['id']]]))
        check('"%s" -> %s: %s jobs shown = %d stored jobs matching; all %d on page 1 match; the job itself matches' % (label[:30], href, shown, expected, len(ids)),
              st == 200 and shown == expected and expected > 0 and not wrong and own, {'shown': shown, 'expected': expected, 'wrong': wrong[:3], 'own': own})

print('\n=== the tags of the job CARDS (results, search, a company page, a category page, Latest Jobs) ===')


def card_links(page, latest=False):
    """{href: label} of the filter links inside the job cards of a page."""
    out = {}
    pat = r'<article class="o_llmd_lcard">(.*?)</article>' if latest else r'<article class="o_llmd_job o_llmd_card">(.*?)</article>'
    for part in re.findall(pat, page, re.S):
        for attrs, inner in re.findall(r'<a\b([^>]*)>(.*?)</a>', part, re.S):
            h = re.search(r'href="([^"]+)"', attrs)
            if h and re.search(r'o_llmd_(tag_link|loc_link|co_link)', attrs):
                out.setdefault(html.unescape(h.group(1)), re.sub(r'<[^>]+>', '', html.unescape(inner)).strip())
    return out


checked = set()
for page_path, latest in (('/jobs?q=engineer', False), ('/jobs/company/bosch-group', False), ('/jobs/category/finance', False), ('/jobs?mode=onsite&view=all', False), ('/jobs', True)):
    st, pg = get(page_path)
    links = card_links(pg, latest)
    kinds = sorted({k for h in links for k in kinds_of(h)[:1]} | {'company' for h in links if h.startswith('/companies/')})
    check('%s%s: the card tags are filter links (%d different): %s' % (page_path, ' (Latest Jobs cards)' if latest else '', len(links), ', '.join(kinds)),
          st == 200 and len(links) >= 5 and {'mode', 'jtype', 'posted'} <= set(kinds), kinds)
    for href, label in links.items():
        if href in checked:
            continue
        checked.add(href)
        dom = domain_of(href)
        expected = count(dom)
        st2, lp = get(href)
        ids = job_ids(lp)
        check('  card tag "%s" -> %s: %s shown = %d matching, page 1 all match' % (label[:28], href, count_of(lp), expected),
              st2 == 200 and count_of(lp) == expected and expected > 0 and not ids_matching(dom, ids), (count_of(lp), expected))

print('\n=== "All regions" removes only the region ===')
st, pg = get('/jobs?region=asia-pacific&mode=remote&jtype=fulltime')
allr = re.search(r'<a\b[^>]*o_llmd_all_regions[^>]*href="([^"]+)"|<a\b[^>]*href="([^"]+)"[^>]*o_llmd_all_regions', pg)
href = html.unescape((allr.group(1) or allr.group(2)) if allr else '')
q = to_query(href)[1] if href else {}
check('with a region chosen, the panel offers "All regions": %s - region gone, Remote + Full-time kept' % href,
      bool(allr) and 'region' not in q and q.get('mode') == ['remote'] and q.get('jtype') == ['fulltime'], href)
st, lp = get(href)
check('... and that list = every Remote + Full-time job (%s = %d)' % (count_of(lp), count(domain_of(href))), count_of(lp) == count(domain_of(href)))
st, pg = get('/jobs/remote')
check('without a region chosen there is no "All regions" link (nothing to clear)', 'o_llmd_all_regions' not in pg)

print('\n=== several filters together ===')
for href in ('/jobs/remote/region-asia-pacific/category-finance', '/jobs/full-time/2-3-years-experience/company-bosch-group',
             '/companies/harvey/remote/full-time', '/jobs/remote/full-time/senior-level/company-harvey', '/jobs/remote/full-time/salary-usd-150-200k/posted-7-days',
             '/jobs/senior-level/region-north-america/department-product'):
    dom = domain_of(href)
    expected = count(dom)
    st, lp = get(href)
    ids = job_ids(lp)
    check('%s: %s jobs shown = %d matching ALL the filters, every job of page 1 matches' % (href, count_of(lp), expected), st == 200 and count_of(lp) == expected and not ids_matching(dom, ids),
          (count_of(lp), expected))
st, lp = get('/jobs/full-time/senior-level')
nxt = re.search(r'href="([^"]*/page/2[^"]*)"', lp)
check('the pages of a filtered list keep the filters (page 2 link: %s)' % (html.unescape(nxt.group(1)) if nxt else None),
      bool(nxt) and html.unescape(nxt.group(1)) == '/jobs/full-time/senior-level/page/2')

print('\n=== the same filters written another way -> their one path (ONE 301) ===')
for given, want in (('/jobs?company=Harvey&work_mode=remote&employment_type=full-time', '/jobs/remote/full-time/company-harvey'),
                    ('/jobs?department=Product&experience_level=Senior-level', '/jobs/senior-level/department-product'),
                    ('/jobs?department=AI%2FML', '/jobs/track-aiml'),
                    ('/jobs?region=North%20America&posted=today', '/jobs/region-north-america/posted-24-hours'),
                    ('/jobs?salary_range=USD-150-200', '/jobs/salary-usd-150-200k'),
                    ('/jobs?region=Asia-Pacific', '/jobs/region-asia-pacific'),
                    ('/jobs?work_mode=remote', '/jobs/remote'),
                    ('/jobs?department=Finance%20%26%20Accounting', '/jobs/category-finance'),
                    ('/jobs?department=Engineering', '/jobs/department-engineering'),
                    ('/jobs?company=Bosch%20Group&employment_type=full-time', '/jobs/full-time/company-bosch-group'),
                    ('/jobs?experience=2-3', '/jobs/2-3-years-experience'),
                    ('/jobs?experience=5%2B', '/jobs/5-plus-years-experience'),
                    ('/jobs?experience=senior', '/jobs/senior-level'),
                    ('/jobs?posted=24h', '/jobs/posted-24-hours')):
    st, loc = head(given)
    check('%s -> %s' % (given, loc.replace(gw.site_url(), '')), st == 301 and loc.replace(gw.site_url(), '') == want, (st, loc))

print('\n=== a fact a job does not have is no link ===')
no_salary = gw.search('llmd.job.listing', [['active', '=', True], ['salary_band', '=', False], ['salary', '!=', False], ['salary', '!=', '']], 1) or \
    gw.search('llmd.job.listing', [['active', '=', True], ['salary_band', '=', False]], 1)
no_level = gw.search('llmd.job.listing', [['active', '=', True], ['exp_level', '=', '']], 1)
old = gw.search('llmd.job.listing', [['active', '=', True], ['posted', '<', (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=31)).strftime('%Y-%m-%d %H:%M:%S')]], 1)
for job, key, what in ((no_salary, 'salary', 'a salary that cannot be read for sure (%s)'), (no_level, 'level', 'no experience level'), (old, 'posted', 'posted more than 30 days ago')):
    if not job:
        print('  (no job with %s: skipped)' % key)
        continue
    j = job[0]
    links = fact_links(get(j['page_url'])[1])
    has = [h for _l, h in links if ('%s=' % key) in h]
    check('job %d, %s: no "%s" filter link' % (j['id'], (what % (j.get('salary') or '-')[:30]) if '%s' in what else what, key), not has, has)

print('\nRESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
