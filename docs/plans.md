# Archer Plans and planning setup

Implemented in the Linux checkout on feature/user-accounts.

Choose Plans from the Archer menu or selected athlete profile. No accessible own
profile leads to a profile setup/claim explanation. Plans names the selected athlete
and shows No plan yet. Eligible profile editors can save an incomplete draft, return
to it, and submit when essential details are complete. Defaults: 84 days and Monday
for requested weekly review. Supported requested length: 1-365 days.

Goals and availability start from the profile; saving the brief does not overwrite
profile fields. Discipline stays sourced from the profile. Experience, current
weekly sessions/arrows (including zero), available days/time, range access/distances
and equipment are required for submission. Competition date is optional. Submitted
briefs are read-only; replay does not create duplicates or overwrite submitted text.

## Permissions and consistency

Viewing uses existing accessible-athlete scope and view permission. Editing uses
edit_profile: own athlete 16+, managing editing parent under 16, or an explicit
post-16 parent editing grant. Juniors 14-15 and view-only parents can read. Linked
coaches can read training fields but cannot change setup, even with plan editing.
Role selection and staff flags do not grant access. Revocation, closure and age
rules apply on direct requests and under the athlete row lock on writes.

Successful saves increment the shared athlete version. Stale writes return 409
with entries preserved. Audit metadata records actor and operation without the
planning text. POST requires CSRF. Migration 0004_plansetup adds a single brief per
stable athlete. It is not registered in routine admin. Future closure/anonymisation
must include this text; that lifecycle remains unimplemented across the app.

## Scope boundary

Submitting stores the brief only. Manager assignment/delivery, AI generation,
published plans, activation, sharing and recommendations are not connected yet.
The page explicitly says preparation has not started. No fake plan or active-plan
state is shown. End-to-end plan delivery is separate work.

## Validation

Run the account tests and Django checks in Docker. accounts.test_plans covers the
empty state, navigation, draft persistence, validation, zero volume, replay, stale
edits, coach denial, junior restrictions, parent age transitions, revocation,
closed/inactive/unrelated access, login and CSRF.
