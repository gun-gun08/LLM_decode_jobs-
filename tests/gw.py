"""Helper for talking to Odoo: the LOCAL dev instance (XML-RPC) or the live site (MCP gateway).

  LOCAL (safe):  ODOO_URL=http://127.0.0.1:8070  ODOO_DB=llmd_local  ODOO_USER=admin  ODOO_PASSWORD=<local admin password>
  LIVE:          MCP_KEY=<gateway key>      reading is always possible; WRITING to the live site is refused unless ALLOW_PRODUCTION=yes

Nothing here ever stores a key or a password: they are read from environment variables only.
"""
import json
import os
import sys
import urllib.request
import xmlrpc.client
from urllib.parse import urlparse

LIVE_URL = 'https://learn.llmdecode.com'
GATEWAY = os.environ.get('MCP_URL', LIVE_URL + '/mcp_gateway')
WRITE_TOOLS = {'create_record', 'update_record', 'delete_record', 'unlink_record', 'call_method'}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
_xml = {}


def site_url():
    """The website the page checks run against (the local instance when ODOO_URL is set, the live site otherwise)."""
    return os.environ.get('ODOO_URL', LIVE_URL).rstrip('/')


def is_local():
    return bool(os.environ.get('ODOO_URL')) and (urlparse(site_url()).hostname or '') in LOCAL_HOSTS


def target_name():
    return 'LOCAL ' + site_url() if is_local() else 'LIVE ' + site_url()


def _guard(tool):
    if tool in WRITE_TOOLS and not is_local() and os.environ.get('ALLOW_PRODUCTION') != 'yes':
        sys.exit('REFUSED: %s would WRITE to %s.\nPoint ODOO_URL at the local instance, or (only after your approval) set ALLOW_PRODUCTION=yes.' % (tool, target_name()))


def _rpc():
    if 'uid' not in _xml:
        for var in ('ODOO_DB', 'ODOO_USER', 'ODOO_PASSWORD'):
            if not os.environ.get(var):
                sys.exit('Set the %s environment variable first.' % var)
        url = site_url()
        common = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/common', allow_none=True)
        uid = common.authenticate(os.environ['ODOO_DB'], os.environ['ODOO_USER'], os.environ['ODOO_PASSWORD'], {})
        if not uid:
            sys.exit('Login to %s failed (database / user / password).' % url)
        _xml['uid'] = uid
        _xml['models'] = xmlrpc.client.ServerProxy(url + '/xmlrpc/2/object', allow_none=True)
    return _xml['models'], _xml['uid']


def _local_call(tool, a):
    models, uid = _rpc()

    def run(model, method, args, kw=None):
        return models.execute_kw(os.environ['ODOO_DB'], uid, os.environ['ODOO_PASSWORD'], model, method, args, kw or {})

    if tool == 'search_records':
        return run(a['model'], 'search_read', [a.get('domain') or []], {'limit': a.get('limit', 200)})
    if tool == 'create_record':
        new_id = run(a['model'], 'create', [a['values']])
        return {'id': new_id, 'display_name': ''}
    if tool == 'update_record':
        return run(a['model'], 'write', [[a['res_id']], a['values']])
    if tool == 'delete_record':
        return run(a['model'], 'unlink', [[a['res_id']]])
    if tool == 'call_method':                      # call_method(model, ids, method): runs a public method of the model (local instance only)
        return run(a['model'], a['method'], [a['ids']] if a.get('ids') is not None else [])      # ids=None: a model-level method (@api.model)
    raise RuntimeError('tool %s is not supported on the local backend' % tool)


def call(tool, **arguments):
    _guard(tool)
    if os.environ.get('ODOO_URL'):
        return _local_call(tool, arguments)
    key = os.environ.get('MCP_KEY')
    if not key:
        sys.exit('Set ODOO_URL (local instance) or MCP_KEY (live gateway) first.')
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}}).encode()
    req = urllib.request.Request(GATEWAY, body, {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode())
    if 'error' in out:
        raise RuntimeError('%s failed: %s' % (tool, out['error']))
    text = out['result']['content'][0]['text']
    try:
        return json.loads(text)
    except ValueError:
        return text


def search(model, domain=None, limit=200):
    res = call('search_records', model=model, domain=domain or [], limit=limit)
    if not isinstance(res, list):
        raise RuntimeError('search %s: %r' % (model, res))
    return res
