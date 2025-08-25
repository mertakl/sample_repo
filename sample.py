from collections import defaultdict
import logging
import os
import tempfile
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class SharePointClient:
    """Main SharePoint client class with vector DB integration."""

    def __init__(self, sp_config: SharePointConfig):  # noqa: D107
        self.config = sp_config
        self.cos_api = self._create_cos_api()

        # Initialize components
        self.azure_creds = self._initialize_azure_credentials()
        self.authenticator = SharePointAuthenticator(sp_config, self.azure_creds)
        self.api_client = SharePointAPIClient(sp_config, self.authenticator)
        self.metadata_manager = MetadataManager(self.cos_api)
        self.document_processor = DocumentProcessor(self.api_client, self.cos_api, self.metadata_manager)
        
        # Track processed documents for vector DB updates
        self.newly_uploaded_documents = defaultdict(list)

    def run(self, project_args) -> None:
        """Main execution method with vector DB integration."""
        config_handler = self._get_config_handler(project_args.project_name)
        languages = self._get_languages(project_args, config_handler)

        # Handle deleted files
        self._process_deleted_files()

        # Process documents by language
        grouped_documents = self._get_grouped_documents(["Documents"])

        for language in languages:
            documents = grouped_documents.get(language, {})
            self._process_documents_by_language(documents, project_args, language)
            
            # Update vector DB if new documents were uploaded for this language
            if self.newly_uploaded_documents.get(language):
                await self._update_vector_db_for_language(
                    language=language,
                    config_handler=config_handler,
                    project_args=project_args
                )

    def _process_documents_by_language(self, documents_by_source: dict[str, list[dict]], doc_args, language: str) -> None:
        """Process documents grouped by source for a specific language."""
        for source, doc_list in documents_by_source.items():
            for doc_data in doc_list:
                doc = ProcessedDocument(
                    file=doc_data["File"],
                    nota_number=doc_data.get("NotaNumber"),
                    source=source,
                    language=doc_data.get("Language", ""),
                )
                
                # Track if document was newly uploaded
                was_uploaded = self.document_processor.process_document(doc=doc, parsed_args=doc_args)
                if was_uploaded:
                    self.newly_uploaded_documents[language].append(doc)

    async def _update_vector_db_for_language(self, language: str, config_handler: ConfigHandler, project_args) -> None:
        """Update vector DB with newly uploaded documents for a specific language."""
        logger.info(f"Updating vector DB for {language} with {len(self.newly_uploaded_documents[language])} new documents")
        
        try:
            # Parse only the newly uploaded documents
            data_source_to_documents = await self._parse_new_documents(
                language=language,
                config_handler=config_handler,
                project_args=project_args
            )
            
            if not data_source_to_documents or not any(docs for docs in data_source_to_documents.values()):
                logger.info(f"No parseable documents found for {language}")
                return
            
            # Create document chunks
            document_chunks = create_document_chunks(config_handler, data_source_to_documents)
            
            if not document_chunks:
                logger.info(f"No document chunks created for {language}")
                return
            
            # Initialize vector DB
            vector_db = VectorDB(
                vector_db_config=config_handler.get_config("vector_db"),
                embedding_model=BNPPFEmbeddings(config_handler.get_config("embedding_model")),
                language=language,
                project_name=config_handler.get_config("project_name"),
            )
            vector_db.setup_db_instance()
            
            # Add new chunks to existing vector DB (don't drop and reset)
            await vector_db.add_chunks(document_chunks)
            
            # Save updated vector DB to COS
            await vector_db.to_cos(self.cos_api, should_overwrite_on_cos=True)
            
            logger.info(f"Successfully updated vector DB for {language}")
            
        except Exception as e:
            logger.error(f"Failed to update vector DB for {language}: {e}")
            raise

    async def _parse_new_documents(self, language: str, config_handler: ConfigHandler, project_args) -> dict[str, list[Document]]:
        """Parse only the newly uploaded documents."""
        parser = DocumentParser(config_handler)
        
        # Create a temporary mapping of newly uploaded documents by source
        new_docs_by_source = defaultdict(list)
        for doc in self.newly_uploaded_documents[language]:
            new_docs_by_source[doc.source].append(doc)
        
        data_source_to_documents = {}
        
        for source, docs in new_docs_by_source.items():
            parsed_docs = []
            unparsable_docs = []
            
            for doc in docs:
                file_name = doc.file["Name"]
                file_path = self.document_processor.path_manager.get_document_path(
                    source=source, 
                    language=language, 
                    file_name=file_name
                )
                
                try:
                    # Download the file from COS to parse it
                    parsed_doc = await self._parse_document_from_cos(
                        file_path=file_path,
                        parser=parser,
                        source=source,
                        language=language
                    )
                    
                    if parsed_doc:
                        parsed_docs.append(parsed_doc)
                    
                except Exception as e:
                    logger.error(f"Failed to parse document {file_name}: {e}")
                    unparsable_docs.append(f"{file_name} because {str(e)}")
            
            if unparsable_docs:
                DocumentParser.write_unparsed_docs(
                    unparsable_docs=unparsable_docs,
                    source=source,
                    language=language,
                    project_name=project_args.project_name,
                )
            
            data_source_to_documents[source] = parsed_docs
        
        return data_source_to_documents

    async def _parse_document_from_cos(self, file_path: str, parser: DocumentParser, source: str, language: str) -> Optional[Document]:
        """Parse a single document from COS."""
        from tempfile import TemporaryDirectory
        from pathlib import Path
        
        # Get the appropriate parser for this source
        parser_config = parser.parser_config
        file_extensions = parser_config["sources"][source]
        
        # Determine file extension
        file_extension = Path(file_path).suffix.lower()
        if file_extension not in file_extensions:
            logger.warning(f"File extension {file_extension} not supported for source {source}")
            return None
        
        # Get parser for this extension
        parser_info = parser_config["extension_to_parser_map"][file_extension]
        file_parser = PARSER_NAME_TO_OBJECT[parser_info["name"]](**parser_info["kwargs"])
        
        with TemporaryDirectory() as temp_dir:
            temp_file_path = Path(temp_dir) / Path(file_path).name
            
            # Download file from COS
            file_content = self.cos_api.read_file(cos_filename=file_path)
            temp_file_path.write_bytes(file_content.read())
            
            try:
                # Parse the document
                document = await file_parser.parse_as_document(path=temp_file_path, id=temp_file_path.name)
                
                # Apply Eureka-specific processing if needed
                if source == "EUREKA":  # Adjust this constant as needed
                    document = update_titles_and_depths_eureka_nota(
                        document=document,
                        titles=get_titles(filepath=str(temp_file_path)),
                        language=language,
                    )
                
                return document
                
            except Exception as e:
                logger.error(f"Failed to parse document {file_path}: {e}")
                return None

    def _process_deleted_files(self) -> None:
        """Process deleted files from recycle bin."""
        try:
            logger.info("Retrieving deleted files from sharepoint.")
            deleted_files = self._get_deleted_file_names()
            for file_name in deleted_files:
                self.document_processor.delete_document(file_name=file_name)
        except (ConnectionError, ValueError, KeyError) as e:
            logger.error("Failed to process deleted files: %s", e)

    def _get_grouped_documents(self, libraries: list[str]) -> dict[str, dict[str, list[dict]]]:
        """Get documents grouped by language and source."""
        logger.info("Grouping documents by their source and language.")

        grouped_documents = defaultdict(lambda: defaultdict(list))

        for library in libraries:
            try:
                # Retrieve documents from sharepoint
                documents = self._retrieve_documents_from_library(library)
                for doc in documents:
                    language, source = doc["Language"], doc["Source"]
                    if language and source:
                        grouped_documents[language][source].append(doc)
            except (ConnectionError, KeyError, ValueError) as e:
                logger.error("Error processing library %s: %s", library, e)
                continue

        return grouped_documents


class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(  # noqa: D107
        self, api_client: SharePointAPIClient, cos_api: CosBucketApi, metadata_manager: MetadataManager
    ):
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager
        self.path_manager = PathManager()

    def process_document(self, doc: ProcessedDocument, parsed_args) -> bool:
        """Process a single document. Returns True if document was uploaded/updated."""
        file_info = doc.file
        file_name, last_modified, source, language = (
            file_info["Name"],
            file_info["TimeLastModified"],
            file_info["Source"],
            file_info["Language"],
        )

        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)

        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc, parsed_args)
            return False

        if not DocumentFilter.is_recently_modified(last_modified):
            if not self.cos_api.file_exists(file_path):
                # File does not exist, upload it
                self._upload_document(doc, file_path)
                return True
            return False  # File exists and not recently modified
        
        # File was recently modified, upload it
        self._upload_document(doc, file_path)
        return True

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
        
        # TODO: Also remove from vector DB
        # This would require additional logic to remove specific document chunks from the vector DB

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
