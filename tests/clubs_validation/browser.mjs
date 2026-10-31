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

async function freshCode() {
  const remaining = 30000 - Date.now() % 30000;
  if (remaining < 3000) await new Promise(resolve => setTimeout(resolve, remaining + 100));
  return totp(fixture.totpSecret);
}

async function openWithMfa(page, url) {
  await page.goto(url);
  if (new URL(page.url()).pathname.includes('reauthenticate')) {
    await page.locator('[name="code"]').fill(await freshCode());
    await page.locator('form:has(input[name="code"]) button[type="submit"]').click();
    await page.waitForURL(url);
  }
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
  await reviewer.page.locator('[name="code"]').fill(await freshCode());
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
  await applicant.page.locator('[name="code"]').fill(await freshCode());
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
  await outsider.page.locator('[name="code"]').fill(await freshCode());
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
  report.stage = 'M3 scoped sharing';
  await outsider.page.goto(`${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/sharing/`);
  await audit(outsider.page, 'sharing-owner-mobile');
  await outsider.page.locator('[name="club"]').selectOption(privateClub);
  await outsider.page.locator('[name="role"]').selectOption('admin');
  await outsider.page.locator('input[name="scopes"][value="scoring"]').check();
  await outsider.page.locator('[name="purpose"]').fill('Synthetic score review only');
  await outsider.page.locator('[name="starts_at"]').fill(fixture.checkedAt);
  await outsider.page.locator('[name="expires_at"]').fill(fixture.expiresAt);
  await outsider.page.getByRole('button', { name: 'Grant access', exact: true }).click();
  await outsider.page.getByRole('button', { name: 'Revoke access', exact: true }).waitFor();
  const scoringUrl = `${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/shared/scoring/`;
  await applicant.page.goto(scoringUrl);
  await audit(applicant.page, 'shared-scoring-mobile');
  assert.equal((await applicant.context.request.get(scoringUrl + '?format=json')).status(), 200);
  assert.equal((await applicant.context.request.get(`${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/shared/equipment/`)).status(), 404);
  assert.equal((await applicant.context.request.get(`${fixture.origin}/account/athletes/${fixture.memberAthlete}/`)).status(), 404);
  await outsider.page.getByRole('button', { name: 'Revoke access', exact: true }).click();
  assert.equal((await applicant.context.request.get(scoringUrl)).status(), 404);
  report.checks.push('Explicit scoring consent excludes equipment and legacy profile; revocation denies saved links');
  report.stage = 'M4 facilities';
  const facilityManage = `${fixture.origin}/clubs/${fixture.publicClub}/facilities/manage/`;
  await applicant.page.goto(facilityManage);
  await applicant.page.getByRole('link', { name: 'Add a facility access group', exact: true }).click();
  await applicant.page.locator('[name="name"]').fill('Synthetic facility access cohort');
  await applicant.page.locator('[name="members"]').selectOption({ label:'Synthetic new member' });
  await applicant.page.getByRole('button', { name: 'Save facility access group', exact: true }).click();
  await applicant.page.waitForURL(facilityManage);
  await applicant.page.getByRole('link', { name: 'Synthetic facility access cohort', exact: true }).waitFor();
  report.checks.push('Named facility access group is created from current club memberships');
  await applicant.page.getByRole('link', { name: 'Add a facility', exact: true }).click();
  await audit(applicant.page, 'facility-create-mobile');
  await applicant.page.locator('[name="name"]').fill('Synthetic public venue');
  await applicant.page.locator('[name="audience"]').selectOption('public');
  await applicant.page.locator('[name="location_audience"]').selectOption('admins');
  await applicant.page.locator('[name="address"]').fill('PRIVATE SYNTHETIC FACILITY ADDRESS');
  await applicant.page.locator('[name="latitude"]').fill('53.123456');
  await applicant.page.locator('[name="longitude"]').fill('-6.123456');
  await applicant.page.getByRole('button', { name: 'Save facility', exact: true }).click();
  await applicant.page.waitForURL(facilityManage);
  const facilityEdit = await applicant.page.getByRole('link', { name: 'Edit Synthetic public venue', exact: true }).getAttribute('href');
  const facilityId = facilityEdit.split('/').at(-2);
  await applicant.page.getByRole('link', { name: 'Add shooting area', exact: true }).click();
  await applicant.page.locator('[name="name"]').fill('Synthetic 70m line');
  await applicant.page.locator('[name="kind"]').selectOption('outdoor');
  await applicant.page.locator('[name="disciplines"][value="recurve"]').check();
  await applicant.page.locator('[name="distances_m"]').fill('18, 30, 70');
  await applicant.page.locator('[name="lane_capacity"]').fill('8');
  await applicant.page.locator('[name="target_capacity"]').fill('4');
  await applicant.page.locator('[name="audience"]').selectOption('public');
  await applicant.page.getByRole('button', { name: 'Save area', exact: true }).click();
  await applicant.page.waitForURL(facilityManage);
  const ruleHref = await applicant.page.getByRole('link', { name: 'Add weekly hours', exact: true }).getAttribute('href');
  const areaId = ruleHref.split('/').at(-2);
  for (const hours of [{ start:'09:00', end:'12:00', date:'2026-01-01', priority:'0' },
    { start:'13:00', end:'16:00', date:'2026-01-01', priority:'0' },
    { start:'10:00', end:'14:00', date:'2026-06-01', endDate:'2026-08-31', priority:'10' }]) {
    await applicant.page.goto(new URL(ruleHref, fixture.origin).href);
    await applicant.page.locator('[name="weekday"]').selectOption('5');
    await applicant.page.locator('[name="starts_on"]').fill(hours.date);
    if (hours.endDate) await applicant.page.locator('[name="ends_on"]').fill(hours.endDate);
    await applicant.page.locator('[name="start_time"]').fill(hours.start);
    await applicant.page.locator('[name="end_time"]').fill(hours.end);
    await applicant.page.locator('[name="priority"]').fill(hours.priority);
    await applicant.page.locator('[name="audience"]').selectOption('public');
    await applicant.page.getByRole('button', { name: 'Save rule', exact: true }).click();
    await applicant.page.waitForURL(facilityManage);
  }
  const calendarUrl = `${fixture.origin}/clubs/areas/${areaId}/availability/`;
  const winter = await visitor.context.request.get(calendarUrl + '?starts_on=2026-01-03&days=1&format=json');
  assert.equal((await winter.json()).days[0].slots.length, 2);
  const summer = await visitor.context.request.get(calendarUrl + '?starts_on=2026-06-06&days=1&format=json');
  assert.equal((await summer.json()).days[0].slots.length, 1);
  await visitor.page.goto(calendarUrl + '?starts_on=2026-06-06&days=7');
  await audit(visitor.page, 'facility-calendar-mobile');
  await visitor.page.setViewportSize({ width:1365, height:900 });
  await audit(visitor.page, 'facility-calendar-desktop');
  report.checks.push('Facilities support multiple daily slots and seasonal priority with local/UTC times');
  await applicant.page.getByRole('link', { name: 'Add closure or replacement hours', exact: true }).click();
  await applicant.page.locator('[name="starts_on"]').fill('2026-06-06');
  await applicant.page.locator('[name="ends_on"]').fill('2026-06-06');
  await applicant.page.locator('[name="kind"]').selectOption('closed');
  await applicant.page.locator('[name="replacement_slots"]').fill('');
  await applicant.page.locator('[name="reason"]').fill('PRIVATE SYNTHETIC CLOSURE');
  await applicant.page.locator('[name="audience"]').selectOption('admins');
  await applicant.page.getByRole('button', { name: 'Save exception', exact: true }).click();
  await applicant.page.waitForURL(facilityManage);
  const closed = await visitor.context.request.get(calendarUrl + '?starts_on=2026-06-06&days=1&format=json');
  const closedData = await closed.json();
  assert.equal(closedData.days[0].slots.length, 0);
  assert.doesNotMatch(JSON.stringify(closedData), /PRIVATE SYNTHETIC CLOSURE/);
  const facilityUrl = `${fixture.origin}/clubs/facilities/${facilityId}/`;
  const publicData = await (await visitor.context.request.get(facilityUrl + '?format=json')).json();
  assert.equal(publicData.address, undefined);
  assert.equal(publicData.latitude, undefined);
  await visitor.page.goto(facilityUrl);
  await audit(visitor.page, 'facility-public-desktop');
  await visitor.page.setViewportSize({ width:390, height:844 });
  await audit(visitor.page, 'facility-public-mobile');
  assert.doesNotMatch(await visitor.page.locator('main').innerText(), /PRIVATE SYNTHETIC FACILITY ADDRESS/);
  report.checks.push('Private precise location and hidden closure reasons stay absent from public HTML and JSON');
  await applicant.page.getByRole('link', { name: 'Manage photos', exact: true }).click();
  await applicant.page.locator('[name="caption"]').fill('Synthetic range landscape');
  await applicant.page.locator('[name="audience"]').selectOption('public');
  await applicant.page.locator('[name="primary"]').check();
  await applicant.page.locator('[name="upload"]').setInputFiles(fixture.evidenceImage);
  await applicant.page.getByRole('button', { name: 'Upload facility photo' }).click();
  await applicant.page.getByRole('button', { name: 'Archive photo' }).waitFor();
  await visitor.page.goto(facilityUrl);
  const imagePath = await visitor.page.getByRole('img', { name:'Synthetic range landscape' }).getAttribute('src');
  assert.equal((await visitor.context.request.get(new URL(imagePath, fixture.origin).href)).status(), 200);
  await applicant.page.getByRole('button', { name: 'Archive photo' }).click();
  assert.equal((await visitor.context.request.get(new URL(imagePath, fixture.origin).href)).status(), 404);
  report.checks.push('Normalized private-storage facility photo works through controlled URL; archival revokes it');
  await applicant.page.goto(facilityManage);
  await audit(applicant.page, 'facility-admin-mobile');
  report.stage = 'M5 group programmes';
  const programmeCoach = await actor('coach');
  const groupCreate = `${fixture.origin}/clubs/${fixture.publicClub}/training-groups/new/`;
  await openWithMfa(applicant.page, groupCreate);
  await applicant.page.locator('[name="name"]').fill('Synthetic M5 coaching group');
  await applicant.page.locator('[name="description"]').fill('Synthetic group instruction space');
  await applicant.page.locator('[name="discipline"]').selectOption('recurve');
  await applicant.page.locator('[name="coach_role"]').selectOption(fixture.programmeCoachRole);
  await applicant.page.locator('[name="active"]').check();
  await applicant.page.getByRole('button', { name:'Save training group', exact:true }).click();
  await applicant.page.waitForURL(/\/clubs\/training-groups\/[a-f0-9-]+\/$/);
  const groupUrl = applicant.page.url();
  await openWithMfa(programmeCoach.page, groupUrl);
  await programmeCoach.page.getByRole('link', { name:'Invite a club member to the group' }).click();
  await programmeCoach.page.locator('[name="membership"]').selectOption({ label:'Synthetic new member' });
  await programmeCoach.page.getByRole('button', { name:'Invite club member', exact:true }).click();
  await outsider.page.goto(`${fixture.origin}/clubs/programmes/`);
  await outsider.page.getByRole('link', { name:'Respond or leave group', exact:true }).click();
  await outsider.page.locator('[name="decision"]').selectOption('accept');
  await outsider.page.getByRole('button', { name:'Confirm group response', exact:true }).click();
  await outsider.page.waitForURL(`${fixture.origin}/clubs/programmes/`);
  await programmeCoach.page.goto(groupUrl);
  await programmeCoach.page.getByRole('link', { name:'Create a programme template' }).click();
  await programmeCoach.page.locator('[name="title"]').fill('Synthetic M5 programme');
  await programmeCoach.page.locator('[name="instructions"]').fill('Synthetic group guidance retained as a source copy.');
  await programmeCoach.page.locator('[name="start_date"]').fill(fixture.programmeStart);
  await programmeCoach.page.locator('[name="duration_days"]').fill('84');
  await programmeCoach.page.locator('[name="archetype"]').selectOption('stamina_builder');
  await programmeCoach.page.locator('[name="round_format"]').selectOption('wa_720_70m');
  await programmeCoach.page.locator('[name="sessions-0-weekday"]').selectOption('0');
  await programmeCoach.page.locator('[name="sessions-0-start_time"]').fill('18:00');
  await programmeCoach.page.locator('[name="sessions-0-duration_mins"]').fill('90');
  await programmeCoach.page.locator('[name="sessions-0-description"]').fill('Synthetic technical practice');
  await programmeCoach.page.getByRole('button', { name:'Add another weekly session' }).click();
  await programmeCoach.page.locator('[name="sessions-1-weekday"]').selectOption('2');
  await programmeCoach.page.locator('[name="sessions-1-start_time"]').fill('18:00');
  await programmeCoach.page.locator('[name="sessions-1-duration_mins"]').fill('60');
  await programmeCoach.page.locator('[name="sessions-1-description"]').fill('Synthetic focus practice');
  await audit(programmeCoach.page, 'programme-template-desktop');
  await programmeCoach.page.setViewportSize({ width:390, height:844 });
  await audit(programmeCoach.page, 'programme-template-mobile');
  await programmeCoach.page.getByRole('button', { name:'Save template revision', exact:true }).click();
  await programmeCoach.page.waitForURL(/\/clubs\/programmes\/[a-f0-9-]+\/$/);
  const programmeUrl = programmeCoach.page.url();
  await programmeCoach.page.locator('[name="action"]').selectOption('publish');
  await programmeCoach.page.getByRole('button', { name:'Confirm programme action', exact:true }).click();
  await programmeCoach.page.getByRole('link', { name:'Offer programme to an accepted group member' }).click();
  await programmeCoach.page.locator('[name="member"]').selectOption({ label:'Synthetic new member' });
  await programmeCoach.page.getByRole('button', { name:'Offer programme for consent', exact:true }).click();
  await outsider.page.goto(`${fixture.origin}/clubs/programmes/`);
  await outsider.page.getByRole('link', { name:'Synthetic M5 programme', exact:true }).click();
  const assignmentUrl = outsider.page.url();
  const assignmentId = new URL(assignmentUrl).pathname.split('/').at(-2);
  await audit(outsider.page, 'programme-consent-mobile');
  await outsider.page.locator('[name="decision"]').selectOption('accept');
  await outsider.page.locator('[name="private_note"]').fill('PRIVATE SYNTHETIC CUSTOMIZATION');
  await outsider.page.locator('[name="individual-competition_tier"]').selectOption('A');
  await outsider.page.locator('[name="individual-current_draw_weight"]').fill('30');
  await outsider.page.locator('[name="individual-weekly_arrows"]').fill('200');
  await outsider.page.locator('[name="individual-days"][value="5"]').check();
  await outsider.page.getByRole('button', { name:'Confirm programme response', exact:true }).click();
  await outsider.page.waitForURL(assignmentUrl);
  assert.deepEqual(await outsider.page.locator('.errorlist').allTextContents(), [], 'Programme response has validation errors');
  for (let attempt=0; attempt<60; attempt++) {
    await outsider.page.goto(assignmentUrl);
    if (/Version 1[^]*ready/.test(await outsider.page.locator('main').innerText())) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  assert.match(await outsider.page.locator('main').innerText(), /Version 1[^]*ready/);
  await outsider.page.getByRole('link', { name:'Open personal draft version 1', exact:true }).click();
  const personalPlanUrl = outsider.page.url();
  assert.match(await outsider.page.locator('main').innerText(), /Accepted group programme/);
  await audit(outsider.page, 'programme-personal-draft-mobile');
  await outsider.page.goto(assignmentUrl);
  await outsider.page.locator('[name="progress-completed_sessions"]').fill('1');
  await outsider.page.locator('[name="progress-private_note"]').fill('PRIVATE SYNTHETIC PROGRESS NOTE');
  await outsider.page.getByRole('button', { name:'Save private progress report' }).click();
  await outsider.page.waitForURL(assignmentUrl);
  await audit(outsider.page, 'programme-progress-owner-mobile');
  const progressUrl = `${fixture.origin}/clubs/programme-assignments/${assignmentId}/coach-progress/?format=json`;
  assert.equal((await programmeCoach.context.request.get(progressUrl)).status(), 404);
  assert.equal((await programmeCoach.context.request.get(assignmentUrl)).status(), 404);
  assert.equal((await programmeCoach.context.request.get(personalPlanUrl)).status(), 404);
  await outsider.page.goto(`${fixture.origin}/clubs/athletes/${fixture.memberAthlete}/sharing/`);
  await outsider.page.locator('[name="club"]').selectOption(fixture.publicClub);
  await outsider.page.locator('[name="grantee"]').selectOption(fixture.programmeCoachUser);
  await outsider.page.locator('input[name="scopes"][value="programme_progress"]').check();
  await outsider.page.locator('[name="purpose"]').fill('Synthetic session-count review only');
  await outsider.page.locator('[name="starts_at"]').fill(fixture.checkedAt);
  await outsider.page.locator('[name="expires_at"]').fill(fixture.expiresAt);
  await outsider.page.getByRole('button', { name:'Grant access', exact:true }).click();
  const progressResponse = await programmeCoach.context.request.get(progressUrl);
  assert.equal(progressResponse.status(), 200);
  const progressBody = await progressResponse.text();
  assert.doesNotMatch(progressBody, /PRIVATE SYNTHETIC/);
  assert.equal(JSON.parse(progressBody).progress[0].completed_sessions, 1);
  report.checks.push('Programme acceptance generates an independent personal draft; private notes stay owner-only and progress requires separate consent');
  await outsider.page.goto(assignmentUrl);
  await outsider.page.locator('[name="decision"]').selectOption('withdraw');
  await outsider.page.getByRole('button', { name:'Confirm programme response', exact:true }).click();
  assert.equal((await programmeCoach.context.request.get(progressUrl)).status(), 404);
  await openWithMfa(programmeCoach.page, programmeUrl);
  await programmeCoach.page.locator('[name="action"]').selectOption('archive');
  await programmeCoach.page.getByRole('button', { name:'Confirm programme action', exact:true }).click();
  assert.equal((await outsider.context.request.get(personalPlanUrl)).status(), 200);
  report.checks.push('Withdrawal revokes programme progress access and archival preserves the athlete-owned draft');
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
