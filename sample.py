from argparse import Namespace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from bnppf_rag_engine.rag_engine.sharepoint.document_processor import (
    DocumentProcessor,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    ProcessedDocument,
)


class TestDocumentProcessor:
    """Test DocumentProcessor class."""

    @pytest.fixture
    def mock_api_client(self):
        """Create mock API client."""
        return Mock()

    @pytest.fixture
    def mock_cos_api(self):
        """Create mock COS API."""
        return Mock()

    @pytest.fixture
    def mock_metadata_manager(self):
        """Create mock metadata manager."""
        return Mock()

    @pytest.fixture
    def document_processor(self, mock_api_client, mock_cos_api, mock_metadata_manager):
        """Create DocumentProcessor instance."""
        return DocumentProcessor(mock_api_client, mock_cos_api, mock_metadata_manager)

    def test_process_document_not_recent(self, document_processor):
        """Test processing document that's not recently modified."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        time_str = old_time.isoformat().replace("+00:00", "Z")

        doc = ProcessedDocument(
            file={"Name": "test.docx", "TimeLastModified": time_str},
            nota_number="123",
            source="test_source",
            language="EN",
        )

        parsed_args = Namespace(project_name="test_project")

        # Mock the file to exist in COS, so it's not processed
        document_processor.cos_api.file_exists.return_value = True

        # Should not process old documents that already exist
        document_processor.process_document(doc, parsed_args)
        document_processor.api_client.download_file.assert_not_called()
        document_processor.cos_api.upload_file.assert_not_called()

    @patch("bnppf_rag_engine.rag_engine.sharepoint.document_processor.tempfile.NamedTemporaryFile")
    @patch("bnppf_rag_engine.rag_engine.sharepoint.document_processor.os.unlink")
    def test_process_document_success(self, mock_unlink, mock_temp_file, document_processor):
        """Test successful document processing."""
        # Setup recent time
        recent_time = datetime.now(timezone.utc) - timedelta(hours=12)
        time_str = recent_time.isoformat().replace("+00:00", "Z")

        doc = ProcessedDocument(
            file={
                "Name": "test.docx",
                "ServerRelativeUrl": "/sites/test/test.docx",
                "TimeLastModified": time_str,
                "Author": "user@example.com",
            },
            nota_number="123",
            source="test_source",
            language="EN",
        )

        # Setup mocks
        mock_temp_file_obj = Mock()
        mock_temp_file_obj.name = "/tmp/temp_file.docx"
        mock_temp_file_obj.__enter__ = Mock(return_value=mock_temp_file_obj)
        mock_temp_file_obj.__exit__ = Mock(return_value=None)
        mock_temp_file.return_value = mock_temp_file_obj

        document_processor.api_client.download_file.return_value = b"file content"

        parsed_args = Namespace(project_name="test_project")

        document_processor.process_document(doc, parsed_args)

        # Verify API calls
        document_processor.api_client.download_file.assert_called_once_with("/sites/test/test.docx")
        document_processor.cos_api.upload_file.assert_called_once()
        document_processor.metadata_manager.write_metadata.assert_called_once()
        mock_unlink.assert_called_once()

    def test_delete_document_success(self, document_processor):
        """Test successful document deletion."""
        metadata = {"file_name": "test.docx", "source": "test_source", "language": "EN"}

        document_processor.metadata_manager.get_metadata_by_filename.return_value = metadata

        document_processor.delete_document("test.docx")

        document_processor.cos_api.delete_file.assert_called_once()
        document_processor.metadata_manager.remove_metadata.assert_called_once()

    def test_delete_document_not_found(self, document_processor):
        """Test deleting document that's not in metadata."""
        document_processor.metadata_manager.get_metadata_by_filename.return_value = None

        document_processor.delete_document("test.docx")

        document_processor.cos_api.delete_file.assert_not_called()
        document_processor.metadata_manager.remove_metadata.assert_not_called()
