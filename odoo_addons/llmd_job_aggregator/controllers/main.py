import json
import logging
import re
import secrets
from collections import Counter
from datetime import timedelta
from urllib.parse import parse_qsl, quote, unquote, urlencode

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request

from odoo.addons.website.controllers.main import Website
from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment

from ..models import apply_utils as A
from ..models import board_config as C
from ..models import job_facets as F
from ..models import listing as L
from ..models import urls as U
from ..models.listing import valid_url

_logger = logging.getLogger(__name__)

PER_PAGE = 12
VISITOR_COOKIE = 'llmd_vid'                           # a random first-party id: it only lets us count one visitor's clicks on one job once (no name, no e-mail)
BOT = re.compile(r'bot|crawl|spider|slurp|preview|fetch|curl|wget|python|headless|monitor|check', re.I)
NCR = ('Delhi', 'Gurugram', 'Noida', 'Faridabad', 'Ghaziabad')                      # the region "Delhi NCR" = these cities together
REGIONS = {'delhi-ncr': ('Delhi NCR', NCR)}
SORTS = [('relevance', 'Most relevant'), ('newest', 'Most recent')]
POSTED = [('1', 'Last 24 hours', 1), ('7', 'Last 7 days', 7), ('30', 'Last 30 days', 30)]          # Time Posted ("Any time" = no value)
EXP_MAX = 25                                                                        # the experience slider runs 0 .. 25+ years
LATEST = 12                                                                         # "Latest jobs": cards per batch ("Load More Jobs" brings the next batch)
CODE_OF_COUNTRY = {name: code for code, name in F.COUNTRY_OF_CODE.items() if code != 'uk'}
FILTERS = ('q', 'location', 'region', 'country', 'city', 'exp_min', 'exp_max', 'category', 'function', 'role', 'skill', 'company', 'size', 'mode', 'jtype', 'level', 'salary', 'posted', 'track')
OLD = ('loc', 'sort', 'view', 'exp', 'salary', 'tab', 'course')                     # older links that still lead to the results (?course= moves to /jobs/course/<course>)
APPLY_NEXT = re.compile(r'/jobs/(?:ext/\d+/(?:go|apply)|position/\d+/go|apply/[\w-]+)')      # the only pages a sign-in for Apply Now may lead back to
APPLY_NEXT_KEY = 'llmd_apply_next'                                                  # session: the Apply Now the visitor was on when asked to sign in
REGION_INFO = {slug: (name, text, icon) for slug, name, text, icon in F.REGIONS + F.INDIA_ZONES}
ZONES = {slug for slug, _n, _t, _i in F.INDIA_ZONES}
LANDING_STATE = ('latest', 'latest_cat', 'rec', 'cm', 'rec_page')                    # the landing page's own state (Latest Jobs page, the course space): no filters


def latest_path(category='', page=1):
    """/jobs/latest-jobs[/<category>][/page/<n>]: the landing page at that page of Latest Jobs."""
    return '/jobs/latest-jobs%s%s' % ('/' + category if category else '', '/page/%d' % page if page > 1 else '')


# Filter addresses: other names people (and other sites) use for our filters -> our own parameter, so that ONE address form is used everywhere
# (/jobs?work_mode=remote&employment_type=full-time&region=North%20America -> /jobs?mode=remote&jtype=fulltime&region=north-america, 301).
PARAM_ALIASES = {'keyword': 'q', 'keywords': 'q', 'query': 'q', 'work_mode': 'mode', 'workmode': 'mode', 'remote': 'mode', 'employment_type': 'jtype', 'job_type': 'jtype',
                 'type': 'jtype', 'categories': 'category', 'job_category': 'category', 'companies': 'company', 'cities': 'city', 'experience_min': 'exp_min',
                 'experience_max': 'exp_max', 'min_experience': 'exp_min', 'max_experience': 'exp_max', 'sort_by': 'sort', 'place': 'location',
                 'company_size': 'size', 'companysize': 'size', 'department': 'function', 'departments': 'function', 'experience_level': 'level',
                 'seniority': 'level', 'salary_range': 'salary', 'date_posted': 'posted', 'posted_date': 'posted'}
# filters the job data has no values for: never invented - left out of the address (and so of the results)
UNSUPPORTED = ('salary_min', 'salary_max', 'industry')
_MODE_WORDS = {'on-site': 'onsite', 'on site': 'onsite', 'office': 'onsite', 'in-office': 'onsite', 'wfh': 'remote', 'work from home': 'remote', 'true': 'remote'}
_TYPE_WORDS = {'full-time': 'fulltime', 'full time': 'fulltime', 'permanent': 'fulltime', 'part-time': 'parttime', 'part time': 'parttime', 'intern': 'internship',
               'freelance': 'contract', 'temporary': 'contract'}


def _canonical_value(name, value):
    """A filter value as our own pages write it ('North America' -> north-america, 'Full-time' -> fulltime, 'IT & Software' -> it-software, 'in' -> India);
    a value that is not known stays as it is (the filter then simply finds what matches, nothing is guessed)."""
    low = (value or '').strip().lower()
    if name == 'mode':
        return _MODE_WORDS.get(low, low.replace('-', '').replace(' ', '') if low.replace('-', '').replace(' ', '') in F.MODE_LABELS else value)
    if name == 'jtype':
        return ','.join(_TYPE_WORDS.get(v.strip().lower(), v.strip().lower()) for v in value.split(','))
    if name == 'region':
        return next((slug for slug, (label, _t, _i) in REGION_INFO.items() if low in (slug, label.lower(), slugify(label))), value)
    if name == 'category':
        return ','.join(next((slug for slug, label in C.CATEGORY_LABELS.items() if v.strip().lower() in (slug, label.lower(), slugify(label))), v.strip())
                        for v in value.split(','))
    if name == 'function':                                              # a department given by its name ("Product", "Sales") -> its key
        return ','.join(next((k for k, label in C.FUNCTION_LABELS.items() if v.strip().lower() in (k, label.lower(), slugify(label))), v.strip()) for v in value.split(','))
    if name == 'level':                                                 # "Senior-level", "Senior", "Entry level" -> senior / entry
        return ','.join(next((k for k, label in list(F.EXP_FILTER) + list(F.EXP_LEVELS) if slugify(v) in (k, slugify(label), slugify(label).replace('-level', ''))), v.strip()) for v in value.split(','))
    if name == 'salary':                                                # USD-150-200 -> usd-150-200; a value that is no band of ours is left out
        return ','.join(v.strip().lower() for v in value.split(',') if v.strip().lower() in F.SALARY_BAND_LABELS)
    if name == 'posted':                                                # today / week / month -> 1 / 7 / 30
        return {'today': '1', '24h': '1', 'day': '1', 'week': '7', '7d': '7', 'month': '30', '30d': '30'}.get(low, value)
    if name == 'size':                                                  # 51-200, "51–200", 5000+ / 5001+ / 10000+ -> our bands
        return ','.join({'5000+': '5001+', '10000+': '5001+', '10001+': '5001+'}.get(v.strip().replace('–', '-').replace(',', '').replace(' ', '').lower(),
                                                                                      v.strip().replace('–', '-').replace(',', '').replace(' ', '').lower()) for v in value.split(','))
    if name == 'country' and len(low) == 2 and low in F.COUNTRY_OF_CODE:
        return F.COUNTRY_OF_CODE[low]
    return value


def _canonical_query(args):
    """The query string of a filter address in our own words, or None when it already is (aliases, values written another way, unsupported filters dropped)."""
    pairs, changed = [], False
    for key, value in args.items(multi=True):
        name = PARAM_ALIASES.get(key, key)
        if key in UNSUPPORTED:
            changed = True
            continue
        if name == 'function' and value and not any(value.strip().lower() in (k, label.lower(), slugify(label)) for k, label in C.FUNCTION_LABELS.items()):
            low = value.strip().lower()
            category = next((k for k, label in C.CATEGORY_LABELS.items() if low in (k, label.lower(), slugify(label))), '')
            track = next((k for k, label in C.TRACK_LABELS.items() if low in (k, label.lower(), slugify(label))), '')
            if category or track:                                       # "department=Finance & Accounting" is a category, "department=AI/ML" a track
                pairs.append(('category', category) if category else ('track', track))
                changed = True
                continue
        if key in ('experience', 'experience_years', 'years') and value:
            m = re.match(r'^\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:y\w*)?\s*$', value) or re.match(r'^\s*(\d{1,2})\s*\+\s*(?:y\w*)?\s*$', value)
            if m:                                                       # "2-3", "5+" -> the years filter
                pairs.append(('exp_min', m.group(1)))
                if m.lastindex == 2:
                    pairs.append(('exp_max', m.group(2)))
            else:                                                       # "senior", "Entry-level" -> the experience level
                pairs.append(('level', _canonical_value('level', value)))
            changed = True
            continue
        if name in ('mode', 'jtype', 'region', 'category', 'country', 'size', 'function', 'level', 'posted', 'salary') and value:
            fixed = _canonical_value(name, value)
            changed = changed or fixed != value
            value = fixed
            if not value:                                               # nothing of it is a value we know (salary=10-20): out of the address
                continue
        changed = changed or name != key
        pairs.append((name, value))
    return urlencode(pairs) if changed else None


def _any(leaves):
    """A search domain that matches when ANY of the leaves does (nothing at all when there are none)."""
    return ['|'] * (len(leaves) - 1) + list(leaves) if leaves else [('id', '=', 0)]


_SKILL_NAMES = {}                                                      # database -> (stamp, {skill key: name as a job writes it})


def _skill_names(listing):
    """{skill key: the skill as a job writes it} of the visible jobs. The summaries are big, so they are read once and kept until a job changes."""
    stamp = tuple(listing._read_group([('active', '=', True)], [], ['write_date:max', '__count'])[0])
    db = listing.env.cr.dbname
    if _SKILL_NAMES.get(db, (None,))[0] != stamp:
        names = {}
        for row in listing.search_read([('active', '=', True), ('skill_keys', '!=', False)], ['summary_json']):
            try:
                for name in (json.loads(row['summary_json']) if row['summary_json'] else {}).get('skills') or []:
                    names.setdefault(F.skill_key(name), name)
            except ValueError:
                pass
        _SKILL_NAMES[db] = (stamp, names)
    return _SKILL_NAMES[db][1]


def _flag(country):
    """The flag of a country as an emoji (two regional-indicator letters of its ISO code), or '' when the code is not known."""
    code = CODE_OF_COUNTRY.get(country or '', '')
    return ''.join(chr(0x1F1E6 + ord(c) - ord('a')) for c in code) if len(code) == 2 else ''


def _flag_font(flags):
    """The Google Fonts address of the colour-emoji font for just these flags (Windows has no flag emoji of its own), or ''."""
    return 'https://fonts.googleapis.com/css2?family=Noto+Color+Emoji&display=swap&text=%s' % quote(flags) if flags else ''


def _updated_ago(dt, now=None):
    """'Updated 5 minutes ago' for a naive UTC datetime ('' when unknown)."""
    if not dt:
        return ''
    minutes = int(((now or fields.Datetime.now()) - dt).total_seconds() // 60)
    if minutes < 1:
        return 'Updated just now'
    if minutes < 60:
        return 'Updated %d minute%s ago' % (minutes, '' if minutes == 1 else 's')
    if minutes < 48 * 60:
        return 'Updated %d hour%s ago' % (minutes // 60, '' if minutes // 60 == 1 else 's')
    return 'Updated %d days ago' % (minutes // 1440)


def _region_domain(slug):
    """The jobs of a world region or of a region of India (their stored region, worked out from the location: job_facets.region_of / india_zone_of)."""
    return [('india_zone', '=', slug)] if slug in ZONES else [('region', '=', slug)]


def _course_domain(course):
    """The jobs a course of the catalog leads to (its role profiles; a course that matches no profile: jobs that name its topic). Unchanged course matching."""
    leaves = [('courses', 'ilike', ',%s,' % p) for p in course['profiles']]
    if not leaves:
        leaves = [(f, 'ilike', w) for w in course['words'] for f in ('title', 'search_text')]
    return _any(leaves)


def _free(args, name, limit=12, length=80):
    """Free-text values of a filter that can hold several (company names, cities, skills): trimmed, unique, at most `limit` of `length` characters."""
    values = []
    for raw in args.getlist(name):
        for value in (raw.split('|') if '|' in raw else [raw]):
            value = value.strip()[:length]
            if value and value not in values:
                values.append(value)
    return values[:limit]


def _multi(args, name, allowed):
    """The values of a filter that can hold several (?jtype=fulltime&jtype=contract, or ?jtype=fulltime,contract from the pager), known values only, in order."""
    values = []
    for raw in args.getlist(name):
        for value in raw.split(','):
            value = value.strip()
            if value in allowed and value not in values:
                values.append(value)
    return values


slugify = C.slugify


def _location_domain(text):
    """What a typed location means: a country, a region (Delhi NCR), a city (Bangalore = Bengaluru), "remote", or else any location that contains the text."""
    low = (text or '').strip().lower()
    if not low:
        return []
    if low in ('india', 'in'):
        return [('country', '=', 'India')]
    if low.replace(' ', '-') in REGIONS or low in ('ncr', 'delhi ncr'):
        return [('city', 'in', list(NCR))]
    if low in ('remote', 'work from home', 'wfh', 'anywhere'):
        return [('work_mode', '=', 'remote')]
    region = next((slug for slug, (name, _t, _i) in REGION_INFO.items() if low in (slug.replace('-', ' '), name.lower())), None)
    if region:                                                          # "South India", "Europe", "Asia-Pacific"
        return _region_domain(region)
    city = F.city_of(text) or F.world_city_of(text)                     # Bangalore = Bengaluru, NYC = New York
    if city:
        return [('city', '=', city)]
    country = F.country_of(text)
    if country:
        return [('country', '=', country)]
    return [('location', 'ilike', text.strip())]



def _page_numbers(page, pages, span=5):
    """The page numbers to show around the current page: [1, 2, 3, 4, 5, None, 525] - None is an ellipsis; span = how many in a row (3 on a phone)."""
    if pages <= span + 2:
        return list(range(1, pages + 1))
    lo = max(1, min(page - span // 2, pages - span + 1))
    hi = min(pages, lo + span - 1)
    out = list(range(lo, hi + 1))
    if lo > 1:
        out = [1] + ([None] if lo > 2 else []) + out
    if hi < pages:
        out = out + ([None] if hi < pages - 1 else []) + [pages]
    return out

class JobBoard(WebsiteHrRecruitment):
    """/jobs is the job board: a landing page (search, categories, course matches, companies, latest jobs, locations, FAQ) and, as soon as something is searched
    or filtered, the results. /jobs/category|company|location|role/<slug> are the same results for one category, company, place or role; /jobs/<id>/<slug> is ONE job
    (/jobs/ext/<id> moves there).
    The stock Odoo list stays available at /jobs?stock=1 and the pages of our own positions (/jobs/<position>) are untouched."""

    # ------------------------------------------------------------------ the request -> one state of filters
    @staticmethod
    def _llmd_state(args, search=None):
        def years(name, default):
            try:
                return min(max(int(args.get(name, default)), 0), EXP_MAX)
            except (TypeError, ValueError):
                return default
        low, high = sorted((years('exp_min', 0), years('exp_max', EXP_MAX)))
        course = (args.get('course') or '').strip()
        track = args.get('track') or ''
        if course in C.OLD_TRACK_PARAMS and not track:                # old links used ?course=genai for the category chips
            course, track = '', course
        state = {'q': (args.get('q') or search or '').strip()[:80], 'location': (args.get('location') or '').strip()[:60], 'country': (args.get('country') or '').strip()[:60],
                 'city': _free(args, 'city', 10, 60), 'exp_min': low, 'exp_max': high, 'category': _multi(args, 'category', C.CATEGORY_LABELS),
                 'function': _multi(args, 'function', C.FUNCTION_LABELS), 'role': _multi(args, 'role', C.ROLE_LABELS), 'skill': _free(args, 'skill', 10, 60),
                 'company': _free(args, 'company', 15), 'size': _multi(args, 'size', C.COMPANY_SIZE_LABELS),
                 'level': _multi(args, 'level', dict(F.EXP_FILTER)), 'salary': _multi(args, 'salary', F.SALARY_BAND_LABELS), 'mode': args.get('mode') if args.get('mode') in F.MODE_LABELS else '', 'jtype': _multi(args, 'jtype', F.TYPE_LABELS),
                 'posted': args.get('posted') if args.get('posted') in dict((k, l) for k, l, _d in POSTED) else '', 'course': course,
                 'region': args.get('region') if args.get('region') in REGION_INFO else '',
                 'track': track if track in C.TRACK_LABELS else '', 'sort': args.get('sort') if args.get('sort') in dict(SORTS) else ''}
        loc = (args.get('loc') or '').strip()                          # the location select of earlier versions
        if loc == 'india' and not state['country']:
            state['country'] = 'India'
        elif loc == 'remote' and not state['mode']:
            state['mode'] = 'remote'
        elif loc == 'delhi-ncr' and not state['city']:
            state['city'] = list(NCR)
        elif loc and loc != 'all' and not state['city'] and not state['location']:
            state['location'] = loc[:60]                               # a city or a country, read like a typed location
        return state

    # ------------------------------------------------------------------ /jobs: the landing page, or the results of a search
    @http.route()
    def jobs(self, page=1, search=None, **kwargs):
        """/jobs: the landing page; with a search or filters (a query, from a form or an older link) it moves to their address /jobs/<filters> (301)."""
        if kwargs.get('stock'):
            return super().jobs(page=page, search=search, **kwargs)
        args = self._llmd_args()                                       # other names of our filters read as ours: ONE move, straight to the path
        state = self._llmd_state(args, search)
        if 'course' in args:                                            # the course is no general filter: its jobs have their own page (old ?course= links move there)
            course = request.env['llmd.course.catalog'].resolve(state['course']) if state['course'] else None
            return request.redirect(U.path('/jobs/course/%s' % course['code'] if course else '/jobs', state, U.Lookup(request.env)), code=301)
        if int(page or 1) == 1 and not search and not any(k in args for k in FILTERS + OLD):      # an empty search (?q=) is a search: all jobs
            if any(k in args for k in LANDING_STATE):              # the older ?latest= / ?rec= links of the landing page: their own address
                return request.redirect(self._llmd_landing_path(args), code=301)
            return self._llmd_landing(args)
        return request.redirect(U.path('/jobs', state, U.Lookup(request.env), int(page or 1)), code=301)

    @staticmethod
    def _llmd_landing_path(args):
        """The address of a state of the landing page: the course space (/jobs/course-match/<course>[/pick | /jobs[/page/<n>]]) or a page of Latest Jobs
        (/jobs/latest-jobs[/<category>][/page/<n>])."""
        course = request.env['llmd.course.catalog'].resolve(args.get('rec')) if args.get('rec') else None
        if course:
            page = int(args.get('rec_page')) if (args.get('rec_page') or '').isdigit() else 1
            step = 'jobs' if args.get('cm') == 'jobs' or page > 1 else ('pick' if args.get('cm') == 'pick' else '')
            return '/jobs/course-match/%s%s%s' % (course['code'], '/' + step if step else '', '/page/%d' % page if page > 1 else '')
        if args.get('latest') or args.get('latest_cat'):
            cat = args.get('latest_cat') if args.get('latest_cat') in C.CATEGORY_LABELS else ''
            page = int(args.get('latest')) if (args.get('latest') or '').isdigit() else 1
            return latest_path(cat, page)
        return '/jobs'

    @http.route(['/jobs/latest-jobs', '/jobs/latest-jobs/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_latest_page(self, rest='', **kwargs):
        """The landing page at Latest Jobs: /jobs/latest-jobs[/<category>][/page/<n>] (a category that exists, a page that exists)."""
        parts = [p for p in rest.split('/') if p]
        page = 1
        if len(parts) >= 2 and parts[-2] == 'page' and parts[-1].isdigit():
            page, parts = int(parts[-1]), parts[:-2]
        if len(parts) > 1 or (parts and parts[0] not in C.CATEGORY_LABELS) or page < 1:
            raise NotFound()
        cat = parts[0] if parts else ''
        if request.httprequest.path != latest_path(cat, page):
            return request.redirect(latest_path(cat, page), code=301)
        return self._llmd_landing(MultiDict([('latest', str(page)), ('latest_cat', cat)]), focus='latest')

    @http.route(['/jobs/course-match/<string:code>', '/jobs/course-match/<string:code>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_course_flow(self, code, rest='', **kwargs):
        """The landing page at its course space, one step: /jobs/course-match/<course> (the course), .../pick (the course tabs), .../jobs[/page/<n>] (its jobs)."""
        course = request.env['llmd.course.catalog'].resolve(code)
        if not course:
            raise NotFound()
        parts = [p for p in rest.split('/') if p]
        args = [('rec', course['code'])]
        if parts == ['pick']:
            args.append(('cm', 'pick'))
        elif parts and parts[0] == 'jobs' and (len(parts) == 1 or (len(parts) == 3 and parts[1] == 'page' and parts[2].isdigit() and int(parts[2]) > 1)):
            args += [('cm', 'jobs')] + ([('rec_page', parts[2])] if len(parts) == 3 else [])
        elif parts:
            raise NotFound()
        target = self._llmd_landing_path(MultiDict(args))
        if request.httprequest.path != target:
            return request.redirect(target, code=301)
        return self._llmd_landing(MultiDict(args), focus='llmd_cm_flow')

    @http.route('/jobs/companies-by-region/<string:slug>', type='http', auth='public', website=True, sitemap=False)
    def llmd_hq_region(self, slug, **kwargs):
        """The landing page at "Companies by region", that headquarters region's tab open (/jobs/companies-by-region/india-south-asia)."""
        if slug not in REGION_INFO and slug != 'not-verified':
            raise NotFound()
        return self._llmd_landing(MultiDict(), focus='companies', hq_tab=slug)

    @http.route('/jobs/faq', type='http', auth='public', website=True, sitemap=False)
    def llmd_faq(self, **kwargs):
        """The landing page at its questions and answers (the footer's "Jobs Explorer FAQ")."""
        return self._llmd_landing(MultiDict(), focus='faq')

    @http.route('/signup/<string:code>', type='http', auth='public', website=True, sitemap=False)
    def llmd_course_signup(self, code, **kwargs):
        """Sign Up Free of a course: the sign-up of the site the course is on, which brings the new account back to that course afterwards."""
        course = request.env['llmd.course.catalog'].resolve(code)
        if not course or not course.get('signup'):
            raise NotFound()
        return request.redirect(course['signup'], code=302, local=False)

    @http.route(['/jobs/all', '/jobs/all/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_all_jobs(self, rest='', **kwargs):
        """All Jobs: every open job with the search, the filters, the sort and the pages of the results (/jobs/all/<filters>; the sort keeps "Most recent")."""
        scope = {'kind': 'all', 'base': '/jobs/all', 'title': 'All Jobs', 'here': 'All Jobs', 'home': True,
                 'description': 'Explore thousands of opportunities from companies worldwide.'}
        return self._llmd_list(scope, rest)

    def _llmd_list(self, scope, rest=''):
        """A list of jobs at <scope address>/<filters>[/page/<n>] (models/urls.py). A query (a filter form sent, an older link) moves to the same filters as a
        path, a path written in another order to the one address of those filters (301); a part that names nothing is a 404."""
        look = U.Lookup(request.env)
        base = self._llmd_base(scope)
        parsed = U.parse((rest or '').split('/'), look)
        if parsed is None:
            raise NotFound()
        values, page = parsed
        state = self._llmd_state(MultiDict())
        state.update(values)
        args = self._llmd_args()
        if any(k in args for k in FILTERS + OLD):
            sent = self._llmd_state(args)
            for key, value in sent.items():
                if isinstance(value, list):
                    state[key] = list(dict.fromkeys(state.get(key, []) + value))
                elif key in ('exp_min', 'exp_max'):
                    if 'exp_min' in args or 'exp_max' in args:
                        state[key] = value
                elif value:
                    state[key] = value
            return request.redirect(U.path(base, state, look), code=301)
        target = U.path(base, state, look, page)
        if unquote(target) != request.httprequest.path:
            return request.redirect(target, code=301)
        return self._llmd_results(scope, page, state)

    @staticmethod
    def _llmd_base(scope):
        """The address of a list without filters."""
        kind, value = scope['kind'], scope.get('value')
        return scope.get('base') or {'all': '/jobs', 'category': '/categories/%s' % value, 'company': scope.get('company_path'), 'department': '/departments/%s' % value,
                                     'location': '/locations/%s' % value, 'role': '/jobs/role/%s' % (value or '').replace('_', '-'),
                                     'course': '/jobs/course/%s' % value, 'region': U.region_path(value)}[kind]

    # ------------------------------------------------------------------ the addresses: /jobs/<id>/<slug> (ONE job), /jobs/<slug> (a region, Remote, a country or a city),
    # /companies(/<slug>), /categories(/<slug>), /departments/<slug>. The older /jobs/category|company|location|region/<slug>, /industries/<slug> and a job's
    # /jobs/ext/<id> or short /jobs/<slug> move there (301, query kept).
    @http.route(['/jobs/category', '/jobs/categories', '/industries'], type='http', auth='public', website=True, sitemap=False)
    def llmd_old_categories(self, **kwargs):
        """The older and the other names of the category directory -> /categories."""
        return self._llmd_moved('/categories')

    @http.route(['/jobs/category/<string:slug>', '/jobs/category/<string:slug>/page/<int:page>',
                 '/industries/<string:slug>', '/industries/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_category(self, slug, page=1, **kwargs):
        """The older category address and /industries/<slug> (the industry of a job IS its category: one field, job_category) -> /categories/<slug>."""
        return self._llmd_moved(self._llmd_paged('/categories/%s' % C.OLD_CATEGORY_SLUGS.get(slug, slug), page))

    @http.route('/categories', type='http', auth='public', website=True, sitemap=False)
    def llmd_category_directory(self, **kwargs):
        return self.llmd_categories(**kwargs)

    @http.route(['/categories/<string:slug>', '/categories/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_category_page(self, slug, rest='', **kwargs):
        """The jobs of one category / industry (board_config.JOB_CATEGORIES) - only one that has open jobs; an older category name moves to its new one."""
        if slug in C.OLD_CATEGORY_SLUGS:
            return self._llmd_moved('/categories/%s%s' % (C.OLD_CATEGORY_SLUGS[slug], '/' + rest if rest else ''))
        category = {c[0]: c for c in C.JOB_CATEGORIES}.get(slug)
        if not category or not request.env['llmd.job.listing'].sudo().search_count([('active', '=', True), ('job_category', '=', slug)], limit=1):
            raise NotFound()
        scope = {'kind': 'category', 'value': slug, 'label': category[1], 'title': '%s jobs' % category[1], 'description': category[2], 'icon': category[3],
                 'crumb': ('Categories', '/categories')}
        return self._llmd_list(scope, rest)

    @http.route(['/departments/<string:slug>', '/departments/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_department(self, slug, rest='', **kwargs):
        """The jobs of one department (the job function of board_config.JOB_FUNCTIONS) - only a department that has open jobs."""
        label = C.FUNCTION_LABELS.get(slug)
        if not label or not request.env['llmd.job.listing'].sudo().search_count([('active', '=', True), ('job_function', '=', slug)], limit=1):
            raise NotFound()
        scope = {'kind': 'department', 'value': slug, 'label': label, 'title': '%s jobs' % label, 'icon': 'fa-sitemap', 'crumb': ('Jobs Explorer', '/jobs'),
                 'description': 'Open roles in %s teams, from every company on the board.' % label}
        return self._llmd_list(scope, rest)

    @http.route(['/jobs/company/<string:slug>', '/jobs/company/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_company(self, slug, page=1, **kwargs):
        """The older company address (/jobs/company/<name-slug>) -> /companies/<slug>."""
        Company = request.env['llmd.company'].sudo()
        company = Company.search([('slug', '=', slug)], limit=1) or next((c for c in Company.search([], order='id') if slugify(c.name) == slug), None)
        if not company:
            raise NotFound()
        return self._llmd_moved(self._llmd_paged(company.website_path(), page))

    @http.route(['/companies', '/companies/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_companies(self, page=1, q='', industry='', sort='', **kwargs):
        """Every company with open jobs: logo initial, name, the industries of its jobs, headquarters (when verified), number of jobs; search, industry, sort, pages."""
        Listing = request.env['llmd.job.listing'].sudo()
        q, industry = (q or '').strip()[:80], industry if industry in C.CATEGORY_LABELS else ''
        sort = sort if sort in ('jobs', 'name') else 'jobs'
        per = {}
        for company, cat, n in Listing._read_group([('active', '=', True), ('company_id', '!=', False)], ['company_id', 'job_category'], ['__count']):
            entry = per.setdefault(company.id, {'company': company, 'jobs': 0, 'cats': Counter()})
            entry['jobs'] += n
            if cat:
                entry['cats'][cat] += n
        industries = Counter(cat for entry in per.values() for cat in entry['cats'])
        found = [e for e in per.values() if (not q or q.casefold() in e['company'].name.casefold()) and (not industry or industry in e['cats'])]
        found.sort(key=(lambda e: e['company'].name.casefold()) if sort == 'name' else (lambda e: (-e['jobs'], e['company'].name.casefold())))
        per_page = 24
        pages = max((len(found) + per_page - 1) // per_page, 1)
        page = min(max(int(page or 1), 1), pages)
        shown = found[(page - 1) * per_page:page * per_page]
        cards = [{'name': e['company'].name, 'href': e['company'].website_path(), 'jobs': e['jobs'], 'hq': e['company'].hq(),
                  'industries': [C.CATEGORY_LABELS[c] for c, _n in e['cats'].most_common(2) if c in C.CATEGORY_LABELS]} for e in shown]
        args = {k: v for k, v in (('q', q), ('industry', industry), ('sort', sort if sort != 'jobs' else '')) if v}
        href = lambda n: ('/companies' if n == 1 else '/companies/page/%d' % n) + ('?' + urlencode(args) if args else '')      # noqa: E731
        return request.render('llmd_job_aggregator.company_directory', {
            'cards': cards, 'total': len(found), 'all_total': len(per), 'q': q, 'industry': industry, 'sort': sort, 'page': page, 'pages': pages,
            'nav': [(n, href(n) if n else '') for n in _page_numbers(page, pages)], 'prev_href': href(page - 1) if page > 1 else '',
            'next_href': href(page + 1) if page < pages else '',
            'industry_options': [(k, C.CATEGORY_LABELS[k], industries[k]) for k, _l, _d, _i in C.JOB_CATEGORIES if industries.get(k)],
            'first': (page - 1) * per_page + 1 if found else 0, 'last': (page - 1) * per_page + len(shown),
        })

    @http.route(['/companies/<string:slug>', '/companies/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_company_page(self, slug, rest='', **kwargs):
        """ONE company (found by its unique slug - the record ID behind it), with every open job of it, the filters and the pages."""
        company = request.env['llmd.company'].sudo().search([('slug', '=', slug)], limit=1)
        if not company:
            raise NotFound()
        name, hq = company.name, company.hq()
        scope = {'kind': 'company', 'value': name, 'company_id': company.id, 'company_path': company.website_path(), 'label': name, 'title': name,
                 'icon': 'fa-building-o', 'initial': name.strip()[:1].upper(), 'crumb': ('Companies', '/companies'),
                 'description': 'Open roles at %s, read from its own job board%s. Apply Now opens its application page.' % (
                     name, ' - headquarters: %s (%s)' % (hq, F.REGION_LABELS.get(F.COUNTRY_REGION.get(hq, ''), '')) if hq else '')}
        return self._llmd_list(scope, rest)

    @http.route(['/jobs/location/<string:slug>', '/jobs/location/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_location(self, slug, page=1, **kwargs):
        """The older place address -> /locations/<slug> (Remote is a work mode: /jobs/remote)."""
        return self._llmd_moved(self._llmd_paged('/jobs/remote' if slug == 'remote' else '/locations/%s' % slug, page))

    @http.route(['/locations/<string:slug>', '/locations/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_location_page(self, slug, rest='', **kwargs):
        """The jobs of one place: a country or a city that has jobs, or Delhi NCR (/locations/india, /locations/delhi, /locations/bengaluru)."""
        if slug == 'remote':                                            # the countries counted by their remote jobs; Remote itself is a work mode (/jobs/remote)
            return self._llmd_countries('remote') if not rest else self._llmd_moved('/jobs/remote/%s' % rest)
        place = self._llmd_place(slug)
        if not place:
            raise NotFound()
        scope = {'kind': 'location', 'value': slug, 'label': place[0], 'domain': place[1], 'place': place[2], 'title': 'Jobs in %s' % place[0],
                 'description': place[3], 'icon': 'fa-map-marker', 'crumb': ('Locations', '/locations')}
        return self._llmd_list(scope, rest)

    @http.route(['/regions/<string:slug>', '/regions/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_region_page(self, slug, rest='', **kwargs):
        """The jobs of one world region or region of India (/regions/north-america, /regions/south-india)."""
        if slug not in REGION_INFO:
            raise NotFound()
        name, text, icon = REGION_INFO[slug]
        scope = {'kind': 'region', 'value': slug, 'label': name, 'title': 'Jobs in %s' % name if slug != 'worldwide' else 'Global / worldwide jobs', 'description': text,
                 'icon': icon if slug not in ZONES else 'fa-map-marker', 'crumb': ('Regions', '/regions'), 'zone': slug in ZONES}
        return self._llmd_list(scope, rest)

    @http.route(['/jobs/regions', '/jobs/countries'], type='http', auth='public', website=True, sitemap=False)
    def llmd_old_directories(self, **kwargs):
        return self._llmd_moved('/regions' if request.httprequest.path == '/jobs/regions' else '/locations')

    @http.route('/jobs/<path:rest>', type='http', auth='public', website=True, sitemap=False)
    def llmd_jobs_path(self, rest, **kwargs):
        """/jobs/<parts>: the Jobs Explorer with filters (/jobs/remote/full-time/in-bengaluru, models/urls.py), or ONE job by its unique address
        (/jobs/senior-network-engineer-san-francisco). The short-lived /jobs/<region>|<place> move to /regions|/locations; Odoo's own position pages
        (/jobs/<name>-<id>) stay Odoo's."""
        parts = [p for p in rest.split('/') if p]
        look = U.Lookup(request.env)
        if parts and U.parse(parts, look) is None:
            first, more = parts[0], '/'.join(parts[1:])
            if len(parts) == 1:
                job = request.env['llmd.job.listing'].sudo().with_context(active_test=False).search([('url_slug', '=', first)], limit=1)
                if job:
                    if not job.active:
                        return self._llmd_job_gone(job.id)
                    return request.render('llmd_job_aggregator.board_detail', {'job': job, 'd': job.detail_vals(), 'similar': self._llmd_similar(job)})
            if first in REGION_INFO:
                return self._llmd_moved(U.region_path(first) + ('/' + more if more else ''))
            if first != 'remote' and self._llmd_place(first):
                return self._llmd_moved('/locations/%s%s' % (first, '/' + more if more else ''))
            position = self._llmd_position(first) if len(parts) == 1 else None
            if position:
                return super().job(position)
            raise NotFound()
        scope = {'kind': 'all'}
        one = U.facet(parts)
        if one:
            scope.update(one)
        return self._llmd_list(scope, '/'.join(parts))

    @http.route()
    def job(self, job, **kwargs):
        """Odoo's own position page /jobs/<name>-<id>. An address that only looks like one (a job or filters ending in a number, /jobs/size-51-200-employees
        does not, but a job title may) and names no position goes to the job board instead."""
        if not job.sudo().exists():
            raw = job.env.context.get('_converter_value')
            if raw:
                return self.llmd_jobs_path(raw, **kwargs)
            raise NotFound()
        return super().job(job, **kwargs)

    @staticmethod
    def _llmd_position(slug):
        """One of Odoo's own published positions by its address <name>-<id> (when this route got it first), else None."""
        _name, pid = request.env['ir.http']._unslug(slug)
        if not pid:
            return None
        return request.env['hr.job'].sudo().search([('id', '=', abs(pid)), ('website_published', '=', True)], limit=1) or None

    @staticmethod
    def _llmd_paged(path, page):
        return path if int(page or 1) <= 1 else '%s/page/%d' % (path, int(page))

    @staticmethod
    def _llmd_company_slugs(listing):
        """{company name as the jobs write it: the slug of its company record} - the links of the company cards."""
        return {name: company.slug for name, company, _n in listing._read_group([('active', '=', True), ('company_id', '!=', False)], ['company', 'company_id'], ['__count'])}

    @staticmethod
    def _llmd_place(slug):
        """(label, domain, kind, description) of a location slug: a region (delhi-ncr), remote, a country or a city that has jobs; None otherwise."""
        Listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        place = None
        if slug in REGIONS:
            label, cities = REGIONS[slug]
            place = (label, [('city', 'in', list(cities))], 'region', 'Jobs in %s: %s.' % (label, ', '.join(cities)))
        elif slug == 'remote':
            place = ('Remote', [('work_mode', '=', 'remote')], 'remote', 'Remote jobs - mostly open to people in India - from the companies on the board.')
        else:
            countries = [c for c, _n in Listing._read_group(active + [('country', '!=', False)], ['country'], ['__count'])]
            cities = [c for c, _n in Listing._read_group(active + [('city', '!=', False)], ['city'], ['__count'])]
            country = next((c for c in countries if slugify(c) == slug), None)
            city = next((c for c in cities if slugify(c) == slug), None)
            if country:
                place = (country, [('country', '=', country)], 'country', 'Open jobs in %s: on-site, hybrid and remote.' % country)
            elif city:
                place = (city, [('city', '=', city)], 'city', 'Open jobs in %s: on-site and hybrid roles in the city, and remote roles that name it.' % city)
        return place

    @http.route(['/jobs/course/<string:code>', '/jobs/course/<string:code>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_course(self, code, rest='', **kwargs):
        """The jobs one LLM Decode course leads to ("View all course-matched jobs"): the course matching is unchanged, the general filters narrow it."""
        course = request.env['llmd.course.catalog'].resolve(code)
        if not course:
            raise NotFound()
        if course['code'] != code:
            return self._llmd_moved('/jobs/course/%s%s' % (course['code'], '/' + rest if rest else ''))
        scope = {'kind': 'course', 'value': course['code'], 'course': course, 'label': course['name'], 'title': 'Jobs matched to %s' % course['name'], 'icon': 'fa-graduation-cap',
                 'description': 'The roles this course prepares you for, the closest match to what it teaches first.', 'crumb': ('Course matches', '/jobs/course-match/%s' % course['code'])}
        return self._llmd_list(scope, rest)

    @http.route(['/jobs/region/<string:slug>', '/jobs/region/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_region(self, slug, page=1, **kwargs):
        if slug not in REGION_INFO:
            raise NotFound()
        return self._llmd_moved(self._llmd_paged(U.region_path(slug), page))

    @http.route(['/jobs/role/<string:slug>', '/jobs/role/<string:slug>/<path:rest>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_role(self, slug, rest='', **kwargs):
        code = slug.replace('-', '_')
        if code not in C.ROLE_LABELS:
            raise NotFound()
        label = C.ROLE_LABELS[code]
        scope = {'kind': 'role', 'value': code, 'label': label, 'title': '%s jobs' % label, 'icon': 'fa-id-badge', 'crumb': ('Roles', '/jobs#popular'),
                 'description': 'Jobs whose title names this role (%s), from every working source.' % label}
        return self._llmd_list(scope, rest)

    # ------------------------------------------------------------------ the filters as ONE search domain
    @staticmethod
    def _llmd_domain(state, scope, skip=()):
        domain = [('active', '=', True)]
        kind = scope.get('kind')
        if kind == 'category':
            domain.append(('job_category', '=', scope['value']))
        elif kind == 'company':
            domain.append(('company_id', '=', scope['company_id']))
        elif kind == 'department':
            domain.append(('job_function', '=', scope['value']))
        elif kind == 'location':
            domain += scope['domain']
        elif kind == 'role':
            domain.append(('roles', 'ilike', ',%s,' % scope['value']))
        elif kind == 'course':
            domain += _course_domain(scope['course'])
        elif kind == 'region':
            domain += _region_domain(scope['value'])
        if state['track'] and 'track' not in skip:
            domain.append(('tags', 'ilike', ',%s,' % state['track']))
        if state['category'] and 'category' not in skip:
            domain.append(('job_category', 'in', state['category']))
        if state['location'] and 'location' not in skip:
            domain += _location_domain(state['location'])
        if state['region'] and 'region' not in skip:
            domain += _region_domain(state['region'])
        if state['country'] and 'country' not in skip:
            domain.append(('country', '=', state['country']))
        if state['city'] and 'city' not in skip:
            domain.append(('city', 'in', state['city']))
        if (state['exp_min'] > 0 or state['exp_max'] < EXP_MAX) and 'exp' not in skip:       # only jobs that state years, overlapping the chosen range
            domain += [('exp_years_known', '=', True), ('exp_years_max', '>=', state['exp_min'])] + ([('exp_years_min', '<=', state['exp_max'])] if state['exp_max'] < EXP_MAX else [])
        if state['function'] and 'function' not in skip:
            domain.append(('job_function', 'in', state['function']))
        if state['role'] and 'role' not in skip:
            domain += _any([('roles', 'ilike', ',%s,' % r) for r in state['role']])
        if state['skill'] and 'skill' not in skip:
            domain += _any([('skill_keys', 'ilike', ',%s,' % F.skill_key(s)) for s in state['skill']])
        if state['company'] and 'company' not in skip:
            domain.append(('company', 'in', state['company']))
        if state['mode'] and 'mode' not in skip:
            domain.append(('work_mode', '=', state['mode']))
        if state['level'] and 'level' not in skip:
            domain.append(('exp_level', 'in', state['level']))
        if state['salary'] and 'salary' not in skip:
            domain.append(('salary_band', 'in', state['salary']))
        if state['size'] and 'size' not in skip:
            domain.append(('company_size', 'in', state['size']))
        if state['jtype'] and 'jtype' not in skip:
            domain.append(('job_type', 'in', state['jtype']))
        if state['posted'] and 'posted' not in skip:
            domain.append(('posted', '>=', fields.Datetime.now() - timedelta(days=dict((k, d) for k, _l, d in POSTED)[state['posted']])))
        for term in state['q'].split()[:6]:                           # every word must appear in the title, company or skills
            domain += ['|', '|', ('title', 'ilike', term), ('company', 'ilike', term), ('search_text', 'ilike', term)]
        return domain

    @staticmethod
    def _llmd_mixed(listing, domain, offset, limit):
        """The default order (no keyword, no course): the newest jobs in India and the newest elsewhere, one after the other, so that every page shows both;
        when one side runs out, the other goes on, newest first."""
        rows = listing.search_read(domain, ['india', 'posted'], order='posted desc, id desc')
        home, away = [r['id'] for r in rows if r['india']], [r['id'] for r in rows if not r['india']]
        mixed = [i for pair in zip(home, away) for i in pair] + home[len(away):] + away[len(home):]
        return listing.browse(mixed[offset:offset + limit])

    @staticmethod
    def _llmd_ranked(listing, domain, state, course, offset, limit):
        """The jobs of one page, most relevant first: the search words in the title (then company, skills), the terms a selected course teaches, then jobs in India,
        then the newest."""
        terms = [t.lower() for t in state['q'].split()[:6]]
        course_keys = set(course['terms']) if course else set()
        rows = listing.search_read(domain, ['title', 'company', 'skill_keys', 'term_keys', 'india', 'posted'])

        def score(row):
            title, company, skills = (row['title'] or '').lower(), (row['company'] or '').lower(), (row['skill_keys'] or '')
            s = sum(3 if t in title else 2 if t in company else 1 if t in skills else 0 for t in terms)
            s += len(course_keys & set((row['term_keys'] or '').strip(',').split(',')))
            return (s, row['india'], row['posted'] or fields.Datetime.to_datetime('1970-01-01'), row['id'])
        rows.sort(key=score, reverse=True)
        return listing.browse([r['id'] for r in rows[offset:offset + limit]])

    # ------------------------------------------------------------------ the results page (all, a search, a category, a company, a place, a role)
    @staticmethod
    def _llmd_args():
        """The query of the request in our own words (PARAM_ALIASES, values written another way, unsupported filters dropped)."""
        query = _canonical_query(request.httprequest.args)
        return request.httprequest.args if query is None else MultiDict(parse_qsl(query))

    def _llmd_results(self, scope, page, state):
        return request.render('llmd_job_aggregator.results_page', self._llmd_results_values(scope, page, state))

    def _llmd_results_values(self, scope, page, state):
        """Everything a list of results shows: the jobs of one page, every filter with its counts, chips, sort, pages (results pages and the landing page)."""
        listing = request.env['llmd.job.listing'].sudo()
        course = scope.get('course')                                    # only the course page has one: the course is no general filter
        kind = scope['kind']
        own = scope.get('base')                                         # a page with its own address (/jobs/all)
        base = self._llmd_base(scope)
        look = U.Lookup(request.env)
        dom = lambda skip=(): self._llmd_domain(state, scope, skip)                                             # noqa: E731
        keys = FILTERS + ('sort',)

        def params(**override):
            """[(name, value)] of the current filters with some of them changed (chips, pager, sort, the search bar)."""
            data = dict(state, **override)
            found = []
            for k in keys:
                value = data.get(k)
                if k == 'exp_min' and value == 0 or k == 'exp_max' and value == EXP_MAX:
                    continue
                found += [(k, v) for v in value] if isinstance(value, list) else ([(k, value)] if value not in ('', None) else [])
            return found

        def fq(**override):
            found = params(**override)
            if kind == 'all' and not found and not own:
                found.append(('view', 'all'))                         # /jobs without anything is the landing page
            return urlencode(found)

        def href(**override):
            """The address of this list with some filters changed (chips, sort, pager, category pills ...): every filter a part of the path."""
            return U.path(base, dict(state, **override), look)

        domain = dom()
        total = listing.search_count(domain)
        pager = request.website.pager(url=U.path(base, state, look), total=total, page=page, step=PER_PAGE, url_args={})
        sort = state['sort'] or 'relevance'
        if sort == 'newest':
            listings = listing.search(domain, limit=PER_PAGE, offset=pager['offset'], order='posted desc, id desc')
        elif not (state['q'] or course):
            listings = self._llmd_mixed(listing, domain, pager['offset'], PER_PAGE)                 # India and abroad, one after the other, the newest first
        else:
            listings = self._llmd_ranked(listing, domain, state, course, pager['offset'], PER_PAGE)

        def grouped(groupby, skip):
            rows = listing._read_group(dom(skip) + [(g, '!=', False) for g in groupby], groupby, ['__count'])
            return sorted(rows, key=lambda r: (-r[-1], str(r[0]).lower()))

        # every filter's options, counted together with all the OTHER filters: only values that exist here
        companies = grouped(['company'], ('company',))
        city_rows = grouped(['country', 'city'], ('city',))
        countries = grouped(['country'], ('country',))
        functions = [(k, C.FUNCTION_LABELS.get(k, k), n) for k, n in grouped(['job_function'], ('function',))]
        categories = [(k, C.CATEGORY_LABELS.get(k, k), n) for k, n in grouped(['job_category'], ('category',))]
        jtypes = dict(grouped(['job_type'], ('jtype',)))
        sizes = dict(grouped(['company_size'], ('size',)))
        levels = dict(grouped(['exp_level'], ('level',)))
        bands = dict(grouped(['salary_band'], ('salary',)))
        modes = dict(grouped(['work_mode'], ('mode',)))
        role_hits, skill_hits = Counter(), Counter()
        for row in listing.search_read(dom(('role',)), ['roles']):
            role_hits.update(c for c in (row['roles'] or '').strip(',').split(',') if c in C.ROLE_LABELS)
        for row in listing.search_read(dom(('skill',)), ['skill_keys']):
            skill_hits.update(k for k in (row['skill_keys'] or '').strip(',').split(',') if k)
        skill_names = _skill_names(listing)
        skills = [(skill_names.get(k, k), n) for k, n in skill_hits.most_common(40)]
        known = {F.skill_key(s) for s, _n in skills}
        skills += [(s, skill_hits.get(F.skill_key(s), 0)) for s in state['skill'] if F.skill_key(s) not in known]
        now = fields.Datetime.now()
        base_posted = dom(('posted',))
        posted = [(k, l, listing.search_count(base_posted + [('posted', '>=', now - timedelta(days=d))])) for k, l, d in POSTED]
        posted_any = listing.search_count(base_posted)
        exp_base = dom(('exp',))
        exp_total, exp_known = listing.search_count(exp_base), listing.search_count(exp_base + [('exp_years_known', '=', True)])
        world = dict(grouped(['region'], ('region',)))
        zones = dict(grouped(['india_zone'], ('region',)))
        regions = [(slug, name, world.get(slug, 0), False) for slug, name, _t, _i in F.REGIONS if world.get(slug) or slug == state['region']]
        regions += [(slug, name, zones.get(slug, 0), True) for slug, name, _t, _i in F.INDIA_ZONES if zones.get(slug) or slug == state['region']]

        # one chip per active value, each removes only itself; "Clear all" stays on the page (a category, a course ...)
        chips = []
        if state['q']:
            chips.append(('“%s”' % state['q'], href(q='')))
        if state['location']:
            chips.append(('Location: %s' % state['location'], href(location='')))
        if state['region']:
            chips.append(('Region: %s' % REGION_INFO[state['region']][0], href(region='')))
        if state['country']:
            chips.append((state['country'], href(country='')))
        if state['track']:
            chips.append((C.TRACK_LABELS[state['track']], href(track='')))
        for name, values, label_of in (('city', state['city'], None), ('category', state['category'], C.CATEGORY_LABELS), ('function', state['function'], C.FUNCTION_LABELS),
                                       ('role', state['role'], C.ROLE_LABELS), ('skill', state['skill'], None), ('company', state['company'], None), ('size', state['size'], C.COMPANY_SIZE_LABELS),
                                       ('level', state['level'], dict(F.EXP_FILTER)), ('salary', state['salary'], F.SALARY_BAND_LABELS),
                                       ('jtype', state['jtype'], F.TYPE_LABELS)):
            for v in values:
                chips.append(((label_of or {}).get(v, v), href(**{name: [x for x in values if x != v]})))
        if state['mode']:
            chips.append((F.MODE_LABELS[state['mode']], href(mode='')))
        if state['posted']:
            chips.append((dict((k, l) for k, l, _d in POSTED)[state['posted']], href(posted='')))
        if state['exp_min'] > 0 or state['exp_max'] < EXP_MAX:
            chips.append(('%d–%s years' % (state['exp_min'], '25+' if state['exp_max'] >= EXP_MAX else state['exp_max']), href(exp_min=0, exp_max=EXP_MAX)))
        filter_chips = [{'label': l, 'href': h} for l, h in chips]
        clear_href = U.path(base, {}, look)

        course_keys = course['terms'] if course else []
        hidden = [(k, v) for k, v in params() if k not in ('q', 'location')] + ([('view', 'all')] if kind == 'all' and not own else [])
        strip = [c for c in companies if c[0] in state['company']]
        strip += [c for c in companies if c[0] not in state['company']][:max(14 - len(strip), 0)]
        all_counts = dict(listing._read_group([('active', '=', True), ('job_category', '!=', False)], ['job_category'], ['__count']))
        title = scope.get('title') or ('Search results for “%s”' % state['q'] if state['q'] else 'All jobs')
        return {
            'scope': dict(scope, kind=kind, title=title, description=scope.get('description') or 'Every open job on the board: real roles read from company job boards, with original Apply Now links.'),
            'listings': listings, 'total': total, 'pager': pager, 'own_page': bool(own), 'state': state, 'fq': fq, 'href': href, 'base': base, 'form_action': base,
            'chips': filter_chips, 'clear_href': clear_href, 'any_active': bool(filter_chips), 'regions': regions,
            'companies': companies, 'countries': countries, 'cities': [(city, country, n) for country, city, n in city_rows], 'functions': functions, 'categories': categories,
            'roles': [(c, C.ROLE_LABELS[c], n) for c, n in role_hits.most_common()], 'skills': skills,
            'jtypes': [(k, l, jtypes.get(k, 0), k in state['jtype']) for k, l in F.JOB_TYPES],
            'sizes': [(k, l, sizes.get(k, 0), k in state['size']) for k, l in C.COMPANY_SIZES],
            'levels': [(k, l, levels.get(k, 0), k in state['level']) for k, l in F.EXP_FILTER],
            # only the bands some job has (or that are selected): a currency nobody pays in is not offered
            'salary_bands': [(k, l, bands.get(k, 0), k in state['salary']) for k, l, _c, _lo, _hi in F.SALARY_BANDS if bands.get(k) or k in state['salary']], 'modes': F.WORK_MODES, 'mode_counts': modes,
            'posted_options': posted, 'posted_any': posted_any, 'exp_total': exp_total, 'exp_known': exp_known, 'exp_max_value': EXP_MAX,
            'course': course, 'term_labels': C.COURSE_TERM_LABELS, 'sorts': SORTS, 'sort': sort, 'sort_label': dict(SORTS)[sort],
            # all jobs / a category: the other category pages; any other page (a region, a course, a company ...): the categories of ITS jobs, as a filter that keeps the page
            'other_categories': ([(s, l, all_counts.get(s, 0), '/categories/%s' % s, False) for s, l, _d, _i in C.JOB_CATEGORIES if all_counts.get(s) and not (kind == 'category' and s == scope.get('value'))]
                                 if kind in ('all', 'category') and not own else
                                 [(s, l, n, href(category=[x for x in state['category'] if x != s] if s in state['category'] else state['category'] + [s]), s in state['category'])
                                  for s, l, n in sorted(categories, key=lambda c: [k for k, _l, _d, _i in C.JOB_CATEGORIES].index(c[0]) if c[0] in C.CATEGORY_LABELS else 99)]),
            'course_match': lambda job: C.course_match(course_keys, (job.term_keys or '').strip(',').split(',')) if course_keys else [],
            'hidden_params': hidden, 'company_strip': strip, 'scope_value': (scope.get('value') or '').replace('_', '-') if kind == 'role' else (scope.get('value') or ''),
            'card_cols': 'col-md-6 col-xl-4' if own else 'col-md-6 col-xxl-4',      # All Jobs: three across on a desktop 'slugify': slugify,
        }

    # ------------------------------------------------------------------ the landing page
    def _llmd_landing(self, args, focus='', hq_tab=''):
        listing = request.env['llmd.job.listing'].sudo()
        catalog = request.env['llmd.course.catalog']
        courses = catalog.courses()
        active = [('active', '=', True)]
        total = listing.search_count(active)
        cats = dict(listing._read_group(active + [('job_category', '!=', False)], ['job_category'], ['__count']))
        companies = sorted(listing._read_group(active + [('company', '!=', False)], ['company'], ['__count']), key=lambda r: (-r[1], r[0].lower()))
        cities = sorted(listing._read_group(active + [('city', '!=', False)], ['city'], ['__count']), key=lambda r: (-r[1], r[0]))
        countries = sorted(listing._read_group(active + [('country', '!=', False)], ['country'], ['__count']), key=lambda r: -r[1])
        roles = Counter(c for row in listing.search_read(active, ['roles']) for c in (row['roles'] or '').strip(',').split(',') if c in C.ROLE_LABELS)
        world = dict(listing._read_group(active + [('region', '!=', False)], ['region'], ['__count']))
        # companies by the region of their HEADQUARTERS (board_config.COMPANY_HQ), not by where their jobs are
        by_hq = {}
        company_slugs = self._llmd_company_slugs(listing)
        for region, company, hq, n in listing._read_group(active + [('company', '!=', False)], ['company_region', 'company', 'company_hq'], ['__count']):
            by_hq.setdefault(region or '', []).append((company, company_slugs.get(company, ''), n, hq or ''))
        company_regions = [(slug, name, icon, sorted(by_hq[slug], key=lambda c: (-c[2], c[0].lower()))) for slug, name, _t, icon in F.REGIONS if by_hq.get(slug)]
        if by_hq.get(''):
            company_regions.append(('not-verified', 'Headquarters not verified', 'fa-question-circle-o', sorted(by_hq[''], key=lambda c: (-c[2], c[0].lower()))))
        rec_code = args.get('rec') or (courses[0]['code'] if courses else '')
        course = catalog.resolve(rec_code, courses) or (courses[0] if courses else None)
        try:
            rec_pages = min(max(int(args.get('rec_page') or 1), 1), 20)                     # without the script "Load More Jobs" of a course reloads with one batch more
        except ValueError:
            rec_pages = 1
        recs = self._llmd_recommend(course, LATEST * rec_pages) if course else {'jobs': [], 'total': 0}
        own_jobs = request.env['hr.job'].sudo().search([('website_published', '=', True)] + request.website.website_domain(), limit=12)      # our own positions (stock Odoo pages)
        latest_cat = args.get('latest_cat') if args.get('latest_cat') in C.CATEGORY_LABELS else ''
        try:
            latest_page = min(max(int(args.get('latest') or 1), 1), 100000)                 # ?latest=N: page N of Latest Jobs (the page numbers without the script)
        except ValueError:
            latest_page = 1
        latest = self._llmd_latest(latest_cat, (latest_page - 1) * LATEST, LATEST)
        latest_page_total = max(1, -(-latest['total'] // LATEST))
        if latest_page > latest_page_total:                                                  # past the end: the last page
            latest_page = latest_page_total
            latest = self._llmd_latest(latest_cat, (latest_page - 1) * LATEST, LATEST)
        country_rows = sorted(listing._read_group(active + [('country', '!=', False)], ['country'], ['__count']), key=lambda r: (-r[1], r[0]))
        all_categories = sorted([(slug, label, text, icon, cats[slug]) for slug, label, text, icon in C.JOB_CATEGORIES if cats.get(slug)], key=lambda c: -c[4])
        if hq_tab and hq_tab not in [cr[0] for cr in company_regions]:
            raise NotFound()                                            # a region without companies has no tab
        return request.render('llmd_job_aggregator.landing_page', {
            'hq_active': hq_tab or (company_regions[0][0] if company_regions else ''),
            'total': total, 'company_total': len(companies), 'country_total': len(countries),
            'top_categories': all_categories[:8], 'category_total': len(all_categories),
            'company_regions': company_regions, 'region_total': len(world),
            'latest': latest['jobs'], 'latest_total': latest['total'], 'latest_cat': latest_cat,
            'latest_page': latest_page, 'latest_page_total': latest_page_total, 'latest_nav': _page_numbers(latest_page, latest_page_total), 'latest_nav_s': _page_numbers(latest_page, latest_page_total, 3),
            'latest_chips': [(slug, label, cats[slug]) for slug, label, _t, _i in sorted(C.JOB_CATEGORIES, key=lambda c: -cats.get(c[0], 0)) if cats.get(slug)][:8],
            'last_sync': self._llmd_last_sync(),
            'top_countries': [(c, slugify(c), n, _flag(c)) for c, n in country_rows[:10]], 'all_country_total': len(country_rows),
            'flag_font': _flag_font(''.join(_flag(c) for c, _n in country_rows[:10])),
            'popular': [(code.replace('_', '-'), C.ROLE_LABELS[code], n) for code, n in roles.most_common(6)],
            'courses': courses, 'course': course, 'recs': recs, 'rec_page': rec_pages, 'show_courses': bool(args.get('rec')), 'focus': focus,
            'cm_step': 'start' if not args.get('rec') else ('jobs' if args.get('cm') == 'jobs' or args.get('rec_page') else ('pick' if args.get('cm') == 'pick' else 'info')),
            'latest_path': latest_path, 'course_counts': {co['code']: listing.search_count(active + _course_domain(co)) for co in courses},
            'own_jobs': own_jobs,
            'location_options': [c for c, _n in countries] + ['Delhi NCR'] + [c for c, _n in cities[:60]] + ['Remote'],
            'term_labels': C.COURSE_TERM_LABELS, 'card_cols': 'col-md-6 col-xl-4', 'slugify': slugify,
        })

    # ------------------------------------------------------------------ Latest Jobs: the newest by posting date, a category shortcut, the next batch
    @staticmethod
    def _llmd_latest(category, offset, limit):
        """{'jobs', 'total'}: the visible jobs (of one category) newest first by their real posting date - a job without a date comes last, never as "new"."""
        listing = request.env['llmd.job.listing'].sudo()
        domain = [('active', '=', True)] + ([('job_category', '=', category)] if category else [])
        return {'jobs': listing.search(domain, offset=offset, limit=limit, order='posted desc nulls last, id desc'), 'total': listing.search_count(domain)}

    @staticmethod
    def _llmd_last_sync():
        """'Updated 2 hours ago' and the exact time of the last sync that brought jobs (the sync log), or None when there is none."""
        run = request.env['llmd.job.sync'].sudo().search([('finished', '!=', False), ('state', 'in', ('ok', 'partial')), '|', ('created', '>', 0), ('updated', '>', 0)],
                                                       order='finished desc', limit=1)
        return {'text': _updated_ago(run.finished), 'at': fields.Datetime.to_string(run.finished)} if run else None

    @http.route('/jobs/latest', type='http', auth='public', website=True, sitemap=False)
    def llmd_latest(self, category='', page=1, **kwargs):
        """One page of Latest Jobs and its page numbers (the page numbers and the category shortcuts fetch it; without the script the landing page reloads)."""
        category = category if category in C.CATEGORY_LABELS else ''
        try:
            page = min(max(int(page), 1), 100000)                                      # any batch of the board (an empty one past the end)
        except (TypeError, ValueError):
            page = 1
        latest = self._llmd_latest(category, (page - 1) * LATEST, LATEST)
        return request.render('llmd_job_aggregator.latest_batch', {
            'latest': latest['jobs'], 'latest_total': latest['total'], 'more': page * LATEST < latest['total'], 'page': page, 'latest_cat': category, 'latest_path': latest_path,
            'pages': max(1, -(-latest['total'] // LATEST)), 'nav': _page_numbers(page, max(1, -(-latest['total'] // LATEST))),
            'nav_s': _page_numbers(page, max(1, -(-latest['total'] // LATEST)), 3)})

    # ------------------------------------------------------------------ the directories: every category, every region of the world
    def llmd_categories(self, **kwargs):
        """Every job category that has jobs now, with its number of jobs and companies (a category appears as soon as a sync brings jobs for it)."""
        listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        counts = dict(listing._read_group(active + [('job_category', '!=', False)], ['job_category'], ['__count']))
        companies = Counter(cat for cat, _co, _n in listing._read_group(active + [('job_category', '!=', False), ('company', '!=', False)], ['job_category', 'company'], ['__count']))
        cats = sorted([(slug, label, text, icon, counts[slug], companies[slug]) for slug, label, text, icon in C.JOB_CATEGORIES if counts.get(slug)], key=lambda c: -c[4])
        return request.render('llmd_job_aggregator.category_directory', {'cats': cats, 'total': listing.search_count(active)})

    @http.route('/locations', type='http', auth='public', website=True, sitemap=False)
    def llmd_countries(self, mode='', **kwargs):
        """Every country that has jobs now, by region, with its number of jobs (all work modes; /locations/remote counts the remote jobs only, on their own)."""
        if mode:
            return request.redirect('/locations/remote' if mode == 'remote' else '/locations', code=301)
        return self._llmd_countries('')

    def _llmd_countries(self, mode):
        listing = request.env['llmd.job.listing'].sudo()
        mode = mode if mode in F.MODE_LABELS else ''
        domain = [('active', '=', True), ('country', '!=', False)] + ([('work_mode', '=', mode)] if mode else [])
        rows = listing._read_group(domain, ['region', 'country'], ['__count'])
        groups = []
        for slug, name, _t, icon in F.REGIONS:
            found = sorted([(c, slugify(c), n, _flag(c)) for r, c, n in rows if r == slug], key=lambda c: (-c[2], c[0]))
            if found:
                groups.append((slug, name, icon, found, sum(c[2] for c in found)))
        other = sorted([(c, slugify(c), n, _flag(c)) for r, c, n in rows if not r], key=lambda c: (-c[2], c[0]))
        if other:
            groups.append(('other', 'Other countries', 'fa-flag-o', other, sum(c[2] for c in other)))
        total = listing.search_count([('active', '=', True)] + ([('work_mode', '=', mode)] if mode else []))
        return request.render('llmd_job_aggregator.country_directory', {
            'groups': groups, 'mode': mode, 'total': total, 'country_total': sum(len(g[3]) for g in groups),
            'no_country': total - sum(g[4] for g in groups), 'flag_font': _flag_font(''.join(c[3] for g in groups for c in g[3])),
        })

    @http.route('/regions', type='http', auth='public', website=True, sitemap=False)
    def llmd_regions(self, **kwargs):
        """Every region of the world that has jobs - by where the JOBS are - with its countries, its regions of India and the companies hiring there."""
        listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        total = listing.search_count(active)
        world = dict(listing._read_group(active + [('region', '!=', False)], ['region'], ['__count']))
        countries = listing._read_group(active + [('region', '!=', False), ('country', '!=', False)], ['region', 'country'], ['__count'])
        companies = listing._read_group(active + [('region', '!=', False), ('company', '!=', False)], ['region', 'company'], ['__count'])
        company_slugs = self._llmd_company_slugs(listing)
        zones = dict(listing._read_group(active + [('india_zone', '!=', False)], ['india_zone'], ['__count']))
        regions = []
        for slug, name, text, icon in F.REGIONS:
            if not world.get(slug):
                continue
            regions.append({
                'slug': slug, 'name': name, 'text': text, 'icon': icon, 'count': world[slug],
                'countries': sorted([(c, slugify(c), n) for r, c, n in countries if r == slug], key=lambda c: (-c[2], c[0])),
                'companies': sorted([(co, company_slugs.get(co, ''), n) for r, co, n in companies if r == slug], key=lambda c: (-c[2], c[0].lower())),
                'zones': [(z, zname, zones[z]) for z, zname, _t, _i in F.INDIA_ZONES if zones.get(z)] if slug == 'india-south-asia' else [],
            })
        return request.render('llmd_job_aggregator.region_directory', {
            'regions': regions, 'total': total, 'no_region': total - sum(world.values()),
            'empty_regions': [name for slug, name, _t, _i in F.REGIONS if not world.get(slug)],
        })

    @staticmethod
    def _llmd_recommend(course, limit=6, offset=0):
        """The jobs a course leads to (unchanged course matching), the most relevant first: the most terms shared with the course's own text, then the newest."""
        listing = request.env['llmd.job.listing'].sudo()
        domain = [('active', '=', True)] + _course_domain(course)
        rows = listing.search_read(domain, ['term_keys', 'india', 'posted'])
        keys = set(course['terms'])
        rows.sort(key=lambda r: (len(keys & set((r['term_keys'] or '').strip(',').split(','))), r['india'], r['posted'] or fields.Datetime.to_datetime('1970-01-01'), r['id']), reverse=True)
        jobs = listing.browse([r['id'] for r in rows[offset:offset + limit]])
        return {'jobs': [(job, C.course_match(course['terms'], (job.term_keys or '').strip(',').split(','))) for job in jobs], 'total': len(rows)}

    @http.route('/jobs/course-matches', type='http', auth='public', website=True, sitemap=False)
    def llmd_course_matches(self, course=None, page=1, **kwargs):
        """The course-matched jobs of one course, as a piece of the landing page (the course selector swaps it in without reloading the page;
        page 2, 3 ... = the next batch for "Load More Jobs")."""
        catalog = request.env['llmd.course.catalog']
        courses = catalog.courses()
        chosen = catalog.resolve(course or '', courses)
        if not chosen:
            raise NotFound()
        try:
            page = min(max(int(page), 1), 100000)
        except (TypeError, ValueError):
            page = 1
        return request.render('llmd_job_aggregator.course_matches', {'course': chosen, 'recs': self._llmd_recommend(chosen, LATEST, (page - 1) * LATEST),
                                                                     'rec_page': page, 'term_labels': C.COURSE_TERM_LABELS, 'card_cols': 'col-md-6 col-xl-4'})

    @http.route('/jobs/results-count', type='http', auth='public', website=True, sitemap=False)
    def llmd_results_count(self, **kwargs):
        """How many jobs the filter panel would show (its "Apply Filters" button tells before the visitor applies them)."""
        args = request.httprequest.args
        state = self._llmd_state(args)
        kind, value = args.get('scope') or 'all', args.get('scope_value') or ''
        scope = {'kind': 'all'}
        if kind == 'category' and value in C.CATEGORY_LABELS:
            scope = {'kind': 'category', 'value': value}
        elif kind == 'company' and value:
            scope = {'kind': 'company', 'value': value}
        elif kind == 'role' and value.replace('-', '_') in C.ROLE_LABELS:
            scope = {'kind': 'role', 'value': value.replace('-', '_')}
        elif kind == 'location' and value:
            place = self._llmd_place(value)
            if place:
                scope = {'kind': 'location', 'domain': place[1]}
        elif kind == 'region' and value in REGION_INFO:
            scope = {'kind': 'region', 'value': value}
        elif kind == 'course' and value:
            course = request.env['llmd.course.catalog'].resolve(value)
            if course:
                scope = {'kind': 'course', 'value': course['code'], 'course': course}
        count = request.env['llmd.job.listing'].sudo().search_count(self._llmd_domain(state, scope))
        return request.make_json_response({'count': count})

    @staticmethod
    def _llmd_listing(listing_id):
        job = request.env['llmd.job.listing'].sudo().search([('id', '=', listing_id), ('active', '=', True)], limit=1)
        if not job:
            raise NotFound()
        return job

    @http.route('/jobs/<int:listing_id>/<string:slug>', type='http', auth='public', website=True, sitemap=False)
    def llmd_job_page(self, listing_id, slug, **kwargs):
        """ONE job, found by its ID: /jobs/<id>/<title-slug>. A wrong or old slug goes to the right one (301); a job that does not exist or is no longer
        open gets the "job not available" page (404)."""
        job = self._llmd_open_listing(listing_id)
        if not job:
            return self._llmd_job_gone(listing_id)
        return self._llmd_moved(job.website_path())                   # the older /jobs/<id>/<title>: the job's own address /jobs/<slug> (the ID decides)

    @http.route('/jobs/ext/<int:listing_id>', type='http', auth='public', website=True, sitemap=False)
    def llmd_board_detail(self, listing_id, **kwargs):
        """The older address of a job page: kept working, it moves to /jobs/<id>/<slug>."""
        job = self._llmd_open_listing(listing_id)
        return self._llmd_moved(job.website_path()) if job else self._llmd_job_gone(listing_id)

    @staticmethod
    def _llmd_open_listing(listing_id):
        return request.env['llmd.job.listing'].sudo().search([('id', '=', listing_id), ('active', '=', True)], limit=1)

    @staticmethod
    def _llmd_moved(path):
        """A permanent move to `path` (built here, local), the query string kept."""
        query = request.httprequest.query_string.decode()
        return request.redirect(path + ('?' + query if query else ''), code=301)

    def _llmd_job_gone(self, listing_id):
        """404 page for a job ID that does not exist or is no longer open (hidden by a sync): what it was, if we know it, and where to go on."""
        old = request.env['llmd.job.listing'].sudo().with_context(active_test=False).search([('id', '=', listing_id)], limit=1)
        response = request.render('llmd_job_aggregator.job_unavailable', {'old': old, 'similar': self._llmd_similar(old) if old else [],
                                                                          'company_href': old.company_link() if old else ''})
        response.status_code = 404
        return response

    @staticmethod
    def _llmd_similar(job, limit=3):
        """Up to three other real jobs like this one: the same course role first, then the same category (Indian jobs first, the newest first)."""
        Listing = request.env['llmd.job.listing'].sudo()
        found = Listing.browse()
        wanted = [('roles', 'ilike', ',%s,' % r) for r in (job.roles or '').strip(',').split(',') if r][:1]
        code = job.card_track()[0]
        if code:
            wanted.append(('tags', 'ilike', ',%s,' % code))
        for leaf in wanted:
            if len(found) >= limit:
                break
            found |= Listing.search([('active', '=', True), ('id', 'not in', [job.id] + found.ids), leaf], limit=limit - len(found))
        return found

    # ------------------------------------------------------------------ Apply Now - ONE flow for every Apply Now button of the site
    # Every Apply Now (job cards of every list, the detail page, our positions, our form, Odoo's form of our positions) leads to one of these routes:
    #   /jobs/ext/<id>/go, /jobs/ext/<id>/apply, /jobs/position/<id>/go, /jobs/apply/<position>
    # and each of them starts with _llmd_gate() (not signed in -> login / sign-up, back to the same route afterwards) and records with _llmd_track()
    # (Apply Clicks line + the signed-in person's Job Applications record). A new template only has to link to one of these routes.
    @staticmethod
    def _llmd_visitor():
        """(visitor id, is it new): a random first-party id, no name, no e-mail."""
        vid = request.httprequest.cookies.get(VISITOR_COOKIE) or ''
        if re.fullmatch(r'[A-Za-z0-9_-]{16,40}', vid):
            return vid, False
        return secrets.token_urlsafe(16), True

    @staticmethod
    def _llmd_set_cookie(response, vid):
        if vid[1]:
            response.set_cookie(VISITOR_COOKIE, vid[0], max_age=365 * 24 * 3600, httponly=True, samesite='Lax', secure=request.httprequest.is_secure)
        return response

    @classmethod
    def _llmd_send_on(cls, url, vid):
        response = request.redirect(url, local=False)
        response.headers['Cache-Control'] = 'no-store'
        return cls._llmd_set_cookie(response, vid)

    @staticmethod
    def _llmd_sign_in_first():
        """Apply Now asks for a sign-in first (default, llmd_agg.apply_login) and the visitor is not signed in."""
        return L.apply_login_required(request.env) and request.env.user._is_public()

    @staticmethod
    def _llmd_to_login(path):
        """To Odoo's login page (its "Don't have an account?" sign-up keeps the same redirect). Afterwards the visitor comes back to `path` - the same Apply Now of the
        same job - and goes on from there, never to the homepage. `path` is built here from the job ID only; the session keeps it too, for a sign-in that loses the
        redirect on the way (reset password ...)."""
        request.session[APPLY_NEXT_KEY] = path
        response = request.redirect('/web/login?' + urlencode({'redirect': path}))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @staticmethod
    def _llmd_user():
        """The signed-in account (it reached Apply Now, so the pending sign-in is done), or None."""
        user = request.env.user
        if not user or user._is_public():
            return None
        request.session.pop(APPLY_NEXT_KEY, None)
        return user

    def _llmd_gate(self, path):
        """The login step of every Apply Now: the login redirect (back to `path`) when the visitor must sign in first, else None (go on)."""
        return self._llmd_to_login(path) if self._llmd_sign_in_first() else None

    def _llmd_track(self, vid, external, line=True, url=None, listing=None, job=None, person=True):
        """Record one Apply Now: a line in Apply Clicks (`line`: the visitor is sent on to an application page; the job and the time, no name or e-mail) and, for a
        signed-in visitor, their Job Applications record (name, e-mail, user ID; "Redirected to External Site" when `external`, else "Apply Clicked" - never "submitted").
        `person=False`: the click line only (a job without a valid link: nobody is sent anywhere). Crawlers and previews are not counted. A failure to save is
        logged and never keeps the visitor from going on."""
        if request.httprequest.method != 'GET' or BOT.search(request.httprequest.user_agent.string or ''):
            return
        user = self._llmd_user() if person else None
        target = {'listing': listing, 'job': job}
        try:
            with request.env.cr.savepoint():
                if line:
                    request.env['llmd.job.click'].sudo().record_click(visitor=vid[0], url=url, user=user, **target)
                if user:
                    Application = request.env['llmd.job.application'].sudo()
                    Application.record_apply_now(Application.job_info(**target), user, external)
        except Exception:
            _logger.exception('apply now could not be saved (%s); the visitor goes on anyway', {k: getattr(v, 'id', v) for k, v in target.items()})

    @http.route('/jobs/auth/state', type='http', auth='public', website=True, sitemap=False)
    def llmd_auth_state(self, **kwargs):
        """For the sign-in window of a job's Apply Now (the page stays open): is this session signed in, and the CSRF token for Odoo's own /web/login and /web/signup
        forms, which the window posts to. It is also their `redirect` after a successful sign-in / sign-up, so the window knows it worked. Nothing else is read or kept."""
        user = request.env.user
        signed_in = bool(user and not user._is_public())
        body = {'signed_in': signed_in, 'login_required': L.apply_login_required(request.env), 'csrf_token': request.csrf_token(),
                'name': user.name if signed_in else ''}
        return request.make_response(json.dumps(body), headers=[('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])

    @http.route('/jobs/ext/<int:listing_id>/go', type='http', auth='public', website=True, sitemap=False)
    def llmd_board_go(self, listing_id, **kwargs):
        job = self._llmd_listing(listing_id)
        url = job.safe_apply_url()
        if not url:                                                     # no valid link: the line says "no_link", the visitor goes back to the job
            self._llmd_track(self._llmd_visitor(), False, listing=job, person=False)
            return request.redirect(job.website_path())
        login = self._llmd_gate('/jobs/ext/%d/go' % job.id)
        if login:
            return login
        vid = self._llmd_visitor()
        self._llmd_track(vid, True, listing=job)
        return self._llmd_send_on(url, vid)

    @http.route('/jobs/position/<int:job_id>/go', type='http', auth='public', website=True, sitemap=False)
    def llmd_position_go(self, job_id, **kwargs):
        position = request.env['hr.job'].sudo().search([('id', '=', job_id), ('website_published', '=', True)], limit=1)
        if not position:
            raise NotFound()
        url = valid_url(position.apply_url)
        if not url:
            self._llmd_track(self._llmd_visitor(), False, job=position, person=False)
            return request.redirect(position.website_url or '/jobs')
        login = self._llmd_gate('/jobs/position/%d/go' % position.id)
        if login:
            return login
        vid = self._llmd_visitor()
        if L.is_board_link(url) and L.direct_links_only(request.env):
            form = '/jobs/apply/%s' % request.env['ir.http']._slug(position)   # direct links only: a job board page is no direct link - our own position is applied for on our own Odoo form
            self._llmd_track(vid, False, url=form, job=position)
            return self._llmd_send_on(form, vid)
        self._llmd_track(vid, True, job=position)
        return self._llmd_send_on(url, vid)

    @http.route()
    def jobs_apply(self, job, **kwargs):
        """Odoo's own application form of one of our positions (its "Apply Now!" button, and the form our position's Apply Now leads to): the same sign-in first."""
        login = self._llmd_gate('/jobs/apply/%s' % request.env['ir.http']._slug(job))
        if login:
            return login
        self._llmd_track(self._llmd_visitor(), False, line=False, job=job.sudo())
        return super().jobs_apply(job, **kwargs)

    # ------------------------------------------------------------------ Apply Now (mode "form"): OUR application form - the application is SAVED in Odoo first, only then "received" is shown
    @staticmethod
    def _llmd_person():
        """Name / e-mail of a logged-in website user (their own profile), only to pre-fill the form they then send themselves (nothing is stored from it)."""
        user = request.env.user
        if user and not user._is_public() and user.email:
            return {'name': user.name, 'email': user.email}
        return {}

    def _llmd_form_job(self, listing_id):
        job = self._llmd_listing(listing_id)
        if job.apply_mode() != 'form':
            raise NotFound()
        return job

    def _llmd_page(self, template, job, status=200, vid=None, **values):
        response = request.render(template, dict({'job': job, 'd': job.detail_vals()}, **values))
        response.status_code = status
        return self._llmd_set_cookie(response, vid) if vid else response

    @http.route('/jobs/ext/<int:listing_id>/apply', type='http', auth='public', website=True, methods=['GET', 'POST'], sitemap=False)
    def llmd_board_apply(self, listing_id, **post):
        job = self._llmd_form_job(listing_id)
        login = self._llmd_gate('/jobs/ext/%d/apply' % job.id)        # also a POST: a form sent after the session ended is not taken without an account
        if login:
            return login
        vid = self._llmd_visitor()
        max_mb = A.MAX_RESUME // (1024 * 1024)
        if request.httprequest.method != 'POST':
            self._llmd_track(vid, False, line=False, listing=job)       # "Apply Clicked" in Job Applications; sending the form makes it "Received"
            return self._llmd_page('llmd_job_aggregator.board_apply', job, vid=vid, vals=self._llmd_person(), errors={}, max_mb=max_mb)
        if post.get('company_website'):                                # hidden field that only bots fill in
            return request.redirect('/jobs')
        vals, errors = A.validate(post)                                   # name + e-mail: no phone is read
        upload = request.httprequest.files.get('resume')
        data = upload.read(A.MAX_RESUME + 1) if upload else b''
        error, _ext, mimetype, filename = A.check_resume(upload.filename if upload else '', data)
        if error:
            errors['resume'] = error
        if errors:
            return self._llmd_page('llmd_job_aggregator.board_apply', job, 400, vid, vals=vals, errors=errors, max_mb=max_mb)
        Application = request.env['llmd.job.application'].sudo()
        if Application._too_many(vid[0]):
            errors['form'] = 'Too many applications from this browser. Please try again in an hour.'
            return self._llmd_page('llmd_job_aggregator.board_apply', job, 429, vid, vals=vals, errors=errors, max_mb=max_mb)
        try:
            rec, status = Application.submit_own(job, vals, filename, mimetype, data, vid[0])
        except Exception:
            _logger.exception('job application could not be saved (listing %s)', job.id)
            errors['form'] = 'Sorry, your application could not be saved right now, so nothing was sent. Please try again in a few minutes.'
            return self._llmd_page('llmd_job_aggregator.board_apply', job, 500, vid, vals=vals, errors=errors, max_mb=max_mb)
        return self._llmd_set_cookie(request.redirect('/jobs/ext/%d/applied?ref=%d&t=%s%s' % (job.id, rec.id, Application.token(rec.id), '&again=1' if status == 'duplicate' else '')), vid)

    @http.route('/jobs/ext/<int:listing_id>/applied', type='http', auth='public', website=True, sitemap=False)
    def llmd_board_applied(self, listing_id, ref=None, t=None, again=None, **kwargs):
        job = self._llmd_form_job(listing_id)
        Application = request.env['llmd.job.application'].sudo()
        rec = Application.with_context(active_test=False).browse(int(ref) if (ref or '').isdigit() else 0).exists()
        if not rec or not Application.token_ok(rec.id, t) or rec.job_key != Application.job_info(listing=job)['job_key'] or rec.state not in ('reported', 'submitted', 'confirmed'):
            raise NotFound()
        return self._llmd_page('llmd_job_aggregator.board_applied', job, application=rec, again=bool(again))

    # ------------------------------------------------------------------ the backend API: applicant data only from an authorized provider integration (X-Api-Key)
    @http.route('/api/llmd/applications', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def llmd_api_applications(self, **payload):
        """JSON-RPC body {"jsonrpc": "2.0", "method": "call", "params": {"action": "applicant", "job": {"listing_id": 1} | {"source": "Jooble", "ext_id": "123"} | {"hr_job_id": 2},
        "name": ..., "email": ..., "note": ... (optional), "provider_ref": ... (optional)}} with the header X-Api-Key. Without a valid key nothing is stored."""
        Application = request.env['llmd.job.application'].sudo()
        try:
            with request.env.cr.savepoint():
                return Application.process_api(payload, Application.api_key_ok(request.httprequest.headers.get('X-Api-Key') or payload.get('api_key')))
        except Exception:
            _logger.exception('application API: request could not be processed')
            return {'ok': False, 'error': 'server_error', 'message': 'The request could not be saved right now. Nothing was stored.'}


class LlmdLogin(Website):
    """After a sign-in / sign-up that started at Apply Now, back to that Apply Now (job ID kept) - also when the login page lost its `redirect` on the way."""

    def _login_redirect(self, uid, redirect=None):
        if not redirect:
            pending = request.session.pop(APPLY_NEXT_KEY, None)
            if isinstance(pending, str) and APPLY_NEXT.fullmatch(pending):
                redirect = pending
        return super()._login_redirect(uid, redirect=redirect)
