import pytest
import psycopg2
from unittest.mock import patch
from search_adapters import TsVectorChunkIndexerAdapter, PostgresQueries, SearchQuery, PGVectorDBConfig

class FakePsycopgCursor:
    """Simulates a DB cursor to test SQL generation and Row parsing."""
    def __init__(self, rows=None, raise_on_execute=None):
        self.rows = rows or []
        self.executed_queries = []
        self.raise_on_execute = raise_on_execute
        self.closed = False

    def execute(self, query, params=None):
        if self.raise_on_execute:
            raise self.raise_on_execute
        # Store query to verify SQL generation logic
        self.executed_queries.append((query.strip(), params))

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True
    
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

class FakePsycopgConnection:
    """Simulates a DB connection to test Commit/Rollback logic."""
    def __init__(self, cursor_factory=None, rows_to_return=None, error_to_raise=None):
        self.cursor_factory = cursor_factory
        self.committed = False
        self.rolled_back = False
        self.rows_to_return = rows_to_return
        self.error_to_raise = error_to_raise
        self.created_cursors = []

    def cursor(self, cursor_factory=None):
        cur = FakePsycopgCursor(rows=self.rows_to_return, raise_on_execute=self.error_to_raise)
        self.created_cursors.append(cur)
        return cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass

class TestTsVectorChunkIndexerAdapter:

    @pytest.fixture
    def pg_adapter(self):
        config = PGVectorDBConfig()
        adapter = TsVectorChunkIndexerAdapter(config=config)
        return adapter

    def test_initialize_schema_success(self, pg_adapter):
        """
        Verify that initialize_schema executes the correct sequence of SQL 
        and commits the transaction.
        """
        fake_conn = FakePsycopgConnection()

        with patch('psycopg2.connect', return_value=fake_conn):
            pg_adapter.initialize_schema()

        assert fake_conn.committed is True
        assert fake_conn.rolled_back is False
        
        # Verify SQL Sequence
        cursor = fake_conn.created_cursors[0]
        queries = [q[0] for q in cursor.executed_queries]
        
        # Check if basic SQL parts are present in the queries sent
        assert any("ALTER TABLE" in q for q in queries)
        assert any("CREATE INDEX" in q for q in queries)
        assert any("CREATE OR REPLACE FUNCTION" in q for q in queries)
        assert any("CREATE TRIGGER" in q for q in queries)

    def test_initialize_schema_failure_rollback(self, pg_adapter):
        """
        Verify that if an SQL error occurs, the transaction is Rolled Back.
        """
        # Create a connection that raises an error on execution
        fake_conn = FakePsycopgConnection(error_to_raise=RuntimeError("DB Locked"))

        with patch('psycopg2.connect', return_value=fake_conn):
            with pytest.raises(RuntimeError):
                pg_adapter.initialize_schema()

        assert fake_conn.committed is False
        assert fake_conn.rolled_back is True  # CRITICAL: Ensure rollback happened

    @pytest.mark.asyncio
    async def test_search_success_parsing(self, pg_adapter):
        """
        Test that raw SQL results (dicts) are correctly converted to 
        QueryResponse objects using the base class logic.
        """
        # Simulate rows returned by Postgres
        fake_rows = [
            {
                "document": "Page Content A",
                "cmetadata": {"author": "John"},
                "score": 0.88
            },
            {
                "document": "Page Content B",
                "cmetadata": {"author": "Jane"},
                "score": 0.75
            }
        ]
        
        fake_conn = FakePsycopgConnection(rows_to_return=fake_rows)

        with patch('psycopg2.connect', return_value=fake_conn):
            query = SearchQuery(text="test query")
            responses = await pg_adapter.search(query)

        # 1. Check SQL Generation
        cursor = fake_conn.created_cursors[0]
        executed_sql, params = cursor.executed_queries[0]
        
        # Verify language injection
        assert "websearch_to_tsquery('english', %s)" in executed_sql
        # Verify parameters passed safely
        assert params == ("test query", "test query", 10)

        # 2. Check Object Transformation
        assert len(responses) == 2
        assert responses[0].chunk.key == "Page Content A"
        assert responses[0].score == 0.88
        assert responses[0].metadata["author"] == "John"

    @pytest.mark.asyncio
    async def test_search_failure_logs_error(self, pg_adapter):
        """Test connection failure during search is caught and logged."""
        fake_conn = FakePsycopgConnection(error_to_raise=psycopg2.DatabaseError("Conn lost"))

        with patch('psycopg2.connect', return_value=fake_conn):
            results = await pg_adapter.search(SearchQuery(text="test"))

        assert results == []
        # (In a real scenario, you would also verify the logger was called)
