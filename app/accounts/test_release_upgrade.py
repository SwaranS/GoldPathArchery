"""Regression for deploying relationship code over the existing account database."""

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from .models import UserRole


class AccountReleaseUpgradeTests(TransactionTestCase):
    def test_profile_works_after_upgrading_existing_account_schema(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        # Always restore the test schema, including if an assertion fails.
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate([("accounts", "0002_userrole")])

        user = get_user_model().objects.create_user(
            username="existing-member", email="existing@example.test"
        )
        UserRole.objects.create(user=user, role="parent")
        self.client.force_login(user)

        # This is the failure caused by serving new code before release migrations.
        with self.assertRaises(DatabaseError) as error:
            self.client.get(reverse("account-profile"))
        self.assertIn("accounts_athleteprofile", str(error.exception))

        MigrationExecutor(connection).migrate(latest)
        response = self.client.get(reverse("account-profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My athletes and connections")
        self.assertEqual(list(user.role_assignments.values_list("role", flat=True)), ["parent"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
