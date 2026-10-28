"""Exercise real response policies and CSRF middleware, including allauth logout."""

from datetime import date
from html.parser import HTMLParser

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AthleteProfile, UserRole


class ReferrerMetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.policies = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").lower() == "referrer":
            self.policies.append(attrs.get("content"))


class CsrfTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="csrf-member", email="member@example.test"
        )
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True
        )
        UserRole.objects.create(user=self.user, role="archer")
        self.athlete = AthleteProfile.objects.create(
            account=self.user, display_name="Member", birth_date=date(2000, 1, 1),
            discipline="recurve", transitioned_at=timezone.now(),
        )
        self.client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost:8000")
        self.client.force_login(self.user)

    def token(self, secure=False):
        response = self.client.get(reverse("account-profile"), secure=secure)
        self.assertEqual(response.status_code, 200)
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def assert_form_policy(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        parser = ReferrerMetaParser()
        parser.feed(response.content.decode())
        self.assertEqual(parser.policies, [])

    def test_rendered_pages_inherit_same_origin_without_meta_override(self):
        for name, args in (
            ("home", []), ("account-profile", []), ("athletes", []),
            ("athlete-detail", [self.athlete.pk]),
            ("invitation-accept", ["synthetic-token"]), ("account_logout", []),
        ):
            with self.subTest(page=name):
                self.assert_form_policy(self.client.get(reverse(name, args=args), follow=True))
        self.assertIn(SESSION_KEY, self.client.session)  # GET logout only confirms.
        self.assert_form_policy(
            Client(HTTP_HOST="localhost:8000").get(reverse("account_login"))
        )

    def test_invitation_handoff_and_acceptance_keep_policy_and_no_store(self):
        token = self.token()
        self.athlete.refresh_from_db()
        response = self.client.post(
            reverse("invitation-create", args=[self.athlete.pk]),
            {"kind": "coach", "email": "coach@example.test",
             "version": self.athlete.version, "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="http://localhost:8000",
        )
        self.assert_form_policy(response)
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(reverse("invitation-accept", args=["synthetic-token"]))
        self.assert_form_policy(response)
        self.assertIn("no-store", response["Cache-Control"])

    def test_same_origin_logout_with_token_over_http_and_https(self):
        for secure, scheme in ((False, "http"), (True, "https")):
            with self.subTest(scheme=scheme):
                self.client.force_login(self.user)
                response = self.client.post(
                    reverse("account_logout"),
                    {"csrfmiddlewaretoken": self.token(secure)}, secure=secure,
                    HTTP_ORIGIN=f"{scheme}://localhost:8000",
                )
                self.assertRedirects(response, "/", fetch_redirect_response=False)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_https_logout_without_origin_uses_same_origin_referer(self):
        response = self.client.post(
            reverse("account_logout"), {"csrfmiddlewaretoken": self.token(True)},
            secure=True, HTTP_REFERER="https://localhost:8000/account/profile/",
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_rejects_null_and_foreign_origins_even_with_valid_token(self):
        token = self.token()
        for origin in ("null", "https://attacker.example", "http://localhost:8001"):
            with self.subTest(origin=origin):
                response = self.client.post(
                    reverse("account_logout"), {"csrfmiddlewaretoken": token},
                    HTTP_ORIGIN=origin,
                    HTTP_REFERER="http://localhost:8000/account/profile/",
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn(SESSION_KEY, self.client.session)

    def test_logout_rejects_missing_and_incorrect_tokens(self):
        self.token()
        for data in ({}, {"csrfmiddlewaretoken": "x" * 64}):
            with self.subTest(data=data):
                response = self.client.post(
                    reverse("account_logout"), data, HTTP_ORIGIN="http://localhost:8000"
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn(SESSION_KEY, self.client.session)

    def test_https_logout_without_origin_rejects_missing_or_foreign_referer(self):
        token = self.token(True)
        for headers in ({}, {"HTTP_REFERER": "https://attacker.example/"}):
            with self.subTest(headers=headers):
                response = self.client.post(
                    reverse("account_logout"), {"csrfmiddlewaretoken": token},
                    secure=True, **headers,
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn(SESSION_KEY, self.client.session)
