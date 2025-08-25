# main.py (or wherever you run the process)

# 1. Initialize Configuration
sp_config = SharePointConfig(...)
config_handler = get_or_raise_config(project_args.project_name)
cos_api = create_cos_api()

# 2. Instantiate Services (Dependency Injection)
authenticator = SharePointAuthenticator(sp_config, ...)
api_client = SharePointAPIClient(sp_config, authenticator)
metadata_manager = MetadataManager(cos_api)
document_parser = DocumentParser(config_handler)

sharepoint_service = SharePointService(api_client)
document_processor = DocumentProcessor(api_client, cos_api, metadata_manager)
vector_db_manager = VectorDBManager(
    config_handler=config_handler,
    document_parser=document_parser,
    cos_api=cos_api,
)

# 3. Instantiate and Run the Orchestrator
client = SharePointOrchestrator(
    sharepoint_service=sharepoint_service,
    document_processor=document_processor,
    vector_db_manager=vector_db_manager,
    config_handler=config_handler,
)

await client.run(project_args)


# sharepoint_service.py

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

class SharePointService:
    """Handles all data retrieval from SharePoint."""

    def __init__(self, api_client: SharePointAPIClient):
        self.api_client = api_client

    def get_documents_by_language(
        self, libraries: list[str]
    ) -> dict[str, dict[str, list[dict]]]:
        """
        Retrieves documents from specified libraries and groups them by language and source.
        """
        logger.info("Grouping documents by their source and language.")
        grouped_documents = defaultdict(lambda: defaultdict(list))

        for library in libraries:
            try:
                documents = self._retrieve_documents_from_library(library)
                for doc in documents:
                    language, source = doc.get("Language"), doc.get("Source")
                    if language and source:
                        grouped_documents[language][source].append(doc)
            except (ConnectionError, KeyError, ValueError) as e:
                logger.error("Error processing library %s: %s", library, e)
        return grouped_documents

    def get_deleted_file_names(self) -> list[str]:
        """Retrieves a list of deleted file names from the SharePoint recycle bin."""
        logger.info("Retrieving deleted file names from SharePoint recycle bin.")
        try:
            endpoint = "/_api/site/RecycleBin?$filter=ItemState eq 1"
            response = self.api_client.send_request(endpoint)
            deleted_items = response.get("d", {}).get("results", [])
            return [item.get("Title", "") for item in deleted_items if item.get("Title")]
        except (ConnectionError, KeyError) as e:
            logger.error("Failed to retrieve deleted files: %s", e)
            return []

    def _retrieve_documents_from_library(
        self, library_name: str
    ) -> list[dict[str, Any]]:
        """Retrieves and formats document metadata from a specific SharePoint library."""
        endpoint = (
            f"/_api/web/lists/GetByTitle('{library_name}')/items?"
            "$select=notanumber,source,language,File&$expand=File"
        )
        response = self.api_client.send_request(endpoint)
        items = response.get("d", {}).get("results", [])

        return [
            {
                "File": item.get("File", {}),
                "NotaNumber": item.get("notanumber"),
                "Source": item.get("source"),
                "Language": item.get("language"),
            }
            for item in items
        ]


# vector_db_manager.py

import logging
import os
import warnings
from collections import defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Coroutine

logger = logging.getLogger(__name__)

# This map is better placed here, with the code that uses it.
PARSER_NAME_TO_OBJECT = {
    "HtmlParser": HtmlParser,
    "EurekaDocxParser": EurekaDocxParser,
    "DoclingParser": DoclingParser,
}

class VectorDBManager:
    """Manages parsing, chunking, and updating the vector database."""

    def __init__(self, config_handler: ConfigHandler, document_parser: DocumentParser, cos_api: CosBucketApi):
        self.config_handler = config_handler
        self.parser = document_parser
        self.cos_api = cos_api

    async def update_for_language(
        self, language: str, new_documents: list[ProcessedDocument], project_name: str
    ) -> None:
        """
        Orchestrates the entire vector DB update process for a given language.
        """
        logger.info(f"Updating vector DB for {language} with {len(new_documents)} new documents.")
        try:
            # 1. Parse documents
            data_source_to_documents = await self._parse_documents(
                language=language,
                new_documents=new_documents,
                project_name=project_name
            )
            if not any(data_source_to_documents.values()):
                logger.info(f"No parseable documents found for {language}. Aborting update.")
                return

            # 2. Create chunks
            document_chunks = self._create_document_chunks(data_source_to_documents)
            if not document_chunks:
                logger.info(f"No document chunks created for {language}. Aborting update.")
                return

            # 3. Initialize and update DB
            vector_db = self._initialize_vector_db(language)
            drop_and_resetup_vector_db(vector_db.vector_db_config) # Assuming this is a required step
            await vector_db.from_chunks(document_chunks)

            # 4. Save to object storage
            await vector_db.to_cos(self.cos_api, should_overwrite_on_cos=True)
            logger.info(f"Successfully updated vector DB for {language}.")

        except Exception as e:
            logger.error(f"Failed to update vector DB for {language}: {e}", exc_info=True)
            # Optionally re-raise to halt execution
            # raise

    def _initialize_vector_db(self, language: str) -> VectorDB:
        """Initializes and sets up a VectorDB instance."""
        vector_db = VectorDB(
            vector_db_config=self.config_handler.get_config("vector_db"),
            embedding_model=BNPPFEmbeddings(self.config_handler.get_config("embedding_model")),
            language=language,
            project_name=self.config_handler.get_config("project_name"),
        )
        vector_db.setup_db_instance()
        return vector_db

    def _create_document_chunks(
        self, data_source_to_documents: dict[str, list[Document]]
    ) -> list[DocumentChunk]:
        """Concatenates documents by source and splits them into chunks."""
        splitter = DocumentSplitter(self.config_handler.get_config("document_splitter"))
        documents = self.parser.concat_documents(document=data_source_to_documents)
        document_chunks = splitter.split_documents(documents)

        # Check for duplicate keys
        unique_keys = len({chunk.key for chunk in document_chunks})
        if unique_keys != len(document_chunks):
            warnings.warn(
                f"Duplicate keys found: {unique_keys} unique keys for {len(document_chunks)} chunks.",
                stacklevel=2
            )
        return document_chunks

    async def _parse_documents(
        self, language: str, new_documents: list[ProcessedDocument], project_name: str
    ) -> dict[str, list[Document]]:
        """Parses a list of new documents, grouping them by their source."""
        docs_by_source = defaultdict(list)
        for doc in new_documents:
            docs_by_source[doc.source].append(doc)

        parsed_docs_by_source = defaultdict(list)
        unparsable_docs_log = defaultdict(list)

        for source, docs_to_parse in docs_by_source.items():
            for doc in docs_to_parse:
                try:
                    parsed_doc = await self._parse_document_content(
                        sp_file=doc.file, content=doc.content, source=source, language=language
                    )
                    if parsed_doc:
                        parsed_docs_by_source[source].append(parsed_doc)
                except Exception as e:
                    file_name = doc.file.get("Name", "Unknown File")
                    logger.error(f"Failed to parse document {file_name}: {e}")
                    unparsable_docs_log[source].append(f"{file_name} because {e!s}")

        for source, unparsable in unparsable_docs_log.items():
            self.parser.write_unparsed_docs(unparsable, source, language, project_name)

        return parsed_docs_by_source

    async def _parse_document_content(
        self, sp_file: dict, content: bytes, source: str, language: str
    ) -> Document | None:
        """Parses a single document's content from a temporary file."""
        file_name = sp_file.get("Name")
        if not file_name:
            logger.warning("SharePoint file has no name, cannot parse.")
            return None

        file_extension = Path(file_name).suffix.lstrip('.').lower()
        parser_config = self.parser.parser_config

        if file_extension not in parser_config["sources"].get(source, []):
            logger.warning(f"File extension '.{file_extension}' not supported for source '{source}'.")
            return None

        parser_info = parser_config["extension_to_parser_map"][file_extension]
        file_parser = PARSER_NAME_TO_OBJECT[parser_info["name"]](**parser_info["kwargs"])

        with NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as temp_file:
            temp_file.write(content)
            temp_file_path = Path(temp_file.name)

        try:
            document = await file_parser.parse_as_document(path=temp_file_path, id=file_name)
            if source == EUREKA:
                # Apply source-specific post-processing
                document = update_titles_and_depths_eureka_nota(
                    document=document,
                    titles=get_titles(filepath=str(temp_file_path)),
                    language=language,
                )
            return document
        finally:
            os.unlink(temp_file_path) # Ensure cleanup


# sharepoint_orchestrator.py

import logging
from collections import defaultdict

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
        """
        Main execution method to run the entire synchronization process.
        """
        # 1. Handle deleted files
        deleted_files = self.sp_service.get_deleted_file_names()
        if deleted_files:
            self.doc_processor.delete_documents(file_names=deleted_files)

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
                    
                    # The processor determines if the doc is new and returns its content
                    was_uploaded, file_content = self.doc_processor.process_document(
                        doc=processed_doc, parsed_args=project_args
                    )
                    
                    if was_uploaded:
                        processed_doc.content = file_content # Attach content for parsing
                        newly_uploaded_by_lang[lang].append(processed_doc)

        # 3. Update Vector DB for each language that has new documents
        languages_to_process = self._get_languages_to_process(project_args)
        for lang in languages_to_process:
            new_docs_for_lang = newly_uploaded_by_lang.get(lang)
            if not new_docs_for_lang:
                logger.info(f"No new documents to process for language: {lang}")
                continue
            
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
