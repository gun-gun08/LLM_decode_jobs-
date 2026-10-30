// The Job Applications form in the Odoo backend, in a real browser (headless Chrome, DevTools protocol, Node 22+), against the LOCAL instance:
//   - no blue (alert-info) banner on any record;
//   - every field row shown has a value, and every field with a value is shown (compared with the database, read through JSON-RPC as the same user);
//     a value of only spaces counts as empty;
//   - the status bar and the Confirm / Withdraw / Back to Received buttons are still there;
//   - no Application Date anywhere on the form; Job Type always shown: its value, or "Not specified" when there is none.
// It signs in with ODOO_USER / ODOO_PASSWORD of .env (never printed). Only reads, except one TEMPORARY record with an all-spaces field, removed at the end.
//
//   . .\scripts\env.ps1
//   node tests\application_form_test.mjs
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const SITE = (process.env.ODOO_URL || '').replace(/\/$/, '');
if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(SITE) || !process.env.ODOO_USER || !process.env.ODOO_PASSWORD) {
    console.error('application_form_test runs against the LOCAL instance only: . .\\scripts\\env.ps1 first.');
    process.exit(2);
}
const CHROME = process.env.CHROME || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const PORT = 9300 + Math.floor(Math.random() * 500);
const FIELDS = ['applicant_name', 'email', 'resume_count', 'application_type', 'channel', 'clicked_at', 'click_count', 'confirmed_date',
    'confirmed_via', 'provider_ref', 'job_title', 'company', 'department', 'experience_required', 'location', 'posted_type', 'internal_job_id', 'ext_id',
    'source', 'apply_url', 'message'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(label, ok, detail = '') {
    results.push(!!ok);
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${ok ? '' : ' - ' + JSON.stringify(detail).slice(0, 600)}`);
}

const profile = mkdtempSync(join(tmpdir(), 'llmd-form-'));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--headless=new', '--no-first-run', '--window-size=1400,1000', 'about:blank'], { stdio: 'ignore' });
let ws, seq = 0;
const waiting = new Map();
const errors = [];
for (let i = 0; i < 80 && !ws; i++) {
    try {
        const page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === 'page');
        if (page) {
            ws = new WebSocket(page.webSocketDebuggerUrl);
            await new Promise((ok) => { ws.onopen = ok; });
            ws.onmessage = (m) => {
                const x = JSON.parse(m.data);
                if (x.id && waiting.has(x.id)) { waiting.get(x.id)(x); waiting.delete(x.id); }
                else if (x.method === 'Runtime.exceptionThrown') errors.push(x.params.exceptionDetails.exception?.description || x.params.exceptionDetails.text);
            };
        }
    } catch (e) { /* starting */ }
    if (!ws) await sleep(250);
}
const send = (method, params = {}) => { const id = ++seq; ws.send(JSON.stringify({ id, method, params })); return new Promise((ok) => waiting.set(id, ok)); };
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })).result?.result?.value;
async function waitFor(expr, ms = 30000) {
    for (let t = 0; t < ms; t += 200) { try { if (await evaluate(expr)) return true; } catch (e) { /* loading */ } await sleep(200); }
    return false;
}
// JSON-RPC in the signed-in page (same session, same user as the form)
const rpc = (model, method, args, kwargs = {}) => evaluate(`fetch('/web/dataset/call_kw', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {model: ${JSON.stringify(model)}, method: ${JSON.stringify(method)}, args: ${JSON.stringify(args)}, kwargs: ${JSON.stringify(kwargs)}}})})
    .then(r => r.json()).then(r => r.error ? {error: r.error.data && r.error.data.message || r.error.message} : r.result)`);

let tmpId = null;
try {
    await send('Page.enable'); await send('Runtime.enable');
    // sign in through Odoo's own login form
    await send('Page.navigate', { url: SITE + '/web/login' });
    await waitFor(`!!document.querySelector('input[name=login]')`);
    await evaluate(`(() => { const f = document.querySelector('form.oe_login_form'); f.login.value = ${JSON.stringify(process.env.ODOO_USER)}; f.password.value = ${JSON.stringify(process.env.ODOO_PASSWORD)}; f.submit(); return 1; })()`);
    const signed = await waitFor(`location.pathname.startsWith('/odoo') && !!document.querySelector('.o_main_navbar')`, 40000);
    check('signed in to the Odoo backend (login form)', signed);

    // one TEMPORARY record whose department / job type are only spaces and whose provider reference is set: spaces = empty, a value = shown
    const base = (await rpc('llmd.job.application', 'search_read', [[['channel', '=', 'apply_now']]], { fields: ['job_key', 'job_title', 'listing_id'], limit: 1 }))[0];
    const made = await rpc('llmd.job.application', 'create', [{ job_title: 'ZZ Form Test Job', job_key: 'zz-form-test:' + Date.now(), identity_key: 'e:zz.form.test@example.com',
        applicant_name: 'ZZ Form Test', email: 'zz.form.test@example.com', department: '   ', job_type: ' \t ', provider_ref: 'zz-ref-7', channel: 'recruiter', state: 'submitted' }]);
    tmpId = typeof made === 'number' ? made : null;
    check('a temporary record with all-spaces fields is made (for this test only)', !!tmpId, made);

    const recs = await rpc('llmd.job.application', 'search_read', [[['active', 'in', [true, false]]]], { fields: FIELDS.concat(['state', 'llmd_blank', 'job_type']), order: 'id' });
    check(`${recs.length} Job Applications records to check (populated and empty fields, every status)`, Array.isArray(recs) && recs.length > 0, recs);
    const blankValue = (v) => v === false || v === null || v === 0 || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && !v.length);
    for (const rec of recs) {
        await send('Page.navigate', { url: `${SITE}/odoo/action-llmd_job_aggregator.llmd_job_application_action/${rec.id}` });
        const ok = await waitFor(`!!document.querySelector('.o_form_view .o_form_sheet') && !document.querySelector('.o_form_view .o_form_sheet_bg .o_loading')`);
        await sleep(400);
        if (!ok) { check(`record ${rec.id}: the form opens`, false); continue; }
        const shown = await evaluate(`(() => {
            const out = {};
            for (const name of ${JSON.stringify(FIELDS)}) {
                const w = document.querySelector('.o_form_view .o_form_sheet .o_field_widget[name="' + name + '"]');
                const label = document.querySelector('.o_form_view .o_form_sheet label[for="' + name + '_0"]') || (w && w.closest('.o_inner_group') && [...w.closest('.o_inner_group').querySelectorAll('label')].find(l => l.getAttribute('for') && l.getAttribute('for').startsWith(name + '_')));
                const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
                out[name] = { widget: visible(w), label: visible(label), text: w ? (w.innerText || (w.querySelector('input,textarea') || {}).value || '').trim() : '' };
            }
            return out;
        })()`);
        const banner = await evaluate(`document.querySelectorAll('.o_form_view .alert-info').length`);
        const extra = await evaluate(`({ date: !!document.querySelector('.o_form_view .o_field_widget[name="application_date"]') || [...document.querySelectorAll('.o_form_view label')].some(l => /Application Date/i.test(l.innerText)),
            user: !!document.querySelector('.o_form_view .o_field_widget[name="user_id"]') || [...document.querySelectorAll('.o_form_view .o_inner_group label')].some(l => /^User\b/.test(l.innerText.trim())),
            statuses: [...document.querySelectorAll('.o_form_view .o_statusbar_status button, .o_form_view .o_statusbar_status .o_arrow_button')].map(b => b.innerText.trim()).filter(Boolean),
            jobType: (document.querySelector('.o_form_view .o_field_widget[name="job_type_label"]') || {}).innerText })`);
        const wantType = (rec.job_type || '').trim() || 'Not specified';
        check(`record ${rec.id}: no Application Date and no User on the form (Applicant Name only); Job Type shows "${wantType}"`, !extra.date && !extra.user && (extra.jobType || '').trim() === wantType, extra);
        check(`record ${rec.id}: status "${rec.state === 'submitted' ? 'Received' : rec.state}"; the status bar is Received -> Confirmed only`,
            ['submitted', 'confirmed', 'withdrawn', 'reported'].includes(rec.state) && extra.statuses.join('|').replace(/\s+/g, ' ') .includes('Received') && !extra.statuses.some(t => /Redirected|Apply Clicked/.test(t)), extra.statuses);
        const ctrl = await evaluate(`({ statusbar: !!document.querySelector('.o_form_view .o_statusbar_status'), buttons: [...document.querySelectorAll('.o_form_view .o_statusbar_buttons button')].map(b => b.getAttribute('name')) })`);
        const wrongHidden = FIELDS.filter((f) => !blankValue(rec[f]) && !shown[f].widget);
        const wrongShown = FIELDS.filter((f) => blankValue(rec[f]) && (shown[f].widget || shown[f].label));
        const emptyCount = FIELDS.filter((f) => blankValue(rec[f])).length;
        check(`record ${rec.id} (${rec.state}, ${emptyCount} empty fields): no blue banner; every empty field row hidden (label too), every value shown`,
            banner === 0 && !wrongHidden.length && !wrongShown.length, { banner, wrongHidden, wrongShown });
        const expected = { confirmed: ['action_withdraw', 'action_receive'], withdrawn: ['action_receive'], submitted: ['action_confirm', 'action_withdraw'] }[rec.state] || ['action_confirm', 'action_withdraw', 'action_receive'];
        check(`record ${rec.id}: status bar and the buttons of its status (${expected.join(', ')})`, ctrl.statusbar && expected.every((b) => ctrl.buttons.includes(b)), ctrl);
        if (rec.id === tmpId) {
            check('... the all-spaces Department row is hidden, the all-spaces Job Type says "Not specified"; the Provider reference (a value) is shown', !shown.department.widget && shown.provider_ref.widget && shown.provider_ref.text === 'zz-ref-7', shown);
        }
    }
    const db = await rpc('llmd.job.application', 'read', [[tmpId], ['department', 'job_type']]);
    check('the database values are unchanged (spaces stay spaces: nothing is filled in or cleaned)', db && db[0] && db[0].department === '   ' && db[0].job_type === ' \t ', db);
    check(`no JavaScript errors in the backend (${errors.length})`, errors.length === 0, errors.slice(0, 3));
} catch (e) {
    check('the test ran to the end', false, e.message);
} finally {
    if (tmpId) {
        const r = await rpc('llmd.job.application', 'unlink', [[tmpId]]);
        console.log('cleanup: temporary record removed:', r === true);
    }
    try { ws.close(); } catch (e) { /* closing */ }
    chrome.kill();
    await sleep(400);
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* in use */ }
}
const passed = results.filter(Boolean).length;
console.log(`\nRESULT: ${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 1);
