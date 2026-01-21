import pytest
from search_adapters import BaseChunkIndexerPort, Document  # Adjust import

class TestBaseChunkIndexerPort:
    
    def test_document_to_chunk_success(self):
        """Test conversion of Document to DocumentChunk with full metadata."""
        doc = Document(
            page_content="Main Content",
            metadata={
                "content": "Full Content",
                "document_id": "doc_123",
                "hyperlinks": [{"url": "http://test.com"}],
                "metadata": {"author": "Tester"}
            }
        )
        
        chunk = BaseChunkIndexerPort._document_to_chunk(doc)
        
        assert chunk.key == "Main Content"
        assert chunk.document_id == "doc_123"
        assert chunk.content == "Full Content"
        assert len(chunk.hyperlinks) == 1
        assert chunk.metadata["author"] == "Tester"

    def test_document_to_chunk_missing_metadata(self):
        """Test conversion handles missing metadata gracefully."""
        doc = Document(page_content="Just Content", metadata=None)
        
        chunk = BaseChunkIndexerPort._document_to_chunk(doc)
        
        assert chunk.key == "Just Content"
        assert chunk.content == ""  # Default from .get()
        assert chunk.document_id == ""

    def test_documents_with_scores_to_query_responses(self):
        """Test batch conversion logic."""
        doc1 = Document(page_content="A", metadata={"id": 1})
        doc2 = Document(page_content="B", metadata={"id": 2})
        input_data = [(doc1, 0.95), (doc2, 0.80)]

        # Note: Depending on how you implemented the fix for the variable name bug
        responses = BaseChunkIndexerPort.documents_wıth_scores_to_query_responses(input_data)
        
        assert len(responses) == 2
        assert responses[0].score == 0.95
        assert responses[0].chunk.key == "A"
        assert responses[1].score == 0.80
