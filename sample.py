##Also this? 

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

        # Should not process old documents
        document_processor.process_document(doc, parsed_args)
        document_processor.api_client.download_file.assert_not_called()

    @patch("bnppf_rag_engine.rag_engine.sharepoint.db_manager.tempfile.NamedTemporaryFile")
    @patch("bnppf_rag_engine.rag_engine.sharepoint.db_manager.os.unlink")
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


##Original code;

"""DocumentProcessor class."""

import logging
import os
import tempfile

from bnppf_cos import CosBucketApi

from bnppf_rag_engine.rag_engine.document_parser import DocumentParser
from bnppf_rag_engine.rag_engine.sharepoint.api_client import (
    SharePointAPIClient,
)
from bnppf_rag_engine.rag_engine.sharepoint.document_filter import (
    DocumentFilter,
)
from bnppf_rag_engine.rag_engine.sharepoint.metadata_manager import (
    MetadataManager,
)
from bnppf_rag_engine.rag_engine.sharepoint.path_manager import (
    PathManager,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    DocumentMetadata,
    ProcessedDocument,
)

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(  # noqa: D107
        self, api_client: SharePointAPIClient, cos_api: CosBucketApi, metadata_manager: MetadataManager
    ):
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager
        self.path_manager = PathManager()

    def process_document(self, doc: ProcessedDocument, parsed_args) -> tuple[bool, bytes]:
        """Process a single document. Returns True if document was uploaded/updated."""
        file_info = doc.file
        file_name, last_modified, source, language = (
            file_info["Name"],
            file_info["TimeLastModified"],
            doc.source,
            doc.language,
        )

        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)

        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc, parsed_args)
            return False, None

        if not DocumentFilter.is_recently_modified(last_modified):
            if not self.cos_api.file_exists(file_path):
                # File does not exist, upload it
                file_content = self._upload_document(doc, file_path)
                return True, file_content
            return False, None  # File exists and not recently modified

        # File was recently modified, upload it
        file_content = self._upload_document(doc, file_path)
        return True, file_content

    def delete_document(self, file_name: str) -> None:
        """Delete document from COS and update metadata."""
        metadata_path = self.path_manager.get_metadata_path()

        deleted_doc_metadata = self.metadata_manager.get_metadata_by_filename(
            file_name=file_name, metadata_path=metadata_path
        )

        if not deleted_doc_metadata:
            # Nothing to delete
            return

        # Delete file from COS
        source, language = deleted_doc_metadata["source"], deleted_doc_metadata["language"]
        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)
        logger.info("Deleting file %s", file_name)
        self.cos_api.delete_file(str(file_path))

        # Remove from metadata
        self.metadata_manager.remove_metadata(metadata_path=metadata_path, file_name=file_name)

    def _upload_document(self, doc: ProcessedDocument, document_path: str) -> None:
        """Upload document to COS and save metadata."""
        file_info = doc.file
        file_name, server_relative_url = file_info["Name"], file_info["ServerRelativeUrl"]

        logger.info("Downloading document %s from sharepoint...", file_name)

        # Download file content
        file_content = self.api_client.download_file(server_relative_url)

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            logger.info("Uploading document %s to COS...", file_name)
            # Upload to COS
            self.cos_api.upload_file(temp_file_path, document_path)

            # Save metadata
            metadata = DocumentMetadata(
                file_name=file_name,
                url=server_relative_url,
                created_by=file_info.get("Author"),
                last_modified=file_info["TimeLastModified"],
                nota_number=doc.nota_number,
                language=doc.language,
                source=doc.source,
            )

            metadata_path = self.path_manager.get_metadata_path()
            self.metadata_manager.write_metadata(metadata, metadata_path)

            return file_content

        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)

    def _log_unparseable_document(self, file_name: str, doc: ProcessedDocument, p_args) -> None:
        """Log unparseable document."""
        DocumentParser.write_unparsed_docs(
            unparsable_docs=[file_name],
            source=doc.source,
            language=doc.language,
            project_name=p_args.project_name,
        )

        _, extension = os.path.splitext(file_name)
        logger.error("Files with extension '%s' are not supported", extension)


