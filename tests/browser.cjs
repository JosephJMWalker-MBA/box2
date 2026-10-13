// Optional development-only Playwright checks. No Node tooling is required to run BOX2.
const { chromium } = require(process.env.BOX2_PLAYWRIGHT || 'playwright');
const { spawn, spawnSync } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const probe = net.createServer();
  await new Promise((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  const setup = spawnSync('php', [path.join(__dirname, 'browser-fixture.php'), base], { encoding: 'utf8' });
  if (setup.status !== 0) throw new Error(setup.stderr);
  const fixture = JSON.parse(setup.stdout);
  const server = spawn('php', ['-S', `127.0.0.1:${port}`, '-t', path.join(__dirname, '../public'), path.join(__dirname, '../public/router.php')], {
    env: { ...process.env, BOX2_CONFIG: fixture.config }, stdio: 'ignore',
  });
  let browser;
  try {
    for (let i = 0; i < 50; i++) {
      try { await fetch(base); break; } catch { await new Promise((resolve) => setTimeout(resolve, 40)); }
    }
    browser = await chromium.launch({ channel: process.env.BOX2_BROWSER_CHANNEL || 'chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 360, height: 800 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const fits = async (label) => {
      const dimensions = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
      assert.ok(dimensions.content <= dimensions.viewport, `${label}: no horizontal overflow ${JSON.stringify(dimensions)}`);
      console.log(`PASS ${label}: no horizontal overflow`);
    };
    await page.goto(base);
    await fits('360px homepage');
    await page.screenshot({ path: path.join(fixture.directory, 'home-mobile.png'), fullPage: true });
    await page.goto(`${base}/book?night=${fixture.night}`);
    assert.equal(await page.locator('.orientation-card').count(), 9);
    assert.equal(await page.locator('[data-booking-fields]').isVisible(), false);
    assert.equal(await page.locator('.orientation-card:visible').count(), 1);
    await page.screenshot({ path: path.join(fixture.directory, 'onboarding-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: 'I understand', exact: true }).click();
    assert.match(await page.locator('[data-orientation-progress]').textContent(), /Card 2 of 9/);
    assert.equal(await page.locator('.orientation-card:visible').count(), 1);
    console.log('PASS first acknowledgment advances exactly one card');
    await page.getByRole('button', { name: 'Previous', exact: true }).click();
    assert.match(await page.locator('[data-orientation-progress]').textContent(), /Card 1 of 9/);
    await page.getByRole('button', { name: 'I understand', exact: true }).click();
    for (let i = 0; i < 7; i++) {
      await page.getByRole('button', { name: 'I understand', exact: true }).click();
      assert.equal(await page.locator('.orientation-card:visible').count(), 1);
      assert.equal(await page.locator('[data-booking-fields]').isVisible(), false);
    }
    await page.getByRole('button', { name: 'I understand. Open booking.', exact: true }).focus();
    await page.keyboard.press('Space');
    assert.equal(await page.locator('[data-booking-fields]').isVisible(), true);
    assert.equal(await page.locator('[data-orientation-check]').isChecked(), true);
    await fits('360px booking');
    assert.deepEqual(await page.locator('input[name$="_allowed"]').evaluateAll((inputs) => inputs.map((input) => input.checked)), [false, false, false, false, false]);
    await page.getByLabel('Stage minutes', { exact: true }).selectOption('15');
    assert.equal(await page.locator('.slot[data-visibility="private"]:visible').count(), 0);
    assert.equal(await page.locator('.slot.available:visible').count(), 20);
    await page.screenshot({ path: path.join(fixture.directory, 'book-mobile.png'), fullPage: true });
    await page.locator('.slot.available:visible input').first().check();
    await page.getByRole('button', { name: 'Continue with this block', exact: true }).click();
    await page.getByLabel('Stage name', { exact: true }).fill('Browser Synthetic');
    await page.getByLabel('Email', { exact: true }).fill('browser-synthetic@example.test');
    await page.getByLabel('Comedy format').selectOption('standup');
    const formats = await page.locator('select[name="performance_type"] option').evaluateAll((options) => options.map((option) => option.value));
    assert.deepEqual(formats, ['', 'standup', 'musical_comedy', 'host_practice', 'sketch_comedy']);
    await page.getByRole('button', { name: 'Change block', exact: true }).click();
    await page.getByLabel('Show evening', { exact: true }).selectOption(String(fixture.other_night));
    await page.waitForFunction((night) => document.querySelector('input[name="night_id"]').value === String(night), fixture.other_night);
    assert.equal(await page.getByLabel('Stage name', { exact: true }).inputValue(), 'Browser Synthetic');
    assert.equal(await page.getByLabel('Email', { exact: true }).inputValue(), 'browser-synthetic@example.test');
    assert.equal(await page.getByLabel('Stage minutes', { exact: true }).inputValue(), '15');
    await page.locator('.slot.available:visible input').first().check();
    await page.getByRole('button', { name: 'Continue with this block', exact: true }).click();
    await page.getByRole('button', { name: 'Recording choices', exact: true }).click();
    console.log('PASS nine acknowledgments, three booking steps, actual length filtering, and state-preserving night change');
    await page.locator('input[name="livestream_allowed"]').check();
    await page.locator('input[name="terms_agreed"]').check();
    await page.getByRole('button', { name: 'Reserve stage block', exact: true }).click();
    await page.getByRole('heading', { name: 'Your place in the room.', exact: true }).waitFor();
    assert.match(await page.locator('.receipt').textContent(), /Email confirmations and reminders are unavailable/);
    const receipt = await page.locator('.receipt').textContent();
    assert.match(receipt, /15 stage minutes/); assert.match(receipt, /30 minutes · 3 adjacent allocations/);
    assert.match(receipt, /Arrival window/); assert.match(receipt, /Check in immediately upon arrival/); assert.match(receipt, /On deck at/);
    await fits('360px confirmation');
    console.log('PASS keyboard onboarding and full browser booking complete');
    await page.goto(`${base}/admin/login`);
    await page.getByLabel('Host password').fill('synthetic-host-password');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('heading', { name: 'Host desk.', exact: true }).waitFor();
    await fits('360px host desk');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(base);
    await fits('1280px homepage');
    await page.screenshot({ path: path.join(fixture.directory, 'home-desktop.png'), fullPage: true });
    await page.goto(`${base}/book?night=${fixture.night}`);
    await fits('1280px onboarding');
    await page.screenshot({ path: path.join(fixture.directory, 'onboarding-desktop.png'), fullPage: true });
    await page.goto(`${base}/rules`);
    assert.equal(await page.locator('.orientation-card:visible').count(), 9);
    console.log('PASS all nine cards readable independently on rules page');
    const noJs = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 360, height: 800 } });
    const fallback = await noJs.newPage(); await fallback.goto(`${base}/book?night=${fixture.night}`);
    assert.equal(await fallback.locator('.orientation-card:visible').count(), 9);
    assert.equal(await fallback.getByLabel('Stage name', { exact: true }).isVisible(), true);
    await noJs.close(); console.log('PASS accessible full-form fallback without JavaScript');
    assert.deepEqual(errors, []);
    console.log('PASS no browser JavaScript errors');
    console.log(`Screenshots: ${fixture.directory}`);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise((resolve) => server.once('exit', resolve));
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
