"""SharePointOrchestrator class."""

import logging
from collections import defaultdict

from bnppf_rag_engine.config.config_handler import ConfigHandler
from bnppf_rag_engine.rag_engine.sharepoint.db_manager import (
    VectorDBManager,
)
from bnppf_rag_engine.rag_engine.sharepoint.document_processor import (
    DocumentProcessor,
)
from bnppf_rag_engine.rag_engine.sharepoint.service import (
    SharePointService,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    ProcessedDocument,
)

logger = logging.getLogger(__name__)


class SharePointOrchestrator:
    """Main SharePoint client to orchestrate document processing and vector DB updates."""

    def __init__(
        self,
        sharepoint_service: SharePointService,
        document_processor: DocumentProcessor,
        vector_db_manager: VectorDBManager,
        config_handler: ConfigHandler,
    ):
        """Initializes the orchestrator with dependency-injected services."""
        self.sp_service = sharepoint_service
        self.doc_processor = document_processor
        self.db_manager = vector_db_manager
        self.config_handler = config_handler
    ## Refactor this function to reduce its Cognitive Complexity from 16 to the 15 allowed.
    async def run(self, project_args) -> None:
        """Main execution method to run the entire synchronization process."""
        # 1. Handle deleted files
        deleted_files = self.sp_service.get_deleted_file_names()
        if deleted_files:
            for file_name in deleted_files:
                self.doc_processor.delete_document(file_name=file_name)

        # 2. Fetch and process existing documents to find new/updated ones
        all_documents_by_lang = self.sp_service.get_documents_by_language(["Documents"])

        newly_uploaded_by_lang = defaultdict(list)
        for lang, sources in all_documents_by_lang.items():
            for source, doc_list in sources.items():
                for doc_data in doc_list:
                    processed_doc = ProcessedDocument(
                        file=doc_data["File"],
                        nota_number=doc_data.get("NotaNumber"),
                        source=source,
                        language=lang,
                    )

                    # Determine if the doc is new and return its content
                    was_uploaded, file_content = self.doc_processor.process_document(
                        doc=processed_doc, parsed_args=project_args
                    )

                    if was_uploaded:
                        processed_doc.content = file_content  # Attach content for parsing
                        newly_uploaded_by_lang[lang].append(processed_doc)

        # Update Vector DB for each language that has new documents
        languages_to_process = self._get_languages_to_process(project_args)
        for lang in languages_to_process:
            new_docs_for_lang = newly_uploaded_by_lang.get(lang)
            if not new_docs_for_lang:
                logger.info("No new documents to process for language: %s", {lang})
                continue

            await self.db_manager.update_for_language(
                language=lang, new_documents=new_docs_for_lang, project_name=project_args.project_name
            )

    def _get_languages_to_process(self, project_args) -> list[str]:
        """Determines the list of languages to process based on arguments or config."""
        if hasattr(project_args, "language") and project_args.language:
            return [project_args.language]
        return self.config_handler.get_config("languages")
