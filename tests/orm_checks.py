"""Run inside `odoo shell`: checks that need the ORM. Everything runs in ONE transaction that is rolled back at the end, so nothing is stored.

  Get-Content tests\\orm_checks.py | docker compose --env-file .env -f docker/docker-compose.yml exec -T -e DBN=$env:ODOO_DB odoo sh -c 'odoo shell -d "$DBN" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http --log-level=warn'

No real job API is called here: the HTTP layer is replaced by canned answers shaped like the providers' documented responses.
"""
import os
from datetime import date
from unittest import mock

from odoo import fields
from odoo.addons.llmd_job_aggregator.models import board_config as C
from odoo.addons.llmd_job_aggregator.models import sources as S

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))


Listing = env['llmd.job.listing']
from odoo.addons.llmd_job_aggregator.models import board_config as _BC
_BC.COMPANY_BOARDS = 'off'          # canned answers only: the company job boards send no real request in these checks (survives the rollbacks, changes no data)
_BC.DIRECT_LINKS_ONLY = False      # sections M-...: all sources combined (job board links included); section N checks the default "direct links only"

print('\n=== M. Adzuna + JSearch + Jooble are combined, with Remote, Hybrid AND On-site jobs; Himalayas (the keyless fallback) is not needed then (mocked API answers, nothing stored) ===')


class Resp:
    def __init__(self, payload, status=200):
        self.status_code, self._p, self.text = status, payload, ''

    def json(self):
        return self._p


TITLES = ['Sales Manager', 'Account Executive', 'Python Developer', 'SEO Specialist', 'Data Scientist', 'Machine Learning Engineer', 'Digital Marketing Manager', 'Customer Success Manager',
          'Business Development Manager', 'Data Analyst', 'Content Writer', 'Growth Marketing Manager', 'AI Engineer', 'Prompt Engineer', 'Solutions Engineer']
SNIPPET = {'': 'We are hiring a %s for our office. You will visit customers and own the results every day of the week in a fast growing company.',
           'remote': 'We are hiring a %s. This is a remote position: you can work from home and own the results every day of the week in a fast growing company.',
           'hybrid': 'We are hiring a %s. Hybrid work model: three days in the office and two days at home, owning the results in a fast growing company.'}


def adzuna_jobs(prefix, n, mode, place):
    return [{'id': '%s%d' % (prefix, i), 'title': '%s %s%d' % (TITLES[i % len(TITLES)], prefix, i), 'company': {'display_name': 'Adzuna Co %s%d' % (prefix, i)}, 'location': {'display_name': place},
             'description': SNIPPET[mode] % TITLES[i % len(TITLES)], 'redirect_url': 'https://www.adzuna.in/land/ad/%s%d' % (prefix, i), 'created': '2026-10-20T10:00:00Z', 'contract_time': 'full_time'}
            for i in range(n)]


ADZUNA = {'': {'results': adzuna_jobs('az', 12, '', 'Pune, Maharashtra')}, 'remote': {'results': adzuna_jobs('azr', 6, 'remote', 'India')}, 'hybrid': {'results': adzuna_jobs('azh', 6, 'hybrid', 'Bengaluru, Karnataka')}}
LONG = ' '.join('You will own part %d of the work and report on the results to the team every single week.' % i for i in range(8))


def js(job_id, title, company, city, state, country, remote=False, kind='FULLTIME', months=None, url=None, text=LONG):
    return {'job_id': job_id, 'job_title': title, 'employer_name': company, 'job_publisher': 'LinkedIn', 'job_employment_type': kind, 'job_apply_link': url or 'https://careers.example.com/%s' % job_id,
            'apply_options': [{'publisher': company, 'apply_link': url or 'https://careers.example.com/%s' % job_id, 'is_direct': True}], 'job_description': text, 'job_is_remote': remote,
            'job_city': city, 'job_state': state, 'job_country': country, 'job_posted_at_datetime_utc': '2026-10-21T10:00:00.000Z',
            'job_required_experience': {'required_experience_in_months': months} if months is not None else {}}


JSEARCH = {'': {'status': 'OK', 'data': [js('js-dup', 'Sales Manager az0', 'Adzuna Co az0', 'Pune', 'Maharashtra', 'IN', url='https://careers.adzunaco0.example/jobs/sm0'),
                                         js('js-london', 'Senior Data Scientist', 'London Labs', 'London', '', 'GB'), js('js-junior', 'Junior Data Analyst', 'Mumbai Metrics', 'Mumbai', 'Maharashtra', 'IN', months=12),
                                         js('js-india', 'Python Developer', 'Indian Software Ltd', 'Bengaluru', 'Karnataka', 'IN', months=48)]},
           'remote': {'status': 'OK', 'data': [js('js-remote', 'Marketing Intern', 'Remote Media', 'Pune', 'Maharashtra', 'IN', remote=True, kind='INTERN', months=0),
                                               js('js-remote2', 'Content Writer', 'Words Remote', '', '', 'IN', remote=True)]},
           'hybrid': {'status': 'OK', 'data': [js('js-hybrid', 'Digital Marketing Manager', 'Hybrid Brands', 'Gurugram', 'Haryana', 'IN', text='Hybrid work model: three days in the office and two days at home. ' + LONG)]}}
JOOBLE = {'': {'jobs': [{'id': 7000 + i, 'title': 'Jooble %s' % TITLES[i], 'company': 'Jooble Co %d' % i, 'location': 'Delhi', 'snippet': 'Jooble snippet: we need a strong %s at our Delhi office, with full ownership of the work.' % TITLES[i],
                         'link': 'https://in.jooble.org/desc/%d' % (7000 + i), 'updated': '2026-10-20T00:00:00.0000000'} for i in range(5)]},
          'remote': {'jobs': [{'id': 7100, 'title': 'Jooble SEO Specialist (Remote)', 'company': 'Jooble Remote Co', 'location': 'India', 'snippet': 'Work from home and own organic growth for our brands every week.',
                               'link': 'https://in.jooble.org/desc/7100', 'updated': '2026-10-20T00:00:00.0000000'}]},
          'hybrid': {'jobs': [{'id': 7200, 'title': 'Jooble Account Executive', 'company': 'Jooble Hybrid Co', 'location': 'Pune', 'snippet': 'Hybrid work model: two days at the Pune office, the rest from home, selling to enterprise accounts.',
                               'link': 'https://in.jooble.org/desc/7200', 'updated': '2026-10-20T00:00:00.0000000'}]}}
calls = {'adzuna': 0, 'jooble': 0, 'jsearch': 0, 'jsearch_remote': 0, 'jsearch_hybrid': 0, 'other': [], 'adzuna_urls': set(), 'locations': set()}


def mode_of(words):
    return 'remote' if 'remote' in words else 'hybrid' if 'hybrid' in words else ''


def fake_get(url, *a, **k):
    params = k.get('params') or {}
    if 'adzuna' in url:
        calls['adzuna'] += 1
        calls['adzuna_urls'].add(url.split('/jobs/')[1].split('/')[0])
        return Resp(ADZUNA[mode_of(params.get('what', ''))])
    if 'jsearch' in url:
        calls['jsearch'] += 1
        calls['locations'].add((params.get('country'), 'India' in params.get('query', '')))
        mode = 'remote' if params.get('remote_jobs_only') == 'true' else 'hybrid' if 'hybrid' in params.get('query', '') else ''
        calls['jsearch_remote'] += mode == 'remote'
        calls['jsearch_hybrid'] += mode == 'hybrid'
        return Resp(JSEARCH[mode])
    calls['other'].append(url)                                   # any other host - Himalayas included - is a failure of this test: the keyed sources deliver enough jobs, so it must not be asked
    return Resp({'jobs': []})


def fake_post(url, *a, **k):
    calls['jooble'] += 1
    calls['locations'].add(('jooble', k['json']['location']))
    return Resp(JOOBLE[mode_of(k['json']['keywords'])])


legacy = Listing.search_count([('source', '=', 'Himalayas'), ('active', '=', True)])
if not legacy:                                               # the board's own Himalayas jobs are hidden once a keyed source delivers: use a temporary one (rolled back)
    Listing.create({'source': 'Himalayas', 'ext_id': 'orm-m-himalayas', 'title': 'Sales Manager (Himalayas test)', 'company': 'Test Co', 'location': 'Remote · India', 'apply_url': 'https://himalayas.app/test',
                    'roles': ',sales_manager,', 'courses': ',sell-ai,', 'tags': ',sales,', 'fetched_at': fields.Datetime.now()})
    legacy = 1
keys = {'ADZUNA_APP_ID': 'test-id', 'ADZUNA_APP_KEY': 'test-key', 'JOOBLE_API_KEY': 'test-key', 'JSEARCH_API_KEY': 'test-key'}
used_before = {s.name: s.requests_used for s in env['llmd.job.source'].search([])}          # the real Jooble requests already counted
with mock.patch.dict(os.environ, keys), mock.patch.object(S.requests, 'get', fake_get), mock.patch.object(S.requests, 'post', fake_post), mock.patch.object(S.time, 'sleep'):
    stats = Listing.fetch_now()
    src = {s.name: s for s in env['llmd.job.source'].search([])}
    active = Listing.search([('active', '=', True)])
    by_source = {}
    for r in active:
        by_source[r.source] = by_source.get(r.source, 0) + 1
    check('with keys, Adzuna, JSearch and Jooble are read and report "Working"', all(src[n].last_status == 'ok' and src[n].last_count > 0 for n in ('Adzuna', 'JSearch', 'Jooble')), [(n, src[n].last_count) for n in ('Adzuna', 'JSearch', 'Jooble')])
    check('Himalayas is NOT asked when the keyed sources deliver enough jobs: it says "Not needed" and no request went anywhere else', src['Himalayas'].last_status == 'skipped' and not calls['other'], (src['Himalayas'].last_status, calls['other']))
    check('India only: Adzuna India, JSearch "... in India" with country=in, Jooble location India', calls['adzuna_urls'] == {'in'} and calls['locations'] == {('in', True), ('jooble', 'India')}, (calls['adzuna_urls'], calls['locations']))
    check('every search is sent as plain, remote and hybrid (a rotating window of all three modes: Adzuna 39, Jooble 9, JSearch 6 requests)', (calls['adzuna'], calls['jooble'], calls['jsearch']) == (39, 9, 6), calls)
    check('JSearch uses its own remote filter for the remote searches (2 of its 6) and the word "hybrid" for the hybrid ones (2 of 6)', (calls['jsearch_remote'], calls['jsearch_hybrid']) == (2, 2), calls)
    check('the request counters count what was sent (Jooble 9, JSearch 6 this month)', (src['Jooble'].requests_used - used_before['Jooble'], src['JSearch'].requests_used - (used_before['JSearch'] if src['JSearch'].budget_period == fields.Date.today().strftime('%Y-%m') else 0), src['JSearch'].budget_period) == (9, 6, fields.Date.today().strftime('%Y-%m')),
          (src['Jooble'].requests_used - used_before['Jooble'], src['JSearch'].requests_used, used_before['JSearch']))          # what THIS run sent (a real sync may have counted some before)
    check('the board holds jobs of all three sources (next to the company board jobs already stored); the Himalayas jobs are hidden again (not deleted)',
          {'Adzuna', 'JSearch', 'Jooble'} <= set(by_source) <= {'Adzuna', 'JSearch', 'Jooble', 'Company job boards'} and Listing.search_count([('source', '=', 'Himalayas'), ('active', '=', True)]) == 0,
          (by_source, '%d Himalayas jobs active before, hidden now' % legacy))
    modes = {m: Listing.search_count([('active', '=', True), ('work_mode', '=', m)]) for m in ('remote', 'hybrid', 'onsite')}
    check('the results hold Remote, Hybrid AND On-site jobs (not only remote ones)', all(modes.values()) and modes['onsite'] > modes['remote'], modes)
    modes_in = {m: Listing.search_count([('active', '=', True), ('india', '=', True), ('work_mode', '=', m)]) for m in ('remote', 'hybrid', 'onsite')}
    check('... also inside the default Location "India"', all(modes_in.values()), modes_in)
    per_source_modes = {n: sorted({r.work_mode for r in active if r.source == n}) for n in ('Adzuna', 'JSearch', 'Jooble')}
    check('every one of the three APIs contributes more than one work mode', all(len(v) >= 2 for v in per_source_modes.values()), per_source_modes)
    dup = Listing.search([('active', '=', True), ('dedupe_key', 'ilike', 'salesmanageraz0')])
    check('the same job from Adzuna and JSearch is stored once: the full text of JSearch wins and the job keeps ITS OWN application URL', len(dup) == 1 and dup.source == 'JSearch' and 'Adzuna' in (dup.also_on or '')
          and dup.apply_url == 'https://careers.adzunaco0.example/jobs/sm0' and dup.full_text, [(d.source, d.also_on, d.apply_url) for d in dup])
    check('every stored job has its original application URL (http/https)', all(r.apply_url.startswith('https://') for r in active), len(active))
    dv = active.filtered(lambda r: r.source == 'Adzuna')[:1].detail_vals()
    check('Apply Now of a job goes straight to the employer through the tracked /go link (no form by default); the own application URL of the job is only behind that link and never in the page data',
          all(r.apply_url.startswith('https://') for r in active) and dv['apply_form_href'] == '' and dv['go_href'].endswith('/go') and dv['internal_href'] == '' and dv['apply_url'].startswith('https://www.adzuna.in/'))
    d = active.filtered(lambda r: r.ext_id == 'js-london').detail_vals()          # by its id: a real company job can have the same title
    check('no source or site name is part of what the pages are given (title, company, location, tags, notice, apply)', 'JSearch' not in str(d) and 'LinkedIn' not in str(d) and d['source_text'] == '' and not d['badge'] and 'apply_host' not in d)
    remote = active.filtered(lambda r: r.ext_id == 'js-remote')
    hybrid = active.filtered(lambda r: r.ext_id == 'js-hybrid')
    london = active.filtered(lambda r: r.ext_id == 'js-london')
    check('JSearch jobs get their work mode and location values: remote flag, hybrid text, city, India or not',
          (remote.work_mode, remote.city, remote.india) == ('remote', 'Pune', True) and (hybrid.work_mode, hybrid.city) == ('hybrid', 'Gurugram') and (london.india, london.work_mode, london.city) == (False, 'onsite', 'London'),        # v19.0.26: cities all over the world
          [(remote.work_mode, remote.city), (hybrid.work_mode, hybrid.city), (london.india, london.work_mode, london.city)])
    seen = {e: (active.filtered(lambda r: r.ext_id == e).work_mode or 'MISSING') for e in ('azr0', 'azh0', 'az1', '7200', '7100')}
    check('Adzuna / Jooble snippets that say "remote position" / "hybrid work model" are recognized, plain ones stay on-site', seen == {'azr0': 'remote', 'azh0': 'hybrid', 'az1': 'onsite', '7200': 'hybrid', '7100': 'remote'}, seen)
    ordered = Listing.search([('active', '=', True)])
    flags = [r.india for r in ordered]
    order_keys = [(not r.posted, str(r.posted or ''), r.id) for r in ordered]                # PostgreSQL: DESC puts a job without a date first
    check('the stored order is the newest first (posted, then id) - since v19.0.26 the board mixes India and abroad itself (controller _llmd_mixed)',
          order_keys == sorted(order_keys, reverse=True) and not london.india, (len(flags), sum(flags)))
    check('jobs from other countries are still stored (shown under "All locations")', bool(london) and Listing.search_count([('active', '=', True), ('india', '=', False)]) >= 1)

    print('\n=== N. the small plans: monthly JSearch budget and the rotating searches ===')
    js_src = src['JSearch']
    js_src.write({'requests_used': 150})
    run = js_src.run([('a', ''), ('b', '')])
    check('JSearch at its monthly budget: no request is sent, the source says so, the board is not touched', run == [] and js_src.last_status == 'error' and 'budget' in js_src.last_message and calls['jsearch'] == 6, js_src.last_message)
    js_src.write({'requests_used': 150, 'budget_period': '2000-01'})
    with mock.patch.dict(os.environ, keys):
        js_src.run([('a', '')])
    check('a new month starts the counter again', js_src.requests_used == 1 and js_src.budget_period == fields.Date.today().strftime('%Y-%m'), js_src.requests_used)
    variants = C.query_variants()
    check('26 queries x 3 work modes = %d searches, the three modes of one query next to each other' % len(variants), len(variants) == 78 and [m for _q, m in variants[:3]] == ['', 'remote', 'hybrid'] and len({q for q, _m in variants[:3]}) == 1)
    with mock.patch.object(fields.Date, 'today', return_value=date(2026, 10, 22)):
        day1, adz1 = js_src._queries_for_run(variants), src['Adzuna']._queries_for_run(variants)
    with mock.patch.object(fields.Date, 'today', return_value=date(2026, 10, 23)):
        day2, adz2 = js_src._queries_for_run(variants), src['Adzuna']._queries_for_run(variants)
    check('JSearch sends 6 searches a day (2 queries x 3 modes) and the next day other ones', len(day1) == len(day2) == 6 and set(day1).isdisjoint(day2) and len({m for _q, m in day1}) == 3 and len({q for q, _m in day1}) == 2)
    check('Adzuna sends 39 of the 78 a day and the other half the next day (every search is used every two days)', len(adz1) == len(adz2) == 39 and set(adz1).isdisjoint(adz2) and set(adz1) | set(adz2) == set(variants))
env.cr.rollback()

print('\n=== O. a source that fails does not take the others down; what happens without keys (Himalayas = temporary fallback) ===')


def failing_get(url, *a, **k):
    if 'jsearch' in url:
        return Resp({}, 500)
    return fake_get(url, *a, **k)


with mock.patch.dict(os.environ, keys), mock.patch.object(S.requests, 'get', failing_get), mock.patch.object(S.requests, 'post', fake_post), mock.patch.object(S.time, 'sleep'):
    Listing.fetch_now()
    src = {s.name: s for s in env['llmd.job.source'].search([])}
    check('JSearch answering HTTP 500 -> it says "Error" (no key in the message), Adzuna and Jooble still deliver their jobs', src['JSearch'].last_status == 'error' and 'HTTP 500' in src['JSearch'].last_message and 'test-key' not in src['JSearch'].last_message
          and src['Adzuna'].last_status == src['Jooble'].last_status == 'ok' and Listing.search_count([('active', '=', True), ('source', 'in', ('Adzuna', 'Jooble'))]) > 10, src['JSearch'].last_message)
env.cr.rollback()

HIMALAYAS = {'jobs': [{'guid': 'hm-%d' % i, 'title': TITLES[i], 'companyName': 'Himalayas Co %d' % i, 'description': '<h3>Responsibilities</h3><ul><li>Own the results</li><li>Work with the team</li><li>Report every week</li></ul><p>%s</p>' % LONG,
                       'applicationLink': 'https://himalayas.app/companies/co%d/jobs/%d' % (i, i), 'locationRestrictions': ['India'] if i % 2 else [], 'employmentType': 'Full Time', 'pubDate': 1792627212} for i in range(6)]}
hcalls = {'himalayas': 0, 'other': []}


def only_himalayas(url, *a, **k):
    if 'himalayas' in url:
        hcalls['himalayas'] += 1
        assert k['params']['country'] == 'IN', 'India only'
        return Resp(HIMALAYAS)
    hcalls['other'].append(url)
    raise AssertionError('no request may be sent to ' + url)


no_keys = {k: '' for k in keys}
before_active = Listing.search_count([('active', '=', True)])
with mock.patch.dict(os.environ, no_keys), mock.patch.object(S.requests, 'get', only_himalayas), mock.patch.object(S.requests, 'post', side_effect=AssertionError('no request')), mock.patch.object(S.time, 'sleep'):
    stats = Listing.fetch_now()
    src = {s.name: s for s in env['llmd.job.source'].search([])}
    statuses = {n: s.last_status for n, s in src.items()}
    hm = Listing.search([('source', '=', 'Himalayas'), ('ext_id', '=like', 'hm-%')])
    check('without any key the keyed sources say "Not connected" and ONLY the keyless Himalayas fallback is read (26 plain queries, India only)',
          {n: v for n, v in statuses.items() if n != 'Himalayas'} == {n: 'not_configured' for n in ('Adzuna', 'JSearch', 'Company job boards', 'Jooble', 'Indeed', 'Naukri.com')} and statuses['Himalayas'] == 'ok' and hcalls['himalayas'] == 26 and not hcalls['other'], (statuses, hcalls))
    check('its jobs are stored and active; they are remote jobs', len(hm) == 6 and all(r.active and r.work_mode == 'remote' for r in hm) and all(r.apply_url.startswith('https://himalayas.app/') for r in hm), [(r.work_mode, r.location) for r in hm][:2])
    check('the jobs that were already on the board are still there (a fetch never empties it)', Listing.search_count([('active', '=', True)]) >= before_active, stats)
env.cr.rollback()
icp = env['ir.config_parameter'].sudo()
icp.set_param('llmd_agg.himalayas_mode', 'off')
with mock.patch.dict(os.environ, no_keys), mock.patch.object(S.requests, 'get', side_effect=AssertionError('no request may be sent')), mock.patch.object(S.requests, 'post', side_effect=AssertionError('no request')):
    stats = Listing.fetch_now()
    statuses = {s.name: s.last_status for s in env['llmd.job.source'].search([])}
check('llmd_agg.himalayas_mode = off: nothing is read at all, no key = every source "Not connected", Himalayas "Not needed", no job is hidden',
      {n: v for n, v in statuses.items() if n != 'Himalayas'} == {n: 'not_configured' for n in ('Adzuna', 'JSearch', 'Company job boards', 'Jooble', 'Indeed', 'Naukri.com')} and statuses['Himalayas'] == 'skipped' and stats['hidden'] == 0
      and Listing.search_count([('active', '=', True)]) == before_active, statuses)
env.cr.rollback()
print('\n=== N. direct links only (the default): Apply Now never opens a job board page first; the same job in two spellings of a city is kept once (mocked answers, rolled back) ===')
from odoo.addons.llmd_job_aggregator.models.listing import is_board_link
_BC.DIRECT_LINKS_ONLY = True
ncalls = {'board': [], 'jsearch': 0}
NJS = {'status': 'OK', 'data': [js('n-direct', 'Data Analyst', 'Direct Co', 'Pune', 'Maharashtra', 'IN', url='https://careers.directco.example/jobs/1'),
                                js('n-board', 'Data Scientist', 'Board Co', 'Pune', 'Maharashtra', 'IN', url='https://in.jooble.org/desc/42')]}


def direct_get(url, *a, **k):
    if 'jsearch' in url:
        ncalls['jsearch'] += 1
        return Resp(NJS)
    ncalls['board'].append(url)
    return Resp({'jobs': [], 'results': []})


def direct_post(url, *a, **k):
    ncalls['board'].append(url)
    return Resp({'jobs': []})


old_jooble = Listing.create({'source': 'Jooble', 'ext_id': 'orm-n-jooble', 'title': 'Sales Manager (Jooble test)', 'company': 'Test Co', 'location': 'Pune', 'apply_url': 'https://in.jooble.org/desc/1',
                             'roles': ',sales_manager,', 'courses': ',sell-ai,', 'tags': ',sales,', 'fetched_at': fields.Datetime.now()})
with mock.patch.dict(os.environ, keys), mock.patch.object(S.requests, 'get', direct_get), mock.patch.object(S.requests, 'post', direct_post), mock.patch.object(S.time, 'sleep'):
    stats = Listing.fetch_now()
    src = {s.name: s for s in env['llmd.job.source'].search([])}
    check('Adzuna, Jooble and Himalayas (their Apply Now opens their own page) are not asked at all, even with keys, and say "Off"',
          all(src[n].last_status == 'skipped' and src[n].last_message.startswith('Off') for n in ('Adzuna', 'Jooble', 'Himalayas')) and not ncalls['board'],
          ([(n, src[n].last_status) for n in ('Adzuna', 'Jooble', 'Himalayas')], ncalls['board'][:2]))
    every = Listing.with_context(active_test=False)
    check('JSearch is still read: its job with a direct link is stored, the one whose link is a job board page is not', ncalls['jsearch'] > 0 and src['JSearch'].last_status == 'ok'
          and Listing.search_count([('ext_id', '=', 'n-direct')]) == 1 and every.search_count([('ext_id', '=', 'n-board')]) == 0, (ncalls['jsearch'], stats))
    check('a job already on the board whose Apply Now opens Jooble is hidden (kept in the database, not deleted)', old_jooble.exists() and not old_jooble.active)
    check('no visible job opens a job board page first', not Listing.search([]).filtered(lambda r: is_board_link(r.apply_url)), stats)
position = env['hr.job'].search([('website_published', '=', True)], limit=1) or env['hr.job'].with_context(llmd_skip=True).create({'name': 'ORM N position', 'website_published': True})   # rolled back
if position:
    position.with_context(llmd_skip=True).write({'apply_url': 'https://himalayas.app/companies/x/jobs/y'})
    pd = position.llmd_content()
check('our own position whose saved link is a job board page: Apply Now opens our own Odoo application form instead', bool(position) and pd['go_href'] == '' and pd['internal_href'].startswith('/jobs/apply/'),
      bool(position) and (pd['go_href'], pd['internal_href']))
base_job = {'source': 'JSearch', 'title': 'Data Analyst', 'company': 'Same Co', 'html': '<p>Analyse the sales data every week and build the reports for the team.</p>', 'full_text': False}
merged = Listing.preview_merge([dict(base_job, ext_id='a', location='Bangalore', apply_url='https://careers.same.example/1'),
                                dict(base_job, ext_id='b', location='Bengaluru, Karnataka', apply_url='https://careers.same.example/2'),
                                dict(base_job, ext_id='c', location='Pune', apply_url='https://careers.same.example/3')])
check('the same job as "Bangalore" and "Bengaluru, Karnataka" is kept once; the same title in another city stays its own job', len(merged) == 2, [(m['title'], m['apply_url'][-2:]) for m in merged])
env.cr.rollback()
_BC.DIRECT_LINKS_ONLY = False
check('no job API key is stored in the system parameters', not env['ir.config_parameter'].sudo().search([('key', 'ilike', 'llmd_agg.%key'), ('value', '!=', False)]) and not env['ir.config_parameter'].sudo().search([('key', 'ilike', 'llmd_agg.adzuna_app')]))

print('\nSHELL RESULT: %d/%d checks passed' % (sum(RESULTS), len(RESULTS)))
env.cr.rollback()
