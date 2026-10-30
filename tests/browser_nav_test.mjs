// Navigation of the LOCAL job board in a real browser (headless Chrome, DevTools protocol - Node 22+ has WebSocket built in, nothing to install):
// real clicks on cards, job pages, company / category / country / region / course pages, the menu, login, filters, pages, Back / Forward, Clear All, Load More,
// filter addresses written another way, old and wrong job addresses, a job that does not exist, Apply Now while logged out - and every console error,
// uncaught exception and failed request of every page on the way.
//
//   . .\scripts\env.ps1
//   node tests\browser_nav_test.mjs            (CHROME=path\to\chrome.exe if Chrome is somewhere else)
//
// It never logs in, never submits a form that saves anything and never follows Apply Now past the login page: nothing is stored in Odoo.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const SITE = (process.env.ODOO_URL || '').replace(/\/$/, '');
if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(SITE)) {
    console.error('browser_nav_test runs against the LOCAL instance only: set ODOO_URL (. .\\scripts\\env.ps1).');
    process.exit(2);
}
const CHROME = process.env.CHROME || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const PORT = 9300 + Math.floor(Math.random() * 500);
const results = [];
const problems = [];                 // console errors, exceptions, failed requests: [{page, text}]
let currentPage = '';

function check(label, ok, detail = '') {
    results.push(!!ok);
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${ok ? '' : ' - ' + JSON.stringify(detail).slice(0, 300)}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ Chrome + the DevTools protocol
const profile = mkdtempSync(join(tmpdir(), 'llmd-nav-'));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--headless=new', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--window-size=1366,900', 'about:blank'], { stdio: 'ignore' });
let ws;
let seq = 0;
const waiting = new Map();
const listeners = [];
let lastDocStatus = 0;

async function connect() {
    for (let i = 0; i < 60; i++) {
        try {
            const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
            const page = list.find((t) => t.type === 'page');
            if (page) {
                ws = new WebSocket(page.webSocketDebuggerUrl);
                await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
                ws.onmessage = (m) => {
                    const msg = JSON.parse(m.data);
                    if (msg.id && waiting.has(msg.id)) {
                        const { ok, bad } = waiting.get(msg.id);
                        waiting.delete(msg.id);
                        msg.error ? bad(new Error(msg.error.message)) : ok(msg.result);
                    } else if (msg.method) {
                        listeners.forEach((fn) => fn(msg));
                    }
                };
                return;
            }
        } catch (e) { /* Chrome is still starting */ }
        await sleep(250);
    }
    throw new Error('Chrome did not start');
}
function send(method, params = {}) {
    const id = ++seq;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((ok, bad) => waiting.set(id, { ok, bad }));
}
listeners.push((m) => {
    if (m.method === 'Runtime.exceptionThrown') {
        problems.push({ page: currentPage, text: 'exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text) });
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
        problems.push({ page: currentPage, text: 'console.error: ' + m.params.args.map((a) => a.value ?? a.description).join(' ') });
    } else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
        problems.push({ page: currentPage, text: `${m.params.entry.source}: ${m.params.entry.text} ${m.params.entry.url || ''}` });
    } else if (m.method === 'Network.responseReceived' && m.params.type === 'Document') {
        lastDocStatus = m.params.response.status;
    }
});

async function evaluate(expression) {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
        throw new Error('evaluate: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    }
    return r.result.value;
}
const href = () => evaluate('location.href');
const path = async () => { const u = new URL(await href()); return u.pathname + u.search; };

async function settled(changedFrom, timeout = 20000) {
    // the address changed (when `changedFrom` is given) and the new page finished loading
    const end = Date.now() + timeout;
    while (Date.now() < end) {
        try {
            const [url, state] = await evaluate('[location.href, document.readyState]');
            if ((changedFrom === undefined || url !== changedFrom) && state === 'complete') {
                currentPage = new URL(url).pathname + new URL(url).search;
                await sleep(300);                                   // late scripts / requests of the page
                return url;
            }
        } catch (e) { /* the page is being replaced */ }
        await sleep(100);
    }
    throw new Error('page did not load (from ' + changedFrom + ')');
}
async function go(p) {
    // a fresh load of `p` (through about:blank, so that a redirect back to the address already shown is seen as a load too)
    if ((await href()) !== 'about:blank') {
        await send('Page.navigate', { url: 'about:blank' });
        await settled(undefined);
        for (let i = 0; i < 50 && (await href()) !== 'about:blank'; i++) await sleep(50);
    }
    lastDocStatus = 0;
    await send('Page.navigate', { url: SITE + p });
    await settled('about:blank');
    return path();
}
async function click(selector) {
    const before = await href();
    const found = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null;
        el.removeAttribute('target'); const text = (el.textContent || '').trim(); const h = el.getAttribute('href'); el.click(); return {text, href: h}; })()`);
    if (!found) {
        throw new Error('nothing to click: ' + selector);
    }
    await settled(before);
    return found;
}
async function reload() {
    // a real refresh (F5) of the page shown: the same history entry, loaded again
    await evaluate('window.__llmdBeforeReload = 1');
    lastDocStatus = 0;
    await send('Page.reload', { ignoreCache: true });
    for (let i = 0; i < 200; i++) {
        await sleep(100);
        try {
            if ((await evaluate('window.__llmdBeforeReload === undefined && document.readyState === "complete"'))) break;
        } catch (e) { /* the page is being replaced */ }
    }
    await sleep(300);
    return path();
}
async function back() { const b = await href(); await evaluate('history.back()'); await settled(b); return path(); }
async function forward() { const b = await href(); await evaluate('history.forward()'); await settled(b); return path(); }
const text = (sel) => evaluate(`(document.querySelector(${JSON.stringify(sel)})?.textContent || '').replace(/\\s+/g, ' ').trim()`);
const count = (sel) => evaluate(`document.querySelectorAll(${JSON.stringify(sel)}).length`);

async function step(name, fn) {
    console.log(`\n=== ${name} ===`);
    try {
        await fn();
    } catch (e) {
        check(`${name}: no error while testing`, false, e.message);
    }
}

// ------------------------------------------------------------------ the tests
try {
    await connect();
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Log.enable');
    await send('Network.enable');
    console.log(`=== LOCAL ${SITE} | ${CHROME.split('/').pop()} headless ===`);

    await step('1. landing page -> a job card -> the job\'s own page (/jobs/<job-slug>)', async () => {
        await go('/jobs');
        check('the landing page opens', lastDocStatus === 200 && (await count('.o_llmd_job_title a')) > 0, lastDocStatus);
        const link = await click('.o_llmd_job_title a');
        const p = await path();
        check(`the card title opens its job page: ${p}`, /^\/jobs\/[a-z0-9]+(-[a-z0-9]+)*$/.test(p) && p === link.href, { p, href: link.href });
        check('... and that page shows the same job (title)', (await text('h1.o_llmd_title')) === link.text, [await text('h1.o_llmd_title'), link.text]);
        await reload();
        check('refresh of the job address works (same job)', lastDocStatus === 200 && (await text('h1.o_llmd_title')) === link.text, lastDocStatus);
        check('back to /jobs with Back', (await back()) === '/jobs', await path());
        check('... and to the job again with Forward', (await forward()) === p, await path());
    });

    await step('2. job page -> company page -> another job (View Details) -> breadcrumb', async () => {
        const job = await path();
        const co = await click('a.o_llmd_meta_link');
        const p = await path();
        check(`the company link opens its company page: ${p}`, p.startsWith('/companies/') && (await text('h1')).includes(co.text), [p, await text('h1')]);
        const see = await click('a.o_llmd_see');
        const p2 = await path();
        check(`View Details on the company page opens that job: ${p2}`, /^\/jobs\/[a-z0-9]+(-[a-z0-9]+)*$/.test(p2) && p2 === see.href);
        await click('.breadcrumb a[href="/jobs"], a[href="/jobs"]');
        check('the "Jobs" breadcrumb / link leads back to /jobs', (await path()) === '/jobs');
        await back();                                                     // /jobs -> the second job
        await back();                                                     // -> the company page
        check('Back three times returns to the first job page (job -> company -> job -> /jobs)', (await back()) === job, await path());
    });

    await step('3. category, country, region, role and course pages from the landing page', async () => {
        await go('/jobs');
        const cat = await click('a.o_llmd_catcard');
        check(`a category card opens its page: ${await path()}`, (await path()).startsWith('/categories/') && lastDocStatus === 200 && (await count('.o_llmd_job_title a')) > 0);
        await go('/jobs');
        await click('a.o_llmd_countrycard');
        check(`a country card opens its page: ${await path()}`, (await path()).startsWith('/locations/') && (await count('.o_llmd_job_title a')) > 0);
        await go('/regions');
        await click('a[href^="/regions/"]');
        check(`a region link opens its page: ${await path()}`, (await path()).startsWith('/regions/') && (await count('.o_llmd_job_title a')) > 0);
        await go('/jobs');
        if (await count('a[href^="/jobs/role/"]')) {
            await click('a[href^="/jobs/role/"]');
            check(`a role link opens its page: ${await path()}`, (await path()).startsWith('/jobs/role/') && (await count('.o_llmd_job_title a')) > 0);
            await go('/jobs');
        }
        await click('a[href^="/jobs/course/"]');
        check(`"View all course-matched jobs" opens the course page: ${await path()}`, (await path()).startsWith('/jobs/course/') && (await text('h1')).startsWith('Jobs matched to'), await text('h1'));
        await go('/categories');
        await click('a[href^="/categories/"]');
        check(`the category directory links work: ${await path()}`, (await path()).startsWith('/categories/'));
        await go('/locations');
        await click('a[href^="/locations/"]');
        check(`the country directory links work: ${await path()}`, (await path()).startsWith('/locations/'));
    });

    await step('4. filters in the address (as parts of the path): apply, page 2, Back / Forward, refresh, Clear All', async () => {
        await go('/jobs/all');
        await evaluate(`document.querySelector('#llmd_mode_remote').click()`);
        await click('.o_llmd_apply_filters');
        const p = await path();
        check(`Apply Filters puts the filter in the path: ${p}`, p === '/jobs/all/remote' && (await evaluate(`document.querySelector('#llmd_mode_remote').checked`)), p);
        const n1 = await text('.o_llmd_count, .o_llmd_rcount');
        const pager = await count('.o_llmd_pager a[href*="/page/2"]');
        if (pager) {
            await click('.o_llmd_pager a[href*="/page/2"]');
            const p2 = await path();
            check(`page 2 keeps the filter: ${p2}`, p2 === '/jobs/all/remote/page/2' && (await evaluate(`document.querySelector('#llmd_mode_remote').checked`)), p2);
            check('Back -> page 1 with the filter still set', (await back()) === p && (await evaluate(`document.querySelector('#llmd_mode_remote').checked`)), await path());
            check('Forward -> page 2 again', (await forward()) === p2, await path());
            await back();
        }
        await go(p);
        check('refresh / direct access restores the filter (the option stays selected)', await evaluate(`document.querySelector('#llmd_mode_remote').checked`));
        await evaluate(`document.querySelector('input[type="checkbox"][name="jtype"][value="fulltime"]')?.click()`);
        await click('.o_llmd_apply_filters');
        const both = await path();
        check(`two filters at once: ${both}`, both === '/jobs/all/remote/full-time', both);
        check('... a chip for each active filter', (await count('.o_llmd_fchip')) >= 2, await count('.o_llmd_fchip'));
        await click('.o_llmd_clear');
        const cleared = await path();
        check(`Clear All removes every filter: ${cleared}`, cleared === '/jobs/all' && (await count('.o_llmd_fchip')) === 0, cleared);
        check('Back after Clear All brings the filters back', (await back()) === both, await path());
        const kc = await go('/jobs?q=engineer&country=India');
        check(`a keyword + country query moves to its path: ${kc}`, kc === '/jobs/in-india/search/engineer', kc);
        check('a keyword + country address shows its chips and its search text', (await evaluate(`document.querySelector('input[name="q"]').value`)) === 'engineer' && (await count('.o_llmd_fchip')) >= 2);
    });

    await step('5. filter addresses written another way -> one address (301)', async () => {
        const p = await go('/jobs?work_mode=Remote&region=North%20America&company_size=51-200&employment_type=full-time');
        check(`aliases and names -> our own filters, as the path: ${p}`, p === '/jobs/remote/full-time/region-north-america/size-51-200-employees', p);
        check('... the page shows those 4 filters as chips, the company size one too ("51–200 employees")', (await count('.o_llmd_fchip')) === 4 && (await evaluate('document.body.innerText')).includes('51–200 employees'), await count('.o_llmd_fchip'));
        const p3 = await go('/jobs?salary=10-20&industry=fintech&q=engineer');
        check(`filters the job data has no values for (salary, industry) are left out of the address: ${p3}`, p3 === '/jobs/search/engineer', p3);
        const p2 = await go('/jobs/category/it-software?keywords=python&country=in');
        check(`an old category address with aliases -> ${p2}`, p2 === '/categories/it-software/in-india/search/python', p2);
        const p4 = await go('/jobs/in-bengaluru/remote');
        check(`the same filters written in another order -> the one address: ${p4}`, p4 === '/jobs/remote/in-bengaluru', p4);
    });

    await step('6. job addresses: old, wrong slug, not existing', async () => {
        await go('/jobs');
        const link = await evaluate(`document.querySelector('.o_llmd_job_title a').getAttribute('href')`);
        const id = await evaluate(`document.querySelector('.o_llmd_job_title a').closest('.o_llmd_job').querySelector('a.o_llmd_card_apply').getAttribute('href').match(/\\/jobs\\/ext\\/(\\d+)\\//)[1]`);
        check(`the old address /jobs/ext/${id} moves to ${link}`, (await go('/jobs/ext/' + id)) === link, await path());
        check(`the older /jobs/${id}/<any title> moves to it too (the ID decides)`, (await go(`/jobs/${id}/not-the-title`)) === link, await path());
        await go('/jobs/no-such-job-here');
        check('an address that is no job, no filter and no page: 404', lastDocStatus === 404, lastDocStatus);
        await go('/jobs/999999999/no-such-job');
        check('a job that does not exist: 404 "no longer available" page with links on', lastDocStatus === 404 && (await text('h1')).includes('no longer available') && (await count('a[href="/jobs/all"]')) > 0,
              [lastDocStatus, await text('h1')]);
        await go('/jobs/ext/999999999');
        check('... the same for an old address of a job that does not exist', lastDocStatus === 404, lastDocStatus);
    });

    await step('7. Latest Jobs: the page numbers and the category shortcuts keep the address in step', async () => {
        await go('/jobs');
        const firstIds = () => evaluate(`[...document.querySelectorAll('#llmd_latest_grid .o_llmd_lcard a[href^="/jobs/"]')].map(a => a.getAttribute('href')).join()`);
        const ids0 = await firstIds();
        await evaluate(`document.querySelector('.o_llmd_latest_pager a[data-page="2"]').click()`);
        for (let i = 0; i < 50 && (await firstIds()) === ids0; i++) await sleep(200);
        const ids1 = await firstIds();
        const p = await path();
        check(`page 2 swaps the jobs (12 others, 2 highlighted) and the address says so: ${p}`, ids1 !== ids0 && (await count('#llmd_latest_grid .o_llmd_lcard')) === 12 && (await evaluate(`document.querySelector('.o_llmd_latest_pager .page-item.active')?.textContent.trim()`)) === '2' && p === '/jobs/latest-jobs/page/2', p);
        await go(p);
        check('refresh shows the same page of latest jobs', (await firstIds()) === ids1);
        const cat = await evaluate(`document.querySelectorAll('.o_llmd_lchip[data-cat]')[1]?.getAttribute('data-cat')`);
        if (cat) {
            await evaluate(`document.querySelectorAll('.o_llmd_lchip[data-cat]')[1].click()`);
            for (let i = 0; i < 50 && (await path()) !== '/jobs/latest-jobs/' + cat; i++) await sleep(200);
            const pc = await path();
            check(`a category shortcut puts its category in the address: ${pc}`, pc === '/jobs/latest-jobs/' + cat, pc);
            await go(pc);
            check('refresh keeps that category selected', (await evaluate(`document.querySelector('.o_llmd_lchip.active')?.getAttribute('data-cat')`)) === cat);
        }
    });

    await step('8. menu, login / sign up, Apply Now while logged out', async () => {
        await go('/');
        const menu = await evaluate(`[...document.querySelectorAll('header a[href]')].map(a => a.getAttribute('href'))`);
        check('the header menu has the job board', menu.includes('/jobs'), menu);
        await click('header a[href="/jobs"]');
        check('the menu entry opens /jobs', (await path()) === '/jobs');
        const login = await evaluate(`[...document.querySelectorAll('a[href^="/web/login"]')].length`);
        if (login) {
            await click('a[href^="/web/login"]');
            check(`the Sign in link opens the login page: ${await path()}`, (await path()).startsWith('/web/login') && (await count('input[name="login"]')) === 1);
            await click('a[href^="/web/signup"]');
            check(`... and its sign-up link the sign-up page: ${await path()}`, (await path()).startsWith('/web/signup') && (await count('input[name="confirm_password"]')) === 1);
        } else {
            check('a Sign in link is in the header', false, 'none found');
        }
        await go('/jobs?view=all');
        const apply = await evaluate(`document.querySelector('.o_llmd_card_apply').getAttribute('href')`);
        await click('.o_llmd_card_apply');
        const p = await path();
        check(`Apply Now (logged out) -> the login page, back to ${apply} afterwards`, p === '/web/login?redirect=' + encodeURIComponent(apply), p);
        await go('/jobs');
        await click('.o_llmd_job_title a');
        const detailPage = await path();
        await evaluate(`document.querySelector('a.o_llmd_apply').click()`);
        let shown = false;
        for (let i = 0; i < 30 && !shown; i++) { await sleep(150); shown = await evaluate(`!document.getElementById('llmd_auth').hidden`); }
        check('Apply Now of a job page (logged out) -> the sign-in window over the SAME page (no navigation)', shown && (await path()) === detailPage, await path());
    });

    await step('9. every link of the visited pages has a real destination', async () => {
        const pages = ['/jobs', '/jobs?view=all', '/regions', '/categories', '/locations', '/companies', '/jobs/remote'];
        for (const p of pages) {
            await go(p);
            // a link without a destination is broken - except a disabled pager item ("previous" on page 1, "...") and a Bootstrap toggle (Odoo's header search: a modal)
            const bad = await evaluate(`[...document.querySelectorAll('a')].filter(a => a.offsetParent !== null || a.getClientRects().length)
                .filter(a => !a.closest('.disabled') && !a.hasAttribute('data-bs-toggle'))
                .map(a => [a.getAttribute('href'), (a.textContent || a.getAttribute('aria-label') || '').trim().slice(0, 40)])
                .filter(([h]) => h === null || h === '' || h === '#' || /^javascript:/i.test(h))`);
            check(`${p}: no empty, "#" or javascript: links (${bad.length})`, bad.length === 0, bad.slice(0, 5));
            // every "#" toggle must open what it controls: a modal (Odoo's header search) or a dropdown (Odoo's "+" menu when the header is full)
            const toggles = await evaluate(`[...document.querySelectorAll('a[data-bs-toggle][href="#"]')].map((a, i) => [i, a.getAttribute('data-bs-toggle'), a.getAttribute('data-bs-target'), a.getClientRects().length > 0])`);
            for (const [i, kind, target, shown] of toggles) {
                if (!shown) continue;
                await evaluate(`document.querySelectorAll('a[data-bs-toggle][href="#"]')[${i}].click()`);
                let open = false;
                for (let t = 0; t < 30 && !open; t++) {
                    await sleep(100);
                    open = await evaluate(`(() => { const a = document.querySelectorAll('a[data-bs-toggle][href="#"]')[${i}];
                        return ${JSON.stringify(kind)} === 'dropdown' ? !!(a.parentElement.querySelector('.dropdown-menu.show') || a.getAttribute('aria-expanded') === 'true')
                                                                       : !!document.querySelector(${JSON.stringify(target || '#none')} + '.show'); })()`);
                }
                check(`${p}: the "#" ${kind} toggle ${target || ''} opens what it controls`, open);
                await evaluate(`(() => { const m = document.querySelector('.modal.show [data-bs-dismiss]'); if (m) m.click(); else document.body.click(); return 1; })()`);
                await sleep(400);
            }
            const deadButtons = await evaluate(`[...document.querySelectorAll('button:not([type="submit"]):not([disabled])')].filter(b =>
                !b.closest('form') && !b.dataset.bsToggle && !b.getAttribute('data-bs-toggle') && !b.onclick && !b.className.match(/llmd|navbar|o_|btn-close|dropdown/)).map(b => b.outerHTML.slice(0, 80))`);
            check(`${p}: no plain buttons without an action`, deadButtons.length === 0, deadButtons.slice(0, 3));
        }
    });

    await step('10. clickable tags: a card tag ADDS its filter, the panel follows the address, Back / Forward / refresh keep it', async () => {
        const TYPE_SLUG = { fulltime: 'full-time', parttime: 'part-time', internship: 'internship', contract: 'contract' };
        await go('/companies/harvey');
        const mode = await evaluate(`document.querySelector('.o_llmd_job a.o_llmd_tag_link[data-kind="mode"]')?.getAttribute('data-filter')`);
        const modeKey = new URLSearchParams(mode).get('mode');
        check(`a work mode tag links its own page (${await evaluate(`document.querySelector('.o_llmd_job a.o_llmd_tag_link[data-kind="mode"]').getAttribute('href')`)})`,
              (await evaluate(`document.querySelector('.o_llmd_job a.o_llmd_tag_link[data-kind="mode"]').getAttribute('href')`)) === '/jobs/' + modeKey);
        await click('.o_llmd_job a.o_llmd_tag_link[data-kind="mode"]');
        const p1 = await path();
        check(`Harvey's page -> card tag "${modeKey}": ${p1} (the company page keeps, the work mode is added)`, p1 === '/companies/harvey/' + modeKey, p1);
        check('... the panel shows it: that work mode is selected', await evaluate(`document.querySelector('#llmd_mode_${modeKey}').checked`));
        const typeHref = await evaluate(`document.querySelector('.o_llmd_job a.o_llmd_tag_link[data-kind="type"]')?.getAttribute('data-filter')`);
        const typeKey = new URLSearchParams(typeHref).get('jtype');
        await click('.o_llmd_job a.o_llmd_tag_link[data-kind="type"]');
        const p2 = await path();
        check(`... + card tag "${typeKey}": ${p2} (both filters together)`, p2 === `/companies/harvey/${modeKey}/${TYPE_SLUG[typeKey]}`, p2);
        check('... the panel shows both: the work mode selected and the type checked; one chip each',
              (await evaluate(`document.querySelector('#llmd_mode_${modeKey}').checked && document.querySelector('input[type=checkbox][name="jtype"][value="${typeKey}"]').checked`))
              && (await count('.o_llmd_fchip')) === 2, await count('.o_llmd_fchip'));
        check('Back -> only the work mode', (await back()) === p1, await path());
        check('Forward -> both again', (await forward()) === p2, await path());
        await reload();
        check('refresh keeps both (address and panel)', (await path()) === p2 && (await evaluate(`document.querySelector('input[type=checkbox][name="jtype"][value="${typeKey}"]').checked`)));
        await click('.o_llmd_job a.o_llmd_posted.o_llmd_tag_link');
        const p3 = await path();
        check(`... + card tag "posted": ${p3} (three filters)`, p3.startsWith(p2 + '/posted-'), p3);
        await go('/jobs?region=asia-pacific&mode=remote');
        await click('a.o_llmd_all_regions');
        check(`"All regions" removes only the region (Remote left: its own page): ${await path()}`, (await path()) === '/jobs/remote', await path());
        await go('/jobs/remote');
        await click('.o_llmd_job a.o_llmd_tag_link[data-kind="type"]');
        check(`/jobs/remote -> a card's job type tag: ${await path()} (Remote kept, the type added)`, /^\/jobs\/remote\/(full-time|part-time|internship|contract)$/.test(await path()), await path());
        await go('/jobs/16882/senior-product-manager-embedded-experiences');
        const det = await path();
        await click('.o_llmd_view a.o_llmd_mode_pill');
        check(`job page -> "Remote" pill: ${await path()} (that one filter, its own page)`, (await path()) === '/jobs/remote' && (await evaluate(`document.querySelector('#llmd_mode_remote').checked`)), await path());
        check('Back -> the job page again', (await back()) === det, await path());
    });

    console.log('\n=== console errors, uncaught exceptions and failed requests on every page visited ===');
    // the 404 of the job addresses this test opens ON PURPOSE (a job that does not exist) is the expected answer, not an error of the site
    const real = problems.filter((x) => !/favicon/i.test(x.text) && !/\/jobs\/(ext\/)?999999999|\/jobs\/no-such-job-here/.test(x.text));
    check(`none (${real.length})`, real.length === 0, real.slice(0, 8));
} catch (e) {
    check('the browser test ran to the end', false, e.message);
} finally {
    try { ws && ws.close(); } catch (e) { /* closing */ }
    chrome.kill();
    await sleep(500);
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* Chrome may still hold files */ }
}
const passed = results.filter(Boolean).length;
console.log(`\nRESULT: ${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 1);
