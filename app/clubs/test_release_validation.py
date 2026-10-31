"""Production-style shared-cache MFA validation in disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
import sys
import time
from unittest import skipUnless

from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, hotp_value
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from allauth.mfa.models import Authenticator
from . import tests as foundation


@override_settings(CLUBS_ENABLED=True)
class ClubAdminMFAValidationTests(TestCase):
    setUp = foundation.FoundationTests.setUp
    claim = foundation.FoundationTests.claim
    evidence = foundation.FoundationTests.evidence
    approve = foundation.FoundationTests.approve

    def test_first_club_admin_requires_fresh_live_mfa(self):
        claim = self.claim(visibility="private")
        self.evidence(claim)
        club = self.approve(claim).club
        url = reverse("clubs:manage", args=[club.pk])
        self.client.force_login(self.applicant)
        self.assertIn(reverse("mfa_index"), self.client.get(url).url)
        foundation.login_with_mfa(self.client, self.applicant)
        self.assertEqual(self.client.get(url).status_code, 200)
        Authenticator.objects.filter(user=self.applicant).delete()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_mfa_does_not_replace_platform_reviewer_permission(self):
        self.other.is_staff = True
        self.other.save()
        foundation.login_with_mfa(self.client, self.other)
        self.assertEqual(self.client.get(reverse("clubs:queue")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:clubs_club_changelist")).status_code, 403)


CHILD = r'''
import json, os, sys
from unittest import mock
payload = json.load(sys.stdin)
sys.path.insert(0, payload["app_dir"])
os.environ["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
from django.conf import settings
settings.DATABASES = {"default": payload["database"]}
settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "release_validation_cache"}}
settings.MFA_ENCRYPTION_KEYS = [payload["key"]]
import django
django.setup()
from allauth.mfa.models import Authenticator
try:
    authenticator = Authenticator.objects.get(pk=payload["authenticator"])
    with mock.patch("allauth.mfa.totp.internal.auth.time.time", return_value=payload["clock"]):
        accepted = authenticator.wrap().validate_code(payload["code"])
    print(json.dumps({"accepted": accepted}))
except Exception as exc:
    print(json.dumps({"error": type(exc).__name__}))
    sys.exit(1)
'''


@skipUnless(connection.vendor == "postgresql", "Requires the disposable PostgreSQL shared cache")
class SharedCacheMFAValidationTests(TransactionTestCase):
    def test_totp_replay_is_rejected_across_independent_processes(self):
        database = {name: connection.settings_dict[name] for name in ("ENGINE", "NAME", "USER", "PASSWORD", "HOST", "PORT")}
        self.assertTrue(str(database["NAME"]).startswith("test_"), "Refuse validation against an application database")
        call_command("createcachetable", "release_validation_cache", verbosity=0)
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "release_validation_cache"')
        key = Fernet.generate_key().decode("ascii")
        secret = "JBSWY3DPEHPK3PXP"  # Synthetic test vector only.
        actor = get_user_model().objects.create_user(username="synthetic-shared-cache-reviewer")
        with override_settings(MFA_ENCRYPTION_KEYS=[key]):
            auth = TOTP.activate(actor, secret).instance
        clock = time.time()
        payload = dict(app_dir=str(Path(__file__).resolve().parents[1]), database=database,
            key=key, authenticator=auth.pk, clock=clock,
            code=format_hotp_value(hotp_value(secret, int(clock)//30)))

        def validate(_):
            result = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps(payload),
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, "MFA validation subprocess failed; no sensitive output retained")
            return json.loads(result.stdout)["accepted"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(validate, range(2)))
        self.assertCountEqual(outcomes, [True, False])
        self.assertFalse(validate(None), "Replay must remain denied after the first two processes exit")
