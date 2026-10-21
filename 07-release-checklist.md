# GoldPathArchery — Pilot and Production Release Checklist

Status: Template; nothing checked means no completion claim  
Related: [delivery plan](06-delivery-plan.md), [architecture](05-architecture.md)

## Product readiness

- [ ] Pilot participants, included roles and success measures agreed.
- [ ] MVP requirements and outstanding limitations reviewed.
- [ ] Core journey tested with representative accounts on mobile.
- [ ] Loading, empty, validation and error states reviewed.
- [ ] Junior/guardian requirements completed before including juniors.
- [ ] Support contact and feedback process established.

## Access and data

- [ ] Sign-in, sign-out, verification and recovery work as designed.
- [ ] Object-level access tests cover own, linked and unrelated records.
- [ ] Revoked coach/guardian access is enforced on subsequent requests.
- [ ] Administrator actions and support access follow the approved policy.
- [ ] Production configuration contains no development credentials.
- [ ] Data collection, retention, export and deletion procedures agreed.
- [ ] Privacy information and applicable junior/guardian requirements reviewed for the actual service.

## Operations

- [ ] Hosting region, service limits and monthly budget agreed.
- [ ] Staging and production data/credentials are separated.
- [ ] Automated deployment and required checks pass.
- [ ] Production migrations validated against a representative environment.
- [ ] Backup policy configured and a restore successfully rehearsed.
- [ ] Recovery point/time targets documented.
- [ ] Health monitoring and error alerts reach the responsible operator.
- [ ] Logs exclude credentials and unnecessary personal information.
- [ ] Application rollback and migration compatibility procedures rehearsed.
- [ ] Domain ownership, DNS, HTTPS and renewal responsibility confirmed.
- [ ] Email delivery configured and tested if used.

## Release execution

- [ ] Record release version/commit and known limitations.
- [ ] Confirm migration and backup prerequisites.
- [ ] Deploy the reviewed version.
- [ ] Verify public homepage and authenticated core journey in production.
- [ ] Verify access denial with an unrelated test account.
- [ ] Confirm monitoring and error reporting after deployment.
- [ ] Observe pilot feedback before expanding access.

## Release record

| Field | Value |
|---|---|
| Release owner | TBD |
| Domain | TBD |
| Version / commit | TBD |
| Release date | TBD |
| Pilot success targets | TBD |
| Known limitations | TBD |
| Rollback procedure / version | TBD |
| Backup restore evidence | TBD |
| Review outcome | TBD |
