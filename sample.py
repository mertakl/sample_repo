-- 1. Add the ts_vector column
ALTER TABLE my_documents
ADD COLUMN tsv tsvector;

-- 2. Create a trigger to automatically update the tsv column
-- (This keeps it in sync whenever a document is added or changed)
CREATE OR REPLACE FUNCTION update_tsv_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.tsv := to_tsvector('english', NEW.document); -- Use your language
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvector_update_trigger
BEFORE INSERT OR UPDATE ON my_documents
FOR EACH ROW
EXECUTE FUNCTION update_tsv_column();

-- 3. Create a GIN index for fast searching
CREATE INDEX tsv_gin_idx ON my_documents USING GIN(tsv);


from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_postgres.vectorstores import PGVector
from typing import List

class TsVectorRetriever(BaseRetriever):
    """
    A simple retriever that wraps the PGVector.full_text_search() method.
    """
    vectorstore: PGVector
    """The PGVector store instance that contains the full_text_search method."""
    
    search_type: str = "websearch"
    """The tsquery search type to use (e.g., 'plain', 'phrase', 'websearch')."""

    class Config:
        """Allow arbitrary types for the vectorstore."""
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        """
        Implementation of the abstract method for retrieving relevant documents.
        
        Args:
            query: The search query string.
            
        Returns:
            A list of Document objects.
        """
        # Use the built-in full_text_search method from the PGVector store
        # This method handles the tsquery conversion and ranking (ts_rank)
        return self.vectorstore.full_text_search(
            query=query, 
            search_type=self.search_type
)
        import os
from langchain_core.documents import Document
from langchain_postgres.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings # Or any other embedding model
from langchain.retrievers import EnsembleRetriever

# --- Assume this is your existing setup ---

# 1. Database Connection
CONNECTION_STRING = "postgresql+psycopg://user:password@localhost:5432/my_db"
os.environ["POSTGRES_URL"] = CONNECTION_STRING

# 2. Embedding Model
embeddings = OpenAIEmbeddings()

# 3. Example Documents
docs = [
    Document(page_content="The quick brown fox jumps over the lazy dog."),
    Document(page_content="A journey of a thousand miles begins with a single step."),
    Document(page_content="To be or not to be, that is the question."),
    Document(page_content="LangChain provides tools for building applications with LLMs."),
]

# 4. Initialize and populate PGVector
# This will create the table, embeddings, and (if you set it up) the tsv column.
# Ensure you have run the SQL from Step 1 on the "langchain_pg_embedding" table
# *after* this step, if the table is new.
collection_name = "my_doc_collection"
pgvector_store = PGVector.from_documents(
    documents=docs,
    embedding=embeddings,
    collection_name=collection_name,
    connection=CONNECTION_STRING,
    # This pre-deletes the collection for a clean demo
    pre_delete_collection=True, 
)

print("PGVector store populated.")
# IMPORTANT: If this table was just created, you must now run the
# SQL from Step 1 on the table (e.g., "langchain_pg_collection")
# to add and index the 'tsv' column.

# --- End of setup ---


# --- HERE IS THE SOLUTION ---

# 5. Initialize the standard vector retriever
vector_retriever = pgvector_store.as_retriever(search_kwargs={"k": 2})

# 6. Initialize your new TsVectorRetriever
# It re-uses the *same* vector store object and its connection
ts_retriever = TsVectorRetriever(
    vectorstore=pgvector_store,
    search_type="websearch" # 'websearch' is good for natural language
)

# 7. Initialize the EnsembleRetriever
# This combines and re-ranks the results (using Reciprocal Rank Fusion)
ensemble_retriever = EnsembleRetriever(
    retrievers=[vector_retriever, ts_retriever],
    weights=[0.5, 0.5]  # 50% vector, 50% keyword
)

# 8. Run your hybrid search!
query = "building apps with langchain"

print(f"\n--- Hybrid Search Results for: '{query}' ---")
hybrid_results = ensemble_retriever.invoke(query)
for doc in hybrid_results:
    print(doc)

# You can also test them individually
print(f"\n--- Vector-Only Results ---")
vector_results = vector_retriever.invoke(query)
for doc in vector_results:
    print(doc.page_content)

print(f"\n--- Keyword-Only (ts_vector) Results ---")
keyword_results = ts_retriever.invoke(query)
for doc in keyword_results:
    print(doc.page_content)
