# Accounts implementation (feature/user-accounts)

Open registration uses Google OAuth via django-allauth. Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET as server-side environment variables; never commit credentials. Google OAuth authorised redirect URI: https://YOUR_HOST/accounts/google/login/callback/.

One stable Django User can hold multiple UserRole rows. Archer, Parent/Guardian and Coach are all self-selectable and removable on the account profile. Any combination is supported, including Coach + Parent/Guardian + Archer. Saving replaces the selected roles; existing selections are shown when returning to the form.

A role alone NEVER grants access to an athlete's private records, Django permissions, groups or administrator privileges. Coach is a declared role, not a grant to browse athletes. Athlete-record models and endpoints are not implemented yet. Explicit parent-child and accepted coach-athlete relationships/invitations, guardian consent, and operation-specific object permissions must be implemented and tested before exposing athlete data. Unrelated, pending or revoked relationships must deny access, regardless of selected roles.

Run database migrations and tests separately before releasing. Keep this branch out of main and production until Google OAuth credentials, correct callback URLs, HTTPS settings, minor safeguarding and access-control checks are finished.
