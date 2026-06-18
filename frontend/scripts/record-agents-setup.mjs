// Records a short WebM screen-capture of the /agents/<harness> setup flow (pick a
// trigger, wire in tools, watch the agent graph build) and writes it to
// public/video/agents-setup.webm for embedding on the /agents page. Uses
// Playwright's recordVideo + an injected follow-cursor so visual learners can see
// where to click. Run with the dev server up:  node scripts/record-agents-setup.mjs
import { chromium } from 'playwright';
import { mkdirSync, readdirSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const BASE = process.env.BASE_URL || 'http://localhost:5173';
const URL = `${BASE}/agents/claude-code`;
const REC_DIR = '/tmp/agents-rec';
const OUT_DIR = 'public/video';
const OUT = `${OUT_DIR}/agents-setup.webm`;
const W = 1280, H = 1000;
const NAV_H = 80; // page nav cropped off the top
const TRIM_S = 2.0; // seconds of white page-load trimmed off the front (no loop flash)
const SCROLL_Y = 440; // brings "Select trigger" near the top of the viewport

rmSync(REC_DIR, { recursive: true, force: true });
mkdirSync(REC_DIR, { recursive: true });
mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 2,
    // Capture matches the viewport; deviceScaleFactor 2 keeps rendering crisp and
    // the ffmpeg pass uses a low CRF so text stays sharp.
    recordVideo: { dir: REC_DIR, size: { width: W, height: H } },
});
const page = await ctx.newPage();
const wait = (ms) => page.waitForTimeout(ms);

await page.goto(URL, { waitUntil: 'domcontentloaded' });

// Follow-cursor: a soft pointer dot that tracks real mouse events Playwright fires.
await page.addStyleTag({
    content: `#__cur{position:fixed;top:0;left:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;
      background:rgba(255,255,255,.92);border:1.5px solid rgba(0,0,0,.25);border-radius:50%;
      box-shadow:0 2px 9px rgba(0,0,0,.5);transition:transform .08s ease}
      #__cur.down{transform:scale(.78)}`,
});
await page.evaluate(() => {
    const c = document.createElement('div');
    c.id = '__cur';
    document.body.appendChild(c);
    addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => c.classList.add('down'), true);
    addEventListener('mouseup', () => c.classList.remove('down'), true);
});

await page.waitForSelector('.react-flow__node', { timeout: 25000 });
await page.evaluate((y) => window.scrollTo({ top: y, behavior: 'instant' }), SCROLL_Y);
await page.mouse.move(W / 2, H / 2, { steps: 2 });
// Hold on the settled (dark) default builder. The ffmpeg pass trims the white
// page-load frames off the front (TRIM_S) so the loop opens on this dark frame
// with no white flash — keep this wait > TRIM_S.
await wait(2200);

// Find a button by label within a section delimited by its <h2> (Y-range in the
// post-scroll viewport). Returns viewport-center coords or null.
async function coords(section, label) {
    return page.evaluate(({ section, label }) => {
        const h2 = [...document.querySelectorAll('h2')];
        const i = h2.findIndex((h) => (h.textContent || '').toLowerCase().includes(section));
        if (i < 0) return null;
        const top = h2[i].getBoundingClientRect().top + scrollY;
        const bot = h2[i + 1] ? h2[i + 1].getBoundingClientRect().top + scrollY : Infinity;
        const btns = [...document.querySelectorAll('button')].filter((b) => {
            const y = b.getBoundingClientRect().top + scrollY;
            return y >= top && y < bot;
        });
        const norm = (s) => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
        const btn = btns.find((b) => norm(b.textContent) === label || norm(b.textContent).startsWith(label));
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        // Only target on-screen buttons so the follow-cursor never jumps off the
        // viewport (below-the-fold grid items would otherwise yield bogus coords).
        if (r.top < 4 || r.bottom > innerHeight - 4) return null;
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, { section, label });
}

async function clickThing(section, label, { hover = false } = {}) {
    const c = await coords(section, label);
    if (!c) { console.warn('not found:', section, label); return; }
    await page.mouse.move(c.x, c.y, { steps: 28 });
    await wait(420);
    if (!hover) { await page.mouse.down(); await wait(110); await page.mouse.up(); }
    await wait(950);
}

// 1) Pick a trigger — its node wires into the agent's input in the live preview.
await clickThing('select trigger', 'schedule');
await wait(700);
// 2) Wire in tools — each becomes a tool node under the agent (visible grid items
// so the cursor stays on-screen).
await clickThing('select tools', 'airtable');
await clickThing('select tools', 'github');
await wait(700);
// 3) Land on the one-click open button.
const openC = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button,a')].find((e) => /open this .* agent/i.test(e.textContent || ''));
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
});
if (openC) { await page.mouse.move(openC.x, openC.y, { steps: 30 }); await wait(1500); }

await ctx.close();
await browser.close();

const file = readdirSync(REC_DIR).find((f) => f.endsWith('.webm'));
if (!file) throw new Error('no recording produced');
rmSync(OUT, { force: true });
// Post-process: trim the white page-load frames off the front (so the loop has
// no white flash), crop the page nav off the top, and re-encode VP9 at a low CRF
// to keep text crisp.
execFileSync('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-ss', String(TRIM_S),
    '-i', `${REC_DIR}/${file}`,
    '-vf', `crop=${W}:${H - NAV_H}:0:${NAV_H}`,
    '-c:v', 'libvpx-vp9', '-crf', '20', '-b:v', '0', '-an',
    OUT,
], { stdio: 'inherit' });
console.log('wrote', OUT);
