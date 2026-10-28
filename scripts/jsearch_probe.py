r"""One real JSearch request with the key in .env (package root) (the key is never printed): does the key work, and where do the apply links go?

    python scripts\jsearch_probe.py ["data analyst"]
"""
import collections
import io
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'odoo_addons', 'llmd_job_aggregator', 'models'))
import requests  # noqa: E402
import sources as S  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
env = dict(l.strip().split('=', 1) for l in io.open(os.path.join(HERE, '..', '.env'), encoding='utf-8') if '=' in l and not l.lstrip().startswith('#'))
key, base = env.get('JSEARCH_API_KEY', '').strip(), env.get('JSEARCH_BASE_URL', '').strip()
query = sys.argv[1] if len(sys.argv) > 1 else 'data analyst'
print('endpoint:', base or S.JSEARCH_URL, '| key set:', bool(key))

# the raw answer once (to see the apply options), then the adapter on the same query
url = base or S.JSEARCH_URL
headers = dict(S.UA)
if 'rapidapi' in url:
    headers.update({'X-RapidAPI-Key': key, 'X-RapidAPI-Host': urlparse(url).netloc})
else:
    headers['x-api-key'] = key
resp = requests.get(url, params={'query': '%s in India' % query, 'page': 1, 'num_pages': 1, 'country': 'in', 'date_posted': 'month'}, headers=headers, timeout=40)
print('HTTP', resp.status_code)
if resp.status_code != 200:
    print('answer:', resp.text[:300].replace(key, '***'))
    sys.exit(1)
data = resp.json().get('data') or []
print('jobs in the answer:', len(data))
hosts = collections.Counter()
direct = 0
for j in data:
    opts = [o for o in (j.get('apply_options') or []) if isinstance(o, dict) and o.get('apply_link')]
    direct += any(o.get('is_direct') for o in opts)
    for o in opts:
        hosts[(urlparse(o['apply_link']).hostname or '').replace('www.', '')] += 1
print('jobs with an option marked is_direct:', direct)
print('apply option sites:', dict(hosts.most_common(12)))
for j in data[:6]:
    print('  - %s | %s | publisher %s | job_apply_link -> %s' % (j.get('job_title', '')[:45], j.get('employer_name', '')[:25], j.get('job_publisher'), (urlparse(j.get('job_apply_link') or '').hostname or '')))
