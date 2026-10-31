"""Local-only M1 rehearsal. Creates and drops ONLY new disposable databases.

Uses config.clubs_test_settings' fixed localhost:55440 test account. Never reads
deployment credentials, contacts a federation, provisions Azure, or deploys code.
Browser sessions and all verification outcomes are synthetic. Artifacts stay ignored.
"""
import argparse
from datetime import date, datetime, timedelta, timezone as utc_timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "app")]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass  # Do not log request/query/session payloads.


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def db_identifier(name):
    from psycopg import sql
    if not re.fullmatch(r"clubs_validation_[a-f0-9]{12}(?:_restore)?", name):
        raise ValueError("Refusing any database outside this run's disposable namespace")
    return sql.Identifier(name)


def legacy_fixture():
    from accounts.models import User, UserRole, AthleteProfile, GuardianLink
    from scoring.models import Equipment, EquipmentRevision, TargetFace, ScoringRuleSet, RoundDefinition, RoundStage
    from scoring import services as scoring
    from training.models import GeneratedPlan
    from django.utils import timezone
    actor = User.objects.create_user(username="synthetic-legacy-athlete")
    UserRole.objects.create(user=actor, role="archer")
    athlete = AthleteProfile.objects.create(account=actor, display_name="Synthetic legacy athlete",
        birth_date=date(1990, 1, 1), discipline="recurve", transitioned_at=timezone.now())
    child = AthleteProfile.objects.create(display_name="Synthetic guardian-managed junior",
        birth_date=date(2015, 1, 1), discipline="recurve")
    guardian = GuardianLink.objects.create(athlete=child, parent=actor, managing=True, access="edit")
    equipment = Equipment.objects.create(athlete=athlete, name="Synthetic legacy bow", kind="bow", division="recurve")
    revision = EquipmentRevision.objects.create(equipment=equipment, number=1, name=equipment.name, division="recurve")
    target = TargetFace.objects.create(name="Synthetic 40cm", diameter_cm=40,
        geometry=dict(spots=[[0, 0, 1]], rings=[.05, .1, 1]))
    rules = ScoringRuleSet.objects.create(name="Synthetic scoring", rules=dict(zones=[
        dict(radius=.05, symbol="X", points=10, x=True), dict(radius=.1, symbol="10", points=10),
        dict(radius=1, symbol="1", points=1)]))
    round_ = RoundDefinition.objects.create(name="Synthetic legacy round", division="recurve")
    RoundStage.objects.create(round=round_, order=1, distance_m=18, target=target, rules=rules, ends=1, arrows_per_end=3)
    session = scoring.start(actor, athlete, dict(mode="round", context="training", round=round_.pk, bow=equipment.pk))
    for position, symbol in enumerate(["X", "10", "M"]):
        session.refresh_from_db()
        scoring.mutate(actor, session.pk, dict(key=str(uuid.uuid4()), version=session.version,
            action="shot", position=position, symbol=symbol, method="manual"))
    for action in ("review", "complete"):
        session.refresh_from_db()
        scoring.mutate(actor, session.pk, dict(key=str(uuid.uuid4()), version=session.version, action=action))
    plan = GeneratedPlan.objects.create(athlete=athlete, requested_by=actor, status="draft",
        inputs={"synthetic": True}, roadmap={"synthetic_preserved_plan": True})
    scopes = [(actor._meta.label, [actor.pk]), (athlete._meta.label, [athlete.pk, child.pk]),
        (guardian._meta.label, [guardian.pk]), (equipment._meta.label, [equipment.pk]),
        (revision._meta.label, [revision.pk]), (session._meta.label, [session.pk]),
        ("scoring.ArrowShot", list(session.shots.values_list("pk", flat=True))),
        ("scoring.ScoreChangeAudit", list(session.audit.values_list("pk", flat=True))),
        (plan._meta.label, [plan.pk])]
    return scopes, athlete, child


def fingerprint(scopes):
    from django.apps import apps
    rows = {label: list(apps.get_model(label).objects.filter(pk__in=ids).order_by("pk").values()) for label, ids in scopes}
    encoded = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "counts": {label: len(values) for label, values in rows.items()}}


def browser_fixture(output, athlete):
    from allauth.account.models import EmailAddress
    from allauth.mfa.totp.internal.auth import TOTP
    from accounts.models import User
    from clubs import services
    from clubs.models import KnownClubListing
    from django.contrib.auth.models import Permission
    from django.conf import settings
    from django.test import Client
    from django.utils import timezone
    from PIL import Image
    actors = {}
    sessions = {}
    for name in ("applicant", "reviewer", "outsider"):
        user = actors[name] = User.objects.create_user(username=f"synthetic-{name}", email=f"{name}@example.test",
            is_staff=name == "reviewer")
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        client = Client()
        client.force_login(user)
        sessions[name] = client.cookies[settings.SESSION_COOKIE_NAME].value
    reviewer = actors["reviewer"]
    reviewer.user_permissions.add(Permission.objects.get(codename="review_club_claim"))
    secret = "JBSWY3DPEHPK3PXP"  # Synthetic local fixture, never a real user's secret.
    TOTP.activate(reviewer, secret)
    TOTP.activate(actors["applicant"], secret)
    TOTP.activate(actors["outsider"], secret)
    from accounts.models import AthleteProfile
    member_athlete = AthleteProfile.objects.create(account=actors["outsider"], display_name="Synthetic new member", birth_date=date(1990, 1, 1), discipline="recurve")
    listing = KnownClubListing.objects.create(name="Synthetic known validation club", country="Ireland",
        source_url="https://official.example.test/synthetic-directory", reviewed_on=timezone.now().date())
    claim = services.submit_claim(actors["applicant"], dict(name="Synthetic public validation club", country="Ireland",
        region="", town="Synthetic town", website="https://example.test", description="Synthetic public fixture only",
        visibility="public", timezone="Europe/Dublin", role_assertion="Synthetic fixture secretary", listing=None))
    services.record_evidence(reviewer, claim.pk, dict(source_url="https://official.example.test/synthetic-public",
        contact_reference="Synthetic contact", outcome="Synthetic confirmation, not a real club verification",
        confirmed=True, checked_at=timezone.now()-timedelta(hours=1), expires_at=timezone.now()+timedelta(days=1)),
        expected_version=claim.version)
    claim.refresh_from_db()
    club = services.decide_claim(reviewer, claim.pk, decision="approved", reason="Synthetic local fixture only",
        expected_version=claim.version, duplicates_reviewed=True).club
    image = output / "synthetic-evidence.png"
    Image.new("RGB", (64, 48), color="#17343b").save(image)
    return dict(sessions=sessions, cookieName=settings.SESSION_COOKIE_NAME, listing=str(listing.pk),
        publicSlug=club.slug, publicClub=str(club.pk), memberAthlete=str(member_athlete.pk), totpSecret=secret, evidenceImage=str(image), output=str(output),
        checkedAt=timezone.localtime(timezone.now()-timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="minutes"),
        expiresAt=timezone.localtime(timezone.now()+timedelta(days=1)).replace(tzinfo=None).isoformat(timespec="minutes")), actors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run only against newly created disposable local databases")
    parser.add_argument("--browser-cache", help="Optional isolated PLAYWRIGHT_BROWSERS_PATH used when installing Chromium")
    parser.add_argument("--container", default="goldpath-clubs-test-db")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to authorize this disposable local test workflow")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.clubs_test_settings"
    from django.conf import settings
    database = dict(settings.DATABASES["default"])
    if (database["HOST"], str(database["PORT"]), database["USER"]) != ("127.0.0.1", "55440", "clubs_test"):
        raise RuntimeError("Refusing any configuration except the dedicated localhost test database")
    import psycopg
    from psycopg import sql
    suffix = uuid.uuid4().hex[:12]
    source, restore = f"clubs_validation_{suffix}", f"clubs_validation_{suffix}_restore"
    output = REPO / "tests" / "clubs_validation" / "artifacts" / f"run-{suffix}"
    output.mkdir(parents=True, exist_ok=False)
    report = {"synthetic_only": True, "generated_at_utc": datetime.now(utc_timezone.utc).isoformat(),
        "source_revision": subprocess.check_output(["git", "describe", "--always", "--dirty"], cwd=REPO, text=True).strip(),
        "source_database": source, "restore_database": restore, "disposable_databases_removed": False,
        "passed": False, "checks": {}, "errors": []}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    admin = psycopg.connect(host="127.0.0.1", port=55440, user=database["USER"], password=database["PASSWORD"], dbname="postgres", autocommit=True)
    created = []
    server = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(db_identifier(source)))
        created.append(source)
        settings.DATABASES["default"]["NAME"] = source
        settings.SECRET_KEY = secrets.token_urlsafe(40)
        from cryptography.fernet import Fernet
        settings.MFA_ENCRYPTION_KEYS = [Fernet.generate_key().decode("ascii")]
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "release_validation_cache"}}
        settings.CLUB_EVIDENCE_BACKEND = "local"
        settings.CLUB_EVIDENCE_ROOT = str(output / "private-evidence")
        settings.CLUBS_ENABLED = False
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connection, connections
        from django.db.migrations.executor import MigrationExecutor
        from django.test import Client, override_settings
        executor = MigrationExecutor(connection)
        base_targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] not in ("clubs", "mfa")]
        executor.migrate(base_targets)
        scopes, athlete, junior = legacy_fixture()
        baseline = fingerprint(scopes)
        call_command("migrate", verbosity=0, interactive=False)
        call_command("createcachetable", "release_validation_cache", verbosity=0)
        report["checks"]["legacy_records_preserved_after_migration"] = fingerprint(scopes) == baseline
        report["legacy_baseline"] = baseline
        settings.CLUBS_ENABLED = True
        settings.CLUB_MEMBERSHIPS_ENABLED = True
        settings.CLUB_DATA_SHARING_ENABLED = True
        settings.CLUB_FACILITIES_ENABLED = True
        settings.CLUB_FACILITY_PHOTO_BACKEND = "local"
        settings.CLUB_FACILITY_PHOTO_ROOT = str(output / "private-facility-photos")
        fixture, actors = browser_fixture(output, athlete)
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.core.wsgi import get_wsgi_application
        server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), server_class=ThreadedServer, handler_class=QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        fixture["origin"] = f"http://127.0.0.1:{server.server_port}"
        env = dict(os.environ)
        if args.browser_cache:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(args.browser_cache).resolve())
        browser = subprocess.run(["node", str(Path(__file__).with_name("browser.mjs"))], input=json.dumps(fixture),
            text=True, capture_output=True, timeout=300, env=env)
        (output / "browser-command.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
        report["checks"]["browser_and_accessibility"] = browser.returncode == 0
        report["checks"]["legacy_records_preserved_after_browser_workflow"] = fingerprint(scopes) == baseline
        from accounts.permissions import can
        report["checks"]["club_admin_has_no_private_athlete_access"] = not can(actors["applicant"], athlete, "view")
        report["checks"]["guardian_managed_junior_stays_without_login"] = junior.account_id is None
        from clubs.models import Club
        private_club = Club.objects.filter(visibility="private").first()
        if private_club:
            import requests
            report["checks"]["private_profile_exact_url_is_hidden"] = requests.get(
                fixture["origin"] + f"/clubs/{private_club.slug}/", timeout=10).status_code == 404
        with override_settings(CLUBS_ENABLED=False):
            report["checks"]["feature_off_rollback"] = Client(HTTP_HOST="localhost").get("/clubs/").status_code == 404 and fingerprint(scopes) == baseline
        server.shutdown()
        server.server_close()
        server = None
        report["checks"]["legacy_records_preserved_before_backup"] = fingerprint(scopes) == baseline
        from clubs.models import (Club, ClubClaim, ClubAuditEvent, ClubVerificationEvidence,
            ClubMembership, ClubRoleAssignment, ClubClaimDecision, KnownClubListing, ClubSecurityEvent, EvidenceUpload,
            ClubMembershipAction, AthleteHomeClub, AthleteHomeClubHistory, ClubDataGrant,
            ClubFacility, ShootingArea, FacilityAvailabilityRule, FacilityAvailabilityException, FacilityPhoto, FacilityPhotoUpload, FacilityAccessGroup)
        from allauth.mfa.models import Authenticator
        club_models = (Club, ClubClaim, ClubAuditEvent, ClubVerificationEvidence, ClubMembership,
            ClubRoleAssignment, ClubClaimDecision, KnownClubListing, ClubSecurityEvent, EvidenceUpload, Authenticator,
            ClubMembershipAction, AthleteHomeClub, AthleteHomeClubHistory, ClubDataGrant,
            ClubFacility, ShootingArea, FacilityAvailabilityRule, FacilityAvailabilityException, FacilityPhoto, FacilityPhotoUpload, FacilityAccessGroup, FacilityAccessGroup.members.through)
        club_scopes = [(model._meta.label, list(model.objects.values_list("pk", flat=True))) for model in club_models]
        club_baseline = fingerprint(club_scopes)
        report["club_state_baseline"] = club_baseline
        restored_counts = club_baseline["counts"]
        dump = output / "synthetic-backup.dump"
        with dump.open("wb") as stream:
            subprocess.run(["docker", "exec", args.container, "pg_dump", "-U", "clubs_test", "-Fc", "--no-owner", "--no-privileges", "-d", source],
                stdout=stream, stderr=subprocess.PIPE, check=True, timeout=60)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(db_identifier(restore)))
        created.append(restore)
        with dump.open("rb") as stream:
            subprocess.run(["docker", "exec", "-i", args.container, "pg_restore", "-U", "clubs_test", "--no-owner", "--no-privileges", "--exit-on-error", "-d", restore],
                stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=60)
        connections.close_all()
        settings.DATABASES["default"]["NAME"] = restore
        connection.settings_dict["NAME"] = restore
        restored_legacy = fingerprint(scopes)
        report["checks"]["backup_restore_preserves_legacy_data"] = restored_legacy == baseline
        report["checks"]["backup_restore_preserves_club_audit_relations"] = fingerprint(club_scopes) == club_baseline
        from allauth.mfa.adapter import get_adapter
        restored_factors = Authenticator.objects.filter(user_id__in=[actors["applicant"].pk, actors["reviewer"].pk], type="totp")
        report["checks"]["restore_mfa_key_recovery"] = restored_factors.count() == 2 and all(
            get_adapter().decrypt(auth.data["secret"]) == fixture["totpSecret"] for auth in restored_factors)
        report["backup_bytes"] = dump.stat().st_size
        report["club_record_counts"] = restored_counts
        from clubs.facilities import FacilityPhotoStore
        photos = list(FacilityPhoto.objects.all())
        if photos:
            original_photos = Path(settings.CLUB_FACILITY_PHOTO_ROOT)
            restored_photos = output / "restored-facility-photos"
            shutil.copytree(original_photos, restored_photos)
            settings.CLUB_FACILITY_PHOTO_ROOT = str(restored_photos)
            report["checks"]["restore_facility_photo_blobs"] = all(
                hashlib.sha256(FacilityPhotoStore().get(photo.storage_key)).digest() ==
                hashlib.sha256((original_photos / photo.storage_key).read_bytes()).digest() for photo in photos)
        else:
            report["checks"]["restore_facility_photo_blobs"] = False
        from django.utils import timezone
        evidence = ClubVerificationEvidence.objects.filter(storage_key__gt="").first()
        if evidence:
            original_root = Path(settings.CLUB_EVIDENCE_ROOT)
            restored_root = output / "restored-private-evidence"
            shutil.copytree(original_root, restored_root)
            original_key = evidence.storage_key
            settings.CLUB_EVIDENCE_ROOT = str(restored_root)
            evidence.expires_at = timezone.now()-timedelta(seconds=1)
            evidence.save(update_fields=["expires_at"])
            from clubs.services import cleanup_evidence
            first = cleanup_evidence(dry_run=False)
            second = cleanup_evidence(dry_run=False)
            evidence.refresh_from_db()
            report["checks"]["cleanup_after_restore_is_idempotent"] = first[0] >= 1 and second == (0, 0) and evidence.purged_at is not None
            report["checks"]["restore_cleanup_does_not_touch_source_blobs"] = (original_root / original_key).is_file() and not (restored_root / original_key).exists()
        else:
            report["checks"]["cleanup_after_restore_is_idempotent"] = False
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc).splitlines()[0])
    finally:
        if server:
            server.shutdown()
            server.server_close()
        try:
            from django.db import connections
            connections.close_all()
        finally:
            for name in reversed(created):
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(db_identifier(name)))
            admin.close()
        report["disposable_databases_removed"] = True
        report["passed"] = not report["errors"] and all(report["checks"].values())
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "artifact_directory": str(output), "checks": report["checks"], "errors": report["errors"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
