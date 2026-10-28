r"""Click check of the local job board: everything a visitor can click works.

  . .\scripts\env.ps1
  python tests\link_check.py            internal links + every job's View Details and Apply Now + a sample of the application pages (15 per site)
  python tests\link_check.py --no-ext   without opening the companies' application pages
  python tests\link_check.py --all-ext  every application page (about 1600: SmartRecruiters and Greenhouse then block this network for a while - avoid)

1. Opens the landing page, the all-jobs pages, every category, company, location and role page and the course-matched blocks, and then every internal link
   found on them (filters, chips, pages, sort, companies, categories, cards): each must answer 200 (or redirect to a page that does).
2. Every visible job: View Details (/jobs/ext/<id>) answers 200 with ONE Apply Now, and Apply Now (/jobs/ext/<id>/go) answers 303 to the application URL
   stored in Odoo. The checker says it is a link checker, so these visits are NOT saved as Apply clicks (checked at the end).
3. The application pages answer (the companies' own job pages), slowly and only a sample per site unless --all-ext: SmartRecruiters and Greenhouse refuse
   scripts (403) and block a network that opens hundreds of their pages at once. A refusal is counted separately; a 404 / 410 is a broken link.
"""
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import gw

sys.stdout.reconfigure(encoding='utf-8')
if not gw.is_local():
    sys.exit('link_check.py only runs against the local instance (run  . .\\scripts\\env.ps1  first).')

UA = {'User-Agent': 'LLMDecode link check (Mozilla/5.0 compatible)'}            # "check" = not a visitor: /go does not save a click for it
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
           'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'en-IN,en;q=0.9'}
SKIP = re.compile(r'^/(web|odoo|website|shop|slides|blog|forum|event|my|contactus|@)|^/$')
RESULTS = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


NO_REDIRECT = urllib.request.build_opener(_NoRedirect())


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


def get(path, follow=True):
    """(status, body, location) of a local page."""
    req = urllib.request.Request(gw.site_url() + path, headers=UA)
    try:
        r = (urllib.request.urlopen if follow else NO_REDIRECT.open)(req, timeout=60)
        return r.status, r.read().decode('utf-8', 'replace'), ''
    except urllib.error.HTTPError as exc:
        return exc.code, '', exc.headers.get('Location', '')
    except Exception as exc:                                                    # noqa: BLE001
        return 0, '', exc.__class__.__name__


def internal_links(page):
    out = set()
    for href in re.findall(r'\bhref="([^"]+)"', page):
        href = html.unescape(href).split('#', 1)[0]
        if href.startswith('/') and not href.startswith('//') and not SKIP.search(href):
            out.add(href)
    return out


def external(url):
    """(status, final url) of an application page, as a browser would open it."""
    req = urllib.request.Request(url, headers=BROWSER)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, url
    except Exception as exc:                                                    # noqa: BLE001
        return 0, '%s %s' % (url, exc.__class__.__name__)


def main():
    started = time.time()
    rows = gw.search('llmd.job.listing', [['active', '=', True]], 50000)
    clicks0 = len(gw.search('llmd.job.click', [], 100000))
    print('%d visible jobs in Odoo (Recruitment > Job board > Job board listings)' % len(rows))

    print('\n=== 1. every page of the board and every internal link on them ===')
    status, landing, _l = get('/jobs')
    status_all, all_jobs, _l = get('/jobs?view=all')
    count = re.search(r'(\d+)\s*jobs? found', re.sub(r'<[^>]+>', ' ', all_jobs))
    check('the website shows exactly the jobs stored in Odoo (all jobs: %s, Odoo: %d)' % (count and count.group(1), len(rows)), status == 200 and count and int(count.group(1)) == len(rows))
    pages = {'/jobs', '/jobs?view=all'}
    for href in internal_links(landing) | internal_links(all_jobs):
        if re.match(r'^/jobs/(category|company|location|role|region|course)/[^/?]+$', href) or href in ('/jobs/categories', '/jobs/regions', '/jobs/countries'):
            pages.add(href)
    for code in re.findall(r'data-course="([^"]+)"', landing):
        pages.add('/jobs/course-matches?course=%s' % code)
    found = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for path, (st, body, _l) in zip(sorted(pages), pool.map(get, sorted(pages))):
            found[path] = st
            for href in internal_links(body):
                found.setdefault(href, None)
    bad_pages = {p: s for p, s in found.items() if s is not None and s != 200}
    check('%d board pages open (landing, all jobs, every category / company / location / role page, the course blocks)' % len(pages), not bad_pages, list(bad_pages.items())[:5])
    links = sorted(h for h, s in found.items() if s is None and '/go' not in h)
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(lambda h: get(h)[0], links))
    broken = [(h, s) for h, s in zip(links, statuses) if s != 200]
    check('%d different links on those pages (filters, chips, pages, sort, companies, categories, places, View Details) all open' % len(links), not broken, broken[:8])

    print('\n=== 2. every visible job: View Details and Apply Now ===')
    ids = [r['id'] for r in rows]
    with ThreadPoolExecutor(max_workers=6) as pool:
        details = list(pool.map(lambda i: get('/jobs/ext/%d' % i), ids))
    no_detail = [i for i, (st, _b, _l) in zip(ids, details) if st != 200]
    applies = {}
    for i, (st, body, _l) in zip(ids, details):
        applies[i] = [html.unescape(a or b) for a, b in re.findall(r'<a\s[^>]*o_llmd_apply[^>]*href="([^"]+)"|<a\s[^>]*href="([^"]+)"[^>]*o_llmd_apply', body)]
    not_one = [i for i in ids if i not in no_detail and len(applies[i]) != 1]
    check('View Details: all %d job pages open, each with ONE Apply Now' % len(ids), not no_detail and not not_one, (no_detail[:5], not_one[:5]))
    by_id = {r['id']: r for r in rows}
    with ThreadPoolExecutor(max_workers=6) as pool:
        gos = list(pool.map(lambda i: get('/jobs/ext/%d/go' % i, follow=False), ids))
    wrong = [(i, st, loc[:60]) for i, (st, _b, loc) in zip(ids, gos) if not (st == 303 and loc == by_id[i]['apply_url'])]
    check('Apply Now: all %d jobs redirect (303) to the application URL stored in Odoo' % len(ids), not wrong, wrong[:5])
    hosts = Counter(urllib.parse.urlparse(r['apply_url']).hostname for r in rows)
    board_hosts = [h for h in hosts if re.search(r'jooble|adzuna|himalayas|indeed|naukri|linkedin', h or '')]
    check('every application URL is the company\'s own page or its job-board provider (%d hosts), never a job site' % len(hosts), not board_hosts and all(r['apply_url'] for r in rows), board_hosts)

    if '--no-ext' not in sys.argv:
        print('\n=== 3. every application page answers (the companies\' own sites) ===')
        urls = sorted({r['apply_url'] for r in rows})
        if '--all-ext' not in sys.argv:                                         # a polite sample: at most 15 pages per site, one site at a time per worker
            per_host = {}
            for u in urls:
                per_host.setdefault(urllib.parse.urlparse(u).hostname, []).append(u)
            urls = [u for found in per_host.values() for u in found[::max(1, len(found) // 15)][:15]]
            print('  a sample of %d application pages (at most 15 per site, %d sites)' % (len(urls), len(per_host)))

        def slow(url):
            time.sleep(0.5)
            return external(url)
        with ThreadPoolExecutor(max_workers=3 if '--all-ext' not in sys.argv else 12) as pool:
            res = dict(zip(urls, pool.map(slow, urls)))
        ok = [u for u, (st, _f) in res.items() if 200 <= st < 400]
        refused = [u for u, (st, _f) in res.items() if st in (401, 403, 429)]
        dead = [(u, st) for u, (st, _f) in res.items() if st in (404, 410)]
        other = [(u, st, f) for u, (st, f) in res.items() if not (200 <= st < 400) and st not in (401, 403, 429, 404, 410)]
        by_host = Counter(urllib.parse.urlparse(u).hostname for u in refused)
        print('  %d open, %d refuse scripts (open in a browser: %s), %d not found, %d other' % (len(ok), len(refused), dict(by_host.most_common(4)), len(dead), len(other)))
        check('no application page is gone (404 / 410)', not dead, dead[:8])
        check('no application page fails otherwise (time-out, server error)', len(other) <= max(2, len(urls) // 100), other[:5])

    clicks1 = len(gw.search('llmd.job.click', [], 100000))
    check('the link checker saved NO Apply click (it is not a visitor)', clicks1 == clicks0, '%d -> %d' % (clicks0, clicks1))
    print('\nLINK CHECK: %d/%d checks passed (%.0f s)' % (sum(RESULTS), len(RESULTS), time.time() - started))


if __name__ == '__main__':
    main()
