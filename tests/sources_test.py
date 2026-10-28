"""Unit tests of the job source adapters (models/sources.py) WITHOUT any real key: the HTTP layer is replaced by canned answers shaped like the providers' documented
responses. Nothing here is stored anywhere or shown on the website - it only proves that normalization and error handling work.

    python tests\\sources_test.py
"""
import json
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import sources as S  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
S.time.sleep = lambda *_: None                      # the retries wait 1-2 s: no real waiting in the unit tests


class Resp:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload


ADZUNA = {'count': 2, 'results': [
    {'id': '4411', 'title': 'Senior <strong>Data</strong> Analyst', 'company': {'display_name': 'Acme Analytics'}, 'location': {'display_name': 'Gurugram, Haryana'},
     'description': 'Build dashboards and analyse customer data for the growth team ...', 'redirect_url': 'https://www.adzuna.in/land/ad/4411?se=x', 'created': '2026-10-20T10:00:00Z',
     'contract_time': 'full_time', 'category': {'label': 'IT Jobs'}},
    {'id': '', 'title': 'No id - must be skipped', 'redirect_url': 'https://www.adzuna.in/land/ad/0'}]}
JOOBLE = {'totalCount': 1, 'jobs': [
    {'id': 987654, 'title': 'Python Developer', 'location': 'Bengaluru', 'snippet': 'Work on <b>Python</b> services &amp; APIs ...', 'salary': '', 'source': 'naukri.com',
     'type': 'Full-time', 'link': 'https://in.jooble.org/desc/987654', 'company': 'Beta Labs', 'updated': '2026-10-20T00:00:00.0000000'}]}
INDEED_XML = '''<?xml version="1.0" encoding="utf-8"?>
<source><publisher>Partner</publisher><job><title>Sales Manager</title><date>Tue, 20 Oct 2026 08:00:00 GMT</date><referencenumber>SM-1</referencenumber>
<url>https://careers.example.com/jobs/SM-1</url><company>Gamma Corp</company><city>Pune</city><state>MH</state><country>IN</country>
<description><![CDATA[<p>Lead a regional sales team and own the quota.</p>]]></description><jobtype>fulltime</jobtype></job></source>'''
NAUKRI_JSON = json.dumps({'jobs': [{'id': 'N-7', 'title': 'SEO Specialist', 'company': 'Delta Media', 'location': 'Noida', 'description': 'Own organic growth.',
                                   'apply_url': 'https://careers.example.org/seo-7', 'date': '2026-10-19'}]})


class AdzunaTests(unittest.TestCase):
    def test_normalizes_and_skips_rows_without_id(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, ADZUNA)) as get, mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_adzuna('APPID', 'APPKEY', ['data analyst'])
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual((j['source'], j['ext_id'], j['title'], j['company'], j['location']), ('Adzuna', '4411', 'Senior Data Analyst', 'Acme Analytics', 'Gurugram, Haryana'))
        self.assertEqual(j['apply_url'], 'https://www.adzuna.in/land/ad/4411?se=x')
        self.assertFalse(j['full_text'])
        self.assertEqual(j['employment_type'], 'Full Time')
        self.assertEqual(j['posted'].year, 2026)
        self.assertEqual(get.call_args.kwargs['params']['what'], 'data analyst')

    def test_bad_key_gives_a_message_without_the_key(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(401, {})), mock.patch.object(S.time, 'sleep'):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_adzuna('APPID', 'SECRETKEY123', ['x'])
        self.assertIn('refused the credentials', str(ctx.exception))
        self.assertNotIn('SECRETKEY123', str(ctx.exception))

    def test_rate_limit_and_server_errors(self):
        for code, word in ((429, 'rate limit'), (500, 'HTTP 500')):
            with mock.patch.object(S.requests, 'get', return_value=Resp(code, {})), mock.patch.object(S.time, 'sleep'):
                with self.assertRaises(S.SourceError) as ctx:
                    S.fetch_adzuna('a', 'b', ['x'])
            self.assertIn(word, str(ctx.exception))

    def test_network_failure(self):
        with mock.patch.object(S.requests, 'get', side_effect=requests.ConnectionError('boom https://api.adzuna.com/?app_key=SECRET')):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_adzuna('a', 'SECRET', ['x'])
        self.assertNotIn('SECRET', str(ctx.exception))


class WorkModeSearchTests(unittest.TestCase):
    def test_adzuna_and_jooble_ask_for_remote_and_hybrid_in_the_search_words(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, ADZUNA)) as get, mock.patch.object(S.time, 'sleep'):
            S.fetch_adzuna('a', 'b', [('data analyst', ''), ('data analyst', 'remote'), ('data analyst', 'hybrid'), 'data scientist'])
        self.assertEqual([c.kwargs['params']['what'] for c in get.call_args_list], ['data analyst', 'data analyst remote', 'data analyst hybrid', 'data scientist'])
        self.assertTrue(all('/jobs/in/' in c.args[0] for c in get.call_args_list))                              # Adzuna India
        with mock.patch.object(S.requests, 'post', return_value=Resp(200, JOOBLE)) as post, mock.patch.object(S.time, 'sleep'):
            S.fetch_jooble('k', [('seo specialist', 'remote'), ('seo specialist', 'hybrid'), ('seo specialist', '')], 'India')
        self.assertEqual([c.kwargs['json'] for c in post.call_args_list], [{'keywords': 'seo specialist remote', 'location': 'India'}, {'keywords': 'seo specialist hybrid', 'location': 'India'},
                                                                          {'keywords': 'seo specialist', 'location': 'India'}])

    def test_the_same_job_found_by_two_searches_is_returned_once(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, ADZUNA)), mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_adzuna('a', 'b', [('x', ''), ('x', 'remote'), ('x', 'hybrid')])
        self.assertEqual(len(jobs), 1)


class JoobleTests(unittest.TestCase):
    def test_normalizes(self):
        with mock.patch.object(S.requests, 'post', return_value=Resp(200, JOOBLE)) as post, mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_jooble('JOOBLEKEY', ['python developer'], 'India')
        j = jobs[0]
        self.assertEqual((j['source'], j['ext_id'], j['title'], j['company'], j['via']), ('Jooble', '987654', 'Python Developer', 'Beta Labs', 'naukri.com'))
        self.assertEqual(j['apply_url'], 'https://in.jooble.org/desc/987654')
        self.assertIn('Python services & APIs', j['html'].replace('&amp;', '&'))
        self.assertEqual(post.call_args.args[0], 'https://in.jooble.org/api/JOOBLEKEY')                     # the India domain (jooble.org itself answers 403 to API calls)
        self.assertEqual(post.call_args.kwargs['json'], {'keywords': 'python developer', 'location': 'India'})

    def test_request_budget_stops_before_the_free_plan_is_used_up(self):
        with mock.patch.object(S.requests, 'post', return_value=Resp(200, JOOBLE)), mock.patch.object(S.time, 'sleep'):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_jooble('k', ['a', 'b'], 'India', count_request=lambda: False)
        self.assertIn('budget', str(ctx.exception))

    def test_error_statuses(self):
        for code in (401, 403, 429, 503):
            with mock.patch.object(S.requests, 'post', return_value=Resp(code, {})), mock.patch.object(S.time, 'sleep'):
                with self.assertRaises(S.SourceError):
                    S.fetch_jooble('k', ['a'], 'India')


JSEARCH = {'status': 'OK', 'request_id': 'r1', 'data': [
    {'job_id': 'abc123==', 'job_title': 'Senior <b>Python</b> Developer', 'employer_name': 'Delta Tech', 'job_publisher': 'LinkedIn', 'job_employment_type': 'FULLTIME', 'job_employment_types': ['FULLTIME'],
     'job_apply_link': 'https://www.linkedin.com/jobs/view/1', 'job_apply_is_direct': False,
     'apply_options': [{'publisher': 'LinkedIn', 'apply_link': 'https://www.linkedin.com/jobs/view/1', 'is_direct': False}, {'publisher': 'Delta Tech', 'apply_link': 'https://careers.deltatech.example/jobs/77', 'is_direct': True}],
     'job_description': 'We are hiring.\n\nYou will build APIs and own the quality of our services in a fast growing product company.', 'job_is_remote': False, 'job_posted_at_datetime_utc': '2026-10-20T10:00:00.000Z',
     'job_city': 'Bengaluru', 'job_state': 'Karnataka', 'job_country': 'IN', 'job_min_salary': 1500000, 'job_max_salary': 2500000, 'job_salary_currency': 'INR', 'job_salary_period': 'YEAR',
     'job_highlights': {'Qualifications': ['5 years of Python'], 'Responsibilities': ['Build APIs', 'Review code'], 'Benefits': ['Insurance']},
     'job_required_experience': {'no_experience_required': False, 'required_experience_in_months': 60, 'experience_mentioned': True}},
    {'job_id': 'remote1', 'job_title': 'Marketing Intern', 'employer_name': 'Echo Media', 'job_publisher': 'Indeed', 'job_employment_type': 'INTERN', 'job_apply_link': 'https://example.com/apply/9', 'job_description': 'Help our team.',
     'job_is_remote': True, 'job_city': 'Pune', 'job_state': 'Maharashtra', 'job_country': 'IN', 'job_posted_at_timestamp': 1792627212, 'job_required_experience': {'no_experience_required': True}},
    {'job_id': '', 'job_title': 'No id - must be skipped', 'job_apply_link': 'https://example.com/x'},
    {'job_id': 'abc123==', 'job_title': 'Duplicate of the first one', 'job_apply_link': 'https://example.com/y'}]}


class JSearchTests(unittest.TestCase):
    def test_normalizes(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, JSEARCH)) as get, mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_jsearch('KEY', ['python developer'])
        self.assertEqual([j['ext_id'] for j in jobs], ['abc123==', 'remote1'])
        a, b = jobs
        self.assertEqual((a['source'], a['title'], a['company'], a['location'], a['countries'], a['employment_type'], a['seniority']),
                         ('JSearch', 'Senior Python Developer', 'Delta Tech', 'Bengaluru, Karnataka, India', 'IN', 'Full Time', 'Mid-level'))     # 60 months asked for
        self.assertEqual(a['apply_url'], 'https://careers.deltatech.example/jobs/77')               # the employer's own link wins over the job site's
        self.assertEqual(a['via'], 'LinkedIn')
        self.assertFalse(a['full_text'])                                                          # a short text is not called a "full" description
        self.assertIn('<h3>Responsibilities</h3><ul><li>Build APIs</li><li>Review code</li></ul>', a['html'])
        self.assertIn('<h3>Qualifications</h3>', a['html'])
        self.assertNotIn('Insurance', a['html'])
        self.assertEqual(a['salary'], 'INR 1,500,000 – 2,500,000 per year')
        self.assertEqual(a['posted'].year, 2026)
        self.assertEqual((b['location'], b['employment_type'], b['seniority'], b['apply_url']), ('Remote · Pune, Maharashtra, India', 'Internship', 'Fresher', 'https://example.com/apply/9'))
        self.assertIsNotNone(b['posted'])
        params = get.call_args.kwargs['params']
        self.assertEqual((params['query'], params['country'], params['num_pages']), ('python developer in India', 'in', 1))

    def test_both_providers(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, JSEARCH)) as get, mock.patch.object(S.time, 'sleep'):
            S.fetch_jsearch('KEY', ['x'])
            rapid = get.call_args
            S.fetch_jsearch('KEY2', ['x'], 'https://api.openwebninja.com/jsearch/search')
            ninja = get.call_args
        self.assertEqual(rapid.args[0], 'https://jsearch.p.rapidapi.com/search')
        self.assertEqual((rapid.kwargs['headers']['X-RapidAPI-Key'], rapid.kwargs['headers']['X-RapidAPI-Host']), ('KEY', 'jsearch.p.rapidapi.com'))
        self.assertEqual(ninja.args[0], 'https://api.openwebninja.com/jsearch/search')
        self.assertEqual(ninja.kwargs['headers']['x-api-key'], 'KEY2')
        self.assertNotIn('X-RapidAPI-Key', ninja.kwargs['headers'])

    def test_errors_never_show_the_key(self):
        for code in (401, 403, 429, 500):
            with mock.patch.object(S.requests, 'get', return_value=Resp(code, {})), mock.patch.object(S.time, 'sleep'):
                with self.assertRaises(S.SourceError) as ctx:
                    S.fetch_jsearch('SECRETKEY123', ['x'])
            self.assertNotIn('SECRETKEY123', str(ctx.exception))
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, {'status': 'ERROR', 'error': {'message': 'You are not subscribed to this API.'}})):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_jsearch('k', ['x'])
        self.assertIn('not subscribed', str(ctx.exception))
        with mock.patch.object(S.requests, 'get', side_effect=requests.ConnectionError('boom https://x?key=SECRETKEY123')):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_jsearch('SECRETKEY123', ['x'])
        self.assertNotIn('SECRETKEY123', str(ctx.exception))

    def test_request_budget(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, JSEARCH)), mock.patch.object(S.time, 'sleep'):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_jsearch('k', ['a', 'b'], count_request=lambda: False)
        self.assertIn('budget', str(ctx.exception))

    def test_remote_hybrid_and_plain_searches(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, JSEARCH)) as get, mock.patch.object(S.time, 'sleep'):
            S.fetch_jsearch('k', [('sales manager', ''), ('sales manager', 'remote'), ('sales manager', 'hybrid'), 'plain query'])
        sent = [c.kwargs['params'] for c in get.call_args_list]
        self.assertEqual([p['query'] for p in sent], ['sales manager in India', 'sales manager in India', 'sales manager hybrid in India', 'plain query in India'])
        self.assertEqual([p.get('remote_jobs_only') for p in sent], [None, 'true', None, None])             # JSearch's own remote filter is used for the remote search only
        self.assertTrue(all(p['country'] == 'in' for p in sent))

HIMALAYAS = {'jobs': [
    {'guid': 'https://himalayas.app/companies/acme/jobs/data-analyst', 'title': 'Data Analyst', 'companyName': 'Acme', 'description': '<p>Analyse data every day.</p>', 'applicationLink': 'https://himalayas.app/companies/acme/jobs/data-analyst?utm=api',
     'locationRestrictions': ['India', 'Brazil', 'Spain'], 'employmentType': 'Full Time', 'seniority': ['Mid-level'], 'categories': ['Data'], 'pubDate': 1792627212, 'minSalary': 10, 'maxSalary': 20, 'currency': 'USD', 'salaryPeriod': 'hourly'},
    {'guid': 'g2', 'title': 'Growth Marketer', 'companyName': 'Beta', 'description': '', 'applicationLink': 'https://himalayas.app/companies/beta/jobs/growth', 'locationRestrictions': []},
    {'guid': 'g3', 'title': 'Sales Manager', 'companyName': 'Gamma', 'applicationLink': 'https://himalayas.app/companies/gamma/jobs/sales', 'locationRestrictions': ['United States', 'Canada', 'Mexico', 'Chile']},
    {'guid': '', 'applicationLink': '', 'title': 'No id'}]}


class HimalayasFallbackTests(unittest.TestCase):
    def test_normalizes_remote_jobs_open_to_india(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, HIMALAYAS)) as get, mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_himalayas([('data analyst', ''), ('data analyst', 'remote'), ('data analyst', 'hybrid'), 'sales manager'])
        self.assertEqual(get.call_count, 2)                                                                   # no work-mode variants: only the plain queries are sent
        self.assertEqual(get.call_args.kwargs['params']['country'], 'IN')
        self.assertEqual([j['ext_id'] for j in jobs], ['https://himalayas.app/companies/acme/jobs/data-analyst', 'g2', 'g3'])
        self.assertEqual([j['location'] for j in jobs], ['Remote · India + 2 more countries', 'Remote · Worldwide', 'Remote · United States, Canada, Mexico +1'])
        a = jobs[0]
        self.assertEqual((a['source'], a['company'], a['employment_type'], a['seniority'], a['salary'], a['full_text']), ('Himalayas', 'Acme', 'Full Time', 'Mid-level', 'USD 10 – 20 per hour', True))
        self.assertEqual(a['apply_url'], 'https://himalayas.app/companies/acme/jobs/data-analyst?utm=api')

    def test_errors_are_clean(self):
        for code in (403, 429, 500):
            with mock.patch.object(S.requests, 'get', return_value=Resp(code, {})), mock.patch.object(S.time, 'sleep'):
                with self.assertRaises(S.SourceError):
                    S.fetch_himalayas(['x'])
        with mock.patch.object(S.requests, 'get', side_effect=requests.ConnectionError('boom')):
            with self.assertRaises(S.SourceError):
                S.fetch_himalayas(['x'])


class RetryTests(unittest.TestCase):
    """Temporary failures are retried, a bad key is not; every retry is counted in the plan's budget; no key reaches the log."""

    def test_503_then_200_is_retried_and_succeeds(self):
        with mock.patch.object(S.requests, 'get', side_effect=[Resp(503, {}), Resp(502, {}), Resp(200, ADZUNA)]) as get:
            jobs = S.fetch_adzuna('a', 'b', ['x'])
        self.assertEqual((get.call_count, len(jobs)), (3, 1))

    def test_network_error_then_success(self):
        with mock.patch.object(S.requests, 'post', side_effect=[requests.ConnectionError('boom'), requests.Timeout('slow'), Resp(200, JOOBLE)]) as post:
            jobs = S.fetch_jooble('KEY', ['python developer'], 'India')
        self.assertEqual((post.call_count, len(jobs)), (3, 1))

    def test_gives_up_after_three_tries_with_a_clean_message(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(500, {})) as get:
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_adzuna('a', 'SECRET', ['x'])
        self.assertEqual(get.call_count, 3)
        self.assertIn('HTTP 500', str(ctx.exception))
        with mock.patch.object(S.requests, 'get', side_effect=requests.ConnectionError('boom')) as get:
            with self.assertRaises(S.SourceError):
                S.fetch_adzuna('a', 'SECRET', ['x'])
        self.assertEqual(get.call_count, 3)

    def test_a_bad_key_or_a_normal_error_is_not_retried(self):
        for code in (400, 401, 403, 404):
            with mock.patch.object(S.requests, 'get', return_value=Resp(code, {})) as get:
                with self.assertRaises(S.SourceError):
                    S.fetch_adzuna('a', 'b', ['x'])
            self.assertEqual(get.call_count, 1, code)

    def test_retry_after_is_respected_and_capped(self):
        class Slow(Resp):
            headers = {'Retry-After': '60'}
        waits = []
        with mock.patch.object(S.time, 'sleep', side_effect=waits.append), mock.patch.object(S.requests, 'get', side_effect=[Slow(429, {}), Resp(200, ADZUNA)]):
            S.fetch_adzuna('a', 'b', ['x'])
        self.assertEqual(waits[0], 10)                                                                    # asked 60 s, capped at 10 s

    def test_retries_are_counted_and_stop_when_the_budget_is_used_up(self):
        counter = iter([True, True, False])                                                               # the first request was counted by the caller, then two retries are allowed ...
        with mock.patch.object(S.requests, 'post', return_value=Resp(503, {})) as post:
            with self.assertRaises(S.SourceError):
                S.fetch_jooble('k', ['a'], 'India', count_request=lambda: next(counter))
        self.assertEqual(post.call_count, 2)                                                              # ... first call + the one retry the budget paid for

    def test_the_key_is_never_logged(self):
        with self.assertLogs(S._logger, level='WARNING') as logs, mock.patch.object(S.requests, 'post', side_effect=requests.ConnectionError('https://in.jooble.org/api/SECRETKEY123 failed')):
            with self.assertRaises(S.SourceError):
                S.fetch_jooble('SECRETKEY123', ['a'], 'India')
        self.assertTrue(logs.output)
        self.assertNotIn('SECRETKEY123', ' '.join(logs.output))


class FeedTests(unittest.TestCase):
    def test_xml_feed(self):
        jobs = S.parse_feed(INDEED_XML, 'Indeed')
        j = jobs[0]
        self.assertEqual((j['source'], j['ext_id'], j['title'], j['company'], j['location']), ('Indeed', 'SM-1', 'Sales Manager', 'Gamma Corp', 'Pune, MH, IN'))
        self.assertEqual(j['apply_url'], 'https://careers.example.com/jobs/SM-1')
        self.assertIn('Lead a regional sales team', j['html'])

    def test_json_feed(self):
        j = S.parse_feed(NAUKRI_JSON, 'Naukri.com')[0]
        self.assertEqual((j['source'], j['ext_id'], j['title'], j['company'], j['apply_url']), ('Naukri.com', 'N-7', 'SEO Specialist', 'Delta Media', 'https://careers.example.org/seo-7'))

    def test_broken_feeds_raise_a_clean_error(self):
        for bad in ('<job><title>x', '{not json', ''):
            with self.assertRaises(S.SourceError):
                S.parse_feed(bad, 'Indeed') if bad else (_ for _ in ()).throw(S.SourceError('empty'))

    def test_feed_token_is_sent_as_bearer_and_errors_are_clean(self):
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, None, INDEED_XML)) as get:
            S.fetch_feed('https://feeds.example.com/indeed.xml', 'TOKEN123', 'Indeed')
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer TOKEN123')
        with mock.patch.object(S.requests, 'get', return_value=Resp(403, None, '')):
            with self.assertRaises(S.SourceError) as ctx:
                S.fetch_feed('https://feeds.example.com/indeed.xml', 'TOKEN123', 'Indeed')
        self.assertNotIn('TOKEN123', str(ctx.exception))


class SalaryTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(S.format_salary(70000, 150000, 'USD', 'annual'), 'USD 70,000 – 150,000 per year')
        self.assertEqual(S.format_salary(900, 1400, 'EUR', 'monthly'), 'EUR 900 – 1,400 per month')
        self.assertEqual(S.format_salary(60, None, 'USD', 'hourly'), 'USD 60 per hour')
        self.assertEqual(S.format_salary(None, None, 'USD', 'annual'), '')
        self.assertEqual(S.format_salary(0, 0), '')

    def test_adapters_only_show_a_salary_the_source_states(self):
        predicted = dict(ADZUNA['results'][0], salary_min=500000, salary_max=700000, salary_is_predicted='1')
        stated = dict(ADZUNA['results'][0], id='4412', salary_min=500000, salary_max=700000, salary_is_predicted='0')
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, {'results': [predicted, stated]})), mock.patch.object(S.time, 'sleep'):
            jobs = S.fetch_adzuna('a', 'b', ['x'])
        self.assertEqual([j['salary'] for j in jobs], ['', 'INR 500,000 – 700,000 per year'])
        with mock.patch.object(S.requests, 'post', return_value=Resp(200, {'jobs': [dict(JOOBLE['jobs'][0], salary='Rs. 8 LPA')]})), mock.patch.object(S.time, 'sleep'):
            self.assertEqual(S.fetch_jooble('k', ['x'], 'India')[0]['salary'], 'Rs. 8 LPA')


class TextTests(unittest.TestCase):
    def test_snippets_escaped_twice_and_tags(self):
        self.assertEqual(S._strip('SQL, BI &amp;amp; Data Analytics | <b>Remote</b>'), 'SQL, BI & Data Analytics | Remote')
        self.assertEqual(S._strip('&nbsp;...Sales &amp; Marketing'), '...Sales & Marketing')
        self.assertEqual(S._strip('We&amp;#x27;re looking for an AI Intern. You&amp;amp;#x27;ll build &lt;b&gt;things&lt;/b&gt;'), "We're looking for an AI Intern. You'll build <b>things</b>")
        self.assertEqual(S._strip('Plain text with 5 &lt; 6 and a <b>tag</b>'), 'Plain text with 5 < 6 and a tag')


class DateTests(unittest.TestCase):
    def test_formats(self):
        for value in ('2026-10-20T10:00:00Z', '2026-10-20', 'Tue, 20 Oct 2026 08:00:00 GMT', '2026-10-20T00:00:00.0000000', 1792627212, '1792627212'):
            self.assertIsNotNone(S.parse_dt(value), value)
        self.assertIsNone(S.parse_dt('garbage'))
        self.assertIsNone(S.parse_dt(''))


GREENHOUSE = {'jobs': [
    {'id': 11, 'title': 'Data Analyst', 'company_name': 'Rubrik Job Board', 'location': {'name': 'Bengaluru, India'}, 'absolute_url': 'https://www.rubrik.com/careers?gh_jid=11',
     'first_published': '2026-10-20T10:00:00-04:00', 'content': '&lt;p&gt;Analyse &lt;b&gt;data&lt;/b&gt; for the sales team every week, build dashboards and reports.&lt;/p&gt;' * 5,
     'departments': [{'name': 'Analytics'}], 'offices': []},
    {'id': 12, 'title': 'Data Analyst', 'company_name': 'Rubrik', 'location': {'name': 'Tokyo, Japan'}, 'absolute_url': 'https://www.rubrik.com/careers?gh_jid=12', 'content': '', 'offices': []},
    {'id': 13, 'title': 'Office Manager', 'company_name': 'Rubrik', 'location': {'name': 'Pune, India'}, 'absolute_url': 'https://www.rubrik.com/careers?gh_jid=13', 'content': '', 'offices': []}]}
LEVER = [
    {'id': 'abc', 'text': 'Account Executive', 'createdAt': 1792000000000, 'workplaceType': 'hybrid', 'applyUrl': 'https://jobs.lever.co/paytm/abc/apply', 'hostedUrl': 'https://jobs.lever.co/paytm/abc',
     'categories': {'commitment': 'Full-time Employment', 'location': 'Dubai', 'allLocations': ['Dubai', 'Noida, Uttar Pradesh'], 'department': 'Sales'},
     'description': '<p>Own the enterprise pipeline.</p>', 'lists': [{'text': 'What you will do', 'content': '<li>Close deals</li>'}], 'additional': '<p>Benefits</p>'}]
ASHBY = {'jobs': [
    {'id': 'x1', 'title': 'Machine Learning Engineer', 'location': 'Bengaluru', 'secondaryLocations': [], 'isRemote': False, 'workplaceType': 'OnSite', 'isListed': True,
     'descriptionHtml': '<p>Train models.</p>', 'jobUrl': 'https://jobs.ashbyhq.com/sarvam/x1', 'publishedAt': '2026-10-21T08:00:00.000+00:00', 'employmentType': 'FullTime',
     'shouldDisplayCompensationOnJobPostings': True, 'compensation': {'compensationTierSummary': 'INR 30L - 45L'}},
    {'id': 'x2', 'title': 'Machine Learning Engineer', 'location': 'Bengaluru', 'isListed': False, 'jobUrl': 'https://jobs.ashbyhq.com/sarvam/x2'}]}
SR_LIST = {'content': [{'id': '7001', 'name': 'Senior Account Executive - Inside Sales', 'location': {'city': 'Chennai', 'region': 'TN', 'country': 'in', 'remote': False},
                        'releasedDate': '2026-10-19T09:00:00.000Z', 'company': {'name': 'Freshworks'}, 'typeOfEmployment': {'label': 'Full-time'}, 'experienceLevel': {'label': 'Mid-Senior Level'}}]}
SR_DETAIL = {'applyUrl': 'https://jobs.smartrecruiters.com/Freshworks/7001-senior-ae/apply', 'jobAd': {'sections': {
    'jobDescription': {'title': 'Job Description', 'text': '<p>Run inside sales.</p>'}, 'qualifications': {'title': 'Qualifications', 'text': '<ul><li>5+ years in SaaS sales</li></ul>'}}}}


def ats_router(url, **kw):
    if 'boards-api.greenhouse.io' in url:
        return Resp(200, GREENHOUSE)
    if 'api.lever.co' in url:
        return Resp(200, LEVER)
    if 'api.ashbyhq.com' in url:
        return Resp(200, ASHBY)
    if url.endswith('/postings'):
        return Resp(200, SR_LIST)
    if '/postings/7001' in url:
        return Resp(200, SR_DETAIL)
    return Resp(404, {})


def india_and_roles(title, location, department=''):
    return any(w in (location or '') for w in ('India', 'Noida', 'Bengaluru', 'Chennai')) and any(w in title for w in ('Analyst', 'Account', 'Machine Learning'))


class CompanyBoardTests(unittest.TestCase):
    BOARDS = S.parse_boards('greenhouse:rubrik, lever:paytm=Paytm, ashby:sarvam=Sarvam AI, smartrecruiters:Freshworks, bamboo:nope, junk')

    def test_parse_boards(self):
        self.assertEqual(self.BOARDS, [('greenhouse', 'rubrik', ''), ('lever', 'paytm', 'Paytm'), ('ashby', 'sarvam', 'Sarvam AI'), ('smartrecruiters', 'Freshworks', '')])
        self.assertEqual(S.parse_boards('off'), [])

    def test_every_provider_is_read_and_only_india_jobs_that_fit_are_kept(self):
        with mock.patch.object(S.requests, 'get', side_effect=ats_router):
            jobs = S.fetch_company_boards(self.BOARDS, india_and_roles, keep_place=lambda l: 'India' in l or 'Noida' in l)
        by = {j['ext_id']: j for j in jobs}
        self.assertEqual(sorted(by), ['ab:sarvam:x1', 'gh:rubrik:11', 'lv:paytm:abc', 'sr:Freshworks:7001'])
        gh, lv, ab, sr = by['gh:rubrik:11'], by['lv:paytm:abc'], by['ab:sarvam:x1'], by['sr:Freshworks:7001']
        self.assertEqual((gh['company'], gh['location'], gh['apply_url']), ('Rubrik', 'Bengaluru, India', 'https://www.rubrik.com/careers?gh_jid=11'))
        self.assertIn('<b>data</b>', gh['html'])
        self.assertTrue(gh['full_text'])
        self.assertEqual((lv['company'], lv['location'], lv['employment_type'], lv['apply_url']), ('Paytm', 'Noida, Uttar Pradesh (Hybrid)', 'Full Time', 'https://jobs.lever.co/paytm/abc/apply'))
        self.assertEqual(lv['posted'].year, 2026)
        self.assertIn('<h3>What you will do</h3><ul><li>Close deals</li></ul>', lv['html'])
        self.assertEqual((ab['company'], ab['salary'], ab['employment_type'], ab['apply_url']), ('Sarvam AI', 'INR 30L - 45L', 'Full Time', 'https://jobs.ashbyhq.com/sarvam/x1'))
        self.assertEqual((sr['company'], sr['location'], sr['seniority'], sr['apply_url']), ('Freshworks', 'Chennai, TN, India', 'Mid-Senior Level', 'https://jobs.smartrecruiters.com/Freshworks/7001-senior-ae/apply'))
        self.assertIn('5+ years in SaaS sales', sr['html'])
        self.assertTrue(all(j['source'] == 'Company job boards' for j in jobs))

    def test_every_board_tells_which_postings_it_lists_now(self):
        """The sync hides a stored job that its company's board no longer lists (the company closed it): every board that answered gives the ids of ALL its
        open postings, not only the ones that were kept (an unlisted Ashby posting is not open)."""
        listed = {}
        with mock.patch.object(S.requests, 'get', side_effect=ats_router):
            S.fetch_company_boards(self.BOARDS, india_and_roles, keep_place=lambda l: 'India' in l or 'Noida' in l, listed=listed)
        self.assertEqual(listed, {'gh:rubrik': {'gh:rubrik:11', 'gh:rubrik:12', 'gh:rubrik:13'}, 'lv:paytm': {'lv:paytm:abc'}, 'ab:sarvam': {'ab:sarvam:x1'},
                                  'sr:Freshworks': {'sr:Freshworks:7001'}})

    def test_at_most_per_board_jobs_newest_first(self):
        many = {'jobs': [dict(GREENHOUSE['jobs'][0], id=100 + i, first_published='2026-10-%02dT10:00:00Z' % (i + 1)) for i in range(20)]}
        with mock.patch.object(S.requests, 'get', return_value=Resp(200, many)):
            jobs = S.fetch_company_boards([('greenhouse', 'rubrik', '')], india_and_roles, per_board=5)
        self.assertEqual([j['ext_id'] for j in jobs], ['gh:rubrik:%d' % (100 + i) for i in (19, 18, 17, 16, 15)])

    def test_a_board_that_does_not_answer_is_skipped_and_none_answering_is_an_error(self):
        def half(url, **kw):
            return Resp(404, {}) if 'lever' in url else ats_router(url)
        with mock.patch.object(S.requests, 'get', side_effect=half):
            jobs = S.fetch_company_boards([('greenhouse', 'rubrik', ''), ('lever', 'paytm', 'Paytm')], india_and_roles)
        self.assertEqual([j['ext_id'] for j in jobs], ['gh:rubrik:11'])
        with mock.patch.object(S.requests, 'get', return_value=Resp(404, {})):
            with self.assertRaises(S.SourceError):
                S.fetch_company_boards([('greenhouse', 'rubrik', '')], india_and_roles)


if __name__ == '__main__':
    unittest.main(verbosity=2)
