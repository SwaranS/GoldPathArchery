"""Schema rollback is exercised only inside the test runner's disposable database."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class FoundationMigrationTests(TransactionTestCase):
    def test_new_tables_can_be_reversed_without_changing_legacy_identity(self):
        user = get_user_model().objects.create_user(username="migration-preserved")
        existing = {name for name in connection.introspection.table_names() if not name.startswith("clubs_")}
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("clubs", None)])
            self.assertFalse(any(name.startswith("clubs_") for name in connection.introspection.table_names()))
            self.assertEqual(set(connection.introspection.table_names()), existing)
            self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        finally:
            MigrationExecutor(connection).migrate(targets)
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
