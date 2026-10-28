"""Seed the LOCAL database so it looks like the live recruitment setup: the company address and the four jobs of the live site.
Run by setup.ps1 (needs ODOO_URL / ODOO_DB / ODOO_USER / ODOO_PASSWORD from .env). Refuses to run against anything but localhost.
"""
import os
import sys
import xmlrpc.client

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tests'))
import gw  # noqa: E402

if not gw.is_local():
    sys.exit('seed_local.py only runs against the local instance (set ODOO_URL=http://127.0.0.1:<port>).')

url, db, user, password = gw.site_url(), os.environ['ODOO_DB'], os.environ['ODOO_USER'], os.environ['ODOO_PASSWORD']
common = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common')
if not common.authenticate(db, user, password, {}):          # a freshly initialised database has the password "admin": replace it with the one from .env
    uid = common.authenticate(db, user, 'admin', {})
    if not uid:
        sys.exit('Cannot log in to the local database with the .env password or the initial one.')
    xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object').execute_kw(db, uid, 'admin', 'res.users', 'write', [[uid], {'password': password}])
    print('local admin password set from .env')

India = gw.search('res.country', [['code', '=', 'IN']], 1)[0]['id']
company = gw.search('res.company', [], 1)[0]
gw.call('update_record', model='res.partner', res_id=company['partner_id'][0], values={'name': 'LLM Decode', 'city': 'Gurugram', 'country_id': India})
gw.call('update_record', model='res.company', res_id=company['id'], values={'name': 'LLM Decode'})
print('company address set: LLM Decode, Gurugram, India')

LIVE_JOBS = [('Sales manager', False), ('AiEngenner', False), ('Test', True), ('Mern Stack', False)]     # (title, published) exactly as on the live site
existing = {j['name'] for j in gw.search('hr.job', [['active', 'in', [True, False]]], 100)}
for title, published in LIVE_JOBS:
    if title in existing:
        continue
    new = gw.call('create_record', model='hr.job', values={'name': title})['id']
    if published:
        gw.call('update_record', model='hr.job', res_id=new, values={'website_published': True})
    print('job #%s %r created (published: %s)' % (new, title, published))
