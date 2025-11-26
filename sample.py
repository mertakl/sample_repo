"""
Refactored TsVectorSearchRetriever with improved structure and maintainability.
"""
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
import logging
import psycopg2
from psycopg2.extensions import cursor as PsycopgCursor

# Assuming these imports from your codebase
from config_handler import ConfigHandler
from chunk_database import ChunkDatabase
from reranker import Reranker
from models import Document, QueryResponse, SearchQuery

logger = logging.getLogger(__name__)

AVAILABLE_LANGUAGES_TYPE = str  # Replace with actual type


@dataclass
class RetrieverConfig:
    """Configuration for the retriever."""
    max_k: int
    semantic_proportion_before_reranker: float
    search_k_before_reranker: int


@dataclass
class VectorDBConfig:
    """Configuration for vector database connection."""
    username: str
    password: str
    host: str
    port: int
    database: str
    schema: str

    def get_connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return (
            f"postgresql+psycopg://{self.username}:{self.password}@"
            f"{self.host}:{self.port}/{self.database}"
            f"?options=-csearch_path%3D{self.schema},ibm_extension"
        )


class SQLQueries:
    """SQL query templates for database operations."""
    
    ALTER_TABLE_ADD_TSVECTOR = """
        ALTER TABLE aisc_ap04.langchain_pg_embedding
        ADD COLUMN IF NOT EXISTS document_tsvector tsvector;
    """
    
    CREATE_GIN_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_document_tsvector
        ON aisc_ap04.langchain_pg_embedding
        USING GIN(document_tsvector);
    """
    
    CREATE_TSVECTOR_TRIGGER = """
        CREATE OR REPLACE FUNCTION document_tsvector_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.document_tsvector := to_tsvector('{language}', COALESCE(NEW.document, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """
    
    DROP_TRIGGER = """
        DROP TRIGGER IF EXISTS tsvector_update ON aisc_ap04.langchain_pg_embedding;
    """
    
    CREATE_TRIGGER = """
        CREATE TRIGGER tsvector_update
        BEFORE INSERT OR UPDATE ON aisc_ap04.langchain_pg_embedding
        FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
    """
    
    TSVECTOR_SEARCH = """
        SELECT
            document,
            cmetadata,
            ts_rank(document_tsvector, websearch_to_tsquery('{language}', %s)) as score
        FROM langchain_pg_embedding
        WHERE document_tsvector @@ websearch_to_tsquery('{language}', %s)
        ORDER BY score DESC
        LIMIT %s;
    """


class DatabaseManager:
    """Handles database connections and setup operations."""
    
    def __init__(self, config: VectorDBConfig, language: str):
        self.config = config
        self.language = language
        self._connection = None
    
    def connect(self) -> psycopg2.extensions.connection:
        """Establish database connection."""
        if self._connection is None or self._connection.closed:
            connection_str = self.config.get_connection_string()
            # Remove the postgresql+psycopg prefix for psycopg2
            connection_str = connection_str.replace("postgresql+psycopg://", "")
            self._connection = psycopg2.connect(connection_str)
        return self._connection
    
    def close(self):
        """Close database connection."""
        if self._connection and not self._connection.closed:
            self._connection.close()
    
    def setup_tsvector_column(self) -> None:
        """Setup tsvector column, index, and triggers."""
        conn = self.connect()
        cur = conn.cursor()
        
        try:
            # Add tsvector column
            cur.execute(SQLQueries.ALTER_TABLE_ADD_TSVECTOR)
            
            # Create GIN index
            cur.execute(SQLQueries.CREATE_GIN_INDEX)
            
            # Create trigger function
            trigger_function = SQLQueries.CREATE_TSVECTOR_TRIGGER.format(
                language=self.language
            )
            cur.execute(trigger_function)
            
            # Drop existing trigger and create new one
            cur.execute(SQLQueries.DROP_TRIGGER)
            cur.execute(SQLQueries.CREATE_TRIGGER)
            
            conn.commit()
            logger.info("TsVector column setup completed successfully")
            
        except psycopg2.Error as e:
            conn.rollback()
            logger.warning("Could not setup tsvector: %s", e)
            raise
        finally:
            cur.close()


class TsVectorSearcher:
    """Handles full-text search operations using PostgreSQL tsvector."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def search(
        self, 
        query: str, 
        k: int = 10
    ) -> List[Tuple[Document, float]]:
        """
        Perform full-text search using tsvector.
        
        Args:
            query: Search query string
            k: Number of results to return
            
        Returns:
            List of (Document, score) tuples
        """
        conn = self.db_manager.connect()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        try:
            # Use ts_rank for scoring
            sql_query = SQLQueries.TSVECTOR_SEARCH.format(
                language=self.db_manager.language
            )
            cur.execute(sql_query, (query, query, k))
            results = cur.fetchall()
            
            # Convert to Document objects with scores
            docs_with_scores = []
            for row in results:
                doc = Document(
                    page_content=row["document"],
                    metadata=row["cmetadata"] or {}
                )
                score = float(row["score"]) if row["score"] else 0.0
                docs_with_scores.append((doc, score))
            
            return docs_with_scores
            
        except psycopg2.Error as e:
            logger.error("TsVector search failed: %s", e)
            return []
        finally:
            cur.close()


class DocumentChunker:
    """Handles document chunking operations."""
    
    @staticmethod
    def chunk_to_query_response(chunk: Document) -> QueryResponse:
        """Convert a Document chunk to QueryResponse format."""
        metadata = chunk.metadata or {}
        
        return QueryResponse(
            chunk=chunk,
            key=metadata.get("content", ""),
            content=metadata.get("content", ""),
            document_id=metadata.get("document_id", ""),
            span_in_document=metadata.get("span_in_document"),
            hyperlinks=metadata.get("hyperlinks", []),
            tables=metadata.get("tables", []),
            header_to_type={},  # Populate as needed
            title=metadata.get("title", ""),
            headers_before=metadata.get("headers_before", []),
            metadata=metadata,
            score=0.0,
        )
    
    @classmethod
    def documents_to_chunks(
        cls, 
        documents: List[Document]
    ) -> List[QueryResponse]:
        """Convert multiple documents to QueryResponse chunks."""
        return [cls.chunk_to_query_response(doc) for doc in documents]


class TsVectorSearchRetriever:
    """
    Hybrid search retriever combining semantic vector search with full-text search.
    
    Uses PostgreSQL's tsvector for full-text search and combines results with
    semantic embeddings for improved retrieval quality.
    """
    
    def __init__(
        self,
        config_handler: ConfigHandler,
        database: ChunkDatabase,
        reranker: Reranker,
        language: AVAILABLE_LANGUAGES_TYPE,
    ):
        """Initialize the retriever with necessary components."""
        self.config_handler = config_handler
        self.database = database
        self.reranker = reranker
        self.language = language
        
        # Load configurations
        self.retriever_config = self._load_retriever_config()
        self.vectordb_config = self._load_vectordb_config()
        
        # Initialize components
        self.db_manager = DatabaseManager(self.vectordb_config, language)
        self.tsvector_searcher = TsVectorSearcher(self.db_manager)
        
        # Setup database
        self._setup_database()
    
    def _load_retriever_config(self) -> RetrieverConfig:
        """Load retriever configuration from config handler."""
        retriever_config = self.config_handler.get_config("retriever")
        max_k = int(retriever_config["k"])
        
        return RetrieverConfig(
            max_k=max_k,
            semantic_proportion_before_reranker=float(
                retriever_config.get("semantic_proportion_before_reranker", 0.5)
            ),
            search_k_before_reranker=int(
                retriever_config.get("search_k", max_k)
            )
        )
    
    def _load_vectordb_config(self) -> VectorDBConfig:
        """Load vector database configuration."""
        vectordb_config = self.config_handler.get_config("vector_db")
        
        return VectorDBConfig(
            username=vectordb_config["db_user"],
            password=vectordb_config["db_password"],
            host=vectordb_config["db_host"],
            port=int(vectordb_config["db_port"]),
            database=vectordb_config["db_name"],
            schema=vectordb_config["db_schema"]
        )
    
    def _setup_database(self) -> None:
        """Setup database with tsvector support."""
        try:
            self.db_manager.setup_tsvector_column()
        except psycopg2.Error as e:
            logger.warning("Database setup failed: %s", e)
    
    async def retrieve(
        self, 
        query: SearchQuery
    ) -> List[QueryResponse]:
        """
        Retrieve documents using hybrid search approach.
        
        Combines semantic vector search with full-text search for better results.
        
        Args:
            query: Search query with text and parameters
            
        Returns:
            List of ranked query responses
        """
        # Calculate how many results from each method
        max_k_semantic = int(
            self.retriever_config.search_k_before_reranker * 
            self.retriever_config.semantic_proportion_before_reranker
        )
        
        # Perform vector search (await the result)
        try:
            semantic_documents = await self._perform_semantic_search(
                query.text, 
                max_k_semantic
            )
            semantic_responses = DocumentChunker.documents_to_chunks(
                semantic_documents
            )
        except Exception as e:
            logger.error("Semantic search failed: %s", e)
            semantic_responses = []
        
        # Perform full-text search
        try:
            vector_results = self.tsvector_searcher.search(
                query.text,
                k=(self.retriever_config.search_k_before_reranker - max_k_semantic)
            )
            vector_responses = DocumentChunker.documents_to_chunks(
                [doc for doc, _ in vector_results]
            )
        except Exception as e:
            logger.error("TsVector search failed: %s", e)
            vector_responses = []
        
        # Combine results
        combined_responses = semantic_responses + vector_responses
        
        if not combined_responses:
            logger.warning("No results found from either search method")
            return []
        
        # Rerank combined results
        reranked_docs = await self._rerank_results(
            query_responses=combined_responses,
            query=query
        )
        
        return reranked_docs
    
    async def _perform_semantic_search(
        self, 
        query_text: str, 
        k: int
    ) -> List[Document]:
        """Perform semantic vector search."""
        results = await self.database.vector_store.asimilarity_search_with_score(
            query_text, 
            k=k
        )
        # Extract just the documents from (document, score) tuples
        return [doc for doc, score in results]
    
    async def _rerank_results(
        self,
        query_responses: List[QueryResponse],
        query: SearchQuery,
        rerank_field: str = "key"
    ) -> List[QueryResponse]:
        """Rerank combined search results."""
        return await self.reranker.rerank(
            query_responses=query_responses,
            query=query,
            rerank_field=rerank_field
        )
    
    def __del__(self):
        """Cleanup database connections."""
        if hasattr(self, 'db_manager'):
            self.db_manager.close()
