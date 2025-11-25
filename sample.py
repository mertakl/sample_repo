from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector
from langchain_core.documents import Document
from typing import List, Tuple
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine


class AsyncHybridSearchPgVector:
    """
    Async hybrid search combining PgVector semantic search with PostgreSQL ts_vector full-text search.
    Results are combined and can be reranked.
    """
    
    def __init__(
        self,
        async_connection_string: str,
        embeddings,
        collection_name: str = "langchain_documents",
        k: int = 10
    ):
        """
        Initialize hybrid search with PgVector and ts_vector in async mode.
        
        Args:
            async_connection_string: Async PostgreSQL connection string (postgresql+asyncpg://...)
            embeddings: LangChain embeddings instance
            collection_name: Name of the vector store collection
            k: Number of results to retrieve from each method
        """
        self.async_connection_string = async_connection_string
        self.collection_name = collection_name
        self.k = k
        self.embeddings = embeddings
        
        # Create async engine
        self.async_engine = create_async_engine(async_connection_string)
        
        # Initialize PgVector with async engine
        self.vectorstore = PGVector(
            embeddings=embeddings,
            collection_name=collection_name,
            async_mode=True,
            engine=self.async_engine,
            use_jsonb=True,
        )
        
        # Extract connection params for asyncpg
        self._parse_connection_params()
    
    def _parse_connection_params(self):
        """Parse connection string for asyncpg direct connections."""
        # Extract from postgresql+asyncpg://user:pass@host:port/dbname
        from urllib.parse import urlparse
        parsed = urlparse(self.async_connection_string)
        
        self.db_params = {
            'host': parsed.hostname,
            'port': parsed.port or 5432,
            'user': parsed.username,
            'password': parsed.password,
            'database': parsed.path.lstrip('/')
        }
    
    async def setup_tsvector_column(self):
        """Add ts_vector column and index to the collection if not exists."""
        conn = await asyncpg.connect(**self.db_params)
        
        try:
            # Add tsvector column if not exists
            await conn.execute("""
                ALTER TABLE langchain_pg_embedding 
                ADD COLUMN IF NOT EXISTS document_tsvector tsvector;
            """)
            
            # Create GIN index for faster full-text search
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_document_tsvector 
                ON langchain_pg_embedding 
                USING GIN(document_tsvector);
            """)
            
            # Create trigger to automatically update tsvector on insert/update
            await conn.execute("""
                CREATE OR REPLACE FUNCTION document_tsvector_trigger() 
                RETURNS trigger AS $$
                BEGIN
                    NEW.document_tsvector := to_tsvector('english', COALESCE(NEW.document, ''));
                    RETURN NEW;
                END
                $$ LANGUAGE plpgsql;
            """)
            
            await conn.execute("""
                DROP TRIGGER IF EXISTS tsvector_update ON langchain_pg_embedding;
            """)
            
            await conn.execute("""
                CREATE TRIGGER tsvector_update 
                BEFORE INSERT OR UPDATE ON langchain_pg_embedding
                FOR EACH ROW EXECUTE FUNCTION document_tsvector_trigger();
            """)
            
            # Update existing rows
            await conn.execute("""
                UPDATE langchain_pg_embedding
                SET document_tsvector = to_tsvector('english', COALESCE(document, ''))
                WHERE document_tsvector IS NULL;
            """)
            
        except Exception as e:
            print(f"Warning: Could not setup tsvector: {e}")
        finally:
            await conn.close()
    
    async def _tsvector_search(self, query: str, k: int = None) -> List[Tuple[Document, float]]:
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
            
        conn = await asyncpg.connect(**self.db_params)
        
        try:
            # Use ts_rank for scoring
            results = await conn.fetch("""
                SELECT 
                    document,
                    cmetadata,
                    ts_rank(document_tsvector, websearch_to_tsquery('english', $1)) as rank
                FROM langchain_pg_embedding
                WHERE document_tsvector @@ websearch_to_tsquery('english', $1)
                    AND collection_id = (SELECT uuid FROM langchain_pg_collection WHERE name = $2)
                ORDER BY rank DESC
                LIMIT $3;
            """, query, self.collection_name, k)
            
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
            await conn.close()
    
    async def hybrid_search(
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
        
        # Vector search (async)
        vector_results = await self.vectorstore.asimilarity_search_with_score(
            query, k=retrieval_k
        )
        
        # Full-text search (async)
        text_results = await self._tsvector_search(query, k=retrieval_k)
        
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
    
    async def search_with_reranking(
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
        hybrid_results = await self.hybrid_search(query, k=initial_k)
        docs = [doc for doc, _ in hybrid_results]
        
        # Rerank using BME or other reranker
        if hasattr(reranker, 'rerank'):
            reranked_docs = reranker.rerank(query, docs)[:k]
        elif hasattr(reranker, 'arerank'):
            # Support async rerankers
            reranked_docs = await reranker.arerank(query, docs)
            reranked_docs = reranked_docs[:k]
        else:
            # Fallback for different reranker APIs
            reranked_docs = docs[:k]
        
        return reranked_docs
    
    async def add_documents(self, documents: List[Document]) -> List[str]:
        """
        Add documents to the vectorstore.
        
        Args:
            documents: List of documents to add
            
        Returns:
            List of document IDs
        """
        return await self.vectorstore.aadd_documents(documents)
    
    async def close(self):
        """Close the async engine."""
        await self.async_engine.dispose()


# Example usage
async def main():
    from langchain_openai import OpenAIEmbeddings
    
    # Setup - note the postgresql+asyncpg:// prefix for async
    async_connection_string = "postgresql+asyncpg://user:pass@localhost:5432/dbname"
    embeddings = OpenAIEmbeddings()
    
    # Initialize hybrid search
    hybrid_search = AsyncHybridSearchPgVector(
        async_connection_string=async_connection_string,
        embeddings=embeddings,
        collection_name="my_documents",
        k=10
    )
    
    # Setup tsvector column and indexes
    await hybrid_search.setup_tsvector_column()
    
    # Add documents (vectorstore handles embedding)
    documents = [
        Document(page_content="Your document content here", metadata={"source": "doc1"}),
        Document(page_content="Another document with different content", metadata={"source": "doc2"}),
        # ... more documents
    ]
    await hybrid_search.add_documents(documents)
    
    # Perform hybrid search
    results = await hybrid_search.hybrid_search(
        query="your search query",
        k=5,
        vector_weight=0.5,
        text_weight=0.5
    )
    
    print("Hybrid search results:")
    for doc, score in results:
        print(f"Score: {score:.4f} - {doc.page_content[:100]}...")
    
    # With reranking (example with hypothetical reranker)
    # from some_reranker_library import BMEReranker
    # reranker = BMEReranker()
    # reranked_results = await hybrid_search.search_with_reranking(
    #     query="your search query",
    #     reranker=reranker,
    #     k=5,
    #     initial_k=20
    # )
    
    # Clean up
    await hybrid_search.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
