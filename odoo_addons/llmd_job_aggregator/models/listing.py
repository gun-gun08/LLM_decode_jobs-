"""Job board listings: real jobs from every connected source, normalized into ONE shape, one record per job.

Each record keeps the source's own job id (`ext_id`), description and application link, so the details and the Apply Now link of one job can never end up on
another job (unique per source + ext_id). The same job found by two sources (same title + company + place) is stored once (`also_on` names the other source).
Missing data stays empty - nothing is invented.
"""
import json
import logging
import re
from datetime import timedelta
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import board_config as C
from . import job_facets as F
from . import language as LANG
from . import skill_map as SK
from . import parsers as P
from . import summary as SUM
from . import view_helpers as V

_logger = logging.getLogger(__name__)

SYNC_LOCK = 72940011                                  # PostgreSQL advisory lock id: one job sync at a time

# kept for the older imports of the controller / tests
TRACKS = C.TRACKS
TRACK_LABELS = C.TRACK_LABELS


REDIRECT_HOSTS = ('jooble.org', 'adzuna.', 'himalayas.app')     # job boards whose link opens THEIR page first (the employer's page is one more click away)
# Experience Required (experience_required): years written out ("2–5 years", "3+ yrs", "5 to 8 years"), and a title that says fresher / entry level
_STATED_YEARS = re.compile(r'\b\d{1,2}\s*(?:[-–—]|to)\s*\d{1,2}\s*\+?\s*(?:years?|yrs?)\b|\b\d{1,2}\s*\+\s*(?:years?|yrs?)\b|\b\d{1,2}\s*(?:years?|yrs?)\b', re.I)
_TITLE_FRESHER = re.compile(r'\bfreshers?\b', re.I)
_TITLE_ENTRY = re.compile(r'\bentry[- ]?level\b', re.I)


def is_board_link(url):
    """True for a link that goes to a job board's own page instead of straight to the employer / the original job site."""
    host = (urlparse(url or '').hostname or '').lower()
    return any(h in host for h in REDIRECT_HOSTS)


def direct_links_only(env):
    """True while only direct links are used (default): system parameter llmd_agg.direct_links_only = 0 / 1, else board_config.DIRECT_LINKS_ONLY."""
    value = (env['ir.config_parameter'].sudo().get_param('llmd_agg.direct_links_only') or '').strip().lower()
    if value in ('0', 'false', 'off', 'no'):
        return False
    if value in ('1', 'true', 'on', 'yes'):
        return True
    return bool(C.DIRECT_LINKS_ONLY)


def valid_url(url):
    """The link if it is a plain http(s) link with a host, else ''. Anything else (javascript:, data:, relative, broken) is never used."""
    url = (url or '').strip()
    if not url or len(url) > 2000 or re.search(r'\s', url):
        return ''
    try:
        parts = urlparse(url)
    except ValueError:
        return ''
    return url if parts.scheme in ('http', 'https') and parts.netloc and '.' in parts.netloc else ''


def track_codes(title, text):
    """The category chips a job belongs to: its title names the topic, or its text keeps coming back to it ('claude' once is enough)."""
    low_title, low_text = (title or '').lower(), (text or '').lower()
    out = []
    for code, _label, rx in C.TRACKS:
        if re.search(rx, low_title) or len(re.findall(rx, low_text)) >= (1 if code == 'claude' else 3):
            out.append(code)
    return out


def short_text(parsed, plain, limit=200):
    base = parsed.get('about') or (parsed.get('duties') or [''])[0] or plain or ''
    base = re.sub(r'\s+', ' ', base).strip()
    if len(base) <= limit:
        return base
    return base[:limit].rsplit(' ', 1)[0].rstrip(',;:-') + '…'


class LlmdJobListing(models.Model):
    _name = 'llmd.job.listing'
    _rec_name = 'title'
    _description = 'Job board listing (from the job sources)'
    _order = 'posted desc, id desc'                              # the newest first: Indian and international jobs mixed (until v19.0.25 India came first)

    source = fields.Char(required=True, index=True, help='Internal only: the job sources are never named on the website.')
    ext_id = fields.Char(string='Source job id', required=True, index=True)
    title = fields.Char(required=True)
    company = fields.Char()
    location = fields.Char()
    countries = fields.Char(string='Open to (countries)')
    employment_type = fields.Char()
    seniority = fields.Char()
    salary = fields.Char(help='As the source states it; empty when the source gives none.')
    categories = fields.Char()
    posted = fields.Datetime()
    description_html = fields.Html(sanitize=True, sanitize_attributes=False, sanitize_style=False, strip_style=True)
    full_text = fields.Boolean(string='Full description from the source', default=True)
    short_description = fields.Char()
    sections_json = fields.Text(string='Parsed sections (JSON)')
    apply_url = fields.Char(string='Application URL')
    source_url = fields.Char(string='Listing page')
    via = fields.Char(string='Original site (named by the source)')
    also_on = fields.Char(string='Also found on')
    dedupe_key = fields.Char(index=True)
    tags = fields.Char(string='Category chips', index=True)
    roles = fields.Char(string='Job roles', index=True)
    courses = fields.Char(string='Courses', index=True)
    role_type = fields.Char(index=True)
    search_text = fields.Text()
    rank = fields.Integer(default=999)
    active = fields.Boolean(default=True)
    fetched_at = fields.Datetime()

    # what the Jobs page filters on, worked out from the job's own text (models/job_facets.py); stored so the filters are plain database searches
    exp_level = fields.Char(string='Experience level', compute='_compute_facets', store=True, index=True)
    job_type = fields.Char(string='Job type', compute='_compute_facets', store=True, index=True)
    work_mode = fields.Char(string='Work mode', compute='_compute_facets', store=True, index=True)
    india = fields.Boolean(string='In India', compute='_compute_facets', store=True, index=True)
    city = fields.Char(string='City (India)', compute='_compute_facets', store=True, index=True)
    salary_min_lpa = fields.Float(string='Salary from (LPA)', compute='_compute_salary_lpa', store=True, index=True, digits=(8, 2),
                                  help='The stated salary in lakhs of rupees per year (0 when the job states none, or only in another currency).')
    salary_max_lpa = fields.Float(string='Salary to (LPA)', compute='_compute_salary_lpa', store=True, index=True, digits=(8, 2))
    # the category pages (/jobs/category/<slug>): one category per job, the company's team as a job function, country, the years of experience the text asks for, skills
    job_category = fields.Char(string='Job category', compute='_compute_category', store=True, index=True, help='One of board_config.JOB_CATEGORIES (from the title, else the role, else the department).')
    job_function = fields.Char(string='Job function', compute='_compute_category', store=True, index=True, help='The department the company files the job under, mapped onto board_config.JOB_FUNCTIONS.')
    category_label = fields.Char(string='Category', compute='_compute_category', store=True, index=True, help='The name of the job category, as the website shows it.')
    function_label = fields.Char(string='Function', compute='_compute_category', store=True, help='The name of the job function, as the website shows it.')
    page_url = fields.Char(string='Page on the website', compute='_compute_backend_links')
    years_text = fields.Char(string='Experience', compute='_compute_backend_links')
    country = fields.Char(compute='_compute_country', store=True, index=True)
    # "Explore jobs by region": the world region of the country the location names, and inside India the region of its city / state (job_facets.REGIONS / INDIA_ZONES);
    # empty when the location does not say (nothing is guessed)
    region = fields.Char(string='Region code', compute='_compute_region', store=True, index=True)
    india_zone = fields.Char(string='Region of India code', compute='_compute_region', store=True, index=True)
    region_label = fields.Char(string='Region', compute='_compute_region', store=True, index=True)
    india_zone_label = fields.Char(string='Region of India', compute='_compute_region', store=True)
    # where the COMPANY has its headquarters ("Companies by region") - not where the job is (board_config.COMPANY_HQ: verified headquarters only)
    company_hq = fields.Char(string='Company headquarters', compute='_compute_company_hq', store=True, index=True)
    company_region = fields.Char(string='Company region code', compute='_compute_company_hq', store=True, index=True)
    company_region_label = fields.Char(string='Company region', compute='_compute_company_hq', store=True)
    exp_years_known = fields.Boolean(string='States years of experience', compute='_compute_years', store=True, index=True)
    exp_years_min = fields.Integer(string='Experience from (years)', compute='_compute_years', store=True, index=True)
    exp_years_max = fields.Integer(string='Experience to (years)', compute='_compute_years', store=True, index=True, help='99 = open ("5+ years").')
    skill_keys = fields.Char(string='Skills (search keys)', compute='_compute_skill_keys', store=True, index=True)
    term_keys = fields.Char(string='Course terms', compute='_compute_term_keys', store=True, help='board_config.COURSE_TERMS the title and job text talk about (course recommendations).')
    # the skills of the job in Odoo's skill system (hr.skill): Technical Skills, Odoo's Languages and Soft Skills - see link_odoo_skills() and models/skill_map.py
    skill_ids = fields.Many2many('hr.skill', 'llmd_listing_hr_skill_rel', 'listing_id', 'skill_id', string='Skills (Odoo)', readonly=True,
                                 help='The skills this job\'s own text mentions, as Odoo skills. Filled by every sync; only the job, never an applicant.')
    technical_skill_ids = fields.Many2many('hr.skill', string='Technical Skills', compute='_compute_skill_kinds')
    language_skill_ids = fields.Many2many('hr.skill', string='Languages', compute='_compute_skill_kinds')
    soft_skill_ids = fields.Many2many('hr.skill', string='Soft Skills', compute='_compute_skill_kinds')
    posted_type = fields.Selection(C.POSTED_TYPES, string='Posted Type', compute='_compute_posted_type', store=True, index=True,
                                   help='Fetched: the job came from an external API / job provider (its source). Every job board listing is one.')
    source_lang = fields.Char(string='Listing language', compute='_compute_languages', store=True, index=True,
                              help='zh = the employer wrote this listing in Chinese, zh-en = in Chinese and English, zh-title = only its title in Chinese (shown as written; no translation service is configured).')
    languages = fields.Char(string='Languages asked', compute='_compute_languages', store=True,
                            help='The languages the job text asks for, "Mandarin:required,Cantonese:plus" (models/language.py).')
    summary_json = fields.Text(string='Summary (JSON)', compute='_compute_summary', store=True,
                               help='The short summary of the detail page (overview, responsibilities, skills & qualifications, experience level, salary), made from the job text when the job is fetched or updated.')

    _source_ext_uniq = models.Constraint('unique(source, ext_id)', 'This source job is already stored.')

    @api.depends('title', 'location', 'countries', 'employment_type', 'seniority', 'description_html')
    def _compute_facets(self):
        for rec in self:
            text = P.plain_text(rec.description_html)
            facets = F.facets(rec.title, rec.location, rec.countries, rec.employment_type, rec.seniority, text)
            rec.exp_level, rec.job_type, rec.work_mode, rec.india, rec.city = (facets['exp_level'], facets['job_type'], facets['work_mode'], facets['india'], facets['city'])

    @api.depends('salary')
    def _compute_salary_lpa(self):
        for rec in self:
            rec.salary_min_lpa, rec.salary_max_lpa = F.salary_lpa(rec.salary)

    @api.depends('title', 'roles', 'categories')
    def _compute_category(self):
        for rec in self:
            rec.job_category = C.job_category(rec.title, rec.roles, rec.categories) or False
            rec.job_function = C.job_function(rec.categories) or False
            rec.category_label = C.CATEGORY_LABELS.get(rec.job_category or '') or False
            rec.function_label = C.FUNCTION_LABELS.get(rec.job_function or '') or False

    def _compute_backend_links(self):
        for rec in self:
            rec.page_url = '/jobs/ext/%d' % rec.id if rec.id else False
            rec.years_text = rec.years_label() if rec.id else False

    @api.depends('location', 'india')
    def _compute_country(self):
        for rec in self:
            rec.country = F.country_of(rec.location, rec.india) or False

    @api.depends('company')
    def _compute_company_hq(self):
        for rec in self:
            rec.company_hq = C.company_hq(rec.company) or False
            rec.company_region = F.COUNTRY_REGION.get(rec.company_hq or '') or False
            rec.company_region_label = F.REGION_LABELS.get(rec.company_region or '') or False

    @api.depends('location', 'country', 'city', 'work_mode')
    def _compute_region(self):
        for rec in self:
            rec.region = F.region_of(rec.country or '', rec.location, rec.work_mode) or False
            rec.india_zone = F.india_zone_of(rec.location, rec.city or '', rec.country or '') or False
            rec.region_label = F.REGION_LABELS.get(rec.region or '') or False
            rec.india_zone_label = F.REGION_LABELS.get(rec.india_zone or '') or False

    @api.depends('description_html')
    def _compute_years(self):
        for rec in self:
            low, high = F.years_range(P.plain_text(rec.description_html))
            rec.exp_years_known = low is not None
            rec.exp_years_min = low or 0
            rec.exp_years_max = (99 if high is None else high) if low is not None else 0

    @api.depends('skill_ids')
    def _compute_skill_kinds(self):
        lang = self.env.ref('hr_skills.hr_skill_type_lang', raise_if_not_found=False)
        soft = self.env.ref('hr_skills.hr_skill_type_softskill', raise_if_not_found=False)
        for rec in self:
            skills = rec.skill_ids
            rec.language_skill_ids = skills.filtered(lambda s: s.skill_type_id == lang)
            rec.soft_skill_ids = skills.filtered(lambda s: s.skill_type_id == soft)
            rec.technical_skill_ids = skills.filtered(lambda s: s.skill_type_id.name == SK.TECHNICAL_TYPE)

    def link_odoo_skills(self):
        """Link every job to the Odoo skills its own text mentions (models/skill_map.py): technical skills of the parser's vocabulary go into the skill type
        "Technical Skills" (created with its first skill; a skill is created once and then reused), Odoo's Languages and Soft Skills are matched by name and
        never created. Business skills and free lines stay on the website only. Returns the number of jobs whose skills changed."""
        Skill = self.env['hr.skill'].sudo()
        Type = self.env['hr.skill.type'].sudo()
        lang = self.env.ref('hr_skills.hr_skill_type_lang', raise_if_not_found=False)
        soft = self.env.ref('hr_skills.hr_skill_type_softskill', raise_if_not_found=False)
        tech = Type.search([('name', '=', SK.TECHNICAL_TYPE)], limit=1)
        matchable = (lang | soft | tech).filtered(bool)
        by_name = {}
        for skill in Skill.search([('skill_type_id', 'in', matchable.ids)]) if matchable else Skill.browse():
            by_name.setdefault((skill.skill_type_id.id, SK.norm(skill.name)), skill)

        def existing(kind, name):
            return by_name.get((kind.id, SK.norm(name))) if kind else None

        changed = 0
        for rec in self:
            wanted = []
            for key in [k for k in (rec.skill_keys or '').strip(',').split(',') if k]:
                found = existing(soft, key) or existing(lang, key)              # "Communication", "Problem Solving"; a language named in a skills list
                name = SK.technical_name(key)
                if not found and name:
                    found = existing(tech, name)
                    if not found:
                        if not tech:                                          # Odoo wants a skill type to hold at least one skill and one level
                            tech = Type.create({'name': SK.TECHNICAL_TYPE, 'skill_ids': [(0, 0, {'name': name})],
                                                'skill_level_ids': [(0, 0, {'name': n, 'level_progress': p, 'default_level': d}) for n, p, d in SK.TECHNICAL_LEVELS]})
                            found = tech.skill_ids[:1]
                        else:
                            found = Skill.create({'name': name, 'skill_type_id': tech.id})
                        by_name[(tech.id, SK.norm(name))] = found
                if found:
                    wanted.append(found.id)
            for language, _kind in rec.language_tags():
                found = existing(lang, SK.language_skill_name(language))
                if found:
                    wanted.append(found.id)
            wanted = list(dict.fromkeys(wanted))
            if set(wanted) != set(rec.skill_ids.ids):
                rec.skill_ids = [(6, 0, wanted)]
                changed += 1
        return changed

    @api.depends('source')
    def _compute_posted_type(self):
        for rec in self:
            rec.posted_type = 'fetched' if rec.source else False                       # every listing is read from a provider (its source)

    def experience_required(self):
        """The experience the job asks for, only as the job states it, in this order:
        1. the years a sentence about experience states ("3–5 yrs", the Experience filter's value),
        2. the provider's own experience label, as it sent it ("Mid-Senior Level"),
        3. the years its requirements state in a line without the word "experience" ("2–5 years in DevOps, SRE ..."), as written,
        4. "Fresher" / "Entry Level" when the job's title says so,
        else '' - nothing is guessed (a level worked out from words like "Senior" is not used)."""
        self.ensure_one()
        stated = (self.summary() or {}).get('experience_level') or ''              # the summary's level + the years its requirements state
        years = _STATED_YEARS.search(stated)
        title = self.title or ''
        return (self.years_label() or (self.seniority or '').strip() or (years.group(0).strip() if years else '')
                or ('Fresher' if _TITLE_FRESHER.search(title) else 'Entry Level' if _TITLE_ENTRY.search(title) else ''))

    @api.depends('title', 'description_html')
    def _compute_languages(self):
        for rec in self:
            text = LANG.plain(rec.description_html)
            rec.source_lang = LANG.listing_language(rec.title, text) or False
            rec.languages = LANG.encode(LANG.languages_asked(text)) or False

    def title_lang(self):
        """'zh' when the title is written in Chinese (for the lang attribute: screen readers and fonts), else None."""
        self.ensure_one()
        return 'zh' if LANG.has_han(self.title) else None

    def source_lang_label(self):
        """The badge of a listing written (partly) in Chinese, or ''."""
        self.ensure_one()
        return {'zh': 'Listed in Chinese', 'zh-en': 'Chinese & English', 'zh-title': 'Chinese title'}.get(self.source_lang or '', '')

    def language_tags(self):
        """[(language, 'required' | 'plus')] the job asks for (English only when its text asks for it)."""
        self.ensure_one()
        return LANG.decode(self.languages)

    @api.depends('title', 'description_html')
    def _compute_term_keys(self):
        for rec in self:
            keys = C.course_terms('%s %s' % (rec.title or '', P.plain_text(rec.description_html)[:20000]))
            rec.term_keys = ',%s,' % ','.join(keys) if keys else False

    @api.depends('summary_json')
    def _compute_skill_keys(self):
        for rec in self:
            keys = [F.skill_key(s) for s in (rec.summary().get('skills') or []) if F.skill_key(s)]
            rec.skill_keys = ',%s,' % ','.join(keys) if keys else False

    def card_apply(self):
        """(href, opens the employer's page) of Apply Now on a result card - the same target as on the detail page: our form in form mode, otherwise the
        tracked link (/go: the click is saved in Apply Clicks, then the employer's own application page opens); ('', False) when the job has no valid link."""
        self.ensure_one()
        if self.apply_mode() == 'form':
            return '/jobs/ext/%d/apply' % self.id, False
        if self.safe_apply_url():
            return '/jobs/ext/%d/go' % self.id, True
        return '', False

    @api.depends('title', 'company', 'location', 'salary', 'exp_level', 'job_type', 'work_mode', 'description_html', 'sections_json', 'full_text')
    def _compute_summary(self):
        for rec in self:
            try:
                rec.summary_json = json.dumps(rec._build_summary(), ensure_ascii=False)
            except Exception:                                               # a summary never stops a sync: the page then builds it itself
                _logger.exception('job %s: the summary could not be made', rec.id)
                rec.summary_json = False

    def _build_summary(self):
        self.ensure_one()
        mode = F.MODE_LABELS.get(self.work_mode, '') if self.work_mode in ('remote', 'hybrid') else ''      # "On-site" is only a guess from a city name
        return SUM.build(self.title, self.company or '', self.location or '', mode, F.TYPE_LABELS.get(self.job_type, ''), F.EXP_LABELS.get(self.exp_level, ''),
                         self.salary or '', str(self.description_html or ''), self.full_text, self.sections())

    def summary(self):
        """The summary of the detail page (see models/summary.py)."""
        self.ensure_one()
        try:
            data = json.loads(self.summary_json) if self.summary_json else None
        except ValueError:
            data = None
        return data or self._build_summary()

    def posted_text(self):
        self.ensure_one()
        return V.ago(self.posted)

    def is_new(self):
        """Posted in the last 3 days (the "New" badge of a job card)."""
        self.ensure_one()
        return bool(self.posted) and self.posted >= fields.Datetime.now() - timedelta(days=3)

    def facet_tags(self):
        """[(kind, label)] of the job card tags: job type, experience level, work mode - only what the job really says."""
        self.ensure_one()
        return [(kind, label) for kind, label in (('type', F.TYPE_LABELS.get(self.job_type)), ('exp', F.EXP_LABELS.get(self.exp_level)), ('mode', F.MODE_LABELS.get(self.work_mode))) if label]

    def card_text(self, limit=170):
        """The short description of a job card: the overview of the job summary (the generic "<title> role at <company>" fallback is left out), else the stored
        short description; cut at a word."""
        self.ensure_one()
        overview = (self.summary() or {}).get('overview') or ''
        if not overview or overview.startswith((self.title or '').rstrip('.') + ' role'):
            overview = self.short_description or ''
        overview = re.sub(r'\s+', ' ', overview).strip()
        return overview if len(overview) <= limit else overview[:limit].rsplit(' ', 1)[0].rstrip(',;:-') + '…'

    def years_label(self):
        """The years of experience the job text asks for ("3–5 yrs", "5+ yrs"), or '' when it states none."""
        self.ensure_one()
        if not self.exp_years_known:
            return ''
        if self.exp_years_max >= 99 or self.exp_years_max == self.exp_years_min and not self.exp_years_min:
            return '%d+ yrs' % self.exp_years_min
        return '%d–%d yrs' % (self.exp_years_min, self.exp_years_max)

    def card_skills(self, limit=3):
        """(skills, how many more) of a job card: the first skills of its summary."""
        self.ensure_one()
        skills = list((self.summary() or {}).get('skills') or [])
        return skills[:limit], max(len(skills) - limit, 0)

    def category_link(self):
        """(url, label) of the job's category page, or ('', '')."""
        self.ensure_one()
        label = C.CATEGORY_LABELS.get(self.job_category or '')
        return ('/jobs/category/%s' % self.job_category, label) if label else ('', '')

    def company_link(self):
        """The page of the job's company (/jobs/company/<slug>), or ''."""
        self.ensure_one()
        return '/jobs/company/%s' % C.slugify(self.company) if self.company and C.slugify(self.company) else ''

    def facet_labels(self):
        """The small tags of a job card: job type, experience level, work mode (only what the job really says)."""
        self.ensure_one()
        return [label for label in (F.TYPE_LABELS.get(self.job_type), F.EXP_LABELS.get(self.exp_level), F.MODE_LABELS.get(self.work_mode)) if label]

    # ------------------------------------------------------------------ what the website templates use
    def safe_apply_url(self):
        self.ensure_one()
        return valid_url(self.apply_url)

    def track_labels(self):
        self.ensure_one()
        return [C.TRACK_LABELS[c] for c in (self.tags or '').split(',') if c in C.TRACK_LABELS]

    def card_track(self):
        """(code, label) of the category shown on the job card: the first category of the job that its TITLE names (an "Account Executive" is Sales even when its
        text also talks about AI), else its first category; ('', '') when it has none."""
        self.ensure_one()
        codes = [c for c in (self.tags or '').split(',') if c in C.TRACK_LABELS]
        title = (self.title or '').lower()
        code = next((c for c, _l, rx in C.TRACKS if c in codes and re.search(rx, title)), codes[0] if codes else '')
        return (code, C.TRACK_LABELS.get(code, ''))

    def role_labels(self):
        self.ensure_one()
        return [C.ROLE_LABELS[c] for c in (self.roles or '').split(',') if c in C.ROLE_LABELS]

    def source_badge(self):
        self.ensure_one()
        letter, color = C.SOURCE_STYLE.get(self.source, (self.source[:1].upper() or '?', '#6c757d'))
        return {'letter': letter, 'color': color, 'name': self.source}

    def sections(self):
        self.ensure_one()
        try:
            data = json.loads(self.sections_json) if self.sections_json else {}
        except ValueError:
            data = {}
        return {k: data.get(k) or ([] if k != 'about' else '') for k in ('about', 'duties', 'skills', 'quals', 'experience', 'preferred')}

    def detail_vals(self):
        """Everything the shared detail layout (job_view) shows, already short: the same keys as hr.job.llmd_content().
        No source or site name is part of it; the application URL is only used for the Apply Now target."""
        self.ensure_one()
        sm = self.summary()
        block = SUM.display(sm)                                         # one Job Overview block
        apply_url = self.safe_apply_url()
        return {
            'on': True, 'title': self.title, 'company': self.company or '', 'location': self.location or '', 'salary': self.salary or '',
            'job_type': ' \u00b7 '.join(dict.fromkeys(x for x in (F.TYPE_LABELS.get(self.job_type), F.EXP_LABELS.get(self.exp_level)) if x)), 'posted': V.ago(self.posted),
            'badge': None, 'labels': self.track_labels()[:3], 'work_mode': F.MODE_LABELS.get(self.work_mode, ''),
            'overview': block['overview'], 'points': block['points'], 'point_groups': block['point_groups'], 'skills': block['skills'], 'facts': block['facts'], 'from_text': sm['from_text'],
            'notice': '' if self.full_text else 'Only a short summary of this job is available here. The complete description is on the employer\'s application page.',
            'apply_url': apply_url, 'internal_href': '', 'apply_form_href': ('/jobs/ext/%d/apply' % self.id) if self.apply_mode() == 'form' else '', 'go_href': ('/jobs/ext/%d/go' % self.id) if apply_url else '',
            'source_text': '', 'track': self.card_track()[0],
            'category_href': self.category_link()[0], 'category_label': self.category_link()[1],
            'company_href': self.company_link(), 'years': self.years_label(),
            'region': self.region_label or '', 'languages': self.language_tags(), 'title_lang': self.title_lang(), 'source_lang': self.source_lang or '', 'company_hq': self.company_hq or '',
        }

    @api.model
    def apply_mode(self):
        """'redirect' (default): Apply Now saves the click (Apply Clicks) and sends the visitor straight to the employer's own application page - no form of ours.
        'form' (system parameter llmd_agg.apply_mode = form): Apply Now opens OUR application form, which saves the applicant in Odoo; the employer's page stays one tracked click away."""
        return 'form' if (self.env['ir.config_parameter'].sudo().get_param('llmd_agg.apply_mode') or 'redirect').strip().lower() == 'form' else 'redirect'

    def ensure_job(self):
        """The (unpublished) Odoo position that applications for this externally fetched job are filed under: created on the first application, then reused. Applicants therefore appear
        in Recruitment under the right job. Odoo wants unique position names (name + company + department), so the company and, when needed, the external ID are part of the name."""
        self.ensure_one()
        Job = self.env['hr.job'].sudo().with_context(active_test=False)
        job = Job.search([('llmd_listing_id', '=', self.id)], limit=1)
        if job:
            return job
        base_name = ('%s - %s' % (self.title, self.company) if self.company else self.title)[:180]
        for name in (base_name, '%s [%s]' % (base_name, (self.ext_id or str(self.id))[:20]), '%s [%s-%d]' % (base_name, self.source, self.id)):
            if Job.search_count([('name', '=', name)]):
                continue
            values = {'name': name, 'llmd_listing_id': self.id, 'website_published': False}
            if 'description' in Job._fields and self.description_html:
                values['description'] = self.description_html
            try:
                with self.env.cr.savepoint():
                    return Job.with_context(llmd_skip=True).create(values)
            except Exception:
                _logger.warning('job %s: position name %r could not be used, trying another', self.id, name)
        raise UserError('The position for this job could not be created.')

    # ------------------------------------------------------------------ fetching
    @api.model
    def _prepare(self, job):
        """A normalized job from a source -> the values to store, or None when it is not about any course or role."""
        title = (job.get('title') or '').strip()
        ext_id = (job.get('ext_id') or '').strip()
        if not title or not ext_id:
            return None
        raw = job.get('html') or ''
        plain = P.plain_text(raw)
        roles = C.role_codes(title)
        tracks = track_codes(title, plain)
        if not roles and not tracks and not C.board_relevant(title, job.get('categories') or ''):
            return None                                                 # the search returned it, but it fits no course role and no job category
        parsed = P.parse_listing(raw, job.get('company'), title, strict=False) if job.get('full_text') else P.parse_snippet(plain, job.get('company'), title, strict=False)
        order = [c for c, _l, _r in C.TRACKS]
        courses = C.courses_of_roles(roles)
        return {
            'source': job['source'], 'ext_id': ext_id, 'title': title, 'company': (job.get('company') or '').strip(), 'location': job.get('location') or '',
            'countries': job.get('countries') or '', 'employment_type': job.get('employment_type') or '', 'seniority': job.get('seniority') or '',
            'categories': (job.get('categories') or '')[:250], 'salary': (job.get('salary') or '')[:80], 'posted': job.get('posted') or False, 'description_html': raw, 'full_text': bool(job.get('full_text')),
            'short_description': short_text(parsed, plain), 'sections_json': json.dumps(parsed, ensure_ascii=False), 'apply_url': valid_url(job.get('apply_url')),
            'source_url': valid_url(job.get('source_url')) or valid_url(job.get('apply_url')), 'via': (job.get('via') or '')[:120],
            'dedupe_key': C.norm_key(title, job.get('company'), F.city_of(job.get('location')) or job.get('location')),      # "Bangalore" and "Bengaluru" are one place
            'tags': ',' + ','.join(sorted(tracks, key=order.index)) + ',' if tracks else '', 'roles': ',' + ','.join(roles) + ',' if roles else '',
            'courses': ',' + ','.join(courses) + ',' if courses else '', 'role_type': roles[0] if roles else '',
            'search_text': ' '.join([title, job.get('company') or '', ' '.join(parsed['skills']), job.get('categories') or '']),
            'rank': int(job.get('position') or 0), '_plain_len': len(plain)}

    @api.model
    def _dedupe(self, prepared):
        """One record per real job: a direct application link wins over a job board's own page (so Apply Now goes straight to the employer or the original
        job site when one source has that link), then the richest description (full text beats a snippet), then the source order."""
        best = {}
        for vals in prepared:
            key = vals['dedupe_key']
            if key not in best:
                best[key] = {'vals': vals, 'others': []}
                continue
            keeper = best[key]['vals']
            rank_new = (is_board_link(vals['apply_url']), not vals['full_text'], -vals['_plain_len'], C.SOURCE_PRIORITY.get(vals['source'], 99))
            rank_old = (is_board_link(keeper['apply_url']), not keeper['full_text'], -keeper['_plain_len'], C.SOURCE_PRIORITY.get(keeper['source'], 99))
            if rank_new < rank_old:
                best[key]['others'].append(keeper['source'])
                vals['tags'], vals['roles'], vals['courses'] = [self._merge_tags(a, b) for a, b in ((vals['tags'], keeper['tags']), (vals['roles'], keeper['roles']), (vals['courses'], keeper['courses']))]
                vals['rank'] = min(vals['rank'], keeper['rank'])
                best[key]['vals'] = vals
            else:
                if vals['source'] != keeper['source']:
                    best[key]['others'].append(vals['source'])
                keeper['tags'], keeper['roles'], keeper['courses'] = [self._merge_tags(a, b) for a, b in ((keeper['tags'], vals['tags']), (keeper['roles'], vals['roles']), (keeper['courses'], vals['courses']))]
                keeper['rank'] = min(keeper['rank'], vals['rank'])
        out = []
        for entry in best.values():
            vals = entry['vals']
            vals['also_on'] = ', '.join(sorted({s for s in entry['others'] if s != vals['source']}))
            out.append(vals)
        return out

    @staticmethod
    def _merge_tags(a, b):
        items = [x for x in ((a or '').strip(',').split(',') + (b or '').strip(',').split(',')) if x]
        return ',' + ','.join(dict.fromkeys(items)) + ',' if items else ''

    @api.model
    def fetch_now(self, trigger='manual'):
        """Read every connected source, normalize, remove duplicates, store (create or update by source + external job ID). A source that is missing a key or is failing only changes its own
        status; one job that cannot be saved is logged and skipped (its own savepoint) and never stops the others; a sync that is already running makes this call return at once
        (PostgreSQL advisory lock, released with the transaction). Every run is written to the "Sync runs" log."""
        cr = self.env.cr
        cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [SYNC_LOCK])
        if not cr.fetchone()[0]:
            _logger.warning('job sync (%s): skipped, another sync is already running', trigger)
            return {'skipped': 'another sync is already running', 'created': 0, 'updated': 0, 'hidden': 0, 'errors': 0, 'duplicates_removed': 0, 'per_source': {}, 'total_visible': self.search_count([('active', '=', True)])}
        started = fields.Datetime.now()
        Source = self.env['llmd.job.source']
        sources = Source._ensure_sources()
        queries = C.query_variants()
        icp = self.env['ir.config_parameter'].sudo()
        jobs, per_source = [], {}
        direct_only = direct_links_only(self.env)
        off = sources.filtered(lambda s: s.code in C.BOARD_LINK_SOURCES) if direct_only else Source
        for src in off:                                                     # their Apply Now would open their own page first: not asked at all (no request is spent)
            src.mark_skipped('Off: its Apply Now opens its own page first, and only direct links to the employer are used (llmd_agg.direct_links_only).')
        listed = {}                                                         # company job boards: the ids of every posting each board lists now
        for src in sources.filtered(lambda s: s.enabled and s.code != 'himalayas') - off:
            found = src.with_context(llmd_listed=listed).run(queries)
            per_source[src.name] = len(found)
            jobs += found
        # Himalayas (keyless, remote jobs only) is a TEMPORARY fallback: read only while the other sources together return fewer than 20 jobs; once they do, its jobs are hidden again
        himalayas = sources.filtered(lambda s: s.code == 'himalayas')
        mode = (icp.get_param('llmd_agg.himalayas_mode') or 'fallback').strip()
        himalayas_used = False
        if himalayas in off:
            pass                                                            # direct links only: marked "Off" above
        elif himalayas and himalayas.enabled and mode != 'off':
            if mode == 'always' or len(jobs) < 20:
                found = himalayas.run(queries)
                per_source[himalayas.name] = len(found)
                jobs += found
                himalayas_used = True
            else:
                himalayas.mark_skipped('Not needed: the other sources returned %d jobs.' % len(jobs))
        elif himalayas:
            himalayas.mark_skipped('Switched off (llmd_agg.himalayas_mode = off).')
        errors = []
        prepared = []
        for job in jobs:
            try:
                vals = self._prepare(job)
            except Exception as exc:                                       # one broken job from a source must not stop the others
                errors.append('%s %s: %s' % (job.get('source'), job.get('ext_id'), exc.__class__.__name__))
                _logger.exception('job sync: job %s %s could not be normalized', job.get('source'), job.get('ext_id'))
                continue
            if vals and not (direct_only and is_board_link(vals['apply_url'])):       # direct links only: a link to a job board's page is never stored
                prepared.append(vals)
        unique = self._dedupe(prepared)
        merged = {(v['source'], v['ext_id']) for v in prepared} - {(v['source'], v['ext_id']) for v in unique}      # the same job again under another id: kept once
        now = fields.Datetime.now()
        existing = {(r.source, r.ext_id): r for r in self.with_context(active_test=False).search([])}
        created = updated = 0
        kept = set()
        for vals in unique:
            vals = {k: v for k, v in vals.items() if not k.startswith('_')}
            key = (vals['source'], vals['ext_id'])
            vals.update(fetched_at=now, active=True)
            try:
                with cr.savepoint():
                    if key in existing:
                        existing[key].write(vals)
                        updated += 1
                    else:
                        existing[key] = self.create(vals)
                        created += 1
                kept.add(key)
            except Exception as exc:
                errors.append('%s %s: %s' % (key[0], key[1], exc.__class__.__name__))
                _logger.exception('job sync: job %s %s could not be saved', key[0], key[1])
        try:                                                                # the jobs of this run in Odoo's skill system; never stops the sync
            with cr.savepoint():
                self.browse([existing[k].id for k in kept]).link_odoo_skills()
        except Exception:
            _logger.exception('job sync: the skills of the jobs could not be linked to Odoo skills (the jobs are saved)')
        # Nothing is hidden unless a source really delivered jobs in this run (no keys / a failing source never empties the board). Then three kinds of jobs are hidden (kept in
        # the database): jobs of a source that is not needed (the Himalayas fallback), jobs that came back under a new ID, and jobs that no source has returned for KEEP_DAYS days.
        stale = self.browse()
        if unique:
            current = {s.name for s in sources if s.code != 'himalayas' or himalayas_used}
            cutoff = now - timedelta(days=C.KEEP_DAYS)
            kept_keys = {vals['dedupe_key'] for vals in unique}
            stale = self.browse([r.id for k, r in existing.items() if k not in kept and r.active and r.source != 'test'
                                 and (r.source not in current or not r.fetched_at or r.fetched_at < cutoff or r.dedupe_key in kept_keys or k in merged)])
            stale.write({'active': False})
        # a job the company has closed (its own board answered in full and no longer lists it) goes at once, so that Apply Now never opens a closed job;
        # a job that is still listed but was not taken this time (e.g. more than the per-company limit) stays until KEEP_DAYS as before
        company = C.SOURCE_NAMES['company']

        def gone(ext_id, rec):
            board = ext_id.rsplit(':', 1)[0]
            ids = listed.get(board) or (listed.get(board + ':in') if rec.india else None)          # SmartRecruiters: the complete list of its jobs in India
            return ids is not None and ext_id not in ids
        closed = self.browse([r.id for k, r in existing.items() if r.active and k not in kept and r.source == company and gone(k[1], r)])
        closed.write({'active': False})
        stale |= closed
        if direct_only:                                                     # always, even in a run without jobs: no visible job may open a job board's page
            board = self.search([('active', '=', True), ('source', '!=', 'test')]).filtered(lambda r: r.source in off.mapped('name') or is_board_link(r.apply_url))
            board.write({'active': False})
            stale |= board
        stats = {'created': created, 'updated': updated, 'hidden': len(stale), 'closed': len(closed), 'duplicates_removed': len(prepared) - len(unique), 'per_source': per_source, 'errors': len(errors),
                 'total_visible': self.search_count([('active', '=', True)])}
        failing = [s.name for s in sources if s.last_status == 'error']
        self.env['llmd.job.sync'].sudo().create({
            'started': started, 'finished': fields.Datetime.now(), 'trigger': trigger, 'created': created, 'updated': updated, 'hidden': len(stale), 'duplicates': len(prepared) - len(unique),
            'errors': len(errors), 'visible': stats['total_visible'], 'state': 'idle' if not jobs and not errors else 'partial' if (errors or failing) else 'ok',
            'details': '\n'.join(['%s: %s (%s jobs)%s' % (s.name, {'ok': 'working', 'error': 'ERROR', 'not_configured': 'not connected', 'skipped': 'off / not needed'}.get(s.last_status, s.last_status), per_source.get(s.name, 0),
                                                       (' - ' + s.last_message) if s.last_status in ('error', 'skipped') and s.last_message else '') for s in sources] + (['Could not be saved:'] + errors[:20] if errors else []))})
        _logger.info('job sync (%s): %s', trigger, {k: v for k, v in stats.items() if k != 'per_source'} | {'per_source': per_source})
        return stats

    @api.model
    def preview_merge(self, jobs):
        """DRY RUN for tests: normalize and de-duplicate jobs given as source dicts and return the result. Nothing is stored or shown."""
        prepared = [v for v in (self._prepare(j) for j in jobs) if v]
        return [{'title': v['title'], 'source': v['source'], 'also_on': v.get('also_on', ''), 'courses': v['courses'], 'roles': v['roles'], 'apply_url': v['apply_url'],
                 'full_text': v['full_text']} for v in self._dedupe(prepared)]

    @api.model
    def _cron_fetch(self):
        self.fetch_now(trigger='cron')

    def action_fetch_now(self):
        self.env['llmd.job.listing'].fetch_now()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
