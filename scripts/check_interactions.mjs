// SPDX-License-Identifier: Apache-2.0
// Code authors: Vijay and Codex
// Use an already-installed Playwright; never install browsers or packages here.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const [root, baseline, out] = process.argv.slice(2);
assert(root && baseline && out, 'supply candidate, verified baseline and evidence-output directories');
const { chromium } = await import(process.env.SITE_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ headless: true,
  ...(process.env.SITE_CHROMIUM ? { executablePath: process.env.SITE_CHROMIUM } : {}) });
await fs.mkdir(out, { recursive: true });
const pages = JSON.parse(await fs.readFile(path.join(root, 'pages.json'), 'utf8'));
const results = [];
const approved = {
  email: ['mailto:evijay+fleetdiff@gmail.com', 'Contact email'],
  questions: ['https://github.com/llm-measurement/fleetdiff/discussions/categories/q-a', 'Contact Q&A'],
  'show-and-tell': ['https://github.com/llm-measurement/fleetdiff/discussions/categories/show-and-tell', 'Contact Show-and-tell'],
};
const visualState = () => {
  const root = getComputedStyle(document.documentElement);
  const pre = document.querySelector('main pre');
  const style = pre && getComputedStyle(pre);
  return {
    palette: ['--ink', '--paper', '--link', '--link-hover', '--muted', '--line', '--surface', '--selected', '--accent', '--output']
      .map(name => root.getPropertyValue(name)),
    intro: [...document.querySelector('main').children].slice(0, 3).map(e => [e.tagName, e.textContent]),
    typography: [root.fontFamily, root.fontSize, root.lineHeight, root.letterSpacing,
      style?.fontSize, style?.lineHeight, style?.backgroundColor],
  };
};
try {
  for (const width of [1366, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 768 }, colorScheme: 'light' });
    const blockedRequests = [];
    let externalRequestsSent = 0;
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const folder = url.origin === 'https://llm-measurement.github.io' ? root
        : url.origin === 'https://baseline.invalid' ? baseline : null;
      if (!folder) {
        blockedRequests.push(url.origin);
        await route.abort();
        return;
      }
      const rel = decodeURIComponent(url.pathname).replace(/^\//, '') || 'index.html';
      assert(!rel.split('/').includes('..'));
      const target = path.join(folder, 'docs', rel);
      try {
        await route.fulfill({ path: target });
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
        await route.fulfill({ status: 404, body: 'Not found' });
      }
    });
    // Shared init script also protects the baseline pages. No real tracker loads.
    await context.addInitScript(() => {
      window.testCopies = [];
      window.testEvents = [];
      window.plausible = (name, options) => window.testEvents.push({ name, options });
      window.plausible.init = () => {};
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async text => window.testCopies.push(text),
      } });
    });
    context.on('requestfinished', request => {
      const origin = new URL(request.url()).origin;
      if (!['https://llm-measurement.github.io', 'https://baseline.invalid'].includes(origin)) externalRequestsSent++;
    });
    for (const { slug, kind, title } of pages) {
      const page = await context.newPage();
      const original = await context.newPage();
      const newPage = !(await fs.access(path.join(baseline, 'docs', slug + '.html')).then(() => true, () => false));
      assert(!newPage || slug === 'langfuse-spend', 'unexpected missing baseline page');
      await original.goto('https://baseline.invalid/' + (newPage ? 'litellm-spend.html' : slug === 'index' ? '' : slug + '.html'));
      await page.goto('https://llm-measurement.github.io/' + (slug === 'index' ? '' : slug + '.html') +
        '?email=private-email&userid=private-ID&command=private-command#private-fragment');
      const isGuide = slug !== 'index' && !kind;
      assert.equal(await page.locator('.guide-contact').count(), isGuide ? 1 : 0);
      const before = await original.evaluate(visualState), after = await page.evaluate(visualState);
      assert.deepEqual(after.palette, before.palette, 'palette changed');
      assert.deepEqual(after.typography, before.typography, 'typography changed');
      if (newPage) {
        assert.equal(after.intro[0][1], title);
        assert.equal(after.intro[1][0], 'P');
        assert.equal(after.intro[2][0], 'NAV');
      } else {
        assert.deepEqual(after.intro, before.intro, 'input-first introduction changed');
      }
      await original.close();

      const initialBlocks = await page.locator('main pre').evaluateAll(nodes => nodes.map(e => ({
        attrs: Object.fromEntries([...e.attributes].map(a => [a.name, a.value])), text: e.querySelector('code').textContent,
      })));
      assert.equal(await page.locator('main pre.output button').count(), 0);
      const commands = page.locator('main pre:not(.output)');
      assert.equal(await page.locator('.copy-command').count(), await commands.count());
      await page.locator('details').evaluateAll(nodes => nodes.forEach(e => { e.open = true; }));
      for (let i = 0; i < await commands.count(); i++) {
        const pre = commands.nth(i);
        const text = await pre.locator('code').textContent();
        const button = pre.locator('..').getByRole('button');
        await button.focus();
        await page.keyboard.press(i % 2 ? 'Space' : 'Enter');
        await page.waitForFunction(count => window.testCopies.length === count, i + 1);
        assert.equal(await page.evaluate(() => window.testCopies.at(-1)), text, 'copied text mismatch');
        assert(await button.evaluate(e => document.activeElement === e), 'focus lost after copying');
        assert(await button.evaluate(e => getComputedStyle(e).outlineStyle !== 'none'), 'missing keyboard focus outline');
      }
      assert.deepEqual(await page.locator('main pre').evaluateAll(nodes => nodes.map(e => ({
        attrs: Object.fromEntries([...e.attributes].map(a => [a.name, a.value])), text: e.querySelector('code').textContent,
      }))), initialBlocks, 'published block mutated');

      await page.evaluate(() => document.addEventListener('click', e => {
        if (e.target.closest('a[data-contact], a[href$="/security/advisories/new"]')) e.preventDefault();
      }));
      for (const [kind, [href, event]] of Object.entries(approved)) {
        const links = page.locator(`a[data-contact="${kind}"]`);
        assert.equal(await links.count(), isGuide ? 2 : 1);
        for (let i = 0; i < await links.count(); i++) {
          const link = links.nth(i);
          assert.equal(await link.getAttribute('href'), href);
          await link.focus();
          await page.keyboard.press('Enter');
          assert.equal(await page.evaluate(() => window.testEvents.at(-1).name), event);
          assert(await link.evaluate(e => getComputedStyle(e).outlineStyle !== 'none'));
        }
      }
      assert.equal(await page.locator('footer a[href="https://github.com/llm-measurement/fleetdiff/security/advisories/new"]').count(), 1);
      const security = page.locator('footer a[href="https://github.com/llm-measurement/fleetdiff/security/advisories/new"]');
      const eventCount = await page.evaluate(() => window.testEvents.length);
      await security.focus();
      await page.keyboard.press('Enter');
      assert(await security.evaluate(e => document.activeElement === e && getComputedStyle(e).outlineStyle !== 'none'));
      assert.equal(await page.evaluate(() => window.testEvents.length), eventCount, 'security link must not emit a contact event');
      const events = await page.evaluate(() => window.testEvents);
      for (const event of events) {
        const url = new URL(page.url());
        assert.deepEqual(event.options, { url: url.origin + url.pathname, props: { path: url.pathname } });
        assert(!JSON.stringify(event).includes('private-'), 'private query/hash or command escaped into event');
        assert(/^(Copy (install command|database command|configuration|verification command|example command|analysis command)|Contact (email|Q&A|Show-and-tell))$/.test(event.name));
      }
      await page.locator('details').evaluateAll(nodes => nodes.forEach(e => { e.open = false; }));
      const contrastPairs = await page.evaluate(() => {
        const pairs = new Map();
        const lum = color => color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => v / 255)
          .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
          .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        function scan() {
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const node = walker.currentNode, element = node.parentElement;
            if (!node.textContent.trim() || ['SCRIPT', 'STYLE'].includes(element.tagName) || !element.getClientRects().length) continue;
            let parent = element, background;
            while (parent) {
              background = getComputedStyle(parent).backgroundColor;
              if (!['transparent', 'rgba(0, 0, 0, 0)'].includes(background)) break;
              parent = parent.parentElement;
            }
            if (!parent) background = getComputedStyle(document.documentElement).backgroundColor;
            const foreground = getComputedStyle(element).color, a = lum(foreground), b = lum(background);
            const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
            if (ratio < 4.5) throw new Error('text contrast below 4.5:1');
            pairs.set(foreground + background, { foreground, background, ratio });
          }
        }
        scan();
        document.querySelectorAll('details').forEach(e => { e.open = true; });
        scan();
        document.querySelectorAll('details').forEach(e => { e.open = false; });
        return [...pairs.values()];
      });
      await page.locator('.brand').hover();
      assert.equal(await page.locator('.brand').evaluate(e => getComputedStyle(e).color), 'rgb(23, 107, 91)');
      const visibleButton = page.locator('.copy-command:visible').first();
      if (await visibleButton.count()) {
        await visibleButton.hover();
        assert.equal(await visibleButton.evaluate(e => getComputedStyle(e).color), 'rgb(23, 107, 91)');
      }
      await page.mouse.move(0, 0);
      await page.emulateMedia({ colorScheme: 'dark' });
      assert.deepEqual(await page.evaluate(() => {
        const s = getComputedStyle(document.documentElement); return [s.colorScheme, s.backgroundColor, s.color];
      }), ['light', 'rgb(251, 252, 250)', 'rgb(23, 33, 43)']);
      await page.emulateMedia({ colorScheme: 'light' });
      await page.evaluate(() => window.scrollTo(0, 0));
      const geometry = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
        indexBottom: document.querySelector('.path-index')?.getBoundingClientRect().bottom,
        title: document.querySelector('h1').textContent,
        folded: [...document.querySelectorAll('.security-note')].every(e => !e.open) }));
      assert.equal(geometry.width, geometry.scroll, `${slug}/${width}: horizontal overflow`);
      assert(geometry.folded);
      if (slug === 'litellm-spend' && width === 1366) assert(geometry.indexBottom < 768);
      if (['index', 'litellm-spend', 'langfuse-spend'].includes(slug)) {
        await page.screenshot({ path: path.join(out, `${slug}-${width}.png`) });
        await page.locator('footer').scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(out, `${slug}-${width}-contact.png`) });
      }
      results.push({ slug, width, colorScheme: 'light', geometry, contrastPairs,
        inputFirstUnchanged: newPage ? null : true, inputFirstVerified: true, newPage,
        paletteUnchanged: true, systemDarkRemainsLight: true,
        hoverPass: true, keyboardPass: true, clipboardPass: true, contactPass: true,
        commandBlocks: await commands.count(), eventsChecked: events.length,
        qaTrackerStubbed: true, externalRequestsSent, pass: true });
      await page.close();
    }
    assert.equal(externalRequestsSent, 0, 'QA must never send external requests');
    assert(blockedRequests.includes('https://plausible.io'), 'real analytics script must be intercepted');
    await context.close();
  }
} finally {
  await browser.close();
}
const files = {};
for (const name of ['assets/site.css', 'assets/site.js', 'docs/assets/site.css', 'docs/assets/site.js', 'pages.json',
  ...pages.flatMap(({ slug }) => [`pages/${slug}.html`, `docs/${slug}.html`])]) {
  files[name] = createHash('sha256').update(await fs.readFile(path.join(root, name))).digest('hex');
}
const report = { method: 'Installed Chromium; all pages/assets served through local interception; candidate and baseline Plausible stubbed before page scripts; every external request aborted, including the real tracker, with zero external requests completed. All pages at 1366/390/320px with synthetic private query/hash markers. Native button Enter/Space and contact Enter activation, exact mocked clipboard text for every command, explicit query/hash-free Plausible url option and path-only props, unchanged published blocks and input-first introduction/palette/typography, contrast >=4.5 including opened folds, hover, dark-system light palette, closed security notes, no horizontal overflow. Clipboard OS integration and live analytics delivery are not exercised.',
  baselineCommit: execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
  newPageMethod: 'Langfuse is new: verify input-first ordering and match shared palette/typography against the existing LiteLLM guide; no historical Langfuse intro comparison is claimed.', files, results };
await fs.writeFile(path.join(root, 'evidence/contact-copy-visual-verified.json'), JSON.stringify(report, null, 2) + '\n');
await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(report, null, 2) + '\n');
console.log(`PASS: ${results.length} page/viewports; ${results.reduce((n, r) => n + r.commandBlocks, 0)} exact keyboard copies; ${results.reduce((n, r) => n + r.eventsChecked, 0)} path-only events`);
