# Athlete profiles and relationships

Implemented on `feature/user-accounts`, following `03-roles-and-permissions.md` and D04–D06. No deployment or merge to main is part of this work.

## Using the screens

Sign in through the existing Google flow, select all applicable account roles, then open **My athletes and connections** from My account. Roles can coexist; selecting Coach never exposes an athlete.

- Archer: create your own 16+ athlete profile.
- Parent/Guardian: create multiple child profiles below 16 after declaring guardianship. Profiles have their own UUIDs and do not require a login. Choose an athlete explicitly from My athletes.
- Managing parent: invite another guardian, a coach or, from age 14, a junior login using the recipient's Google email. A junior claim links the existing athlete record and keeps its ID. Under-14 profiles cannot be linked to a login. A login can own at most one athlete profile.
- Private invitations: copy the link shown once and deliver it privately. No automatic email is sent. Accept using the matching verified account; choose the required Coach/Parent role first. A guardian accepting a child invitation must also declare guardianship. GET never grants access or reveals the target.
- Athlete 16+ / managing parent below 16: grant coach view/plan-edit access, update parent permissions, or revoke invitations and relationships. Coaches can end their own relationship but cannot grant themselves editing. A removed relationship needs a fresh invitation to restart.
- A child's last managing parent cannot end or downgrade their own link until another managing parent accepts an invitation. This prevents orphaned children.

## Age and operation rules

Age uses declared birth date in the profile's validated IANA timezone (Europe/Dublin default). Ages 14–15 can view their own profile but cannot write, score, invite, manage grants, export or close. Under 14 has no athlete login. Linking an account to a profile does not copy training history.

At local midnight on the 16th birthday, request-time checks stop parent editing, exporting, closing and managing grants even without a scheduler. The idempotent transition downgrades existing editing to viewing, preserves revoked links, records audit metadata, creates durable in-app notices and prompts the athlete to review each parent's view/edit/none permissions on next sign-in. The athlete explicitly confirms review. Parents can still issue a private login claim for an unclaimed 16+ profile; this does not restore parent editing. Explicit adult parent editing includes the profile, plans and logs/scores, but never grants administration, exports or closure.

Run `python manage.py process_age_transitions` regularly (for example every minute) using your local scheduler/worker to persist notices near the birthday when nobody is browsing. The same transition runs on account and athlete screens. No external scheduler has been provisioned. Notification delivery is in-app, not email.

`accounts.permissions.can(actor, athlete, operation)` is the shared deny-by-default permission boundary. Supported operations are `view`, `edit_profile`, `edit_plan`, `activate_plan`, `log_scores`, `manage_grants`, `export` and `close`. Unknown operations deny access. Active coaches may view the training allowlist; explicit plan editing never permits scores, actual logs, profile editing, plan activation/sharing, grants, export or closure. Staff/superuser flags do not confer athlete access. Inactive users and closed profiles deny access.

`accessible_athletes` scopes lists to own or explicitly linked, unrevoked profiles. No public or signed-in directory is exposed in this slice, so hidden/under-16 profiles are never discoverable by unrelated accounts. Coach detail responses contain display name, discipline, goals, availability and version only; exact birth date, account email and other relationships are excluded. Athlete/account pages disable browser caching.

## Transaction and invitation guarantees

Writes lock the athlete row before checking current grants. Forms carry the athlete version; stale profile/grant/invitation edits return HTTP 409 without overwriting current state. Claims also lock the login account. PostgreSQL must be used to validate row-lock concurrency; SQLite tests do not exercise those locks.

Invitation secrets use 32 random bytes and only SHA-256 digests are stored. Tokens expire after seven days, accept once, require a matching allauth verified email, and recheck sender authority at acceptance. No access comes from forwarding/opening a link. Revocation immediately removes live access and invalidates outstanding tokens addressed to the removed party and tokens they issued. Replaying an old invitation cannot restore an ended relationship. Invalid/expired/forwarded acceptance returns a uniform unavailable response. Mutation routes require login, POST and CSRF.

Successful relationship/profile mutations and age transitions record minimal actor/athlete/operation/target/time audit metadata, without training content, raw tokens or recipient emails. Application audit records are not a complete operational security log. Reverse proxy and web-server logs must redact private invitation URL paths, including in development; do not share raw request logs containing invitation links. Grant changes are serialized and versioned; grant history remains subject to the athlete's live permissions. Relationship models are intentionally not registered for routine Django admin browsing.

## Validation

From the repository root, with requirements installed:

```sh
python app/manage.py test accounts --settings=config.test_settings
python app/manage.py check --settings=config.test_settings
python app/manage.py makemigrations --check --dry-run --settings=config.test_settings
```

The explicit `accounts` test label matters when running from the repository root. The separate SQLite test settings use only a throwaway database and synthetic secret; production/PostgreSQL settings and Google configuration are unchanged. Migration `0003_athleteprofile_relationshipaudit_and_more` creates the relationship tables; there is no existing athlete data to migrate.

For the planned PostgreSQL/Docker verification, run with your existing local `.env`:

```sh
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py test accounts
docker compose run --rm web python manage.py process_age_transitions
```

Also exercise simultaneous token acceptance, claim-versus-own-profile creation and grant/revocation writes against PostgreSQL, then smoke-test real Google sign-in with your configured callback. Automated Google regression tests mock external token/userinfo calls while exercising the actual OAuth initiation, state, callback, session and stable User/profile link.

## Remaining product work

This is the relationship/profile foundation, not the rest of the MVP. The following are not implemented by this branch change:

- Reauthenticated birth-date/timezone corrections and account transfer. These fields cannot be changed through profile editing; this prevents reversing age transitions through ordinary edits.
- Discovery/search and coach-initiated connection requests. All current coach invitations are initiated by the eligible athlete/managing parent, including for hidden and junior profiles. Hidden settings are stored for future discovery.
- Email delivery of invitations/birthday notices, invitation inbox and notification dismissal. Links are delivered manually; notices are durable in-app.
- Plan/session/score/equipment/report/export/closure handlers, manager assignments, private coach notes and authored contribution snapshots. Operation permissions exist for later handlers, which must recheck them for each live/history request and job. There is no coach contribution content to retain yet. Profile `closed_at` is enforced as a deny gate, not exposed as an unreauthenticated closure workflow.
- Full closure/anonymisation, audit retention and backup restoration jobs. This slice does not claim those launch requirements are complete.
- PostgreSQL row-lock/concurrency, Docker integration, and live Google provider testing remain local follow-up validation.
