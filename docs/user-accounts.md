# Accounts implementation (feature/user-accounts)

Open registration uses Google OAuth via django-allauth. Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET as server-side environment variables; never commit credentials. Google OAuth authorised redirect URI: https://YOUR_HOST/accounts/google/login/callback/.

One stable Django User can hold multiple UserRole rows. Archer and Parent/guardian are self-service; Coach is administrator-assigned. A role alone NEVER grants access to an athlete's private records. Parent-child and coach-athlete links, guardian consent, and object permissions must be implemented and tested before exposing athlete data.

Run database migrations and tests separately before releasing. Keep this branch out of main and production until Google OAuth credentials, correct callback URLs, HTTPS settings, minor safeguarding and access-control checks are finished.
