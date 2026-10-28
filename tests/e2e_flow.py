r"""END-TO-END test of the whole flow against the LOCAL instance and the REAL job API (no fake jobs):

   third-party API -> Odoo (llmd.job.listing) -> local Jobs page -> job details -> Apply Now -> the click is saved in Odoo (Apply Clicks) -> straight to the employer's application page
   and (optional, llmd_agg.apply_mode = form): our form -> applicant + resume + record in Odoo; applicant data from a provider only through the API key.

  . .\scripts\env.ps1
  python tests\e2e_flow.py            runs the flow, prints every step, removes the test applicant, click lines and test records it made (use --keep to keep the click lines)

It needs at least one connected source: the company job boards need no key (with the default "direct links only" Jooble, Adzuna and Himalayas are not asked).
"""
import base64
import calendar
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request

import board_test as T  # the helpers of the board test (HTTP visitor, text(), ...); importing it does not run it
import gw

sys.stdout.reconfigure(encoding='utf-8')
KEEP = '--keep' in sys.argv
RESULTS = []


def step(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' - ' + str(detail)) if detail else ''))
    return ok


def rpc(model, method, args, kw=None):
    models, uid = gw._rpc()
    return models.execute_kw(gw.os.environ['ODOO_DB'], uid, gw.os.environ['ODOO_PASSWORD'], model, method, args, kw or {})


def jsonrpc(path, params, headers=None):
    body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params}).encode()
    req = urllib.request.Request(gw.site_url() + path, body, {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0', **(headers or {})})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    except urllib.error.HTTPError as exc:
        return {'http_error': exc.code}


def main():
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    print('target:', gw.target_name())
    print('\n=== 1. FETCH from the third-party API(s) and SAVE in Odoo ===')
    stats = gw.call('call_method', model='llmd.job.listing', ids=None, method='fetch_now')
    srcs = {s['name']: s for s in gw.search('llmd.job.source', [], 20)}
    working = [n for n, s in srcs.items() if s['last_status'] == 'ok' and s['last_count'] > 0 and n != 'Himalayas']
    step('a real third-party API answered and delivered jobs', bool(working), {n: (s['last_status'], s['last_count']) for n, s in srcs.items() if s['last_status'] != 'not_configured'})
    after = gw.search('llmd.job.listing', [['active', 'in', [True, False]]], 50000)
    fresh = [r for r in after if r['fetched_at'] and r['fetched_at'] >= started]
    step('jobs were created or updated in the Odoo database by this sync', len(fresh) > 0, '%d created, %d updated, %d hidden' % (stats['created'], stats['updated'], stats['hidden']))
    step('no job is stored twice: (source, external job ID) is unique and so is the title+company+place key', len({(r['source'], r['ext_id']) for r in after}) == len(after) and
         len({r['dedupe_key'] for r in after if r['active']}) == len([r for r in after if r['active']]))
    log = gw.search('llmd.job.sync', [], 1)[0]
    step('the run is written to the sync log (Recruitment > Job board > Sync runs)', log['created'] == stats['created'] and log['updated'] == stats['updated'] and log['started'] >= started, (log['state'], log['trigger']))
    second = gw.call('call_method', model='llmd.job.listing', ids=None, method='fetch_now')
    step('running the sync again creates no duplicates (the same jobs are only updated)', second['created'] <= max(2, stats['created']) and second['duplicates_removed'] >= 0 and
         len({(r['source'], r['ext_id']) for r in gw.search('llmd.job.listing', [['active', 'in', [True, False]]], 50000)}) == len(gw.search('llmd.job.listing', [['active', 'in', [True, False]]], 50000)), second)
    job = next(r for r in sorted(fresh, key=lambda r: r['id']) if r['active'] and r['apply_url'] and r['source'] in working and r['title'] and r['company'])
    job = gw.search('llmd.job.listing', [['id', '=', job['id']]], 1)[0]                       # as it is stored NOW (a sync rewrites the apply URL: Jooble puts the search into it)
    print('\n  the job used for the rest of the test (real, from %s): #%d "%s" at %s, %s' % ('a third-party API', job['id'], job['title'], job['company'], job['location']))
    step('it was stored with title, company, location, description, apply URL, source and external ID', all(job[k] for k in ('title', 'company', 'location', 'description_html', 'apply_url', 'source', 'ext_id')),
         {k: (str(job[k])[:40]) for k in ('ext_id', 'source', 'salary', 'apply_url')})
    job_key = 'ext:%s:%s' % (job['source'], job['ext_id'])
    click0 = max([0] + [c['id'] for c in gw.search('llmd.job.click', [], 20000)])                 # the click lines of this run are the ones after this id
    n_apps0 = len(gw.search('llmd.job.application', [['active', 'in', [True, False]]], 5000))
    n_hr0 = len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000))

    def clicks(**dom):
        return sorted(gw.search('llmd.job.click', [[k, '=', v] for k, v in dom.items()] + [['id', '>', click0]], 500), key=lambda c: c['id'])

    pid = None
    pid_form = None
    try:
        print('\n=== 2. DISPLAY on the local Jobs page (read from Odoo) and open the DETAILS ===')
        board = T.get('/jobs?q=' + re.sub(r'[^A-Za-z0-9 ]+', ' ', job['title'])[:40].strip().replace(' ', '+'))
        cards = T.cards(board[1])
        step('the Jobs page lists the stored job (found by searching its title)', any(c['id'] == job['id'] for c in cards), '%d cards' % len(cards))
        card = next((c for c in cards if c['id'] == job['id']), None)
        step('its card shows title, company, location, View Details and Apply Now (the tracked link of this job), and no site name', bool(card) and job['title'] in card['text'] and job['company'] in card['text']
             and 'View Details' in card['text'] and card['apply'] == '/jobs/ext/%d/go' % job['id'] and not T.PLATFORM.search(card['text'].replace(job['company'], '').replace(job['title'], '')))
        status, page = T.get(card['see']) if card else (0, '')
        step('View Details opens the details page of that job', status == 200 and job['title'] in T.text(page) and job['company'] in T.text(page), card['see'] if card else '')
        tags = re.findall(r'<a\s[^>]*o_llmd_apply[^>]*>', page)
        region = (re.search(r'<div class="o_llmd_view">.*?</aside>', page, re.S) or [''])[0]
        step("the details page has ONE Apply Now: the tracked link that goes straight to the employer's application page (no form)",
             len(re.findall(r'>\s*Apply Now', page)) == 1 and len(tags) == 1 and '/jobs/ext/%d/go' % job['id'] in tags[0] and bool(region) and '<form' not in region and '/apply' not in region)
        step('the form, the report and the confirmation page answer 404 (no form by default)', all(T.get('/jobs/ext/%d/%s' % (job['id'], x))[0] == 404 for x in ('apply', 'report', 'applied')))
        step('the visitor never sees the original apply URL or a job site name on the page', job['apply_url'] not in html.unescape(page) and not T.PLATFORM.search(T.text(page)))

        print('\n=== 3. (optional) form mode - llmd_agg.apply_mode = form: our form saves the applicant in Odoo Recruitment before "received" is shown ===')
        pid_form = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.apply_mode', 'value': 'form'})['id']
        email = 'e2e.test+%d@example.com' % int(time.time())
        form = {'name': 'E2E Test Applicant', 'email': email, 'phone': '+91 98765 43210', 'note': 'End-to-end test of the local flow.', 'consent': '1'}
        apply_path = '/jobs/ext/%d/apply' % job['id']
        fv = T.Visitor()
        status, fpage, _ = fv.open(apply_path)
        step('the form opens: name, e-mail, resume (optional), message, consent - no phone field', status == 200 and job['title'] in T.text(fpage) and all(x in fpage for x in ('name="name"', 'name="email"', 'name="resume"', 'name="consent"'))
             and 'name="phone"' not in fpage)
        status, perr, _ = fv.post_form(apply_path, {'name': '', 'email': 'bad'})
        step('wrong data is answered with the field errors and nothing is saved', status == 400 and 'valid email' in T.text(perr) and not gw.search('hr.applicant', [['partner_name', '=', 'E2E Test Applicant']], 2))
        status, _b, ploc = fv.post_form(apply_path, form, {'resume': ('E2E Resume.pdf', T.TEST_PDF)})
        rec = (gw.search('llmd.job.application', [['email', '=', email]], 5) or [{}])[0]
        step('the form was accepted and redirected to the confirmation only after saving', status == 303 and bool(rec) and re.match(r'.*/jobs/ext/%d/applied\?ref=%d&t=[0-9a-f]{32}$' % (job['id'], rec['id']), ploc) is not None, ploc)
        applicant = (gw.search('hr.applicant', [['id', '=', rec['applicant_id'][0]]], 1) or [{}])[0] if rec.get('applicant_id') else {}
        step('Odoo Recruitment has the applicant: name, e-mail, no phone (the form has none), stage "New", active, under an unpublished position made for this job',
             (applicant.get('partner_name'), applicant.get('email_from'), applicant.get('partner_phone')) == ('E2E Test Applicant', email, False) and applicant.get('active') and applicant['stage_id'][1] == 'New' and bool(applicant.get('job_id'))
             and gw.search('hr.job', [['id', '=', applicant['job_id'][0]]], 1)[0]['llmd_listing_id'][0] == job['id'])
        atts = gw.search('ir.attachment', [['res_model', '=', 'hr.applicant'], ['res_id', '=', applicant.get('id', 0)]], 3)
        step('the resume is attached to the applicant, byte for byte', len(atts) == 1 and atts[0]['name'] == 'E2E Resume.pdf' and base64.b64decode(atts[0]['datas']) == T.TEST_PDF)
        step('Recruitment > Job Applications shows it: applicant name, e-mail, (no phone), job title, company, external job ID, source, channel "Our website", status Received, application date',
             (rec.get('applicant_name'), rec.get('email'), 'phone' in rec, rec.get('job_title'), rec.get('company'), rec.get('ext_id'), rec.get('source'), rec.get('channel'), rec.get('state')) ==
             ('E2E Test Applicant', email, False, job['title'], job['company'], job['ext_id'], job['source'], 'own', 'submitted') and bool(rec.get('application_date')) and rec.get('apply_url') == job['apply_url'])
        status, cpage, _ = fv.open(ploc)
        step('the confirmation page says "received" with the reference number', status == 200 and 'Your application was received' in T.text(cpage) and '#%d' % rec['id'] in T.text(cpage))
        status, _b, ploc2 = fv.post_form(apply_path, form, {})
        step('applying again with the same e-mail creates NO duplicate', status == 303 and 'again=1' in ploc2 and len(gw.search('llmd.job.application', [['email', '=', email]], 5)) == 1
             and len(gw.search('hr.applicant', [['email_from', '=', email]], 5)) == 1)
        n_apps_form = len(gw.search('llmd.job.application', [['active', 'in', [True, False]]], 5000))
        n_hr_form = len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000))
        gw.call('delete_record', model='ir.config_parameter', res_id=pid_form)
        pid_form = None
        step('without the parameter (the default) the form is off again', T.get(apply_path)[0] == 404)

        print("\n=== 4. Apply Now (default): the click is SAVED in Odoo, then the visitor goes straight to the original application page ===")
        visitor = T.Visitor()
        status, _b, loc = visitor.open('/jobs/ext/%d/go' % job['id'])
        step('Apply Now redirects (303) to the job\'s own application URL, the one stored in Odoo', status == 303 and loc == job['apply_url'], loc[:70])
        cl = clicks(job_key=job_key)
        c = cl[0] if cl else {}
        step('the click is in Odoo: job title, company, source, external job ID, apply URL and status "clicked"',
             len(cl) == 1 and (c['job_title'], c['company'], c['source'], c['ext_id'], c['apply_url'], c['status']) == (job['title'], job['company'], job['source'], job['ext_id'], job['apply_url'], 'clicked'), c and c['status'])
        age = time.time() - calendar.timegm(time.strptime(c['clicked_at'], '%Y-%m-%d %H:%M:%S')) if c else 9999
        step('... with the time stamp of the click', -5 < age < 120, '%s UTC' % (c and c['clicked_at']))
        step('... linked to the job listing, not a repeat click', bool(c) and c['listing_id'][0] == job['id'] and not c['repeat'])
        step('the click is NOT an application: no applicant in Recruitment, nothing new in Job Applications, and the anonymous click names nobody',
             len(gw.search('hr.applicant', [['active', 'in', [True, False]]], 5000)) == n_hr_form and len(gw.search('llmd.job.application', [['active', 'in', [True, False]]], 5000)) == n_apps_form and bool(c)
             and 'applicant_id' not in c and not (c.get('user_id') or c.get('applicant_name') or c.get('email') or c.get('phone')))
        visitor.open('/jobs/ext/%d/go' % job['id'])
        cl = clicks(job_key=job_key)
        step('the same visitor clicking again is saved as another line (every click is saved) and marked as a repeat', len(cl) == 2 and cl[1]['repeat'] and not cl[0]['repeat'])
        bot = urllib.request.Request(gw.site_url() + '/jobs/ext/%d/go' % job['id'], headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'})
        try:
            urllib.request.build_opener(T._NoRedirect()).open(bot, timeout=30)
        except urllib.error.HTTPError as exc:
            bot_status = exc.code
        step('a crawler is sent on but not counted as a click', bot_status == 303 and len(clicks(job_key=job_key)) == 2)

        print('\n=== 5. What a recruiter sees in the Odoo backend ===')
        views = rpc('llmd.job.click', 'get_views', [[[False, 'list'], [False, 'form'], [False, 'search'], [False, 'pivot'], [False, 'graph']]])
        step('Recruitment > Apply Clicks: list, form, search, pivot and graph views are available', all(k in views['views'] for k in ('list', 'form', 'search', 'pivot', 'graph')))
        menu = gw.search('ir.ui.menu', [['name', '=', 'Apply Clicks']], 3)
        step('the menu "Apply Clicks" exists under Recruitment', len(menu) == 1 and menu[0]['complete_name'].startswith('Recruitment'), menu and menu[0]['complete_name'])
        found = gw.search('llmd.job.click', [['job_title', 'ilike', job['title'][:12]], ['company', '=', job['company']], ['source', '=', job['source']], ['ext_id', '=', job['ext_id']], ['status', '=', 'clicked'],
                                              ['clicked_at', '>=', started]], 10)
        step('searching by job title, company, source, external job ID, status and date finds the two clicks', len(found) == 2)
        groups = rpc('llmd.job.click', 'read_group', [[['id', 'in', [x['id'] for x in cl]]], ['status'], ['status']])
        step('grouping by status works (what the pivot and the graph use)', groups and groups[0]['status'] == 'clicked' and groups[0]['status_count'] == 2)

        print('\n=== 6. Applicant data from an external portal: only from an authorized provider integration (API key) ===')
        ref = {'source': job['source'], 'ext_id': job['ext_id']}
        api_mail = 'e2e.provider+%d@example.com' % int(time.time())
        body = {'action': 'applicant', 'job': ref, 'name': 'E2E Provider Applicant', 'email': api_mail, 'provider_ref': 'e2e-1'}
        r = jsonrpc('/api/llmd/applications', body)
        step('without the API key nothing is accepted (not even what a provider would send)', r['result']['error'] == 'unauthorized' and not gw.search('llmd.job.application', [['email', '=', api_mail]], 2))
        r = jsonrpc('/api/llmd/applications', dict(body, action='submit', consent=True))
        step('the old public "submit" (an applicant typed into a form) does not exist any more', r['result']['error'] == 'unauthorized')
        pid = gw.call('create_record', model='ir.config_parameter', values={'key': 'llmd_agg.application_api_key', 'value': 'e2e-key-%d' % int(time.time())})['id']
        key = gw.search('ir.config_parameter', [['id', '=', pid]], 1)[0]['value']
        r = jsonrpc('/api/llmd/applications', dict(body, name='', email='bad'), {'X-Api-Key': key})
        step('with the key, invalid data is answered with the field errors and nothing is saved', r['result']['error'] == 'validation' and {'name', 'email'} <= set(r['result']['fields']), r['result'].get('fields'))
        r = jsonrpc('/api/llmd/applications', body, {'X-Api-Key': key})
        rec = (gw.search('llmd.job.application', [['email', '=', api_mail]], 2) or [{}])[0]
        step('with the key the applicant is saved exactly as sent: confirmed, channel "provider", provider reference, job snapshot - the phone that was not sent stays empty',
             r['result']['ok'] and rec.get('state') == 'confirmed' and rec.get('channel') == 'provider' and rec.get('provider_ref') == 'e2e-1' and not rec.get('phone')
             and (rec.get('job_title'), rec.get('ext_id'), rec.get('apply_url')) == (job['title'], job['ext_id'], job['apply_url']), r['result'])
        step('... it creates no Odoo applicant and no click line', not rec.get('applicant_id') and len(clicks(job_key=job_key)) == 2)
        menu = gw.search('ir.ui.menu', [['name', '=', 'Job Applications']], 3)
        step('the applicant is in Recruitment > Job Applications (list, form, search, kanban, pivot, graph)', len(menu) == 1 and rec.get('id') and all(
            k in rpc('llmd.job.application', 'get_views', [[[False, 'list'], [False, 'form'], [False, 'search'], [False, 'kanban'], [False, 'pivot'], [False, 'graph']]])['views'] for k in ('list', 'form', 'search', 'kanban', 'pivot', 'graph')))
    finally:
        print('\n=== cleanup ===')
        if pid_form:
            gw.call('delete_record', model='ir.config_parameter', res_id=pid_form)
        if pid:
            gw.call('delete_record', model='ir.config_parameter', res_id=pid)
        for a in gw.search('hr.applicant', [['partner_name', '=', 'E2E Test Applicant'], ['active', 'in', [True, False]]], 10):
            gw.call('delete_record', model='hr.applicant', res_id=a['id'])
        for a in gw.search('llmd.job.application', ['|', ['email', 'like', 'e2e.provider'], ['applicant_name', '=', 'E2E Test Applicant'], ['active', 'in', [True, False]]], 10):
            gw.call('delete_record', model='llmd.job.application', res_id=a['id'])
        for pos in gw.search('hr.job', [['llmd_listing_id', '=', job['id']], ['active', 'in', [True, False]]], 5):
            gw.call('delete_record', model='hr.job', res_id=pos['id'])
        if KEEP:
            print('  --keep: the click lines of this run were kept in Odoo (Recruitment > Apply Clicks)')
        else:
            ids = [c['id'] for c in gw.search('llmd.job.click', [['id', '>', click0]], 20000)]
            if ids:
                rpc('llmd.job.click', 'unlink', [ids])
            step('the click lines of this run are removed again (the real job stays)', not gw.search('llmd.job.click', [['id', '>', click0]], 3))
        step('the test applicant, resume, record and position of this run are removed again (nothing invented stays in the list)', not gw.search('hr.applicant', [['partner_name', '=', 'E2E Test Applicant']], 3)
             and not gw.search('llmd.job.application', ['|', ['email', 'like', 'e2e.provider'], ['applicant_name', '=', 'E2E Test Applicant']], 3) and not gw.search('hr.job', [['llmd_listing_id', '=', job['id']]], 3))
    print('\nE2E RESULT: %d/%d steps passed' % (sum(RESULTS), len(RESULTS)))
    print('URLs: Jobs page http://127.0.0.1:8070/jobs | this job http://127.0.0.1:8070/jobs/ext/%d | Apply Clicks http://127.0.0.1:8070/odoo/action-llmd_job_aggregator.llmd_job_click_action' % job['id'])


if __name__ == '__main__':
    main()
