// UI audit of the LOCAL job board in headless Chrome (DevTools protocol, Node 22+ - nothing to install):
//   1. WCAG contrast of every visible text on the main pages, measured in the browser: the text colour against the colour really painted behind it
//      (the backgrounds of its ancestors blended together; behind a gradient the worst of its colours is used). AA: 4.5:1, large text (24px, or 18.66px bold) 3:1.
//   2. the borders of form controls (inputs, selects, checkboxes, radio buttons) against what is around them: 3:1 (WCAG 1.4.11);
//   3. keyboard focus: Tab through the page, every focused element must show an outline or a focus ring;
//   4. no horizontal scrolling at desktop (1366), tablet (820) and mobile (390) widths; a screenshot of each page at each width (SHOTS=<folder>).
//
//   . .\scripts\env.ps1
//   node tests\ui_audit.mjs                     (SHOTS=C:\some\folder to keep the screenshots; CHROME=... for another browser)
// It only reads pages: nothing is clicked that saves anything, nothing is stored in Odoo.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const SITE = (process.env.ODOO_URL || '').replace(/\/$/, '');
if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(SITE)) {
    console.error('ui_audit runs against the LOCAL instance only: set ODOO_URL (. .\\scripts\\env.ps1).');
    process.exit(2);
}
const CHROME = process.env.CHROME || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const SHOTS = process.env.SHOTS || '';
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const PORT = 9300 + Math.floor(Math.random() * 500);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(label, ok, detail = '') {
    results.push(!!ok);
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${ok ? '' : ' - ' + JSON.stringify(detail).slice(0, 700)}`);
}

const profile = mkdtempSync(join(tmpdir(), 'llmd-ui-'));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--headless=new', '--no-first-run', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
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
                else if (x.method === 'Log.entryAdded' && x.params.entry.level === 'error' && !/favicon|999999999/.test(x.params.entry.url || '')) errors.push(x.params.entry.text + ' ' + (x.params.entry.url || ''));
            };
        }
    } catch (e) { /* starting */ }
    if (!ws) await sleep(250);
}
const send = (method, params = {}) => { const id = ++seq; ws.send(JSON.stringify({ id, method, params })); return new Promise((ok) => waiting.set(id, ok)); };
const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'evaluate');
    return r.result?.result?.value;
};
async function load(path, width) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
    await send('Page.navigate', { url: SITE + path });
    for (let i = 0; i < 150; i++) { await sleep(150); try { if ((await evaluate('document.readyState')) === 'complete') break; } catch (e) { /* loading */ } }
    await evaluate('document.fonts && document.fonts.ready.then(() => 1)');
    // reveal-on-scroll and entry animations: show everything as it ends up
    await evaluate(`document.querySelectorAll('.o_llmd_rv, .o_llmd_cell').forEach(e => e.classList.add('is-in')); document.documentElement.style.scrollBehavior = 'auto';
                    const st = document.createElement('style'); st.textContent = '*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition-duration:0s!important}'; document.head.appendChild(st); 1`);
    await sleep(400);
}

// ------------------------------------------------------------------ measured in the page
const AUDIT = `(() => {
    const parse = (c) => { const m = c && c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
    const over = (top, bot) => { const a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; };
    const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const gradColors = (img) => (img.match(/rgba?\\([^)]+\\)/g) || []).map(parse).filter(Boolean);
    // the background(s) really painted behind an element: blend its ancestors' colours from the page up; a gradient gives every colour it has
    function backs(el) {
        const chain = [];
        for (let e = el; e; e = e.parentElement) chain.push(e);
        let candidates = [[255, 255, 255, 1]];
        for (const e of chain.reverse()) {
            const s = getComputedStyle(e);
            const g = s.backgroundImage !== 'none' ? gradColors(s.backgroundImage) : [];
            const bg = parse(s.backgroundColor);
            if (bg && bg[3] > 0) candidates = candidates.map(c => over(bg, c));
            if (g.length && !/url\\(/.test(s.backgroundImage)) {
                const opaque = g.filter(c => c[3] >= 0.9);
                if (opaque.length) candidates = opaque.map(c => [c[0], c[1], c[2], 1]);
                else candidates = candidates.flatMap(c => g.map(gc => over(gc, c)));
            }
        }
        return candidates;
    }
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05; };
    const label = (el) => (el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '') + ' "' + (el.innerText || el.value || el.placeholder || '').trim().replace(/\\s+/g, ' ').slice(0, 30) + '"');
    const text = [], seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n; let checked = 0;
    while ((n = walker.nextNode())) {
        if (!n.textContent.trim()) continue;
        const el = n.parentElement;
        if (!el || seen.has(el) || !visible(el) || el.closest('[aria-hidden="true"], .visually-hidden, .sr-only, .o_skip_to_content, noscript, script, style, .d-none, .o_llmd_accent')) continue;
        seen.add(el);
        const s = getComputedStyle(el);
        if (s.webkitTextFillColor === 'rgba(0, 0, 0, 0)' || s.color === 'rgba(0, 0, 0, 0)') continue;            // gradient text (checked separately)
        const fg = parse(s.color); if (!fg) continue;
        const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight, 10) >= 700;
        const large = size >= 24 || (size >= 18.66 && bold);
        const need = el.closest('.disabled, :disabled, [aria-disabled="true"]') ? 0 : (large ? 3 : 4.5);
        const worst = Math.min(...backs(el).map(b => ratio(fg[3] < 1 ? over(fg, b) : fg, b)));
        checked++;
        if (need && worst < need) text.push({ el: label(el), ratio: +worst.toFixed(2), need, color: s.color, size });
    }
    // placeholders
    for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
        if (!visible(el)) continue;
        const ph = parse(getComputedStyle(el, '::placeholder').color); if (!ph) continue;
        const worst = Math.min(...backs(el).map(b => ratio(ph[3] < 1 ? over(ph, b) : ph, b)));
        checked++;
        if (worst < 4.5) text.push({ el: 'placeholder of ' + label(el), ratio: +worst.toFixed(2), need: 4.5 });
    }
    // form control borders (WCAG 1.4.11: 3:1 against what is next to them)
    const ui = [];
    for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=range]):not(.btn-check), select, textarea')) {
        if (!visible(el) || el.closest('.o_llmd_bigsearch, [aria-hidden="true"]')) continue;
        const s = getComputedStyle(el);
        const bc = parse(s.borderTopColor), bw = parseFloat(s.borderTopWidth);
        const outside = backs(el.parentElement);
        const inside = parse(s.backgroundColor);
        const best = bw > 0 && bc ? Math.min(...outside.map(o => ratio(bc[3] < 1 ? over(bc, o) : bc, o))) : 0;
        const fill = inside && inside[3] > 0.5 ? Math.min(...outside.map(o => ratio(inside, o))) : 0;
        if (Math.max(best, fill) < 3) ui.push({ el: label(el) + ' [' + (el.type || el.tagName) + ']', border: s.borderTopColor, ratio: +best.toFixed(2) });
    }
    // gradient text (headings like "Grow."): the lightest colour of the gradient against white
    const grad = [];
    for (const el of document.querySelectorAll('.o_llmd_accent')) {
        if (!visible(el)) continue;
        const cols = gradColors(getComputedStyle(el).backgroundImage);
        const worst = Math.min(...cols.flatMap(c => backs(el.parentElement).map(b => ratio(c, b))));
        grad.push(+worst.toFixed(2));
    }
    const doc = document.documentElement;
    return { checked, text, ui, grad, overflow: doc.scrollWidth - doc.clientWidth, wide: [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.right > doc.clientWidth + 2 && visible(e) && getComputedStyle(e).position !== 'fixed' && !e.closest('.o_llmd_side, .offcanvas, .o_llmd_co_strip, .o_llmd_popular, .o_llmd_cat_switch, .o_llmd_lchips, .o_llmd_hq_tabs, [style*="overflow"]'); }).slice(0, 4).map(label) };
})()`;

async function focusAudit(maxTabs) {
    await evaluate('window.scrollTo(0, 0); document.activeElement && document.activeElement.blur(); 1');
    const missing = [];
    let seen = 0;
    for (let i = 0; i < maxTabs; i++) {
        await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
        await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
        await sleep(40);
        const f = await evaluate(`(() => { const e = document.activeElement; if (!e || e === document.body) return null; const s = getComputedStyle(e); const r = e.getBoundingClientRect();
            const ring = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1) || /rgba?\\(/.test(s.boxShadow) && s.boxShadow !== 'none';
            // a visible change of the element itself counts too (e.g. a filled chip)
            return { ring, visible: r.width > 0 && r.height > 0, el: e.tagName.toLowerCase() + '.' + String(e.className || '').trim().split(/\\s+/).slice(0, 2).join('.') + ' "' + (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 24) + '"' }; })()`);
        if (!f || !f.visible) continue;
        seen++;
        if (!f.ring) missing.push(f.el);
    }
    return { seen, missing };
}

const PAGES = [
    ['landing', '/jobs'],
    ['all jobs (results + filters)', '/jobs?view=all'],
    ['filtered results', '/jobs?mode=remote&jtype=fulltime&view=all'],
    ['job detail', null],
    ['company page', null],
    ['category page', '/jobs/category/it-software'],
    ['regions directory', '/jobs/regions'],
    ['countries directory', '/jobs/countries'],
    ['categories directory', '/jobs/categories'],
    ['course page', '/jobs/course/sell-ai'],
    ['no results', '/jobs?q=zzzqqqxxxnothing'],
    ['job not available (404)', '/jobs/999999999/no-such-job'],
    ['login', '/web/login?redirect=%2Fjobs'],
    ['sign up', '/web/signup?redirect=%2Fjobs'],
    ['reset password', '/web/reset_password'],
];
try {
    await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
    await load('/jobs?view=all', 1366);
    const job = await evaluate(`document.querySelector('.o_llmd_job_title a').getAttribute('href')`);
    const co = await evaluate(`document.querySelector('a.o_llmd_co_link').getAttribute('href')`);
    PAGES[3][1] = job; PAGES[4][1] = co;
    console.log(`=== UI audit of ${SITE} (${CHROME.split('/').pop()} headless) ===`);
    for (const [name, path] of PAGES) {
        console.log(`\n=== ${name}: ${path} ===`);
        for (const [w, label] of [[1366, 'desktop'], [820, 'tablet'], [390, 'mobile']]) {
            await load(path, w);
            const a = await evaluate(AUDIT);
            if (w === 1366) {
                check(`contrast: all ${a.checked} texts at least 4.5:1 (3:1 large)`, a.text.length === 0, a.text.slice(0, 6));
                check('form control borders at least 3:1', a.ui.length === 0, a.ui.slice(0, 4));
                if (a.grad.length) check(`gradient heading text: lightest colour ${Math.min(...a.grad)}:1 (large text, 3:1)`, Math.min(...a.grad) >= 3, a.grad);
                const f = await focusAudit(40);
                check(`keyboard focus visible on all ${f.seen} elements reached with Tab`, f.missing.length === 0, f.missing.slice(0, 5));
            } else if (a.text.length) {
                check(`contrast at ${label} width`, false, a.text.slice(0, 4));
            }
            check(`${label} ${w}px: no horizontal scrolling`, a.overflow <= 1, { overflow: a.overflow, wide: a.wide });
            if (SHOTS) {
                const full = await evaluate('Math.min(document.documentElement.scrollHeight, 9000)');
                await send('Emulation.setDeviceMetricsOverride', { width: w, height: full, deviceScaleFactor: 1, mobile: w < 600 });
                await sleep(300);
                const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 62, captureBeyondViewport: true });
                writeFileSync(join(SHOTS, `${name.replace(/[^a-z0-9]+/gi, '-')}-${label}.jpg`), Buffer.from(shot.result.data, 'base64'));
            }
        }
    }
    console.log('\n=== browser console ===');
    check(`no console errors / exceptions on the pages (${errors.length})`, errors.length === 0, errors.slice(0, 5));
} catch (e) {
    check('the audit ran to the end', false, e.message);
} finally {
    try { ws.close(); } catch (e) { /* closing */ }
    chrome.kill();
    await sleep(400);
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* in use */ }
}
const passed = results.filter(Boolean).length;
console.log(`\nRESULT: ${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 1);
