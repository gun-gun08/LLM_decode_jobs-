import json
import logging
import re
import secrets
from collections import Counter
from datetime import timedelta
from urllib.parse import quote, urlencode

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request

from odoo.addons.website_hr_recruitment.controllers.main import WebsiteHrRecruitment

from ..models import apply_utils as A
from ..models import board_config as C
from ..models import job_facets as F
from ..models import listing as L
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
FILTERS = ('q', 'location', 'region', 'country', 'city', 'exp_min', 'exp_max', 'category', 'function', 'role', 'skill', 'company', 'mode', 'jtype', 'posted', 'track')
OLD = ('loc', 'sort', 'view', 'exp', 'salary', 'tab', 'course')                     # older links that still lead to the results (?course= moves to /jobs/course/<course>)
REGION_INFO = {slug: (name, text, icon) for slug, name, text, icon in F.REGIONS + F.INDIA_ZONES}
ZONES = {slug for slug, _n, _t, _i in F.INDIA_ZONES}


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


class JobBoard(WebsiteHrRecruitment):
    """/jobs is the job board: a landing page (search, categories, course matches, companies, latest jobs, locations, FAQ) and, as soon as something is searched
    or filtered, the results. /jobs/category|company|location|role/<slug> are the same results for one category, company, place or role; /jobs/ext/<id> is ONE job.
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
                 'company': _free(args, 'company', 15), 'mode': args.get('mode') if args.get('mode') in F.MODE_LABELS else '', 'jtype': _multi(args, 'jtype', F.TYPE_LABELS),
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
        if kwargs.get('stock'):
            return super().jobs(page=page, search=search, **kwargs)
        args = request.httprequest.args
        state = self._llmd_state(args, search)
        if 'course' in args:                                            # the course is no general filter: its jobs have their own page (old ?course= links move there)
            course = request.env['llmd.course.catalog'].resolve(state['course']) if state['course'] else None
            rest = urlencode([(k, v) for k, v in args.items(multi=True) if k != 'course'] + ([('track', state['track'])] if state['track'] and 'track' not in args else []))
            if course:
                return request.redirect('/jobs/course/%s%s' % (course['code'], '?' + rest if rest else ''), code=301)
            return request.redirect('/jobs%s' % ('?' + rest if rest else ''), code=301)
        if int(page or 1) == 1 and not search and not any(k in args for k in FILTERS + OLD):      # an empty search (?q=) is a search: all jobs
            return self._llmd_landing(args)
        return self._llmd_results({'kind': 'all'}, int(page or 1), state)

    @http.route(['/jobs/category/<string:slug>', '/jobs/category/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_category(self, slug, page=1, **kwargs):
        if slug in C.OLD_CATEGORY_SLUGS:
            query = request.httprequest.query_string.decode()
            return request.redirect('/jobs/category/%s%s' % (C.OLD_CATEGORY_SLUGS[slug], '?' + query if query else ''), code=301)
        category = {c[0]: c for c in C.JOB_CATEGORIES}.get(slug)
        if not category:
            raise NotFound()
        scope = {'kind': 'category', 'value': slug, 'label': category[1], 'title': '%s jobs' % category[1], 'description': category[2], 'icon': category[3],
                 'crumb': ('Categories', '/jobs#categories')}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

    @http.route(['/jobs/company/<string:slug>', '/jobs/company/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_company(self, slug, page=1, **kwargs):
        names = [c for c, _n in request.env['llmd.job.listing'].sudo()._read_group([('active', '=', True), ('company', '!=', False)], ['company'], ['__count'])]
        name = next((c for c in names if slugify(c) == slug), None)
        if not name:
            raise NotFound()
        hq = C.company_hq(name)
        scope = {'kind': 'company', 'value': name, 'label': name, 'title': 'Jobs at %s' % name, 'icon': 'fa-building-o', 'initial': name.strip()[:1].upper(),
                 'description': 'Open roles at %s, read from its own job board%s. Apply Now opens its application page.' % (
                     name, ' - headquarters: %s (%s)' % (hq, F.REGION_LABELS.get(F.COUNTRY_REGION.get(hq, ''), '')) if hq else ''), 'crumb': ('Companies', '/jobs#companies')}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

    @http.route(['/jobs/location/<string:slug>', '/jobs/location/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_location(self, slug, page=1, **kwargs):
        place = self._llmd_place(slug)
        if not place:
            raise NotFound()
        scope = {'kind': 'location', 'value': slug, 'label': place[0], 'domain': place[1], 'place': place[2], 'title': '%s jobs' % place[0] if place[2] == 'remote' else 'Jobs in %s' % place[0],
                 'description': place[3], 'icon': 'fa-wifi' if place[2] == 'remote' else 'fa-map-marker', 'crumb': ('Regions', '/jobs#regions')}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

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

    @http.route(['/jobs/course/<string:code>', '/jobs/course/<string:code>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_course(self, code, page=1, **kwargs):
        """The jobs one LLM Decode course leads to ("View all course-matched jobs"): the course matching is unchanged, the general filters narrow it."""
        course = request.env['llmd.course.catalog'].resolve(code)
        if not course:
            raise NotFound()
        if course['code'] != code:
            return request.redirect('/jobs/course/%s' % course['code'], code=301)
        scope = {'kind': 'course', 'value': course['code'], 'course': course, 'label': course['name'], 'title': 'Jobs matched to %s' % course['name'], 'icon': 'fa-graduation-cap',
                 'description': 'The roles this course prepares you for, the closest match to what it teaches first.', 'crumb': ('Course matches', '/jobs#courses')}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

    @http.route(['/jobs/region/<string:slug>', '/jobs/region/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_region(self, slug, page=1, **kwargs):
        if slug not in REGION_INFO:
            raise NotFound()
        name, text, icon = REGION_INFO[slug]
        scope = {'kind': 'region', 'value': slug, 'label': name, 'title': 'Jobs in %s' % name if slug != 'worldwide' else 'Global / worldwide jobs', 'description': text,
                 'icon': icon if slug not in ZONES else 'fa-map-marker', 'crumb': ('Regions', '/jobs#regions'), 'zone': slug in ZONES}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

    @http.route(['/jobs/role/<string:slug>', '/jobs/role/<string:slug>/page/<int:page>'], type='http', auth='public', website=True, sitemap=False)
    def llmd_role(self, slug, page=1, **kwargs):
        code = slug.replace('-', '_')
        if code not in C.ROLE_LABELS:
            raise NotFound()
        label = C.ROLE_LABELS[code]
        scope = {'kind': 'role', 'value': code, 'label': label, 'title': '%s jobs' % label, 'icon': 'fa-id-badge', 'crumb': ('Roles', '/jobs#popular'),
                 'description': 'Jobs whose title names this role (%s), from every working source.' % label}
        return self._llmd_results(scope, int(page or 1), self._llmd_state(request.httprequest.args))

    # ------------------------------------------------------------------ the filters as ONE search domain
    @staticmethod
    def _llmd_domain(state, scope, skip=()):
        domain = [('active', '=', True)]
        kind = scope.get('kind')
        if kind == 'category':
            domain.append(('job_category', '=', scope['value']))
        elif kind == 'company':
            domain.append(('company', '=', scope['value']))
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
    def _llmd_results(self, scope, page, state):
        return request.render('llmd_job_aggregator.results_page', self._llmd_results_values(scope, page, state))

    def _llmd_results_values(self, scope, page, state):
        """Everything a list of results shows: the jobs of one page, every filter with its counts, chips, sort, pages (results pages and the landing page)."""
        listing = request.env['llmd.job.listing'].sudo()
        course = scope.get('course')                                    # only the course page has one: the course is no general filter
        kind = scope['kind']
        base = {'all': '/jobs', 'category': '/jobs/category/%s' % scope.get('value'), 'company': '/jobs/company/%s' % slugify(scope.get('value')),
                'location': '/jobs/location/%s' % scope.get('value'), 'role': '/jobs/role/%s' % (scope.get('value') or '').replace('_', '-'),
                'course': '/jobs/course/%s' % scope.get('value'), 'region': '/jobs/region/%s' % scope.get('value')}[kind]
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
            if kind == 'all' and not found:
                found.append(('view', 'all'))                         # /jobs without anything is the landing page
            return urlencode(found)

        def href(**override):
            query = fq(**override)
            return base + ('?' + query if query else '')

        domain = dom()
        total = listing.search_count(domain)
        url_args = {}
        for k in keys:
            value = state.get(k)
            if k == 'exp_min' and value == 0 or k == 'exp_max' and value == EXP_MAX or value in ('', None, []):
                continue
            url_args[k] = '|'.join(value) if k in ('city', 'skill', 'company') and isinstance(value, list) else (','.join(value) if isinstance(value, list) else value)
        if kind == 'all' and not url_args:
            url_args['view'] = 'all'
        pager = request.website.pager(url=base, total=total, page=page, step=PER_PAGE, url_args=url_args)
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
                                       ('role', state['role'], C.ROLE_LABELS), ('skill', state['skill'], None), ('company', state['company'], None), ('jtype', state['jtype'], F.TYPE_LABELS)):
            for v in values:
                chips.append(((label_of or {}).get(v, v), href(**{name: [x for x in values if x != v]})))
        if state['mode']:
            chips.append((F.MODE_LABELS[state['mode']], href(mode='')))
        if state['posted']:
            chips.append((dict((k, l) for k, l, _d in POSTED)[state['posted']], href(posted='')))
        if state['exp_min'] > 0 or state['exp_max'] < EXP_MAX:
            chips.append(('%d–%s years' % (state['exp_min'], '25+' if state['exp_max'] >= EXP_MAX else state['exp_max']), href(exp_min=0, exp_max=EXP_MAX)))
        filter_chips = [{'label': l, 'href': h} for l, h in chips]
        clear_href = base + ('?view=all' if kind == 'all' else '')

        course_keys = course['terms'] if course else []
        hidden = [(k, v) for k, v in params() if k not in ('q', 'location')] + ([('view', 'all')] if kind == 'all' else [])
        strip = [c for c in companies if c[0] in state['company']]
        strip += [c for c in companies if c[0] not in state['company']][:max(14 - len(strip), 0)]
        all_counts = dict(listing._read_group([('active', '=', True), ('job_category', '!=', False)], ['job_category'], ['__count']))
        title = scope.get('title') or ('Search results for “%s”' % state['q'] if state['q'] else 'All jobs')
        return {
            'scope': dict(scope, kind=kind, title=title, description=scope.get('description') or 'Every open job on the board: real roles read from company job boards, with original Apply Now links.'),
            'listings': listings, 'total': total, 'pager': pager, 'state': state, 'fq': fq, 'href': href, 'base': base,
            'chips': filter_chips, 'clear_href': clear_href, 'any_active': bool(filter_chips), 'regions': regions,
            'companies': companies, 'countries': countries, 'cities': [(city, country, n) for country, city, n in city_rows], 'functions': functions, 'categories': categories,
            'roles': [(c, C.ROLE_LABELS[c], n) for c, n in role_hits.most_common()], 'skills': skills,
            'jtypes': [(k, l, jtypes.get(k, 0), k in state['jtype']) for k, l in F.JOB_TYPES], 'modes': F.WORK_MODES, 'mode_counts': modes,
            'posted_options': posted, 'posted_any': posted_any, 'exp_total': exp_total, 'exp_known': exp_known, 'exp_max_value': EXP_MAX,
            'course': course, 'term_labels': C.COURSE_TERM_LABELS, 'sorts': SORTS, 'sort': sort, 'sort_label': dict(SORTS)[sort],
            # all jobs / a category: the other category pages; any other page (a region, a course, a company ...): the categories of ITS jobs, as a filter that keeps the page
            'other_categories': ([(s, l, all_counts.get(s, 0), '/jobs/category/%s' % s, False) for s, l, _d, _i in C.JOB_CATEGORIES if all_counts.get(s) and not (kind == 'category' and s == scope.get('value'))]
                                 if kind in ('all', 'category') else
                                 [(s, l, n, href(category=[x for x in state['category'] if x != s] if s in state['category'] else state['category'] + [s]), s in state['category'])
                                  for s, l, n in sorted(categories, key=lambda c: [k for k, _l, _d, _i in C.JOB_CATEGORIES].index(c[0]) if c[0] in C.CATEGORY_LABELS else 99)]),
            'course_match': lambda job: C.course_match(course_keys, (job.term_keys or '').strip(',').split(',')) if course_keys else [],
            'hidden_params': hidden, 'company_strip': strip, 'scope_value': (scope.get('value') or '').replace('_', '-') if kind == 'role' else (scope.get('value') or ''),
            'card_cols': 'col-md-6 col-xxl-4', 'slugify': slugify,
        }

    # ------------------------------------------------------------------ the landing page
    def _llmd_landing(self, args):
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
        for region, company, hq, n in listing._read_group(active + [('company', '!=', False)], ['company_region', 'company', 'company_hq'], ['__count']):
            by_hq.setdefault(region or '', []).append((company, slugify(company), n, hq or ''))
        company_regions = [(slug, name, icon, sorted(by_hq[slug], key=lambda c: (-c[2], c[0].lower()))) for slug, name, _t, icon in F.REGIONS if by_hq.get(slug)]
        if by_hq.get(''):
            company_regions.append(('not-verified', 'Headquarters not verified', 'fa-question-circle-o', sorted(by_hq[''], key=lambda c: (-c[2], c[0].lower()))))
        rec_code = args.get('rec') or (courses[0]['code'] if courses else '')
        course = catalog.resolve(rec_code, courses) or (courses[0] if courses else None)
        recs = self._llmd_recommend(course) if course else {'jobs': [], 'total': 0}
        own_jobs = request.env['hr.job'].sudo().search([('website_published', '=', True)] + request.website.website_domain(), limit=12)      # our own positions (stock Odoo pages)
        latest_cat = args.get('latest_cat') if args.get('latest_cat') in C.CATEGORY_LABELS else ''
        try:
            latest_pages = min(max(int(args.get('latest') or 1), 1), 20)                     # without the script "Load More Jobs" reloads with one batch more
        except ValueError:
            latest_pages = 1
        latest = self._llmd_latest(latest_cat, 0, LATEST * latest_pages)
        country_rows = sorted(listing._read_group(active + [('country', '!=', False)], ['country'], ['__count']), key=lambda r: (-r[1], r[0]))
        all_categories = sorted([(slug, label, text, icon, cats[slug]) for slug, label, text, icon in C.JOB_CATEGORIES if cats.get(slug)], key=lambda c: -c[4])
        return request.render('llmd_job_aggregator.landing_page', {
            'total': total, 'company_total': len(companies), 'country_total': len(countries),
            'top_categories': all_categories[:8], 'category_total': len(all_categories),
            'company_regions': company_regions, 'region_total': len(world),
            'latest': latest['jobs'], 'latest_total': latest['total'], 'latest_cat': latest_cat, 'latest_pages': latest_pages,
            'latest_chips': [(slug, label, cats[slug]) for slug, label, _t, _i in sorted(C.JOB_CATEGORIES, key=lambda c: -cats.get(c[0], 0)) if cats.get(slug)][:8],
            'last_sync': self._llmd_last_sync(),
            'top_countries': [(c, slugify(c), n, _flag(c)) for c, n in country_rows[:10]], 'all_country_total': len(country_rows),
            'latest_more_href': '/jobs?%s#latest' % urlencode([('latest', latest_pages + 1)] + ([('latest_cat', latest_cat)] if latest_cat else [])),
            'flag_font': _flag_font(''.join(_flag(c) for c, _n in country_rows[:10])),
            'popular': [(code.replace('_', '-'), C.ROLE_LABELS[code], n) for code, n in roles.most_common(6)],
            'courses': courses, 'course': course, 'recs': recs, 'course_counts': {co['code']: listing.search_count(active + _course_domain(co)) for co in courses},
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
        """The next batch of Latest Jobs (the "Load More Jobs" button and the category shortcuts fetch it; without the script the landing page reloads)."""
        category = category if category in C.CATEGORY_LABELS else ''
        try:
            page = min(max(int(page), 1), 100000)                                      # any batch of the board (an empty one past the end)
        except (TypeError, ValueError):
            page = 1
        latest = self._llmd_latest(category, (page - 1) * LATEST, LATEST)
        return request.render('llmd_job_aggregator.latest_batch', {
            'latest': latest['jobs'], 'latest_total': latest['total'], 'more': page * LATEST < latest['total'], 'page': page, 'latest_cat': category})

    # ------------------------------------------------------------------ the directories: every category, every region of the world
    @http.route('/jobs/categories', type='http', auth='public', website=True, sitemap=False)
    def llmd_categories(self, **kwargs):
        """Every job category that has jobs now, with its number of jobs and companies (a category appears as soon as a sync brings jobs for it)."""
        listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        counts = dict(listing._read_group(active + [('job_category', '!=', False)], ['job_category'], ['__count']))
        companies = Counter(cat for cat, _co, _n in listing._read_group(active + [('job_category', '!=', False), ('company', '!=', False)], ['job_category', 'company'], ['__count']))
        cats = sorted([(slug, label, text, icon, counts[slug], companies[slug]) for slug, label, text, icon in C.JOB_CATEGORIES if counts.get(slug)], key=lambda c: -c[4])
        return request.render('llmd_job_aggregator.category_directory', {'cats': cats, 'total': listing.search_count(active)})

    @http.route('/jobs/countries', type='http', auth='public', website=True, sitemap=False)
    def llmd_countries(self, mode='', **kwargs):
        """Every country that has jobs now, by region, with its number of jobs (all work modes; ?mode=remote counts the remote jobs only, on their own)."""
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

    @http.route('/jobs/regions', type='http', auth='public', website=True, sitemap=False)
    def llmd_regions(self, **kwargs):
        """Every region of the world that has jobs - by where the JOBS are - with its countries, its regions of India and the companies hiring there."""
        listing = request.env['llmd.job.listing'].sudo()
        active = [('active', '=', True)]
        total = listing.search_count(active)
        world = dict(listing._read_group(active + [('region', '!=', False)], ['region'], ['__count']))
        countries = listing._read_group(active + [('region', '!=', False), ('country', '!=', False)], ['region', 'country'], ['__count'])
        companies = listing._read_group(active + [('region', '!=', False), ('company', '!=', False)], ['region', 'company'], ['__count'])
        zones = dict(listing._read_group(active + [('india_zone', '!=', False)], ['india_zone'], ['__count']))
        regions = []
        for slug, name, text, icon in F.REGIONS:
            if not world.get(slug):
                continue
            regions.append({
                'slug': slug, 'name': name, 'text': text, 'icon': icon, 'count': world[slug],
                'countries': sorted([(c, slugify(c), n) for r, c, n in countries if r == slug], key=lambda c: (-c[2], c[0])),
                'companies': sorted([(co, slugify(co), n) for r, co, n in companies if r == slug], key=lambda c: (-c[2], c[0].lower())),
                'zones': [(z, zname, zones[z]) for z, zname, _t, _i in F.INDIA_ZONES if zones.get(z)] if slug == 'india-south-asia' else [],
            })
        return request.render('llmd_job_aggregator.region_directory', {
            'regions': regions, 'total': total, 'no_region': total - sum(world.values()),
            'empty_regions': [name for slug, name, _t, _i in F.REGIONS if not world.get(slug)],
        })

    @staticmethod
    def _llmd_recommend(course, limit=6):
        """The jobs a course leads to (unchanged course matching), the most relevant first: the most terms shared with the course's own text, then the newest."""
        listing = request.env['llmd.job.listing'].sudo()
        domain = [('active', '=', True)] + _course_domain(course)
        rows = listing.search_read(domain, ['term_keys', 'india', 'posted'])
        keys = set(course['terms'])
        rows.sort(key=lambda r: (len(keys & set((r['term_keys'] or '').strip(',').split(','))), r['india'], r['posted'] or fields.Datetime.to_datetime('1970-01-01'), r['id']), reverse=True)
        jobs = listing.browse([r['id'] for r in rows[:limit]])
        return {'jobs': [(job, C.course_match(course['terms'], (job.term_keys or '').strip(',').split(','))) for job in jobs], 'total': len(rows)}

    @http.route('/jobs/course-matches', type='http', auth='public', website=True, sitemap=False)
    def llmd_course_matches(self, course=None, **kwargs):
        """The course-matched jobs of one course, as a piece of the landing page (the course selector swaps it in without reloading the page)."""
        catalog = request.env['llmd.course.catalog']
        courses = catalog.courses()
        chosen = catalog.resolve(course or '', courses)
        if not chosen:
            raise NotFound()
        return request.render('llmd_job_aggregator.course_matches', {'course': chosen, 'recs': self._llmd_recommend(chosen), 'term_labels': C.COURSE_TERM_LABELS, 'card_cols': 'col-md-6 col-xl-4'})

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

    @http.route('/jobs/ext/<int:listing_id>', type='http', auth='public', website=True, sitemap=False)
    def llmd_board_detail(self, listing_id, **kwargs):
        job = self._llmd_listing(listing_id)
        return request.render('llmd_job_aggregator.board_detail', {'job': job, 'd': job.detail_vals(), 'similar': self._llmd_similar(job)})

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

    # ------------------------------------------------------------------ Apply Now: the click is saved in Odoo, then the visitor is sent to the original application page
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
    def _llmd_count(vid, **job):
        """Save the click (listing=... or job=...). Link checkers, crawlers and previews are not applicants. A failure to save is logged and never keeps the visitor from the employer."""
        if request.httprequest.method != 'GET' or BOT.search(request.httprequest.user_agent.string or ''):
            return
        try:
            with request.env.cr.savepoint():
                request.env['llmd.job.click'].sudo().record_click(visitor=vid[0], **job)                  # the job only: a click names nobody
        except Exception:
            _logger.exception('apply click could not be saved (%s); the visitor is sent on anyway', {k: getattr(v, 'id', v) for k, v in job.items()})

    @http.route('/jobs/ext/<int:listing_id>/go', type='http', auth='public', website=True, sitemap=False)
    def llmd_board_go(self, listing_id, **kwargs):
        job = self._llmd_listing(listing_id)
        vid = self._llmd_visitor()
        self._llmd_count(vid, listing=job)
        url = job.safe_apply_url()
        return self._llmd_send_on(url, vid) if url else request.redirect('/jobs/ext/%d' % job.id)

    @http.route('/jobs/position/<int:job_id>/go', type='http', auth='public', website=True, sitemap=False)
    def llmd_position_go(self, job_id, **kwargs):
        position = request.env['hr.job'].sudo().search([('id', '=', job_id), ('website_published', '=', True)], limit=1)
        if not position:
            raise NotFound()
        vid = self._llmd_visitor()
        url = valid_url(position.apply_url)
        if url and L.is_board_link(url) and L.direct_links_only(request.env):
            form = '/jobs/apply/%s' % request.env['ir.http']._slug(position)   # direct links only: a job board page is no direct link - our own position is applied for on our own Odoo form
            self._llmd_count(vid, job=position, url=form)
            return self._llmd_send_on(form, vid)
        self._llmd_count(vid, job=position)
        return self._llmd_send_on(url, vid) if url else request.redirect(position.website_url or '/jobs')

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
        vid = self._llmd_visitor()
        max_mb = A.MAX_RESUME // (1024 * 1024)
        if request.httprequest.method != 'POST':
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
