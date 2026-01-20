from abc import ABC, abstractmethod
from typing import Any, List, Tuple
from pydantic import BaseModel, ConfigDict
# Assuming these imports exist in your library
from my_library import (
    ChunkDatabase, Document, DocumentChunk, QueryResponse, 
    SearchQuery, ChunkFilterClause, PGVectorDBConfig
)

class BaseSearchAdapter(ChunkDatabase, ABC):
    """
    Base Adapter that implements shared logic for all search implementations.
    This serves as the 'Port' extension for your specific domain logic.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def search(self, query: SearchQuery, max_k: int = 10) -> List[QueryResponse]:
        """Core search method to be implemented by adapters."""
        pass

    # --- Shared Logic (Moved from TsVectorDatabase to here) ---
    
    @staticmethod
    def _document_to_chunk(document: Document) -> DocumentChunk:
        """Shared utility to convert Document to DocumentChunk."""
        metadata = document.metadata or {}
        # Mapping logic (simplified for brevity, insert your full mapping here)
        return DocumentChunk(
            key=document.page_content,
            content=metadata.get("content", ""),
            document_id=metadata.get("document_id", ""),
            metadata=metadata.get("metadata", {}),
            # ... include other fields (span, tables, etc) from your original code
        )

    @classmethod
    def _create_response(cls, document: Document, score: float) -> QueryResponse:
        chunk = cls._document_to_chunk(document)
        return QueryResponse(chunk=chunk, score=score, metadata=document.metadata or {})


import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

class PostgresQueries:
    """Repository for raw SQL strings."""
    ALTER_TABLE = "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS document_tsvector tsvector;"
    CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_document_tsvector ON {table} USING GIN(document_tsvector);"
    
    # Trigger logic
    CREATE_FUNC = """
    CREATE OR REPLACE FUNCTION document_tsvector_trigger() RETURNS trigger AS $$
    BEGIN
        NEW.document_tsvector := to_tsvector('{language}', COALESCE(NEW.document, ''));
        RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """
    
    CREATE_TRIGGER = """
    DROP TRIGGER IF EXISTS tsvector_update ON {table};
    CREATE TRIGGER tsvector_update BEFORE INSERT OR UPDATE ON {table}
    FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
    """

    SEARCH = """
    SELECT document, cmetadata, 
           ts_rank(document_tsvector, websearch_to_tsquery('{language}', %s)) AS score
    FROM {table}
    WHERE document_tsvector @@ websearch_to_tsquery('{language}', %s)
    ORDER BY score DESC LIMIT %s;
    """

class PostgresTsVectorAdapter(BaseSearchAdapter):
    """
    Adapter for Postgres-based Full Text Search.
    """
    config: PGVectorDBConfig
    language: str = "english"
    table_name: str = "aisc_ap04.langchain_pg_embedding"

    def _get_connection(self):
        """Helper to create a raw connection from config."""
        conn_str = self.config.get_connection_string().replace("+psycopg", "")
        return psycopg2.connect(conn_str)

    def initialize_schema(self):
        """Idempotent setup of columns and triggers."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # 1. Add Column
                cur.execute(PostgresQueries.ALTER_TABLE.format(table=self.table_name))
                # 2. Add Index
                cur.execute(PostgresQueries.CREATE_INDEX.format(table=self.table_name))
                # 3. Create Function
                cur.execute(PostgresQueries.CREATE_FUNC.format(language=self.language))
                # 4. Create Trigger
                cur.execute(PostgresQueries.CREATE_TRIGGER.format(table=self.table_name))
            conn.commit()
            logger.info("TsVector schema initialized.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Schema init failed: {e}")
            raise
        finally:
            conn.close()

    async def search(self, query: SearchQuery, max_k: int = 10) -> List[QueryResponse]:
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = PostgresQueries.SEARCH.format(
                    language=self.language, 
                    table=self.table_name
                )
                cur.execute(sql, (query.text, query.text, max_k))
                results = cur.fetchall()

            responses = []
            for row in results:
                doc = Document(page_content=row["document"], metadata=row["cmetadata"])
                score = float(row["score"]) if row["score"] else 0.0
                responses.append(self._create_response(doc, score))
            
            return responses

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
        finally:
            conn.close()

    async def select(self, filter_clauses: List[ChunkFilterClause]):
        # Implement selection logic if needed
        pass


class SearchDatabaseFactory:
    @staticmethod
    def get_database(
        strategy: str, 
        config: dict
    ) -> BaseSearchAdapter:
        
        if strategy == "postgres_tsvector":
            # Initialize Postgres adapter
            db = PostgresTsVectorAdapter(
                config=config['pg_config'],
                language=config.get('language', 'english')
            )
            # Optional: ensure schema is ready
            db.initialize_schema()
            return db
            
        elif strategy == "bm25":
            if 'path' in config:
                return Bm25Adapter.load_from_disk(config['path'])
            else:
                return Bm25Adapter(chunks=config.get('chunks', []))
        
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

# --- Usage Example ---

# 1. Use BM25
bm25_db = SearchDatabaseFactory.get_database("bm25", {"chunks": my_chunks})
results = await bm25_db.search(SearchQuery(text="contract law"))

# 2. Use Postgres
pg_db = SearchDatabaseFactory.get_database("postgres_tsvector", {"pg_config": my_pg_config})
results = await pg_db.search(SearchQuery(text="contract law"))
