r"""Checks candidate company job boards against the PUBLIC job-board APIs of the ATS providers (no key): does the board exist, how many jobs, how many in India,
how many of those fit the roles / categories of the courses. Only boards that really answer are used by the "Company job boards" source.

    python scripts\company_boards_probe.py                 all candidates below
    python scripts\company_boards_probe.py greenhouse:stripe lever:whatfix
"""
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import board_config as C  # noqa: E402
import job_facets as F  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
UA = {'User-Agent': 'LLMDecode-Odoo/1.0', 'Accept': 'application/json'}

CANDIDATES = {
    'greenhouse': ['databricks', 'stripe', 'mongodb', 'elastic', 'gitlab', 'okta', 'rubrik', 'thoughtspot', 'postman', 'phonepe', 'browserstack', 'hackerrank', 'glean', 'druva',
                   'chargebee', 'innovaccer', 'mindtickle', 'airbnb', 'coinbase', 'anthropic', 'groww', 'inmobi', 'sprinklr', 'dream11', 'cloudflare', 'datadog', 'twilio', 'zscaler',
                   'confluent', 'nutanix', 'meesho', 'razorpaysoftwareprivatelimited', 'razorpay', 'pinelabs', 'juspay', 'lenskart', 'urbancompany', 'clevertap', 'moengage', 'netcore',
                   'darwinbox', 'gupshup', 'haptik', 'yellowai', 'turing', 'hasura', 'zetaglobal', 'sigmoid', 'tredence', 'fractal', 'tigeranalytics', 'leadsquared', 'webengage',
                   'samsara', 'figma', 'gojek', 'udemy', 'coursera', 'upgrad', 'simplilearn', 'acko', 'navi', 'zepto', 'swiggy', 'zomato', 'paytm', 'cred'],
    'lever': ['whatfix', 'cred', 'meesho', 'sharechat', 'unacademy', 'jupiter', 'slice', 'zeta', 'rapido', 'cars24', 'udaan', 'khatabook', 'mpl', 'games24x7', 'upgrad',
              'leadsquared', 'clevertap', 'moengage', 'haptik', 'yellowai', 'sprinto', 'spotdraft', 'plivo', 'exotel', 'hevodata', 'rocketlane', 'paytm', 'swiggy', 'zomato',
              'bharatpe', 'dunzo', 'groww', 'smallcase', 'koo', 'pharmeasy', 'cultfit', 'licious', 'innovaccer', 'freshworks', 'mindtickle', 'scaler', 'interviewbit', 'airtel'],
    'ashby': ['openai', 'notion', 'deel', 'ramp', 'linear', 'vercel', 'supabase', 'atlan', 'sarvam', 'cohere', 'elevenlabs', 'perplexity', 'observeai', 'clay', 'retool', 'posthog',
              'mercor', 'rippling', 'cred', 'zeta', 'krutrim', 'composio', 'lovable', 'replit', 'cursor', 'anysphere', 'harvey', 'writer', 'glean'],
    'smartrecruiters': ['Freshworks', 'Visa', 'BoschGroup', 'Wipro', 'Sprinklr', 'Ubisoft', 'Experian', 'NielsenIQ', 'Publicis', 'Dentsu', 'Accolite', 'Cognizant'],
}


def jobs_of(ats, token):
    """-> list of (title, location) or raises."""
    if ats == 'greenhouse':
        r = requests.get('https://boards-api.greenhouse.io/v1/boards/%s/jobs' % token, headers=UA, timeout=20)
        r.raise_for_status()
        return [(j.get('title') or '', (j.get('location') or {}).get('name') or '') for j in r.json().get('jobs') or []]
    if ats == 'lever':
        r = requests.get('https://api.lever.co/v0/postings/%s' % token, params={'mode': 'json'}, headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise ValueError('not a board')
        return [(j.get('text') or '', ', '.join([(j.get('categories') or {}).get('location') or ''] + ((j.get('categories') or {}).get('allLocations') or []))) for j in data]
    if ats == 'ashby':
        r = requests.get('https://api.ashbyhq.com/posting-api/job-board/%s' % token, headers=UA, timeout=20)
        r.raise_for_status()
        return [(j.get('title') or '', ', '.join([j.get('location') or ''] + [s.get('location') or '' for s in j.get('secondaryLocations') or []])) for j in r.json().get('jobs') or []]
    if ats == 'smartrecruiters':
        r = requests.get('https://api.smartrecruiters.com/v1/companies/%s/postings' % token, params={'limit': 100}, headers=UA, timeout=20)
        r.raise_for_status()
        out = []
        for j in r.json().get('content') or []:
            loc = j.get('location') or {}
            out.append((j.get('name') or '', ', '.join(x for x in (loc.get('city') or '', loc.get('region') or '', loc.get('country') or '') if x)))
        return out
    raise ValueError(ats)


def relevant(title):
    return C.board_relevant(title)                  # the rule of the sync (a course role / track or one of the job categories; no plant, driving, freelance ...)


def india(location):
    return F.is_india(location, '') or bool(re.search(r'\bindia\b|\b(?:in)\b', location or '', re.I))


def main(args):
    pairs = [a.split(':', 1) for a in args] if args else [(ats, t) for ats, tokens in CANDIDATES.items() for t in tokens]
    found = []
    for ats, token in pairs:
        try:
            jobs = jobs_of(ats, token)
        except Exception as exc:
            print('%-16s %-32s -> no board (%s)' % (ats, token, exc.__class__.__name__))
            continue
        ind = [(t, l) for t, l in jobs if india(l)]
        rel = [(t, l) for t, l in ind if relevant(t)]
        print('%-16s %-32s -> %4d jobs | %3d in India | %3d fit the courses  %s' % (ats, token, len(jobs), len(ind), len(rel), '; '.join(t for t, _l in rel[:3])[:110]))
        if rel:
            found.append({'ats': ats, 'token': token, 'jobs': len(jobs), 'india': len(ind), 'relevant': len(rel)})
        time.sleep(0.2)
    out = os.path.join(os.environ.get('TEMP', '.'), 'llmd_company_boards.json')
    json.dump(found, open(out, 'w'), indent=1)
    print('\nboards with jobs in India that fit the courses: %d -> %s' % (len(found), out))


if __name__ == '__main__':
    main(sys.argv[1:])
