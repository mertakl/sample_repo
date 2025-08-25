import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

# Assuming these imports are available in the test environment
from orchestrator import SharePointOrchestrator, ProcessedDocument
from project_args import ProjectArgs


class TestSharePointOrchestratorFunctional(unittest.TestCase):
    """
    Functional tests for the SharePointOrchestrator class.
    Mocks external services to test the orchestration logic.
    """

    def setUp(self):
        """Set up mock dependencies and the orchestrator instance for each test."""
        self.mock_sp_service = MagicMock()
        self.mock_doc_processor = MagicMock()
        # AsyncMock is used for methods that are async, like run() and update_for_language()
        self.mock_db_manager = AsyncMock()
        self.mock_config_handler = MagicMock()

        # Instantiate the orchestrator with the mocked dependencies
        self.orchestrator = SharePointOrchestrator(
            sharepoint_service=self.mock_sp_service,
            document_processor=self.mock_doc_processor,
            vector_db_manager=self.mock_db_manager,
            config_handler=self.mock_config_handler,
        )

        # Mock the project arguments object
        self.mock_project_args = MagicMock(spec=ProjectArgs)
        self.mock_project_args.project_name = "test_project"
        self.mock_project_args.language = None  # No language filter by default

    def tearDown(self):
        """Clean up mocks after each test."""
        self.mock_sp_service.reset_mock()
        self.mock_doc_processor.reset_mock()
        self.mock_db_manager.reset_mock()
        self.mock_config_handler.reset_mock()

    async def test_run_with_new_documents(self):
        """Test the orchestrator when new documents are available."""
        # 1. Mock the SharePoint service to return no deleted files and some new documents
        self.mock_sp_service.get_deleted_file_names.return_value = []
        self.mock_sp_service.get_documents_by_language.return_value = {
            "EN": {
                "SourceA": [
                    {
                        "File": {"Name": "doc1.pdf", "TimeLastModified": "2023-01-01T12:00:00Z", "ServerRelativeUrl": "/sites/Test/doc1.pdf"},
                        "Language": "EN",
                        "Source": "SourceA",
                    },
                ]
            }
        }
        # 2. Mock the document processor to indicate the file was uploaded/updated
        self.mock_doc_processor.process_document.return_value = (True, b"file content")
        # 3. Mock the config handler to return a list of languages
        self.mock_config_handler.get_config.return_value = ["EN", "FR"]

        # Run the orchestrator
        await self.orchestrator.run(self.mock_project_args)

        # 4. Assertions to verify the correct behavior
        self.mock_sp_service.get_deleted_file_names.assert_called_once()
        self.mock_doc_processor.delete_document.assert_not_called()
        self.mock_sp_service.get_documents_by_language.assert_called_once_with(["Documents"])
        self.mock_doc_processor.process_document.assert_called_once()
        self.mock_db_manager.update_for_language.assert_called_once_with(
            language="EN",
            new_documents=unittest.mock.ANY,  # We don't care about the exact list, just that it was passed
            project_name="test_project",
        )

    async def test_run_with_deleted_documents(self):
        """Test the orchestrator when files have been deleted from SharePoint."""
        # 1. Mock the SharePoint service to return deleted file names
        self.mock_sp_service.get_deleted_file_names.return_value = ["deleted_doc.docx", "old_file.pdf"]
        self.mock_sp_service.get_documents_by_language.return_value = {}  # No new documents

        # 2. Run the orchestrator
        await self.orchestrator.run(self.mock_project_args)

        # 3. Assertions
        self.mock_sp_service.get_deleted_file_names.assert_called_once()
        self.assertEqual(self.mock_doc_processor.delete_document.call_count, 2)
        self.mock_doc_processor.delete_document.assert_any_call(file_name="deleted_doc.docx")
        self.mock_doc_processor.delete_document.assert_any_call(file_name="old_file.pdf")
        self.mock_db_manager.update_for_language.assert_not_called()

    async def test_run_with_language_filter(self):
        """Test the orchestrator's language filter functionality."""
        # 1. Set the language filter in the mock arguments
        self.mock_project_args.language = "FR"
        self.mock_config_handler.get_config.return_value = ["EN", "FR"]

        # 2. Mock SharePoint to return documents in multiple languages
        self.mock_sp_service.get_deleted_file_names.return_value = []
        self.mock_sp_service.get_documents_by_language.return_value = {
            "EN": {
                "SourceA": [{"File": {"Name": "doc_en.pdf"}, "Language": "EN", "Source": "SourceA"}],
            },
            "FR": {
                "SourceB": [{"File": {"Name": "doc_fr.docx"}, "Language": "FR", "Source": "SourceB"}],
            },
        }
        self.mock_doc_processor.process_document.return_value = (True, b"file content")

        # 3. Run the orchestrator
        await self.orchestrator.run(self.mock_project_args)

        # 4. Assertions
        # The orchestrator should process all documents to check their status
        self.assertEqual(self.mock_doc_processor.process_document.call_count, 2)
        # However, it should only call update_for_language for the French documents
        self.mock_db_manager.update_for_language.assert_called_once_with(
            language="FR",
            new_documents=unittest.mock.ANY,
            project_name="test_project",
        )


if __name__ == "__main__":
    # This allows you to run the tests directly from the command line
    unittest.main(argv=["first-arg-is-ignored"], exit=False, verbosity=2)
