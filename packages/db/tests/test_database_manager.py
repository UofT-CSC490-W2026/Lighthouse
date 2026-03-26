import pytest
from db import DatabaseManager

@pytest.mark.integration
class TestDatabaseManager:
    def test_connect_with_valid_dsn(self, pg_dsn):
        mgr = DatabaseManager(pg_dsn)
        mgr.connect()
        assert mgr.is_connected
        mgr.close()

    def test_connect_without_dsn_raises(self):
        mgr = DatabaseManager("")
        with pytest.raises(RuntimeError, match="POSTGRES_DSN"):
            mgr.connect()

    def test_close_when_connected(self, pg_dsn):
        mgr = DatabaseManager(pg_dsn)
        mgr.connect()
        mgr.close()
        assert not mgr.is_connected

    def test_close_when_not_connected(self):
        mgr = DatabaseManager("")
        mgr.close()  # should not raise

    def test_connection_context(self, db_manager):
        with db_manager.connection_context():
            pass  # should not raise

    def test_initialize_idempotent(self, pg_dsn):
        mgr = DatabaseManager(pg_dsn)
        db1 = mgr.initialize()
        db2 = mgr.initialize()
        assert db1 is db2
        mgr.close()

    def test_database_property_before_init_raises(self):
        mgr = DatabaseManager("postgresql://dummy")
        with pytest.raises(RuntimeError, match="not been initialized"):
            _ = mgr.database

    def test_is_configured(self):
        assert DatabaseManager("postgresql://x").is_configured
        assert not DatabaseManager("").is_configured
        assert not DatabaseManager(None).is_configured
