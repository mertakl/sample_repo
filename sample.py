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


import json
import bm25s
from pathlib import Path
from collections import defaultdict
from pydantic import Field, PrivateAttr

class Bm25Adapter(BaseSearchAdapter):
    """
    Adapter for In-Memory BM25 Search.
    """
    chunks: List[DocumentChunk] = Field(default_factory=list)
    bm25_retriever: Any = None # Typed as Any to avoid Pydantic validaton issues with external libs
    nb_retrieved_doc_factor: int = 1
    
    # Internal index for fast lookups
    _key_to_chunks: dict = PrivateAttr(default_factory=lambda: defaultdict(list))

    def model_post_init(self, __context: Any) -> None:
        """Initialize the internal lookup map and index if chunks exist."""
        for chunk in self.chunks:
            self._key_to_chunks[chunk.key].append(chunk)

        corpus = list(self._key_to_chunks.keys())
        
        # Initialize retriever if not provided
        if not self.bm25_retriever and corpus:
            self.bm25_retriever = bm25s.BM25(corpus=corpus)
            corpus_tokens = bm25s.tokenize(corpus)
            self.bm25_retriever.index(corpus_tokens)

    async def search(self, query: SearchQuery, max_k: int = 10) -> List[QueryResponse]:
        if not self.bm25_retriever:
            return []

        # Tokenize query
        query_tokens = bm25s.tokenize(query.text)
        
        # Adjust retrieval count based on filters
        clauses = query.filter_clauses or []
        factor = self.nb_retrieved_doc_factor if clauses else 1
        
        # Perform retrieval
        docs, scores = self.bm25_retriever.retrieve(
            query_tokens, k=max_k * factor
        )
        
        # Unwrap 2D arrays from bm25s
        doc_keys = docs[0]
        doc_scores = scores[0]

        responses = []
        for key, score in zip(doc_keys, doc_scores):
            matching_chunks = self._key_to_chunks.get(key, [])
            
            for chunk in matching_chunks:
                # Apply filters
                if not clauses or all(clause.matches(chunk) for clause in clauses):
                    responses.append(QueryResponse(chunk=chunk, score=float(score)))
                    
                    if len(responses) >= max_k:
                        return responses
        
        return responses

    # --- Persistence Methods (Specific to this adapter) ---
    
    @classmethod
    def load_from_disk(cls, path: str) -> "Bm25Adapter":
        path_obj = Path(path)
        # Load logic (simplified from your original code)
        retriever = bm25s.BM25.load(str(path_obj), load_corpus=True)
        # Load wrapper data
        data = json.loads((path_obj / "rt_database.json").read_text())
        data['bm25_retriever'] = retriever
        return cls(**data)

    async def select(self, filter_clauses: List[ChunkFilterClause]):
        # Simple in-memory filtering
        return [c for c in self.chunks if all(f.matches(c) for f in filter_clauses)]


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
