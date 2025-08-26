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

    async def run(self, project_args) -> None:
        """Main execution method to run the entire synchronization process."""
        # 1. Handle deleted files
        self._handle_deleted_files()
        
        # 2. Process documents and find new/updated ones
        newly_uploaded_by_lang = self._process_all_documents(project_args)
        
        # 3. Update Vector DB for each language that has new documents
        await self._update_vector_db_for_languages(project_args, newly_uploaded_by_lang)

    def _handle_deleted_files(self) -> None:
        """Handle deletion of files that were removed from SharePoint."""
        deleted_files = self.sp_service.get_deleted_file_names()
        if deleted_files:
            for file_name in deleted_files:
                self.doc_processor.delete_document(file_name=file_name)

    def _process_all_documents(self, project_args) -> defaultdict:
        """Process all documents and return newly uploaded ones by language."""
        all_documents_by_lang = self.sp_service.get_documents_by_language(["Documents"])
        newly_uploaded_by_lang = defaultdict(list)
        
        for lang, sources in all_documents_by_lang.items():
            new_docs_for_lang = self._process_documents_for_language(lang, sources, project_args)
            newly_uploaded_by_lang[lang].extend(new_docs_for_lang)
        
        return newly_uploaded_by_lang

    def _process_documents_for_language(self, lang: str, sources: dict, project_args) -> list:
        """Process documents for a specific language and return newly uploaded ones."""
        newly_uploaded = []
        
        for source, doc_list in sources.items():
            new_docs_for_source = self._process_documents_for_source(
                lang, source, doc_list, project_args
            )
            newly_uploaded.extend(new_docs_for_source)
        
        return newly_uploaded

    def _process_documents_for_source(self, lang: str, source: str, doc_list: list, project_args) -> list:
        """Process documents for a specific source and return newly uploaded ones."""
        newly_uploaded = []
        
        for doc_data in doc_list:
            processed_doc = ProcessedDocument(
                file=doc_data["File"],
                nota_number=doc_data.get("NotaNumber"),
                source=source,
                language=lang,
            )
            
            was_uploaded, file_content = self.doc_processor.process_document(
                doc=processed_doc, parsed_args=project_args
            )
            
            if was_uploaded:
                processed_doc.content = file_content
                newly_uploaded.append(processed_doc)
        
        return newly_uploaded

    async def _update_vector_db_for_languages(self, project_args, newly_uploaded_by_lang: defaultdict) -> None:
        """Update vector database for all languages that have new documents."""
        languages_to_process = self._get_languages_to_process(project_args)
        
        for lang in languages_to_process:
            await self._update_vector_db_for_language(lang, newly_uploaded_by_lang, project_args)

    async def _update_vector_db_for_language(self, lang: str, newly_uploaded_by_lang: defaultdict, project_args) -> None:
        """Update vector database for a specific language."""
        new_docs_for_lang = newly_uploaded_by_lang.get(lang)
        if not new_docs_for_lang:
            logger.info("No new documents to process for language: %s", lang)
            return

        await self.db_manager.update_for_language(
            language=lang, 
            new_documents=new_docs_for_lang, 
            project_name=project_args.project_name
        )

    def _get_languages_to_process(self, project_args) -> list[str]:
        """Determines the list of languages to process based on arguments or config."""
        if hasattr(project_args, "language") and project_args.language:
            return [project_args.language]
        return self.config_handler.get_config("languages")
