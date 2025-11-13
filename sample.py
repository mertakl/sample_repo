from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector
from langchain_core.documents import Document
from typing import List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor


class HybridPgVectorSearch:
    """
    Hybrid search combining PgVector (semantic) and PostgreSQL ts_vector (lexical).
    """
    
    def __init__(
        self,
        connection_string: str,
        embedding_function,
        collection_name: str = "documents",
        semantic_weight: float = 0.8,
        lexical_weight: float = 0.2
    ):
        """
        Initialize hybrid search.
        
        Args:
            connection_string: PostgreSQL connection string
            embedding_function: LangChain embedding function
            collection_name: Name of the collection/table
            semantic_weight: Weight for semantic search (default 0.8)
            lexical_weight: Weight for lexical search (default 0.2)
        """
        self.connection_string = connection_string
        self.collection_name = collection_name
        self.semantic_weight = semantic_weight
        self.lexical_weight = lexical_weight
        
        # Initialize PGVector store
        self.vector_store = PGVector(
            connection=connection_string,
            embeddings=embedding_function,
            collection_name=collection_name,
        )
        
        # Setup ts_vector column if not exists
        self._setup_tsvector()
    
    def _setup_tsvector(self):
        """Create ts_vector column and index if they don't exist."""
        conn = psycopg2.connect(self.connection_string)
        cur = conn.cursor()
        
        try:
            # Add tsvector column if not exists
            cur.execute(f"""
                ALTER TABLE langchain_pg_embedding 
                ADD COLUMN IF NOT EXISTS document_tsvector tsvector;
            """)
            
            # Create or replace function to update tsvector
            cur.execute(f"""
                CREATE OR REPLACE FUNCTION document_tsvector_trigger() RETURNS trigger AS $$
                BEGIN
                    NEW.document_tsvector := to_tsvector('english', COALESCE(NEW.document, ''));
                    RETURN NEW;
                END
                $$ LANGUAGE plpgsql;
            """)
            
            # Create trigger if not exists
            cur.execute(f"""
                DROP TRIGGER IF EXISTS tsvector_update ON langchain_pg_embedding;
                CREATE TRIGGER tsvector_update 
                BEFORE INSERT OR UPDATE ON langchain_pg_embedding
                FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
            """)
            
            # Update existing rows
            cur.execute("""
                UPDATE langchain_pg_embedding 
                SET document_tsvector = to_tsvector('english', COALESCE(document, ''))
                WHERE document_tsvector IS NULL;
            """)
            
            # Create GIN index for fast full-text search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_document_tsvector 
                ON langchain_pg_embedding USING GIN(document_tsvector);
            """)
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error setting up tsvector: {e}")
        finally:
            cur.close()
            conn.close()
    
    def _lexical_search(self, query: str, k: int = 20) -> List[Tuple[Document, float]]:
        """
        Perform lexical search using PostgreSQL ts_vector.
        
        Args:
            query: Search query
            k: Number of results to return
            
        Returns:
            List of (Document, score) tuples
        """
        conn = psycopg2.connect(self.connection_string)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Use ts_rank for scoring
            cur.execute("""
                SELECT 
                    id,
                    document,
                    cmetadata,
                    ts_rank(document_tsvector, websearch_to_tsquery('english', %s)) as score
                FROM langchain_pg_embedding
                WHERE document_tsvector @@ websearch_to_tsquery('english', %s)
                ORDER BY score DESC
                LIMIT %s;
            """, (query, query, k))
            
            results = cur.fetchall()
            
            # Convert to Document objects with scores
            docs_with_scores = []
            for row in results:
                doc = Document(
                    page_content=row['document'],
                    metadata=row['cmetadata'] or {}
                )
                docs_with_scores.append((doc, float(row['score'])))
            
            return docs_with_scores
            
        finally:
            cur.close()
            conn.close()
    
    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """Normalize scores to [0, 1] range."""
        if not scores or max(scores) == min(scores):
            return [1.0] * len(scores)
        
        min_score = min(scores)
        max_score = max(scores)
        return [(s - min_score) / (max_score - min_score) for s in scores]
    
    def hybrid_search(
        self, 
        query: str, 
        k: int = 10,
        fetch_k: int = 20
    ) -> List[Tuple[Document, float]]:
        """
        Perform hybrid search combining semantic and lexical search.
        
        Args:
            query: Search query
            k: Number of final results to return
            fetch_k: Number of results to fetch from each search method
            
        Returns:
            List of (Document, combined_score) tuples
        """
        # Get semantic search results
        semantic_results = self.vector_store.similarity_search_with_score(
            query, 
            k=fetch_k
        )
        
        # Get lexical search results
        lexical_results = self._lexical_search(query, k=fetch_k)
        
        # Normalize scores
        semantic_scores = self._normalize_scores([score for _, score in semantic_results])
        lexical_scores = self._normalize_scores([score for _, score in lexical_results])
        
        # Combine results with weights
        doc_scores = {}
        
        # Add semantic results
        for (doc, _), norm_score in zip(semantic_results, semantic_scores):
            doc_id = doc.page_content  # Use content as ID for deduplication
            doc_scores[doc_id] = {
                'doc': doc,
                'score': self.semantic_weight * norm_score
            }
        
        # Add lexical results
        for (doc, _), norm_score in zip(lexical_results, lexical_scores):
            doc_id = doc.page_content
            if doc_id in doc_scores:
                doc_scores[doc_id]['score'] += self.lexical_weight * norm_score
            else:
                doc_scores[doc_id] = {
                    'doc': doc,
                    'score': self.lexical_weight * norm_score
                }
        
        # Sort by combined score and return top k
        sorted_results = sorted(
            doc_scores.values(),
            key=lambda x: x['score'],
            reverse=True
        )[:k]
        
        return [(item['doc'], item['score']) for item in sorted_results]
    
    def search_with_reranking(
        self,
        query: str,
        k: int = 10,
        fetch_k: int = 20,
        reranker=None
    ) -> List[Document]:
        """
        Perform hybrid search with optional reranking.
        
        Args:
            query: Search query
            k: Number of final results
            fetch_k: Number of results to fetch before reranking
            reranker: BGE reranker or any reranker with rerank() method
            
        Returns:
            List of reranked Documents
        """
        # Get hybrid search results
        hybrid_results = self.hybrid_search(query, k=fetch_k, fetch_k=fetch_k * 2)
        
        if reranker is None:
            return [doc for doc, _ in hybrid_results[:k]]
        
        # Rerank results
        docs = [doc for doc, _ in hybrid_results]
        reranked = reranker.rerank(query, docs, top_k=k)
        
        return reranked
    
    def add_documents(self, documents: List[Document]):
        """Add documents to the vector store."""
        return self.vector_store.add_documents(documents)


# Example usage
if __name__ == "__main__":
    from langchain_openai import OpenAIEmbeddings
    
    # Initialize
    connection_string = "postgresql://user:password@localhost:5432/dbname"
    embeddings = OpenAIEmbeddings()
    
    hybrid_search = HybridPgVectorSearch(
        connection_string=connection_string,
        embedding_function=embeddings,
        semantic_weight=0.8,
        lexical_weight=0.2
    )
    
    # Add documents
    docs = [
        Document(page_content="Python is a high-level programming language."),
        Document(page_content="Machine learning uses algorithms to learn patterns."),
    ]
    hybrid_search.add_documents(docs)
    
    # Search without reranking
    results = hybrid_search.hybrid_search("python programming", k=5)
    for doc, score in results:
        print(f"Score: {score:.4f} - {doc.page_content[:100]}")
    
    # Search with reranking (assuming you have a reranker)
    # from langchain.retrievers import BGERerank
    # reranker = BGERerank()
    # reranked_results = hybrid_search.search_with_reranking(
    #     "python programming", 
    #     k=5, 
    #     reranker=reranker
    # )
