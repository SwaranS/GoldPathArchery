// Only a disposable localhost application, synthetic actors and server-issued test sessions.
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

let input = '';
for await (const part of process.stdin) input += part;
const fixture = JSON.parse(input);
assert.match(fixture.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
const report = { syntheticOnly: true, pages: [], checks: [], errors: [] };
await mkdir(fixture.output, { recursive: true });
const browser = await chromium.launch({ headless: true });

function totp(secret, now = Date.now()) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret].map(c => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30000)));
  const hash = createHmac('sha1', key).update(counter).digest();
  const offset = hash.at(-1) & 15;
  return ((hash.readUInt32BE(offset) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
}

async function actor(name, viewport = { width: 1365, height: 900 }) {
  const context = await browser.newContext({ viewport, locale: 'en-GB', timezoneId: 'Europe/Dublin' });
  await context.route('**/*', route => route.request().url().startsWith(`${fixture.origin}/`)
    ? route.continue() : route.abort());
  if (name) await context.addCookies([{ name: fixture.cookieName, value: fixture.sessions[name],
    url: fixture.origin, httpOnly: true, sameSite: 'Lax' }]);
  return { context, page: await context.newPage() };
}

async function audit(page, label) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const layout = await page.evaluate(() => ({
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
    title: document.title,
    duplicateIds: [...document.querySelectorAll('[id]')].map(node => node.id)
      .filter((id, index, ids) => ids.indexOf(id) !== index),
  }));
  report.pages.push({ label, viewport: page.viewportSize(), ...layout,
    violations: results.violations.map(item => ({ id: item.id, impact: item.impact,
      description: item.help, targets: item.nodes.map(node => node.target) })) });
  await page.screenshot({ path: path.join(fixture.output, `${label}.png`), fullPage: true });
}

async function check(label, run) {
  await run();
  report.checks.push(label);
}

try {
  const visitor = await actor(null);
  await visitor.page.goto(`${fixture.origin}/clubs/`);
  await audit(visitor.page, 'directory-desktop');
  await check('Keyboard skip link reaches main content', async () => {
    await visitor.page.keyboard.press('Tab');
    assert.match(await visitor.page.evaluate(() => document.activeElement.textContent), /Skip to content/);
    await visitor.page.keyboard.press('Enter');
    assert.equal(await visitor.page.evaluate(() => document.activeElement.id), 'main');
  });
  const applicant = await actor('applicant');
  const reviewer = await actor('reviewer');
  const outsider = await actor('outsider');
  await applicant.page.goto(`${fixture.origin}/clubs/request/`);
  await audit(applicant.page, 'application-desktop');
  await applicant.page.setViewportSize({ width: 390, height: 844 });
  await audit(applicant.page, 'application-mobile');
  await applicant.page.locator('[name="name"]').fill('Synthetic private validation club');
  await applicant.page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await applicant.page.waitForURL(/\/clubs\/claims\/[a-f0-9-]+\//);
  const claimUrl = applicant.page.url();
  report.privateClaim = new URL(claimUrl).pathname;
  await check('Draft remains private to the applicant', async () => {
    assert.match(await applicant.page.locator('main').innerText(), /Status: Draft/);
    assert.equal((await outsider.context.request.get(claimUrl)).status(), 404);
  });
  await applicant.page.getByRole('link', { name: 'Continue editing draft' }).click();
  await applicant.page.locator('[name="listing"]').selectOption(fixture.listing);
  await applicant.page.locator('[name="country"]').fill('Ireland');
  await applicant.page.locator('[name="town"]').fill('Synthetic town');
  await applicant.page.locator('[name="website"]').fill('https://example.test/synthetic');
  await applicant.page.locator('[name="description"]').fill('Synthetic club for local validation only.');
  await applicant.page.locator('[name="visibility"]').selectOption('private');
  await applicant.page.locator('[name="role_assertion"]').fill('Synthetic elected secretary; no real club claim.');
  await applicant.page.getByRole('button', { name: 'Submit for independent review' }).click();
  await applicant.page.waitForURL(claimUrl);
  assert.match(await applicant.page.locator('main').innerText(), /Status: Submitted/);
  await audit(applicant.page, 'application-status-mobile');

  await reviewer.page.goto(`${fixture.origin}/clubs/verification/`);
  assert.match(new URL(reviewer.page.url()).pathname, /reauthenticate/);
  await audit(reviewer.page, 'mfa-challenge');
  const validWindow = new Set([-30000, 0, 30000].map(offset => totp(fixture.totpSecret, Date.now() + offset)));
  let wrongCode = 0;
  while (validWindow.has(wrongCode.toString().padStart(6, '0'))) wrongCode++;
  await reviewer.page.locator('[name="code"]').fill(wrongCode.toString().padStart(6, '0'));
  await reviewer.page.locator('form:has(input[name="code"]) button[type="submit"]').click();
  assert.match(new URL(reviewer.page.url()).pathname, /reauthenticate/);
  assert.match(await reviewer.page.locator('main').innerText(), /Incorrect code/);
  await reviewer.page.locator('[name="code"]').fill(totp(fixture.totpSecret));
  await reviewer.page.locator('form:has(input[name="code"]) button[type="submit"]').click();
  if (new URL(reviewer.page.url()).pathname !== '/clubs/verification/') throw new Error('Reviewer MFA form: ' + await reviewer.page.locator('.errorlist').allTextContents());
  await reviewer.page.waitForURL(`${fixture.origin}/clubs/verification/`);
  report.checks.push('Real invalid/valid TOTP challenge gates the verification queue');
  await audit(reviewer.page, 'queue-desktop');
  await reviewer.page.getByRole('link', { name: 'Synthetic private validation club', exact: true }).click();
  const reviewUrl = reviewer.page.url();
  assert.match(await reviewer.page.locator('main').innerText(), /Synthetic known validation club/);
  const evidenceForm = reviewer.page.locator('form:has(input[name="action"][value="evidence"])');
  await evidenceForm.locator('[name="source_url"]').fill('https://official.example.test/synthetic-rehearsal');
  await evidenceForm.locator('[name="contact_reference"]').fill('Synthetic independent contact, no real verification.');
  await evidenceForm.locator('[name="outcome"]').fill('Synthetic authority confirmation for local QA only.');
  await evidenceForm.locator('[name="confirmed"]').check();
  await evidenceForm.locator('[name="checked_at"]').fill(fixture.checkedAt);
  await evidenceForm.locator('[name="expires_at"]').fill(fixture.expiresAt);
  await evidenceForm.locator('[name="upload"]').setInputFiles(fixture.evidenceImage);
  await evidenceForm.getByRole('button', { name: 'Record verification evidence' }).click();
  await reviewer.page.waitForURL(reviewUrl);
  const evidenceLink = reviewer.page.getByRole('link', { name: 'Download private evidence' });
  await evidenceLink.waitFor();
  const evidenceUrl = new URL(await evidenceLink.getAttribute('href'), fixture.origin).href;
  await check('Evidence download requires reviewer MFA and never caches publicly', async () => {
    const response = await reviewer.context.request.get(evidenceUrl);
    assert.equal(response.status(), 200);
    assert.match(response.headers()['cache-control'], /no-store/);
    assert.match(response.headers()['content-disposition'], /attachment/);
    assert.equal((await applicant.context.request.get(evidenceUrl)).status(), 403);
    assert.equal((await outsider.context.request.get(evidenceUrl)).status(), 403);
  });
  await audit(reviewer.page, 'review-desktop');
  await reviewer.page.setViewportSize({ width: 390, height: 844 });
  await audit(reviewer.page, 'review-mobile');
  await reviewer.page.setViewportSize({ width: 1365, height: 900 });
  const decisionForm = reviewer.page.locator('form:has(input[name="action"][value="decision"])');
  await decisionForm.locator('[name="decision"]').selectOption('approved');
  await decisionForm.locator('[name="duplicates_reviewed"]').check();
  await decisionForm.locator('[name="reason"]').fill('Synthetic independent verification rehearsal only.');
  await decisionForm.getByRole('button', { name: 'Record decision' }).click();
  assert.match(await reviewer.page.locator('main').innerText(), /Confirm that the independent verification/);
  report.checks.push('Approval without selected-target confirmation is rejected');
  await decisionForm.locator('[name="target_confirmed"]').check();
  await decisionForm.getByRole('button', { name: 'Record decision' }).click();
  await reviewer.page.waitForURL(reviewUrl);
  assert.match(await reviewer.page.locator('main').innerText(), /Status: Approved/);
  await applicant.page.goto(claimUrl);
  const manageHref = await applicant.page.getByRole('link', { name: 'Club dashboard' }).getAttribute('href');
  await applicant.page.getByRole('link', { name: 'Club dashboard' }).click();
  assert.match(new URL(applicant.page.url()).pathname, /reauthenticate/);
  await audit(applicant.page, 'club-admin-mfa-mobile');
  await applicant.page.locator('[name="code"]').fill(totp(fixture.totpSecret));
  await applicant.page.locator('form:has(input[name="code"]) button[type="submit"]').click();
  await applicant.page.waitForURL(new URL(manageHref, fixture.origin).href);
  report.checks.push('First club administrator completes MFA before private dashboard access');
  report.privateManage = new URL(applicant.page.url()).pathname;
  await audit(applicant.page, 'private-dashboard-mobile');
  await check('Approved admin alone can open private dashboard', async () => {
    assert.equal((await outsider.context.request.get(applicant.page.url())).status(), 404);
    const directory = await visitor.context.request.get(`${fixture.origin}/clubs/`);
    assert.doesNotMatch(await directory.text(), /Synthetic private validation club/);
    assert.equal((await outsider.context.request.get(`${fixture.origin}/clubs/verification/`)).status(), 403);
  });
  await visitor.page.goto(`${fixture.origin}/clubs/${fixture.publicSlug}/`);
  await audit(visitor.page, 'public-profile-desktop');
  await visitor.page.setViewportSize({ width: 390, height: 844 });
  await audit(visitor.page, 'public-profile-mobile');
  report.checks.push('Verified public profile works without signing in');
  // M2: real CSRF-protected join, approval, home preference, invitation and role acceptance.
  await outsider.page.goto(`${fixture.origin}/clubs/${fixture.publicClub}/join/`);
  await outsider.page.locator('[name="athlete"]').selectOption(fixture.memberAthlete);
  await audit(outsider.page, 'membership-join-desktop');
  await outsider.page.getByRole('button', { name: 'Request to join', exact: true }).click();
  await outsider.page.waitForURL(/\/clubs\/memberships\//);
  await applicant.page.goto(`${fixture.origin}/clubs/${fixture.publicClub}/members/`);
  await applicant.page.getByRole('button', { name: 'Approve membership' }).click();
  await applicant.page.waitForURL(`${fixture.origin}/clubs/${fixture.publicClub}/members/`);
  report.checks.push('Member requests to join and administrator approves with real CSRF');
  await audit(applicant.page, 'membership-manager-desktop');
  await applicant.page.setViewportSize({ width: 390, height: 844 });
  await audit(applicant.page, 'membership-manager-mobile');
  await outsider.page.goto(`${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/home/`);
  await audit(outsider.page, 'home-club-desktop');
  await outsider.page.locator('[name="club"]').selectOption(fixture.publicClub);
  report.stage = 'save home club';
  await outsider.page.getByRole('button', { name: 'Save home club' }).click();
  await outsider.page.waitForURL(/\/clubs\/memberships\//);
  const privateClub = report.privateManage.split('/')[2];
  await applicant.page.goto(`${fixture.origin}/clubs/${privateClub}/invite/`);
  await applicant.page.locator('[name="email"]').fill('outsider@example.test');
  report.stage = 'create invitation';
  await applicant.page.getByRole('button', { name: 'Create invitation' }).click();
  await applicant.page.getByRole('heading', { name: /Invitation to/ }).waitFor();
  const invitationUrl = await applicant.page.locator('main a').filter({ hasText: '/clubs/invitations/' }).getAttribute('href');
  const invitationCode = await applicant.page.locator('main code').innerText();
  await outsider.page.goto(invitationUrl);
  await outsider.page.locator('[name="token"]').fill(invitationCode);
  await outsider.page.locator('[name="athlete"]').selectOption(fixture.memberAthlete);
  await outsider.page.locator('[name="decision"]').selectOption('accept');
  report.stage = 'confirm recipient response';
  await outsider.page.getByRole('button', { name: 'Confirm response' }).click();
  if (!new URL(outsider.page.url()).pathname.startsWith('/clubs/memberships/')) throw new Error('Recipient form invalid controls: ' + await outsider.page.locator(':invalid').evaluateAll(nodes => nodes.map(n => n.name + ': ' + n.validationMessage).join('; ')) + ' heading: ' + await outsider.page.locator('h1').allTextContents() + ' Recipient response stayed on ' + new URL(outsider.page.url()).pathname + ': ' + await outsider.page.locator('.errorlist').allTextContents());
  await outsider.page.waitForURL(/\/clubs\/memberships\//);
  await outsider.page.setViewportSize({ width: 390, height: 844 });
  await audit(outsider.page, 'my-clubs-mobile');
  assert.match(await outsider.page.locator('main').innerText(), /Synthetic private validation club/);
  await outsider.page.goto(`${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/home/`);
  await outsider.page.locator('[name="club"]').selectOption(privateClub);
  report.stage = 'save home club';
  await outsider.page.getByRole('button', { name: 'Save home club' }).click();
  await outsider.page.waitForURL(/\/clubs\/memberships\//);
  report.checks.push('Recipient accepts private invitation and explicitly switches home club');
  await applicant.page.goto(`${fixture.origin}/clubs/${privateClub}/members/`);
  const memberRow = applicant.page.locator('li').filter({ has: applicant.page.getByRole('heading', { name: 'Synthetic new member', exact: true }) }).first();
  await memberRow.locator('select[name="role"]').selectOption('admin');
  await memberRow.getByRole('button', { name: 'Offer role for acceptance' }).click();
  await outsider.page.goto(`${fixture.origin}/clubs/memberships/`);
  await outsider.page.getByRole('link', { name: 'Respond to admin offer' }).click();
  await outsider.page.locator('[name="code"]').fill(totp(fixture.totpSecret));
  await outsider.page.locator('form:has(input[name="code"]) button[type="submit"]').click();
  await outsider.page.waitForURL(/\/clubs\/appointments\//);
  await outsider.page.locator('[name="decision"]').selectOption('accept');
  report.stage = 'confirm recipient response';
  await outsider.page.getByRole('button', { name: 'Confirm response' }).click();
  if (!new URL(outsider.page.url()).pathname.startsWith('/clubs/memberships/')) throw new Error('Recipient form invalid controls: ' + await outsider.page.locator(':invalid').evaluateAll(nodes => nodes.map(n => n.name + ': ' + n.validationMessage).join('; ')) + ' heading: ' + await outsider.page.locator('h1').allTextContents() + ' Recipient response stayed on ' + new URL(outsider.page.url()).pathname + ': ' + await outsider.page.locator('.errorlist').allTextContents());
  await outsider.page.waitForURL(/\/clubs\/memberships\//);
  await outsider.page.goto(`${fixture.origin}/clubs/${privateClub}/members/`);
  assert.match(await outsider.page.locator('main').innerText(), /Invite a member/);
  report.checks.push('Additional club admin accepts appointment after real MFA');
} catch (error) {
  report.errors.push(`${report.stage || 'M1'} ${error.name}: ${error.message.split('\n')[0]}`);
} finally {
  await browser.close();
}
report.accessibilityViolations = report.pages.reduce((count, page) => count + page.violations.length, 0);
report.layoutFailures = report.pages.filter(page => page.horizontalOverflow || page.duplicateIds.length).map(page => page.label);
report.passed = !report.errors.length && !report.accessibilityViolations && !report.layoutFailures.length;
await writeFile(path.join(fixture.output, 'browser-report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ passed: report.passed, pages: report.pages.length, checks: report.checks.length,
  violations: report.accessibilityViolations, layoutFailures: report.layoutFailures, errors: report.errors }));
process.exitCode = report.passed ? 0 : 1;
