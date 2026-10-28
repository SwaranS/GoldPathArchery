# Role-based account UI — Codex implementation handoff

Date: 28 October 2026
Target branch: `feature/user-accounts`
Status: Documented for implementation; this document does not implement UI changes.

## Problem and intended outcome

An account that has selected Archer only currently sees **My athletes** as a primary menu item. This language and entry point suggest a coach managing other athletes rather than an archer managing their own training.

Give each user navigation appropriate to their selected roles, while preserving access through existing explicit relationships. Role selection changes presentation and setup options; it never grants permission to athlete data.

The immediate priority is the Archer-only experience. Do not build unimplemented training features merely to populate a menu.

## Sources and precedence

Read these alongside this handoff:

- `01-product-decisions.md`
- `03-roles-and-permissions.md`
- `04-user-flows.md`
- `docs/user-accounts.md`
- `docs/relationships.md`

This handoff clarifies navigation and screen organisation. It does not change age rules, relationship authority, or the permission matrix in those documents. Reuse the existing permission boundary in `accounts.permissions`; do not infer authority from visible menus, role declarations, or URL parameters.

## Required current-screen experience

### Archer only

Primary signed-in navigation:

- **My profile** — the signed-in user's own athlete profile, or an eligible own-profile setup screen if none exists.
- **My connections** — coaches and guardians connected to that own athlete profile, with actions allowed by current permissions.
- **My account** — account identity, role preferences, and sign-out.

Do not show **My athletes**, **Coaching**, or **Family** as primary navigation for an Archer-only account. A coach invitation belongs in My connections; inviting a coach does not make the archer a coach.

After normal sign-in, take an Archer-only user to their own profile or setup journey rather than the generic athlete list or role-editing form. Preserve an explicit, validated invitation destination and the existing age-16 parent-access review journey before applying the ordinary landing-page default.

If no own profile exists, explain how to create an eligible profile or claim an existing profile through a private invitation. Do not create a second profile when the account already owns one, including an invited junior profile. Do not offer under-16 users ordinary self-profile creation as a substitute for the junior invitation flow.

### Parent/Guardian

Use **Family** as the parent entry point. Show only explicitly linked profiles and each profile's current access level. Support several children without requiring separate parent accounts.

Opening a child selects that child's profile explicitly. Show the child's name prominently on every edit, invitation, and confirmation screen. Keep child-profile setup separate from own-profile setup.

### Coach

Use **Coaching** as the workspace entry point and **My athletes** as its linked-athlete list. Show accepted, currently accessible coach relationships only, with **View only** or **Can edit plans** labels.

An account selecting Coach without relationships sees an empty state explaining private invitations, not an athlete directory or private records. Profile editing, scoring, grants, export, and closure must not become available through the coaching workspace.

### Multiple roles and existing relationships

Use distinct **My training**, **Family**, and **Coaching** workspaces where applicable. The training workspace initially contains My profile and My connections; it can acquire training navigation when those features exist.

For multiple selected roles, make workspace choice explicit. Recommended default: remember the last valid workspace; otherwise offer a workspace choice. A single-role account enters its appropriate destination directly.

Role removal does not revoke relationships. Preserve a secondary **All linked athletes** destination, reachable from My account, so an account can still reach profiles it is authorised to access after changing role preferences. This destination does not justify retaining a coach-oriented primary menu on Archer-only accounts. Show creation controls only where existing role and eligibility rules allow them.

Workspace selection and athlete selection are separate. Switching workspaces must not silently retarget an edit or scoring form. Handle unsaved work explicitly before changing the target.

Where a user has several relationships to the same athlete, check each operation against the existing permission model. Entering Coaching neither grants extra authority nor revokes authority the user holds through another valid relationship; make the acting context and available actions clear.

## Junior and parent access

- **Under 14:** parent-managed profile; no child login.
- **14–15:** optional invited login to the existing profile; own profile/training is view-only. No writing, invitations, scoring, export, or closure. Selecting additional roles must not bypass these restrictions.
- **16+:** athlete controls their own training and relationships. At local midnight on the birthday, existing parent editing becomes viewing, even without a login or scheduler run. Preserve the existing request-time safeguards.
- On the athlete's next login after turning 16, retain the parent-access review journey with separate view/edit/no-access choices for each parent. Never restore revoked links automatically.
- If the athlete has no login at 16, allow the existing private claim flow without continuing parental editing in the meantime.
- Parent editing explicitly granted after 16 excludes grant administration, export, and closure.

Do not display sensitive fields to coaches merely because a common profile template is reused. Preserve the existing training-field allowlist.

## Future training navigation — design direction, not current scope

When the underlying features exist, My training should lead to **Today**, with **Plans**, **Score**, **Progress**, and **Equipment** navigation. Profile and connections remain accessible.

The Archer dashboard prioritises today's sessions, unfinished rounds, logging practice, the week ahead, and released plan recommendations. Rest days need no log; absent activity remains unknown rather than automatically skipped.

Family should provide a card per child with today's training and actionable notices. Coaching should prioritise linked athletes, plan review, progress, and shared feedback. Coaches may view score history but cannot enter or correct actual logs or scores.

Do not add dead links, fabricated progress, or working-looking controls for features that have no handlers. Plan Manager and Administrator workspaces are separate future concerns and cannot be enabled through self-selected account roles.

## States and interaction requirements

- Provide meaningful empty states for no own profile, no children, and no coaching relationships.
- Preserve valid form entries after errors and give a clear result after writes.
- Show current access accurately; recheck permission on every request and submission.
- A revoked link, expired invitation, closed profile, or age transition must not leave actionable stale controls or permit stale submissions.
- Handle direct links and denied access without exposing another athlete's identity or private data.
- Preserve mobile usability, keyboard navigation, visible focus, meaningful labels, and the existing skip link.
- Keep public home and Google-only sign-in available. Signed-in home/brand navigation should lead to the appropriate valid workspace.

## Acceptance checks

1. Archer-only user with an own profile sees My profile, My connections, and My account; no primary My athletes, Family, or Coaching menu.
2. Archer-only user without an own profile sees an appropriate setup/claim state, with no duplicate-profile or junior-rule bypass.
3. A coach connection appears under the archer's My connections and does not activate the coaching workspace.
4. Coach-only user sees Coaching/My athletes containing only accepted, accessible coach links. Selecting Coach alone exposes no private athlete records.
5. Parent-only user can select among multiple linked children; every mutation clearly names its target.
6. An account with all three roles can switch workspaces without silently changing the target athlete or losing unsaved work.
7. Removing a role does not end relationships; previously authorised profiles remain reachable through All linked athletes. No new permission is granted.
8. A junior aged 14–15 remains view-only even after selecting Coach or Parent/Guardian. Under-14 profiles have no child login.
9. At 16, existing parent editing stops and the athlete's review flow remains available. An explicit post-16 parent editing grant still excludes grants, export, and closure.
10. View-only coaches cannot edit plans; plan-edit coaches cannot edit profiles, actual logs/scores, activate/share plans, administer grants, export, or close profiles.
11. Unrelated, revoked, inactive, and closed-account requests remain denied through direct URLs and POST requests, not only through hidden controls.
12. Private invitation sign-in/acceptance and the Google-only login template regression continue to work. Invitation acceptance remains explicit and recipient-bound.
13. Current navigation contains no dead links to future training features.

Use focused routing/template tests and existing relationship/age tests to verify these behaviours. Run relevant account tests and Django checks; report actual results and any unverified environment-specific behaviour.

## Repository and environment precautions

- This handoff was prepared from the Windows checkout at `C:\Users\swara\OneDrive\Documents\ChatGPT\GoldPathArchery 2`.
- Docker at `localhost:8000` serves a separate WSL Ubuntu checkout at `/home/swaran-u/projects/GoldPathArchery`. Editing Windows files alone does not update that running site. Verify the checkout being edited and tested before reporting a browser result.
- At review time, `app/config/settings.py` and `app/accounts/tests.py` had existing uncommitted changes for the Google-only login override and regression test. Preserve them. The template setting is `TEMPLATES DIRS = [BASE_DIR / 'accounts' / 'templates']` so the project override takes precedence over allauth.
- The supplied context identifies the CSRF referrer-policy fix as Windows commit `2232fed` and WSL commit `c8473dc`. Confirm the active checkout rather than assuming those histories are identical.
- Inspect current changes before editing. Do not overwrite unrelated work, `.env` files, or backups. Do not copy an entire checkout over the other environment.
- Implement and report the UI changes separately from this documentation task. Deployment, merging, and environment synchronisation are not authorised by this document alone.
