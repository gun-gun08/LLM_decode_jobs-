"""Job source adapters. Each one talks to ONE official API / authorized feed and returns jobs in the same normalized shape:

    source, ext_id, title, company, location, countries, employment_type, seniority, categories, posted (datetime or None),
    html (the description as the source gives it), full_text (True = the whole listing, False = only a short snippet),
    apply_url, source_url, via (original site named by the source, if any)

Nothing here scrapes a website. Keys / feed addresses are passed in by the caller (they come from environment variables, never from code).
No Odoo imports: the module can be tested on its own.
"""
import html as htmllib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

_logger = logging.getLogger(__name__)

TIMEOUT = 25
MAX_ATTEMPTS = 3                                    # one request + two retries for TEMPORARY failures
RETRY_STATUS = {429, 500, 502, 503, 504}
UA = {'User-Agent': 'LLMDecode-Odoo/1.0', 'Accept': 'application/json'}

ADZUNA_URL = 'https://api.adzuna.com/v1/api/jobs/%s/search/%d'
JSEARCH_URL = 'https://jsearch.p.rapidapi.com/search'
HIMALAYAS_URL = 'https://himalayas.app/jobs/api/search'
JOOBLE_URL = 'https://in.jooble.org/api/%s'                   # the India domain: jooble.org itself answers 403 (Cloudflare) to API calls


class SourceError(Exception):
    """A source could not be read (bad key, HTTP error, bad feed). The message is safe to show: it never contains a key."""


def _strip(text):
    """Plain text of a snippet / HTML: tags removed, entities decoded - also when the source escaped them twice or three times ("We&amp;#x27;re" -> "We're")."""
    plain = re.sub(r'<[^>]+>', ' ', text or '')
    for _round in range(3):
        decoded = htmllib.unescape(plain)
        if decoded == plain:
            break
        plain = decoded
    return re.sub(r'\s+', ' ', plain).strip()


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return parse_dt(int(text))
    text = re.sub(r'\.\d+', '', text)                                        # fractional seconds (Jooble sends 7 digits)
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%a, %d %b %Y %H:%M:%S'):
        try:
            return datetime.strptime(re.sub(r'(Z|[+-]\d{2}:?\d{2}| GMT)$', '', text), fmt)
        except ValueError:
            continue
    return None


def _send(method, url, count=None, **kwargs):
    """requests.get / requests.post with retries for TEMPORARY failures only: network errors, timeouts and HTTP 429 / 500 / 502 / 503 / 504 (up to MAX_ATTEMPTS tries, waiting 1 s, 2 s ...,
    longer when the server sends Retry-After). A bad key (401 / 403) or any other answer is returned at once. `count` is the request-budget counter of the plan: every retry is a real
    request, so it is counted too, and the retries stop when the budget is used up. Only the host is ever logged (a key can be part of the URL path)."""
    host = urlparse(url).netloc
    resp, error = None, None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            if count and not count():
                _logger.warning('%s: no retry, the request budget is used up', host)
                break
            retry_after = 0
            headers = getattr(resp, 'headers', None) or {}
            if str(headers.get('Retry-After', '')).isdigit():
                retry_after = min(int(headers['Retry-After']), 10)
            time.sleep(max(2 ** (attempt - 1), retry_after))
        try:
            resp, error = (requests.post if method == 'post' else requests.get)(url, **kwargs), None
        except requests.RequestException as exc:
            resp, error = None, exc
            _logger.warning('%s: temporary network problem (%s), attempt %d of %d', host, exc.__class__.__name__, attempt + 1, MAX_ATTEMPTS)
            continue
        if resp.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
            _logger.warning('%s: temporary answer HTTP %s, attempt %d of %d', host, resp.status_code, attempt + 1, MAX_ATTEMPTS)
            continue
        return resp
    if resp is not None:
        return resp
    raise error


def _check(resp, name):
    if resp.status_code in (401, 403):
        raise SourceError('%s refused the credentials (HTTP %s) - check the key in .env' % (name, resp.status_code))
    if resp.status_code == 429:
        raise SourceError('%s rate limit reached (HTTP 429) - try again later' % name)
    if resp.status_code != 200:
        raise SourceError('%s answered HTTP %s' % (name, resp.status_code))


def _split(item):
    """A search is either a plain query or (query, mode) with mode '' / 'remote' / 'hybrid'."""
    if isinstance(item, (tuple, list)):
        return str(item[0]), (str(item[1]) if len(item) > 1 else '')
    return str(item), ''


def _words(query, mode):
    """The search words sent to a job API: the query, plus 'remote' / 'hybrid' when that variant is asked for."""
    return ('%s %s' % (query, mode)).strip()


def _text_html(text):
    return '<p>%s</p>' % htmllib.escape(text) if text else ''


_PERIODS = {'hourly': 'per hour', 'hour': 'per hour', 'daily': 'per day', 'day': 'per day', 'weekly': 'per week', 'week': 'per week', 'monthly': 'per month', 'month': 'per month',
            'yearly': 'per year', 'annual': 'per year', 'year': 'per year'}


def format_salary(low, high, currency='', period=''):
    """'USD 70,000 \u2013 150,000 per year' from the numbers a source gives; '' when it gives none."""
    def num(x):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return None
        return x if x > 0 else None
    low, high = num(low), num(high)
    if not low and not high:
        return ''
    body = '{:,.0f} \u2013 {:,.0f}'.format(low, high) if low and high and low != high else '{:,.0f}'.format(low or high)
    return ' '.join(x for x in ((currency or '').strip(), body, _PERIODS.get((period or '').lower(), '')) if x)


# ---------------------------------------------------------------------------------------------------------------- Himalayas (no key) - TEMPORARY fallback, remote jobs only
def fetch_himalayas(queries, country='IN', page=1):
    """Himalayas' public job API: no key, remote jobs only, full text. Used only while no keyed source delivers enough jobs (see Listing.fetch_now). Its search has no work-mode
    variants, so only the plain queries are sent; `country` limits it to listings that are open to that country."""
    jobs, seen = [], set()
    for item in queries:
        position_query, mode = _split(item)
        if mode:
            continue
        params = {'q': position_query, 'sort': 'relevant', 'page': page}
        if country:
            params['country'] = country
        try:
            resp = _send('get', HIMALAYAS_URL, params=params, timeout=TIMEOUT, headers=UA)
        except requests.RequestException as exc:
            raise SourceError('Himalayas unreachable (%s)' % exc.__class__.__name__)
        _check(resp, 'Himalayas')
        for position, j in enumerate(resp.json().get('jobs', [])):
            ext_id = (j.get('guid') or j.get('applicationLink') or '').strip()
            if not ext_id or ext_id in seen:
                continue
            seen.add(ext_id)
            restr = j.get('locationRestrictions') or []
            if not restr:
                location = 'Remote \u00b7 Worldwide'
            elif 'India' in restr:
                location = 'Remote \u00b7 India' + (' + %d more countries' % (len(restr) - 1) if len(restr) > 1 else '')
            else:
                location = 'Remote \u00b7 ' + ', '.join(restr[:3]) + (' +%d' % (len(restr) - 3) if len(restr) > 3 else '')
            jobs.append({
                'source': 'Himalayas', 'ext_id': ext_id, 'title': _strip(j.get('title')), 'company': (j.get('companyName') or '').strip(), 'location': location,
                'countries': ', '.join(restr) or 'Worldwide', 'employment_type': j.get('employmentType') or '', 'seniority': ', '.join(j.get('seniority') or []),
                'categories': ', '.join(j.get('categories') or [])[:250], 'posted': parse_dt(j.get('pubDate')), 'html': j.get('description') or '', 'full_text': True,
                'apply_url': j.get('applicationLink') or '', 'source_url': j.get('guid') or j.get('applicationLink') or '', 'via': '', 'position': position,
                'salary': format_salary(j.get('minSalary'), j.get('maxSalary'), j.get('currency'), j.get('salaryPeriod'))})
        time.sleep(0.3)
    return jobs


# ---------------------------------------------------------------------------------------------------------------- Adzuna (app id + key)
def fetch_adzuna(app_id, app_key, queries, country='in', results=20):
    """https://developer.adzuna.com - the API returns only a snippet of each description."""
    jobs, seen = [], set()
    for item in queries:
        q, mode = _split(item)
        params = {'app_id': app_id, 'app_key': app_key, 'what': _words(q, mode), 'results_per_page': results, 'content-type': 'application/json'}
        try:
            resp = _send('get', ADZUNA_URL % (country, 1), params=params, timeout=TIMEOUT, headers=UA)
        except requests.RequestException as exc:
            raise SourceError('Adzuna unreachable (%s)' % exc.__class__.__name__)
        _check(resp, 'Adzuna')
        for position, j in enumerate(resp.json().get('results', [])):
            ext_id = str(j.get('id') or '').strip()
            if not ext_id or ext_id in seen:
                continue
            seen.add(ext_id)
            contract = ' '.join(x.replace('_', ' ') for x in (j.get('contract_time'), j.get('contract_type')) if x)
            jobs.append({
                'source': 'Adzuna', 'ext_id': ext_id, 'title': _strip(j.get('title')), 'company': ((j.get('company') or {}).get('display_name') or '').strip(),
                'location': (j.get('location') or {}).get('display_name') or '', 'countries': country.upper(), 'employment_type': contract.title(), 'seniority': '',
                'categories': (j.get('category') or {}).get('label') or '', 'posted': parse_dt(j.get('created')), 'html': _text_html(_strip(j.get('description'))), 'full_text': False,
                'apply_url': j.get('redirect_url') or '', 'source_url': j.get('redirect_url') or '', 'via': '', 'position': position,
                'salary': '' if str(j.get('salary_is_predicted')) in ('1', 'True', 'true') else format_salary(j.get('salary_min'), j.get('salary_max'), 'INR' if country == 'in' else '', 'annual')})
        time.sleep(0.3)
    return jobs


# ---------------------------------------------------------------------------------------------------------------- Jooble (api key)
def fetch_jooble(api_key, queries, location='India', count_request=None):
    """https://jooble.org/api/about - one POST per query; the free plan allows only 500 requests per key, so the caller counts them."""
    jobs, seen = [], set()
    for item in queries:
        q, mode = _split(item)
        if count_request and not count_request():
            raise SourceError('Jooble request budget used up - raise llmd_agg.jooble_budget only if your plan allows more')
        try:
            resp = _send('post', JOOBLE_URL % api_key, count=count_request, json={'keywords': _words(q, mode), 'location': location}, timeout=TIMEOUT, headers=UA)
        except requests.RequestException as exc:
            raise SourceError('Jooble unreachable (%s)' % exc.__class__.__name__)
        _check(resp, 'Jooble')
        for position, j in enumerate(resp.json().get('jobs', [])):
            ext_id = str(j.get('id') or j.get('link') or '').strip()
            if not ext_id or ext_id in seen:
                continue
            seen.add(ext_id)
            jobs.append({
                'source': 'Jooble', 'ext_id': ext_id, 'title': _strip(j.get('title')), 'company': (j.get('company') or '').strip(), 'location': j.get('location') or '',
                'countries': location, 'employment_type': j.get('type') or '', 'seniority': '', 'categories': '', 'posted': parse_dt(j.get('updated')),
                'html': _text_html(_strip(j.get('snippet'))), 'full_text': False, 'apply_url': j.get('link') or '', 'source_url': j.get('link') or '',
                'via': (j.get('source') or '').strip(), 'position': position, 'salary': _strip(j.get('salary'))[:80]})
        time.sleep(0.3)
    return jobs


# ---------------------------------------------------------------------------------------------------------------- JSearch (API key)
JSEARCH_TYPES = {'FULLTIME': 'Full Time', 'PARTTIME': 'Part Time', 'CONTRACTOR': 'Contract', 'INTERN': 'Internship'}
COUNTRY_NAMES = {'IN': 'India'}


def _experience_label(required):
    """JSearch's job_required_experience -> the label the Experience filter understands ('' when the job does not say)."""
    if not isinstance(required, dict):
        return ''
    if required.get('no_experience_required'):
        return 'Fresher'
    months = required.get('required_experience_in_months')
    if not isinstance(months, (int, float)):
        return ''
    return 'Fresher' if months <= 0 else 'Entry-level' if months < 30 else 'Mid-level' if months < 84 else 'Senior-level'


def _jsearch_html(job):
    """The job text as HTML with Responsibilities / Qualifications headings, so the page can build its short sections from it."""
    out = []
    for para in re.split(r'\n\s*\n', (job.get('job_description') or '').replace('\r\n', '\n')):
        para = para.strip()
        if para:
            out.append('<p>%s</p>' % htmllib.escape(para).replace('\n', '<br/>'))
    highlights = job.get('job_highlights') or {}
    for key in ('Responsibilities', 'Qualifications'):
        items = [i.strip() for i in (highlights.get(key) or []) if isinstance(i, str) and i.strip()]
        if items:
            out.append('<h3>%s</h3><ul>%s</ul>' % (key, ''.join('<li>%s</li>' % htmllib.escape(i) for i in items)))
    return ''.join(out)


def fetch_jsearch(api_key, queries, base_url='', country='in', count_request=None):
    """JSearch (RapidAPI, or OpenWebNinja when base_url points there): job search over several job sites, with the full job text and the employer's own apply link when it has one.
    One request per query; the free plans are small, so the caller counts the requests (count_request) and stops at its budget."""
    url = (base_url or JSEARCH_URL).strip()
    headers = dict(UA)
    if 'rapidapi' in url:
        headers.update({'X-RapidAPI-Key': api_key, 'X-RapidAPI-Host': urlparse(url).netloc})
    else:
        headers['x-api-key'] = api_key
    jobs, seen = [], set()
    for item in queries:
        q, mode = _split(item)
        if count_request and not count_request():
            raise SourceError('JSearch request budget used up for this month - raise llmd_agg.jsearch_budget only if your plan allows more')
        params = {'query': '%s in India' % _words(q, 'hybrid' if mode == 'hybrid' else ''), 'page': 1, 'num_pages': 1, 'country': country, 'date_posted': 'month'}
        if mode == 'remote':
            params['remote_jobs_only'] = 'true'                     # JSearch's own remote filter (the other modes have none: "hybrid" goes into the query words)
        try:
            resp = _send('get', url, count=count_request, params=params, timeout=TIMEOUT + 10, headers=headers)
        except requests.RequestException as exc:
            raise SourceError('JSearch unreachable (%s)' % exc.__class__.__name__)
        _check(resp, 'JSearch')
        payload = resp.json() or {}
        if str(payload.get('status') or 'OK').upper() == 'ERROR':
            raise SourceError('JSearch answered with an error: %s' % str((payload.get('error') or {}).get('message') or 'unknown')[:120])
        for position, j in enumerate(payload.get('data') or []):
            ext_id = str(j.get('job_id') or '').strip()
            options = [o for o in (j.get('apply_options') or []) if isinstance(o, dict) and o.get('apply_link')]
            apply_url = next((o['apply_link'] for o in options if o.get('is_direct')), '') or j.get('job_apply_link') or (options[0]['apply_link'] if options else '')
            if not ext_id or ext_id in seen or not _strip(j.get('job_title')):
                continue
            seen.add(ext_id)
            city, state, code = (j.get('job_city') or '').strip(), (j.get('job_state') or '').strip(), (j.get('job_country') or '').strip()
            place = ', '.join(p for p in (city, state, COUNTRY_NAMES.get(code.upper(), code)) if p) or (j.get('job_location') or '')
            if j.get('job_is_remote'):
                place = 'Remote' + (' \u00b7 ' + place if place else '')
            kinds = j.get('job_employment_types') or [j.get('job_employment_type')]
            description = _jsearch_html(j)
            jobs.append({
                'source': 'JSearch', 'ext_id': ext_id, 'title': _strip(j.get('job_title')), 'company': (j.get('employer_name') or '').strip(), 'location': place,
                'countries': code.upper(), 'employment_type': next((JSEARCH_TYPES[k] for k in kinds if k in JSEARCH_TYPES), ''), 'seniority': _experience_label(j.get('job_required_experience')),
                'categories': '', 'posted': parse_dt(j.get('job_posted_at_datetime_utc') or j.get('job_posted_at_timestamp')), 'html': description,
                'full_text': len(_strip(j.get('job_description'))) > 300, 'apply_url': apply_url, 'source_url': apply_url, 'via': (j.get('job_publisher') or '').strip(), 'position': position,
                'salary': format_salary(j.get('job_min_salary'), j.get('job_max_salary'), j.get('job_salary_currency'), j.get('job_salary_period'))})
        time.sleep(0.3)
    return jobs


# ---------------------------------------------------------------------------------------------------------------- authorized feeds (Indeed / Naukri partner feeds)
_XML_FIELDS = {
    'title': ('title', 'jobtitle', 'position'), 'company': ('company', 'employer', 'companyname'), 'html': ('description', 'jobdescription', 'content', 'summary'),
    'apply_url': ('applyurl', 'apply_url', 'url', 'link', 'joburl'), 'ext_id': ('referencenumber', 'jobid', 'id', 'guid', 'reference'),
    'posted': ('date', 'pubdate', 'posted', 'dateposted', 'created'), 'city': ('city',), 'state': ('state', 'region'), 'country': ('country',), 'location': ('location', 'joblocation'),
    'employment_type': ('jobtype', 'employmenttype', 'type'), 'categories': ('category', 'industry'),
}


def _pick(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, ''):
            return value if not isinstance(value, (dict, list)) else ''
    return ''


def _rows_from_xml(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceError('the feed is not valid XML (%s)' % exc)
    rows = []
    for node in root.iter():
        if node.tag.lower().split('}')[-1] in ('job', 'item', 'listing'):
            row = {}
            for child in node:
                row[child.tag.lower().split('}')[-1]] = ''.join(child.itertext()).strip()
            if row:
                rows.append(row)
    return rows


def _rows_from_json(content):
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise SourceError('the feed is not valid JSON (%s)' % exc)
    if isinstance(data, dict):
        data = data.get('jobs') or data.get('results') or data.get('data') or data.get('items') or []
    return [{str(k).lower(): v for k, v in row.items()} for row in data if isinstance(row, dict)]


def parse_feed(content, source_name):
    """Normalize an XML or JSON job feed that a partner / employer is authorized to give us."""
    content = (content or '').strip()
    rows = _rows_from_xml(content) if content.startswith('<') else _rows_from_json(content)
    jobs, seen = [], set()
    for position, row in enumerate(rows):
        title, apply_url = _strip(str(_pick(row, _XML_FIELDS['title']))), str(_pick(row, _XML_FIELDS['apply_url'])).strip()
        ext_id = str(_pick(row, _XML_FIELDS['ext_id']) or apply_url).strip()
        if not title or not ext_id or ext_id in seen:
            continue
        seen.add(ext_id)
        place = ', '.join(p for p in (str(_pick(row, _XML_FIELDS['city'])), str(_pick(row, _XML_FIELDS['state'])), str(_pick(row, _XML_FIELDS['country']))) if p) or str(_pick(row, _XML_FIELDS['location']))
        description = str(_pick(row, _XML_FIELDS['html']))
        jobs.append({
            'source': source_name, 'ext_id': ext_id, 'title': title, 'company': str(_pick(row, _XML_FIELDS['company'])).strip(), 'location': place,
            'countries': str(_pick(row, _XML_FIELDS['country'])), 'employment_type': str(_pick(row, _XML_FIELDS['employment_type'])), 'seniority': '',
            'categories': str(_pick(row, _XML_FIELDS['categories'])), 'posted': parse_dt(_pick(row, _XML_FIELDS['posted'])),
            'html': description if '<' in description else _text_html(description), 'full_text': len(_strip(description)) > 600, 'apply_url': apply_url, 'source_url': apply_url,
            'via': '', 'position': position, 'salary': _strip(str(_pick(row, ('salary', 'compensation', 'pay'))))[:80]})
    return jobs


def fetch_feed(url, token, source_name):
    headers = dict(UA)
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        resp = _send('get', url, timeout=TIMEOUT + 20, headers=headers)
    except requests.RequestException as exc:
        raise SourceError('%s feed unreachable (%s)' % (source_name, exc.__class__.__name__))
    _check(resp, source_name + ' feed')
    return parse_feed(resp.text, source_name)


# ---------------------------------------------------------------------------------------------------------------- Company job boards (no key)
# The public job-board APIs that the ATS providers offer so that a company's jobs can be shown on other sites. Every job links straight to the company's
# own job / application page: Apply Now skips every job board in between.
GREENHOUSE_URL = 'https://boards-api.greenhouse.io/v1/boards/%s/jobs'
LEVER_URL = 'https://api.lever.co/v0/postings/%s'
ASHBY_URL = 'https://api.ashbyhq.com/posting-api/job-board/%s'
SMARTRECRUITERS_URL = 'https://api.smartrecruiters.com/v1/companies/%s/postings'
ATS_NAMES = {'greenhouse': 'Greenhouse', 'lever': 'Lever', 'ashby': 'Ashby', 'smartrecruiters': 'SmartRecruiters'}
ATS_PREFIX = {'greenhouse': 'gh', 'lever': 'lv', 'ashby': 'ab', 'smartrecruiters': 'sr'}
EMPLOYMENT = {'fulltime': 'Full Time', 'full-time': 'Full Time', 'full time': 'Full Time', 'parttime': 'Part Time', 'part-time': 'Part Time', 'intern': 'Internship', 'internship': 'Internship',
              'contract': 'Contract', 'contractor': 'Contract', 'temporary': 'Contract'}
try:                                                                    # the ISO country codes SmartRecruiters sends ("in", "de", "br") -> the country names of the board
    from .job_facets import COUNTRY_OF_CODE as COUNTRY_CODES, country_of
except ImportError:                                                     # imported on its own (the unit tests)
    from job_facets import COUNTRY_OF_CODE as COUNTRY_CODES, country_of


def _by_country(jobs, limit):
    """At most `limit` of `jobs` (newest first), taken in turns from each country they are in (the country whose newest job is newest first), so that a company
    hiring in many countries shows jobs from each of them - Hong Kong and Shanghai too - instead of only its newest country."""
    groups = {}
    for j in jobs:
        groups.setdefault(country_of(j['location']) or '', []).append(j)
    queues = list(groups.values())
    out = []
    while len(out) < limit and queues:
        for q in list(queues):
            if len(out) >= limit:
                break
            out.append(q.pop(0))
            if not q:
                queues.remove(q)
    return out


def parse_boards(text):
    """"greenhouse:stripe, lever:paytm=Paytm" (commas or new lines) -> [(ats, token, display name or '')]; unknown providers are left out."""
    boards = []
    for entry in re.split(r'[,\n]+', text or ''):
        entry = entry.strip()
        m = re.match(r'^(greenhouse|lever|ashby|smartrecruiters)\s*:\s*([A-Za-z0-9._-]+)\s*(?:=\s*(.+))?$', entry, re.I)
        if m:
            boards.append((m.group(1).lower(), m.group(2), (m.group(3) or '').strip()))
    return boards


def _employment(value):
    return EMPLOYMENT.get(re.sub(r'\s*employment$', '', str(value or '').strip().lower()), str(value or '').strip())


def _place(location, mode):
    """The location as the other sources write it: "Remote · ..." for a remote job, "... (Hybrid)" for a hybrid one."""
    location = (location or '').strip()
    mode = (mode or '').lower()
    if 'remote' in mode:
        return 'Remote' + (' · ' + location if location else '')
    if 'hybrid' in mode and 'hybrid' not in location.lower():
        return (location + ' (Hybrid)') if location else 'Hybrid'
    return location


def _first(locations, keep_place):
    """The first of several locations that `keep_place` accepts (an Indian office of a multi-country job), else the first one."""
    locations = [l for l in locations if l]
    return next((l for l in locations if keep_place(l)), locations[0] if locations else '')


def _greenhouse(token, name, keep, keep_place, ids=None):
    resp = _send('get', GREENHOUSE_URL % token, params={'content': 'true'}, timeout=60, headers=UA)
    _check(resp, 'Greenhouse')
    out = []
    for j in resp.json().get('jobs') or []:
        if ids is not None:
            ids.add('gh:%s:%s' % (token, j.get('id')))
        offices = [o.get('location') or o.get('name') or '' for o in (j.get('offices') or [])]
        location = _first([(j.get('location') or {}).get('name') or ''] + offices, keep_place)
        title = _strip(j.get('title'))
        department = ', '.join(d.get('name') or '' for d in (j.get('departments') or []))
        if not keep(title, location, department):
            continue
        out.append({'ext_id': 'gh:%s:%s' % (token, j.get('id')), 'title': title, 'company': (j.get('company_name') or name or '').strip(), 'location': location,
                    'html': htmllib.unescape(j.get('content') or ''), 'apply_url': j.get('absolute_url') or '', 'posted': parse_dt(j.get('first_published') or j.get('updated_at')),
                    'employment_type': '', 'salary': '', 'categories': ', '.join(d.get('name') or '' for d in (j.get('departments') or []))})
    return out


def _lever(token, name, keep, keep_place, ids=None):
    resp = _send('get', LEVER_URL % token, params={'mode': 'json'}, timeout=90, headers=UA)          # Lever answers slowly for big boards
    _check(resp, 'Lever')
    data = resp.json()
    if not isinstance(data, list):
        raise SourceError('Lever: "%s" is not a job board' % token)
    out = []
    for j in data:
        if ids is not None:
            ids.add('lv:%s:%s' % (token, j.get('id')))
        cat = j.get('categories') or {}
        location = _place(_first([cat.get('location') or ''] + list(cat.get('allLocations') or []), keep_place), j.get('workplaceType'))
        title = _strip(j.get('text'))
        if not keep(title, location, cat.get('department') or cat.get('team') or ''):
            continue
        parts = [j.get('description') or '']
        for block in j.get('lists') or []:
            parts.append('<h3>%s</h3><ul>%s</ul>' % (htmllib.escape(_strip(block.get('text'))), block.get('content') or ''))
        parts.append(j.get('additional') or '')
        out.append({'ext_id': 'lv:%s:%s' % (token, j.get('id')), 'title': title, 'company': name or token.capitalize(), 'location': location, 'html': ''.join(parts),
                    'apply_url': j.get('applyUrl') or j.get('hostedUrl') or '', 'posted': parse_dt(int(j['createdAt']) // 1000) if str(j.get('createdAt') or '').isdigit() else None, 'employment_type': _employment(cat.get('commitment')),
                    'salary': '', 'categories': cat.get('department') or cat.get('team') or ''})
    return out


def _ashby(token, name, keep, keep_place, ids=None):
    resp = _send('get', ASHBY_URL % token, params={'includeCompensation': 'true'}, timeout=60, headers=UA)
    _check(resp, 'Ashby')
    out = []
    for j in resp.json().get('jobs') or []:
        if j.get('isListed') is False:
            continue
        if ids is not None:
            ids.add('ab:%s:%s' % (token, j.get('id')))
        mode = 'remote' if j.get('isRemote') else (j.get('workplaceType') or '')
        location = _place(_first([j.get('location') or ''] + [s.get('location') or '' for s in (j.get('secondaryLocations') or [])], keep_place), mode)
        title = _strip(j.get('title'))
        if not keep(title, location, j.get('department') or j.get('team') or ''):
            continue
        pay = (j.get('compensation') or {}).get('compensationTierSummary') if j.get('shouldDisplayCompensationOnJobPostings') else ''
        out.append({'ext_id': 'ab:%s:%s' % (token, j.get('id')), 'title': title, 'company': name or token.capitalize(), 'location': location, 'html': j.get('descriptionHtml') or '',
                    'apply_url': j.get('jobUrl') or j.get('applyUrl') or '', 'posted': parse_dt(j.get('publishedAt')), 'employment_type': _employment(j.get('employmentType')),
                    'salary': (pay or '')[:80], 'categories': j.get('department') or j.get('team') or ''})
    return out


def _sr_pages(token, keep, country, max_pages, ids, seen):
    """[(posting, location, title)] that `keep` takes from up to `max_pages` pages of 100 postings (only `country`'s when given); True when the list was read to its end."""
    picked, offset = [], 0
    while offset < max_pages * 100:
        resp = _send('get', SMARTRECRUITERS_URL % token, params=dict({'limit': 100, 'offset': offset}, **({'country': country} if country else {})), timeout=40, headers=UA)
        _check(resp, 'SmartRecruiters')
        data = resp.json()
        page = data.get('content') or []
        for j in page:
            if ids is not None:
                ids.add('sr:%s:%s' % (token, j.get('id')))
            if j.get('id') in seen:
                continue
            seen.add(j.get('id'))
            loc = j.get('location') or {}
            code = COUNTRY_CODES.get(str(loc.get('country') or '').lower(), str(loc.get('country') or '').upper())
            location = _place(', '.join(x for x in (loc.get('city') or '', loc.get('region') or '', code) if x), 'remote' if loc.get('remote') else '')
            title = _strip(j.get('name'))
            if keep(title, location, (j.get('function') or {}).get('label') or ''):
                picked.append((j, location, title))
        offset += 100
        if len(page) < 100 or offset >= (data.get('totalFound') or 0):
            return picked, True
        time.sleep(0.2)
    return picked, False


SR_DETAIL_WORKERS = 4                                                   # detail requests of ONE SmartRecruiters board at the same time
SR_DETAIL_SECONDS = 60                                                  # how long ONE SmartRecruiters board may read details (the newest first): a big board (Bosch) or a slow
                                                                        # API must not keep a scheduled run past the server's time limit - the rest come on a later run


def _smartrecruiters(token, name, keep, keep_place, per_board, country=None, ids=None, per_board_world=0, world_pages=3):
    """SmartRecruiters lists 100 postings per page. With `country` (an ISO code such as "in"): ALL its postings in that country (at most 10 pages), then - when
    `per_board_world` - the first `world_pages` pages of its postings everywhere else. Only the kept ones are read in detail (one request each), at most
    `per_board` of the home country and `per_board_world` elsewhere, the newest. `ids` gets the ids of the listed postings - and None when a list was not read to
    its end, so that nothing is hidden because of an incomplete list; `ids_home` (the "<key>:in" set) holds the complete home-country list."""
    deadline = time.monotonic() + SR_DETAIL_SECONDS
    seen = set()
    home_ids = set() if country else None
    picked, complete = _sr_pages(token, keep, country, 10, home_ids if country else ids, seen)
    if country:
        if complete and ids is not None:
            ids.update(home_ids)
            ids.add(('home', country))
        elif ids is not None:
            ids.add(None)
        world, world_complete = _sr_pages(token, keep, None, world_pages, ids, seen) if per_board_world else ([], False)
        if ids is not None and not world_complete:
            ids.add(None)
        home = sorted(picked, key=lambda x: x[0].get('releasedDate') or '', reverse=True)[:per_board]
        away = sorted([w for w in world if not keep_place(w[1])], key=lambda x: x[0].get('releasedDate') or '', reverse=True)[:per_board_world]
        picked = home + away
    else:
        if ids is not None and not complete:
            ids.add(None)
        picked = sorted(picked, key=lambda x: x[0].get('releasedDate') or '', reverse=True)[:per_board]
    def one(item):                                                      # the text is only in the detail of a posting: read it for the jobs that are kept
        j, location, title = item
        if time.monotonic() > deadline:
            return None
        detail = _send('get', (SMARTRECRUITERS_URL % token) + '/' + str(j.get('id')), timeout=30, headers=UA)
        time.sleep(0.15)
        if detail.status_code != 200:
            return None
        d = detail.json()
        sections = (d.get('jobAd') or {}).get('sections') or {}
        html = ''.join('<h3>%s</h3>%s' % (htmllib.escape(_strip((sections.get(k) or {}).get('title'))), (sections.get(k) or {}).get('text') or '')
                       for k in ('jobDescription', 'qualifications', 'additionalInformation', 'companyDescription') if (sections.get(k) or {}).get('text'))
        # a company name given in the board list wins over the one SmartRecruiters sends ("SWIGGY" -> Swiggy)
        return {'ext_id': 'sr:%s:%s' % (token, j.get('id')), 'title': title, 'company': (name or (j.get('company') or {}).get('name') or token).strip(), 'location': location,
                'html': html, 'apply_url': d.get('applyUrl') or d.get('postingUrl') or '', 'posted': parse_dt(j.get('releasedDate')),
                'employment_type': _employment((j.get('typeOfEmployment') or {}).get('label')), 'salary': '', 'categories': (j.get('function') or {}).get('label') or '',
                'seniority': (j.get('experienceLevel') or {}).get('label') or ''}

    # a few details at a time (SR_DETAIL_WORKERS): a whole sync must stay well inside Odoo's time limit of a request / scheduled action, without hammering one host
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=SR_DETAIL_WORKERS) as pool:
        return [job for job in pool.map(one, picked) if job]


ATS_PREFIX = {'greenhouse': 'gh', 'lever': 'lv', 'ashby': 'ab', 'smartrecruiters': 'sr'}           # the first part of a company-board job's ext_id


def fetch_company_boards(boards, keep, keep_place=None, per_board=100, workers=10, country=None, listed=None, per_board_world=None):
    """The jobs of the companies' own job boards. `boards` = parse_boards(); `keep(title, location, department)` decides which jobs fit (a course role or a job
    category). Per company at most `per_board` jobs in the home country (`keep_place` says which, e.g. India) and `per_board_world` elsewhere, the newest of each, so
    that no company fills the board (`per_board_world` None: `per_board` jobs wherever they are). `country` (the home country's ISO code) lets the SmartRecruiters
    boards list their home-country postings in full. A board that does not answer is skipped; when none answers -> SourceError.
    `listed` (a dict, optional) gets, for every board that answered completely, the ids of ALL the postings it lists now ("gh:stripe" -> {"gh:stripe:123", ...}):
    a stored job of that board that is not among them was closed by the company."""
    from concurrent.futures import ThreadPoolExecutor
    keep_place = keep_place or (lambda location: True)

    def one(board):
        ats, token, name = board
        ids = set()
        if ats == 'greenhouse':
            jobs = _greenhouse(token, name, keep, keep_place, ids)
        elif ats == 'lever':
            jobs = _lever(token, name, keep, keep_place, ids)
        elif ats == 'ashby':
            jobs = _ashby(token, name, keep, keep_place, ids)
        else:
            jobs = _smartrecruiters(token, name, keep, keep_place, per_board, country, ids, per_board_world or 0)
        key = '%s:%s' % (ATS_PREFIX[ats], token)
        if listed is not None and None not in ids:
            listed[key] = {i for i in ids if isinstance(i, str)}
        elif listed is not None and ('home', country) in ids:                  # SmartRecruiters: the home-country list is complete even when the world list is not
            listed[key + ':' + country] = {i for i in ids if isinstance(i, str)}
        jobs.sort(key=lambda j: j['posted'] or datetime.min, reverse=True)
        if per_board_world is None:
            return jobs[:per_board]
        home = [j for j in jobs if keep_place(j['location'])]
        return home[:per_board] + _by_country([j for j in jobs if not keep_place(j['location'])], per_board_world)

    results, failed = [], []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(board, pool.submit(one, board)) for board in boards]
        for board, future in futures:
            try:
                results.append((board, future.result()))
            except Exception as exc:                                        # one company's board must not stop the others
                failed.append('%s:%s (%s)' % (board[0], board[1], exc.__class__.__name__))
                _logger.warning('company job board %s:%s could not be read: %s', board[0], board[1], exc)
    if boards and not results:
        raise SourceError('no company job board answered: %s' % ', '.join(failed)[:200])
    jobs, seen = [], set()
    for (ats, _token, _name), found in results:
        for position, j in enumerate(found):
            if j['ext_id'] in seen or not j['title'] or not j['apply_url']:
                continue
            seen.add(j['ext_id'])
            company = re.sub(r'\s+(?:job board|careers|jobs|hiring)$', '', j['company'] or '', flags=re.I).strip()       # "Rubrik Job Board" -> "Rubrik"
            jobs.append(dict(j, company=company, source='Company job boards', countries='', seniority=j.get('seniority') or '', full_text=len(_strip(j['html'])) > 300,
                             source_url=j['apply_url'], via=ATS_NAMES[ats], position=position))
    return jobs
