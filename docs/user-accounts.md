# Accounts implementation (feature/user-accounts)

## Role-based navigation

Normal sign-in and the signed-in home page route through `/account/start/`.
Archer accounts open their own profile or eligible setup screen, with **My profile**,
**My connections**, and **My account** navigation. Parent accounts open **Family**;
coaches open **Coaching**, containing only their active linked athletes. Multiple-role
accounts choose a workspace initially; the session remembers the last valid choice.
Private invitation destinations and the age-16 parent-access review retain priority.

Workspace-specific profile creation separates own and child setup. Existing creation
permissions and age restrictions still apply. **All linked athletes** remains available
from My account, including after role removal. Workspace selection never grants or
revokes athlete access. Profile actions use all current explicit permissions, including
when a user holds several relationships to one athlete. Changed forms warn before
leaving the page. No future training-feature links have been added.

See `docs/role-based-ui-handoff.md` for the design and acceptance criteria, and
`app/accounts/test_navigation.py` for focused routing/access coverage. The initial implementation was created in Windows. It has also been merged into
the Linux checkout while preserving the existing Linux UI styling. All 72 account
tests passed against the Linux Docker/PostgreSQL setup during this merge.

Open registration uses Google OAuth via django-allauth. Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET as server-side environment variables; never commit credentials. Google OAuth authorised redirect URI: https://YOUR_HOST/accounts/google/login/callback/.

One stable Django User can hold multiple UserRole rows. Archer, Parent/Guardian and Coach are all self-selectable and removable on the account profile. Any combination is supported, including Coach + Parent/Guardian + Archer. Saving replaces the selected roles; existing selections are shown when returning to the form.

A role alone NEVER grants access to an athlete's private records, Django permissions, groups or administrator privileges. Coach is a declared role, not a grant to browse athletes. Stable athlete profiles, declared parent links, private recipient-bound invitations, junior login claims and revocable coach/parent grants are now implemented. Unrelated, pending or revoked relationships deny access, regardless of selected roles or staff status. See [relationships](relationships.md) for the permission rules, screens, tests and outstanding work.

Run database migrations and tests separately before releasing. Keep this branch out of main and production until Google OAuth credentials, correct callback URLs, HTTPS settings, minor safeguarding and access-control checks are finished.
