from abc import ABC, abstractmethod
from typing import List, Any
from pydantic import BaseModel

# --- Assumed Domain Models (from your library) ---
# Assuming these exist based on your code snippet
class Document(BaseModel):
    page_content: str
    metadata: dict = {}

class QueryResponse(BaseModel):
    chunk: Any  # DocumentChunk
    score: float
    metadata: dict

# --- The Port ---
class SearchStrategy(ABC):
    """
    The Port: Defines the interface for any search algorithm 
    (TsVector, BM25, TF-IDF, etc.)
    """

    @abstractmethod
    def setup(self) -> None:
        """Perform any necessary initialization (indexing, DB migrations, etc.)."""
        pass

    @abstractmethod
    def search(self, query: str, k: int) -> List[QueryResponse]:
        """Execute the search."""
        pass



import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

class PostgresConnectionManager:
    """Infrastructure: Handles raw DB connections."""
    
    def __init__(self, config: Any):
        self.config = config
        self._connection = None

    def get_connection(self):
        if self._connection is None or self._connection.closed:
            # Reconstruct connection string logic here
            conn_str = self.config.get_connection_string().replace("+psycopg", "")
            self._connection = psycopg2.connect(conn_str)
        return self._connection

    def close(self):
        if self._connection and not self._connection.closed:
            self._connection.close()

    def get_cursor(self):
        """Returns a RealDictCursor for convenient dict-access."""
        return self.get_connection().cursor(cursor_factory=RealDictCursor)



class SQLTemplates:
    """Encapsulates SQL to keep the Adapter clean."""
    
    # Note: Hardcoded table names should ideally be config variables
    SETUP_TSVECTOR_COL = """
    ALTER TABLE aisc_ap04.langchain_pg_embedding
    ADD COLUMN IF NOT EXISTS document_tsvector tsvector;
    """
    
    CREATE_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_document_tsvector
    ON aisc_ap04.langchain_pg_embedding
    USING GIN(document_tsvector);
    """
    
    CREATE_FUNCTION = """
    CREATE OR REPLACE FUNCTION document_tsvector_trigger()
    RETURNS trigger AS $$
    BEGIN
        NEW.document_tsvector :=
            to_tsvector('{language}', COALESCE(NEW.document, ''));
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql;
    """
    
    CREATE_TRIGGER = """
    CREATE TRIGGER tsvector_update
    BEFORE INSERT OR UPDATE ON aisc_ap04.langchain_pg_embedding
    FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
    """

    SEARCH = """
    SELECT document, cmetadata,
           ts_rank(document_tsvector, websearch_to_tsquery('{language}', %s)) AS score
    FROM langchain_pg_embedding
    WHERE document_tsvector @@ websearch_to_tsquery('{language}', %s)
    ORDER BY score DESC LIMIT %s;
    """

class PostgresTsVectorAdapter(SearchStrategy):
    """Adapter for Postgres Full Text Search."""

    def __init__(self, db_manager: PostgresConnectionManager, language: str = 'english'):
        self.db_manager = db_manager
        self.language = language

    def setup(self) -> None:
        """Runs the DDL to set up columns and triggers."""
        conn = self.db_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(SQLTemplates.SETUP_TSVECTOR_COL)
                cur.execute(SQLTemplates.CREATE_INDEX)
                
                # Format function with dynamic language
                cur.execute(SQLTemplates.CREATE_FUNCTION.format(language=self.language))
                
                # Safe trigger creation (drop then create)
                cur.execute("DROP TRIGGER IF EXISTS tsvector_update ON aisc_ap04.langchain_pg_embedding;")
                cur.execute(SQLTemplates.CREATE_TRIGGER)
            conn.commit()
            logger.info("TsVector Postgres setup complete.")
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"Failed to setup TsVector: {e}")
            raise

    def search(self, query: str, k: int) -> List[QueryResponse]:
        """Runs the actual SQL search query."""
        try:
            with self.db_manager.get_cursor() as cur:
                sql = SQLTemplates.SEARCH.format(language=self.language)
                cur.execute(sql, (query, query, k))
                results = cur.fetchall()
                
            return self._map_to_response(results)
        except psycopg2.Error as e:
            logger.error(f"Search failed: {e}")
            return []

    def _map_to_response(self, rows: List[dict]) -> List[QueryResponse]:
        """Maps raw SQL rows to Domain Objects."""
        responses = []
        for row in rows:
            doc = Document(
                page_content=row["document"],
                metadata=row["cmetadata"] or {}
            )
            # Assuming ChunkDatabase.create_query_response exists as a helper
            # If not, you instantiate QueryResponse directly here
            responses.append(
                ChunkDatabase.create_query_response(doc, float(row["score"]))
            )
        return responses



# Pseudo-code for BM25 (requires `rank_bm25` package)
# from rank_bm25 import BM25Okapi

class BM25Adapter(SearchStrategy):
    """Adapter for In-Memory BM25 Search."""

    def __init__(self, documents: List[Document]):
        """
        BM25 needs the documents loaded to build the index.
        You might fetch these from the DB once during initialization.
        """
        self.documents = documents
        self.bm25 = None
        self.is_setup = False

    def setup(self) -> None:
        """Builds the BM25 index in memory."""
        tokenized_corpus = [doc.page_content.split(" ") for doc in self.documents]
        # self.bm25 = BM25Okapi(tokenized_corpus)
        self.is_setup = True
        logger.info("BM25 Index built in memory.")

    def search(self, query: str, k: int) -> List[QueryResponse]:
        if not self.is_setup:
            raise RuntimeError("BM25Adapter not set up. Call setup() first.")

        tokenized_query = query.split(" ")
        # scores = self.bm25.get_scores(tokenized_query)
        # docs = self.bm25.get_top_n(tokenized_query, self.documents, n=k)
        
        # Mock return for architecture demonstration
        return []


class SearchDatabase(ChunkDatabase):
    """
    Refactored class. It acts as a wrapper around a Strategy.
    """

    configuration: Configuration
    language: str
    _strategy: SearchStrategy

    def __init__(self, strategy: SearchStrategy, **data):
        super().__init__(**data)
        self._strategy = strategy

    async def initialize(self):
        """Explicit initialization step."""
        self._strategy.setup()

    async def search(
        self,
        query: SearchQuery,
        max_k: int = 10,
        algorithm: str = "semantic" # This parameter might determine which strategy to inject
    ) -> list[QueryResponse]:
        
        # Delegate the actual work to the strategy
        return self._strategy.search(query=str(query), k=max_k)

# --- Usage Factory ---

def get_search_database(config: Configuration, method: str = "postgres") -> SearchDatabase:
    """Factory to assemble the correct components."""
    
    if method == "postgres":
        # 1. Setup Infra
        db_manager = PostgresConnectionManager(config.vector_db)
        
        # 2. Setup Adapter
        adapter = PostgresTsVectorAdapter(db_manager, language="english")
        
        # 3. Setup Service
        service = SearchDatabase(strategy=adapter, configuration=config)
        return service

    elif method == "bm25":
        # 1. Fetch docs (BM25 specific requirement)
        # docs = fetch_all_docs_from_somewhere()
        
        # 2. Setup Adapter
        adapter = BM25Adapter(documents=[])
        
        # 3. Setup Service
        return SearchDatabase(strategy=adapter, configuration=config)
