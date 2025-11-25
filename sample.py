from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector
from langchain_core.documents import Document
from typing import List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor

class HybridSearchPgVector:
    """
    Hybrid search combining PgVector semantic search with PostgreSQL ts_vector full-text search.
    Results are combined and can be reranked.
    """
    
    def __init__(
        self,
        connection_string: str,
        embeddings,
        collection_name: str = "langchain_documents",
        k: int = 10
    ):
        """
        Initialize hybrid search with PgVector and ts_vector.
        
        Args:
            connection_string: PostgreSQL connection string
            embeddings: LangChain embeddings instance
            collection_name: Name of the vector store collection
            k: Number of results to retrieve from each method
        """
        self.connection_string = connection_string
        self.collection_name = collection_name
        self.k = k
        
        # Initialize PgVector
        self.vectorstore = PGVector(
            embeddings=embeddings,
            collection_name=collection_name,
            connection=connection_string,
            use_jsonb=True,
        )
        
        # Setup ts_vector column if not exists
        self._setup_tsvector_column()
    
    def _setup_tsvector_column(self):
        """Add ts_vector column and index to the collection if not exists."""
        conn = psycopg2.connect(self.connection_string)
        cur = conn.cursor()
        
        try:
            # Add tsvector column if not exists
            cur.execute(f"""
                ALTER TABLE langchain_pg_embedding 
                ADD COLUMN IF NOT EXISTS document_tsvector tsvector;
            """)
            
            # Create GIN index for faster full-text search
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_document_tsvector 
                ON langchain_pg_embedding 
                USING GIN(document_tsvector);
            """)
            
            # Create trigger to automatically update tsvector on insert/update
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION document_tsvector_trigger() 
                RETURNS trigger AS $$
                BEGIN
                    NEW.document_tsvector := to_tsvector('english', COALESCE(NEW.document, ''));
                    RETURN NEW;
                END
                $$ LANGUAGE plpgsql;
            """)
            
            cur.execute(f"""
                DROP TRIGGER IF EXISTS tsvector_update ON langchain_pg_embedding;
                CREATE TRIGGER tsvector_update 
                BEFORE INSERT OR UPDATE ON langchain_pg_embedding
                FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
            """)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Warning: Could not setup tsvector: {e}")
        finally:
            cur.close()
            conn.close()
    
    def _tsvector_search(self, query: str, k: int = None) -> List[Tuple[Document, float]]:
        """
        Perform full-text search using PostgreSQL ts_vector.
        
        Args:
            query: Search query
            k: Number of results to return
            
        Returns:
            List of (Document, score) tuples
        """
        if k is None:
            k = self.k
            
        conn = psycopg2.connect(self.connection_string)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Use ts_rank for scoring
            cur.execute("""
                SELECT 
                    document,
                    cmetadata,
                    ts_rank(document_tsvector, websearch_to_tsquery('english', %s)) as rank
                FROM langchain_pg_embedding
                WHERE document_tsvector @@ websearch_to_tsquery('english', %s)
                    AND collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = %s)
                ORDER BY rank DESC
                LIMIT %s;
            """, (query, query, self.collection_name, k))
            
            results = cur.fetchall()
            
            # Convert to Document objects with scores
            docs_with_scores = []
            for row in results:
                doc = Document(
                    page_content=row['document'],
                    metadata=row['cmetadata'] or {}
                )
                docs_with_scores.append((doc, float(row['rank'])))
            
            return docs_with_scores
            
        finally:
            cur.close()
            conn.close()
    
    def hybrid_search(
        self,
        query: str,
        k: int = None,
        vector_weight: float = 0.5,
        text_weight: float = 0.5
    ) -> List[Tuple[Document, float]]:
        """
        Perform hybrid search combining vector and full-text search.
        
        Args:
            query: Search query
            k: Number of final results to return
            vector_weight: Weight for vector search scores (0-1)
            text_weight: Weight for text search scores (0-1)
            
        Returns:
            List of (Document, score) tuples sorted by combined score
        """
        if k is None:
            k = self.k
        
        # Get results from both methods (retrieve more for better merging)
        retrieval_k = k * 2
        
        # Vector search
        vector_results = self.vectorstore.similarity_search_with_score(
            query, k=retrieval_k
        )
        
        # Full-text search
        text_results = self._tsvector_search(query, k=retrieval_k)
        
        # Normalize scores and combine
        combined = {}
        
        # Normalize vector scores (convert distance to similarity)
        if vector_results:
            max_vector_score = max(score for _, score in vector_results)
            min_vector_score = min(score for _, score in vector_results)
            score_range = max_vector_score - min_vector_score or 1
            
            for doc, score in vector_results:
                # Convert distance to similarity (assuming L2 distance)
                normalized_score = 1 - ((score - min_vector_score) / score_range)
                doc_id = doc.page_content  # Use content as key
                
                if doc_id not in combined:
                    combined[doc_id] = {'doc': doc, 'score': 0}
                combined[doc_id]['score'] += normalized_score * vector_weight
        
        # Normalize text scores
        if text_results:
            max_text_score = max(score for _, score in text_results)
            min_text_score = min(score for _, score in text_results)
            score_range = max_text_score - min_text_score or 1
            
            for doc, score in text_results:
                normalized_score = (score - min_text_score) / score_range if score_range > 0 else 1
                doc_id = doc.page_content
                
                if doc_id not in combined:
                    combined[doc_id] = {'doc': doc, 'score': 0}
                combined[doc_id]['score'] += normalized_score * text_weight
        
        # Sort by combined score and return top k
        sorted_results = sorted(
            combined.values(),
            key=lambda x: x['score'],
            reverse=True
        )[:k]
        
        return [(item['doc'], item['score']) for item in sorted_results]
    
    def search_with_reranking(
        self,
        query: str,
        reranker,
        k: int = None,
        initial_k: int = None
    ) -> List[Document]:
        """
        Perform hybrid search followed by reranking.
        
        Args:
            query: Search query
            reranker: Reranker instance (e.g., from transformers or sentence-transformers)
            k: Number of final results after reranking
            initial_k: Number of results to retrieve before reranking
            
        Returns:
            List of reranked Documents
        """
        if k is None:
            k = self.k
        if initial_k is None:
            initial_k = k * 3  # Retrieve more docs for better reranking
        
        # Get hybrid search results
        hybrid_results = self.hybrid_search(query, k=initial_k)
        docs = [doc for doc, _ in hybrid_results]
        
        # Rerank using BME or other reranker
        # Assuming reranker has a rerank method that takes query and docs
        if hasattr(reranker, 'rerank'):
            reranked_docs = reranker.rerank(query, docs)[:k]
        else:
            # Fallback for different reranker APIs
            reranked_docs = docs[:k]
        
        return reranked_docs


# Example usage
if __name__ == "__main__":
    from langchain_openai import OpenAIEmbeddings
    
    # Setup
    connection_string = "postgresql://user:pass@localhost:5432/dbname"
    embeddings = OpenAIEmbeddings()
    
    # Initialize hybrid search
    hybrid_search = HybridSearchPgVector(
        connection_string=connection_string,
        embeddings=embeddings,
        collection_name="my_documents",
        k=10
    )
    
    # Add documents (vectorstore handles embedding)
    documents = [
        Document(page_content="Your document content here", metadata={"source": "doc1"}),
        # ... more documents
    ]
    hybrid_search.vectorstore.add_documents(documents)
    
    # Perform hybrid search
    results = hybrid_search.hybrid_search(
        query="your search query",
        k=5,
        vector_weight=0.5,
        text_weight=0.5
    )
    
    # Or with reranking (example with hypothetical reranker)
    # from some_reranker_library import BMEReranker
    # reranker = BMEReranker()
    # reranked_results = hybrid_search.search_with_reranking(
    #     query="your search query",
    #     reranker=reranker,
    #     k=5,
    #     initial_k=20
    # )
