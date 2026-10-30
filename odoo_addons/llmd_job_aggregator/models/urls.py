"""The addresses of the job board, built in ONE place (templates, models and the controller use these, nothing writes a path by hand).

  /jobs/<job-slug>        one job (llmd.job.listing.url_slug: unique, the record ID added on a clash)
  /companies/<slug>, /categories/<slug> (= the industry), /departments/<slug>, /locations/<country-or-city>, /regions/<region>, /jobs/course/<code>,
  /jobs/role/<role>, /jobs/all, /jobs (the Jobs Explorer)        a list of jobs (a "scope")

Every filter of a list is a part of its path - never a ?query - one part per value, always in the same order (ORDER), so one set of filters has ONE address:

  /companies/openai/remote/full-time/contract/in-bengaluru/3-6-years-experience/search/python/newest/page/2

  remote | hybrid | onsite                       work mode            full-time | part-time | internship | contract   job type
  <level>-level                                  experience level     <from>-<to>-years-experience, <from>-plus-years-experience   years
  in-<country>, in-<city> (in-<city>-city when a country has the same name)   place          region-<region>
  category-<slug>  department-<slug>  role-<role>  company-<company slug>  size-<band>-employees  salary-<band>
  posted-24-hours | posted-7-days | posted-30-days   track-<chip>   skill-<skill>   near-<typed place>   search/<words>   newest   page/<n>

The values are the ones the filters already know (board_config / job_facets) or that the jobs have (cities, countries, companies, skills): nothing is invented,
and a part that names nothing is no address (404)."""
import re
from urllib.parse import quote, unquote

from . import board_config as C
from . import job_facets as F

EXP_MAX = 25                                                                        # the experience filter runs 0 .. 25+ years
TYPE_SLUGS = {code: C.slugify(label) for code, label in F.JOB_TYPES}               # fulltime -> full-time
LEVEL_SLUGS = {code: '%s-level' % code for code, _label in F.EXP_FILTER}            # senior -> senior-level
YEARS = re.compile(r'(\d{1,2})-(\d{1,2}|plus)-years-experience')
POSTED_SLUGS = {'1': 'posted-24-hours', '7': 'posted-7-days', '30': 'posted-30-days'}
# a salary band with its unit (salary-usd-150-200k, salary-inr-10-25-lpa, salary-usd-250k-plus): the band as the label says it, and never "-<number>" at the end
SALARY_PARTS = {code: 'salary-%s-%s' % (cur, ('%d-%d' % (lo, hi) + ('-lpa' if cur == 'inr' else 'k')) if hi is not None else ('%d' % lo + ('-lpa' if cur == 'inr' else 'k') + '-plus'))
                for code, _label, cur, lo, hi in F.SALARY_BANDS}
ENDS_IN_NUMBER = re.compile(r'-\d+$')      # Odoo's own position pages are /jobs/<name>-<id>: a part never ends like that (a "~" closes such a value)
ORDERS = {'jtype': [c for c, _l in F.JOB_TYPES], 'level': [c for c, _l in F.EXP_FILTER], 'category': [c for c, *_x in C.JOB_CATEGORIES],
          'function': [c for c, *_x in C.JOB_FUNCTIONS], 'role': [c for c, *_x in C.ROLES], 'size': [c for c, _l in C.COMPANY_SIZES],
          'salary': [c for c, *_x in F.SALARY_BANDS]}
EMPTY = {'q': '', 'location': '', 'region': '', 'country': '', 'city': [], 'exp_min': 0, 'exp_max': EXP_MAX, 'category': [], 'function': [], 'role': [], 'skill': [],
         'company': [], 'size': [], 'mode': '', 'jtype': [], 'level': [], 'salary': [], 'posted': '', 'track': '', 'sort': ''}


def _ordered(values, key):
    order = ORDERS[key]
    return sorted(set(values), key=lambda v: order.index(v) if v in order else 999)


def text_part(text):
    """Free words as ONE part of a path: spaces -> '-', anything else unusual percent-encoded ("machine learning" -> machine-learning)."""
    return quote(' '.join((text or '').split()).replace(' ', '-'), safe="+.@!~*'()")


def text_of(part):
    return ' '.join(unquote(part).replace('-', ' ').split())


def size_part(code):
    return 'size-%s-employees' % code.replace('+', '-plus')


class Lookup:
    """The values a path can name that come from the jobs themselves (countries, cities, companies, skills), read once per request."""

    def __init__(self, env):
        self.env = env
        self._cache = {}

    def _rows(self, field):
        if field not in self._cache:
            rows = self.env['llmd.job.listing'].sudo()._read_group([('active', '=', True), (field, '!=', False)], [field], ['__count'])
            self._cache[field] = {C.slugify(v): v for v, _n in rows if C.slugify(v)}
        return self._cache[field]

    def countries(self):
        return self._rows('country')

    def cities(self):
        return self._rows('city')

    def companies(self):
        """({name key: slug}, {slug: name})"""
        if 'companies' not in self._cache:
            recs = self.env['llmd.company'].sudo().search_read([], ['name', 'key', 'slug'])
            self._cache['companies'] = ({r['key']: r['slug'] for r in recs}, {r['slug']: r['name'] for r in recs})
        return self._cache['companies']

    def skills(self):
        """{path part: skill key} of every skill some open job names."""
        if 'skills' not in self._cache:
            keys = set()
            for row in self.env['llmd.job.listing'].sudo().search_read([('active', '=', True), ('skill_keys', '!=', False)], ['skill_keys']):
                keys.update(k for k in (row['skill_keys'] or '').strip(',').split(',') if k)
            self._cache['skills'] = {text_part(k): k for k in sorted(keys)}
        return self._cache['skills']


def segments(state, look):
    """The path parts of a filter state, in ORDER (state: the dict of JobBoard._llmd_state)."""
    s = dict(EMPTY, **{k: v for k, v in state.items() if k in EMPTY})
    out = []
    if s['mode'] in F.MODE_LABELS:
        out.append(s['mode'])
    out += [TYPE_SLUGS[c] for c in _ordered(s['jtype'], 'jtype') if c in TYPE_SLUGS]
    out += [LEVEL_SLUGS[c] for c in _ordered(s['level'], 'level') if c in LEVEL_SLUGS]
    if s['exp_min'] > 0 or s['exp_max'] < EXP_MAX:
        out.append(years_part(s['exp_min'], s['exp_max']))
    if s['country']:
        out.append('in-%s' % C.slugify(s['country']))
    countries = look.countries() if s['city'] else {}
    for city in sorted(set(s['city']), key=str.lower):
        slug = C.slugify(city)
        out.append('in-%s%s' % (slug, '-city' if slug in countries else ''))
    if s['region']:
        out.append('region-%s' % s['region'])
    out += ['category-%s' % c for c in _ordered(s['category'], 'category')]
    out += ['department-%s' % c for c in _ordered(s['function'], 'function')]
    out += ['role-%s' % c.replace('_', '-') for c in _ordered(s['role'], 'role')]
    if s['company']:
        by_key = look.companies()[0]
        out += ['company-%s' % by_key[k] for k in sorted({' '.join(n.casefold().split()) for n in s['company']}) if k in by_key]
    out += [size_part(c) for c in _ordered(s['size'], 'size')]
    out += [SALARY_PARTS[c] for c in _ordered(s['salary'], 'salary') if c in SALARY_PARTS]
    if s['posted'] in POSTED_SLUGS:
        out.append(POSTED_SLUGS[s['posted']])
    if s['track']:
        out.append('track-%s' % s['track'])
    out += ['skill-%s' % text_part(k) for k in sorted({F.skill_key(x) for x in s['skill']})]
    if s['location']:
        out.append('near-%s' % text_part(s['location']))
    if s['q']:
        out += ['search', text_part(s['q'])]
    if s['sort'] == 'newest':
        out.append('newest')
    return [p + '~' if ENDS_IN_NUMBER.search(p) else p for p in out]


def years_part(low, high):
    low, high = max(int(low or 0), 0), min(int(high if high is not None else EXP_MAX), EXP_MAX)
    return '%d-plus-years-experience' % low if high >= EXP_MAX else '%d-%d-years-experience' % (low, high)


def parse(parts, look):
    """(filter values, page) of the path parts after a scope, or None when a part names nothing (a 404). The caller re-builds the path from the values
    and moves (301) to it when the parts were written in another order."""
    parts = [p for p in parts if p]
    page = 1
    if len(parts) >= 2 and parts[-2] == 'page' and parts[-1].isdigit():
        page, parts = int(parts[-1]), parts[:-2]
        if page < 1:
            return None
    v = {k: (list(x) if isinstance(x, list) else x) for k, x in EMPTY.items()}
    types = {s: c for c, s in TYPE_SLUGS.items()}
    levels = {s: c for c, s in LEVEL_SLUGS.items()}
    posted = {s: c for c, s in POSTED_SLUGS.items()}
    sizes = {size_part(c): c for c in ORDERS['size']}
    salaries = {part: c for c, part in SALARY_PARTS.items()}
    i = 0
    while i < len(parts):
        p = parts[i]
        i += 1
        if p.endswith('~') and ENDS_IN_NUMBER.search(p[:-1]):
            p = p[:-1]
        if p == 'search' and i < len(parts) and not v['q']:
            v['q'] = text_of(parts[i])[:80]
            i += 1
        elif p == 'newest' and not v['sort']:
            v['sort'] = 'newest'
        elif p in F.MODE_LABELS and not v['mode']:
            v['mode'] = p
        elif p in types:
            v['jtype'].append(types[p])
        elif p in levels:
            v['level'].append(levels[p])
        elif YEARS.fullmatch(p) and (v['exp_min'], v['exp_max']) == (0, EXP_MAX):
            m = YEARS.fullmatch(p)
            low, high = int(m.group(1)), EXP_MAX if m.group(2) == 'plus' else int(m.group(2))
            if low > high or high > EXP_MAX or p != years_part(low, high) or (low, high) == (0, EXP_MAX):
                return None
            v['exp_min'], v['exp_max'] = low, high
        elif p.startswith('in-'):
            slug = p[3:]
            if slug.endswith('-city') and slug[:-5] in look.cities():
                v['city'].append(look.cities()[slug[:-5]])
            elif slug in look.countries() and not v['country']:
                v['country'] = look.countries()[slug]
            elif slug in look.cities():
                v['city'].append(look.cities()[slug])
            else:
                return None
        elif p.startswith('region-') and p[7:] in F.REGION_LABELS and not v['region']:
            v['region'] = p[7:]
        elif p.startswith('category-') and p[9:] in C.CATEGORY_LABELS:
            v['category'].append(p[9:])
        elif p.startswith('department-') and p[11:] in C.FUNCTION_LABELS:
            v['function'].append(p[11:])
        elif p.startswith('role-') and p[5:].replace('-', '_') in C.ROLE_LABELS:
            v['role'].append(p[5:].replace('-', '_'))
        elif p.startswith('company-') and p[8:] in look.companies()[1]:
            v['company'].append(look.companies()[1][p[8:]])
        elif p in sizes:
            v['size'].append(sizes[p])
        elif p in salaries:
            v['salary'].append(salaries[p])
        elif p in posted and not v['posted']:
            v['posted'] = posted[p]
        elif p.startswith('track-') and p[6:] in C.TRACK_LABELS and not v['track']:
            v['track'] = p[6:]
        elif p.startswith('skill-') and p[6:] in look.skills():
            v['skill'].append(look.skills()[p[6:]])
        elif p.startswith('near-') and not v['location'] and text_of(p[5:]):
            v['location'] = text_of(p[5:])[:60]
        else:
            return None
    return v, page


def path(base, state, look, page=1):
    """The address of a list with these filters: <base>/<parts>[/page/<n>]. The Jobs Explorer without any filter is /jobs/all (/jobs alone is its landing page)."""
    parts = segments(state, look)
    if base == '/jobs' and not parts:
        base = '/jobs/all'
    return '/'.join([base.rstrip('/')] + parts + (['page', str(page)] if page > 1 else [])) or '/'


# ------------------------------------------------------------------ one filter alone: the clean links of the job tags (/jobs/remote, /locations/delhi ...)
def mode_path(code):
    return '/jobs/%s' % code if code in F.MODE_LABELS else ''


def type_path(code):
    return '/jobs/%s' % TYPE_SLUGS[code] if code in TYPE_SLUGS else ''


def level_path(code):
    return '/jobs/%s' % LEVEL_SLUGS[code] if code in LEVEL_SLUGS else ''


def years_path(low, high):
    return '/jobs/%s' % years_part(low, high)


def location_path(name):
    return '/locations/%s' % C.slugify(name) if C.slugify(name) else ''


def region_path(slug):
    return '/regions/%s' % slug if slug else ''


def facet(parts):
    """The title of a Jobs Explorer page that holds ONE filter (/jobs/remote -> "Remote jobs"), else None."""
    if len(parts) != 1:
        return None
    slug = parts[0]
    if slug in F.MODE_LABELS:
        label = F.MODE_LABELS[slug]
        return {'title': '%s jobs' % label, 'here': label,
                'description': {'remote': 'Jobs you can do from home - work mode Remote.', 'hybrid': 'Jobs split between home and the office - work mode Hybrid.',
                                'onsite': 'Jobs at the office - work mode On-site.'}.get(slug, '')}
    code = next((c for c, s in TYPE_SLUGS.items() if s == slug), None)
    if code:
        return {'title': '%s jobs' % F.TYPE_LABELS[code], 'here': F.TYPE_LABELS[code], 'description': 'Jobs of the job type %s.' % F.TYPE_LABELS[code]}
    code = next((c for c, s in LEVEL_SLUGS.items() if s == slug), None)
    if code:
        label = F.EXP_LABELS.get(code) or dict(F.EXP_FILTER)[code]
        return {'title': '%s jobs' % label, 'here': label, 'description': 'Jobs at the experience level %s.' % label}
    m = YEARS.fullmatch(slug)
    if m:
        label = '%s+ years' % m.group(1) if m.group(2) == 'plus' else '%s–%s years' % (m.group(1), m.group(2))
        return {'title': 'Jobs asking %s of experience' % label, 'here': label,
                'description': 'Jobs whose text asks for %s of experience (jobs that state no years are not guessed).' % label}
    return None


def is_reserved_job_slug(slug, look=None):
    """A /jobs/<slug> that is a filter of the Jobs Explorer (or a page of the board), so never the address of a job (`look`: also the filters that name a
    country, city, company or skill of the jobs - a job title starting with "In ..." is no filter unless the rest names a place)."""
    if slug in C.RESERVED_JOB_SLUGS or slug in ('newest', 'search') or YEARS.fullmatch(slug):
        return True
    return parse([slug], look) is not None if look else bool(facet([slug]) or slug in POSTED_SLUGS.values())
