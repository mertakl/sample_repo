class SharePointClient:
    """Main SharePoint client class."""

    def __init__(self, sp_config: SharePointConfig):  # noqa: D107
        self.config = sp_config
        self.cos_api = self._create_cos_api()

        # Initialize components
        self.azure_creds = self._initialize_azure_credentials()
        self.authenticator = SharePointAuthenticator(sp_config, self.azure_creds)
        self.api_client = SharePointAPIClient(sp_config, self.authenticator)
        self.metadata_manager = MetadataManager(self.cos_api)
        self.document_processor = DocumentProcessor(self.api_client, self.cos_api, self.metadata_manager)
        self.parser = None

        # Track processed documents for vector DB updates
        # Stores ProcessedDocument and original doc_data with SharePoint File object
        self.newly_uploaded_documents = defaultdict(list)

    async def run(self, project_args) -> None:
        """Main execution method."""
        config_handler = self._get_config_handler(project_args.project_name)

        self.parser = DocumentParser(config_handler)

        languages = self._get_languages(project_args, config_handler)

        # Handle deleted files
        self._process_deleted_files()

        # Process documents by language
        grouped_documents = self._get_grouped_documents(["Documents"])

        for language in languages:
            documents = grouped_documents.get(language, {})
            await self._process_documents_by_language(documents, project_args)

            # Update vector DB if new documents were uploaded for this language
            if self.newly_uploaded_documents.get(language):
                await self._update_vector_db_for_language(
                    language=language, config_handler=config_handler, project_args=project_args
                )

    def _process_deleted_files(self) -> None:
        """Process deleted files from recycle bin."""
        try:
            logger.info("Retrieving deleted files from sharepoint.")
            deleted_files = self._get_deleted_file_names()
            for file_name in deleted_files:
                self.document_processor.delete_document(file_name=file_name)
        except (ConnectionError, ValueError, KeyError) as e:
            logger.error("Failed to process deleted files: %s", e)

    async     async def _process_documents_by_language(self, documents_by_source: dict[str, list[dict]], doc_args) -> None:
        """Process documents grouped by source for a specific language."""
        for source, doc_list in documents_by_source.items():
            for doc_data in doc_list:
                language = doc_data.get("Language", "")
                doc = ProcessedDocument(
                    file=doc_data["File"],
                    nota_number=doc_data.get("NotaNumber"),
                    source=source,
                    language=language,
                )
                
                # Process document normally
                was_uploaded = self.document_processor.process_document(doc=doc, parsed_args=doc_args)
                
                # Track if document was newly uploaded along with the original doc_data
                if was_uploaded:
                    self.newly_uploaded_documents[language].append({
                        "doc": doc,
                        "doc_data": doc_data  # Keep the original doc_data with File object
                    })

    def _get_grouped_documents(self, libraries: list[str]) -> dict[str, dict[str, list[dict]]]:
        """Get documents grouped by language and source."""
        logger.info("Grouping documents by their source and language.")

        grouped_documents = defaultdict(lambda: defaultdict(list))

        for library in libraries:
            try:
                documents = self._retrieve_documents_from_library(library)
                for doc in documents:
                    language, source = doc["Language"], doc["Source"]
                    if language and source:
                        grouped_documents[language][source].append(doc)
            except (ConnectionError, KeyError, ValueError) as e:
                logger.error("Error processing library %s: %s", library, e)
                continue

        return grouped_documents

    def _retrieve_documents_from_library(self, library_name: str) -> list[dict[str, Any]]:
        """Retrieve documents from specific SharePoint library."""
        endpoint = f"/_api/web/lists/GetByTitle('{library_name}')/items?$select=*&$expand=File"
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

    def _get_deleted_file_names(self) -> list[str]:
        """Get list of deleted file names from recycle bin."""
        try:
            response = self.api_client.send_request(
                "/_api/site/RecycleBin?$filter=ItemState eq 1&$expand=ListItem,ListItem/FieldValueAsText"
            )
            deleted_documents = response.get("d", {}).get("results", [])
            return [doc.get("Title", "") for doc in deleted_documents if doc.get("Title")]
        except (ConnectionError, KeyError):
            return []

    def _initialize_azure_credentials(self) -> AzureCredentials:
        """Initialize Azure credentials."""
        tenant_id = os.environ["AZURE_TENANT_ID"]
        if not tenant_id:
            raise ValueError("AZURE_TENANT_ID environment variable is required")

        return AzureCredentials.from_env(tenant_id, self.config.site_base)

    async def _update_vector_db_for_language(self, language: str, config_handler: ConfigHandler, project_args) -> None:
        """Update vector DB with newly uploaded documents for a specific language."""
        logger.info(
            f"Updating vector DB for {language} with {len(self.newly_uploaded_documents[language])} new documents"
        )

        try:
            # Parse the newly uploaded documents using SharePoint File objects
            data_source_to_documents = await self._parse_new_documents_from_cache(
                language=language, config_handler=config_handler, project_args=project_args
            )

            if not data_source_to_documents or not any(docs for docs in data_source_to_documents.values()):
                logger.info(f"No parseable documents found for {language}")
                return

            # Create document chunks
            document_chunks = self.create_document_chunks(config_handler, data_source_to_documents)

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

            # Important: start the DB from scratch for each language
            drop_and_resetup_vector_db(vector_db.vector_db_config)
            await vector_db.from_chunks(document_chunks)

            # Save updated vector DB to COS
            await vector_db.to_cos(self.cos_api, should_overwrite_on_cos=True)

            logger.info(f"Successfully updated vector DB for {language}")

        except Exception as e:
            logger.error(f"Failed to update vector DB for {language}: {e}")
            raise

    def create_document_chunks(
        self, config_handler: ConfigHandler, data_source_to_documents: dict[str, list[Document]]
    ) -> list[DocumentChunk]:
        """Concatenates and splits documents.

        Args:
            config_handler: object containing the config
            data_source_to_documents: dict with kbm and eureka as key and a list of document as value

        Returns:
            A list of DocumentChunk
        """
        splitter = DocumentSplitter(config_handler.get_config("document_splitter"))
        documents = self.parser.concat_documents(document=data_source_to_documents)
        document_chunks = splitter.split_documents(documents)

        unique_keys = len({chunk.key for chunk in document_chunks})
        nb_keys = len(document_chunks)
        if unique_keys != nb_keys:
            warning_message = f"Duplicate keys found in document chunks: {unique_keys} unique keys for {nb_keys} chunks"
            warnings.warn(warning_message, stacklevel=2)

        return document_chunks

    async def _parse_new_documents_from_cache(
        self, language: str, config_handler: ConfigHandler, project_args
    ) -> dict[str, list[Document]]:
        """Parse newly uploaded documents using SharePoint File objects."""
        # Create a temporary mapping of newly uploaded documents by source
        new_docs_by_source = defaultdict(list)
        for doc_info in self.newly_uploaded_documents[language]:
            source = doc_info["doc"].source
            new_docs_by_source[source].append(doc_info)

        data_source_to_documents = {}

        for source, doc_infos in new_docs_by_source.items():
            parsed_docs = []
            unparsable_docs = []

            for doc_info in doc_infos:
                doc = doc_info["doc"]
                doc_data = doc_info["doc_data"]
                file_name = doc.file["Name"]

                try:
                    # Parse document using SharePoint File object
                    parsed_doc = await self._parse_document_from_sharepoint_file(
                        sharepoint_file=doc_data["File"],
                        source=source,
                        language=language
                    )

                    if parsed_doc:
                        parsed_docs.append(parsed_doc)

                except Exception as e:
                    logger.error(f"Failed to parse document {file_name}: {e}")
                    unparsable_docs.append(f"{file_name} because {e!s}")

            if unparsable_docs:
                self.parser.write_unparsed_docs(
                    unparsable_docs=unparsable_docs,
                    source=source,
                    language=language,
                    project_name=project_args.project_name,
                )

            data_source_to_documents[source] = parsed_docs

        return data_source_to_documents

    async def _parse_document_from_sharepoint_file(self, sharepoint_file: dict, source: str, language: str) -> Document | None:
        """Parse a single document directly from SharePoint File object using temporary file."""
        from pathlib import Path
        from tempfile import NamedTemporaryFile
        import os

        file_name = sharepoint_file.get("Name", "")
        if not file_name:
            logger.warning("SharePoint file has no name")
            return None

        # Get the appropriate parser for this source
        parser_config = self.parser.parser_config
        file_extensions = parser_config["sources"][source]

        # Determine file extension (without dot)
        file_extension = Path(file_name).suffix[1:].lower()
        if file_extension not in file_extensions:
            logger.warning(f"File extension {file_extension} not supported for source {source}")
            return None

        # Get parser for this extension
        parser_info = parser_config["extension_to_parser_map"][file_extension]
        file_parser = PARSER_NAME_TO_OBJECT[parser_info["name"]](**parser_info["kwargs"])

        # Get the file download URL from SharePoint
        server_relative_url = sharepoint_file.get("ServerRelativeUrl")
        if not server_relative_url:
            logger.error(f"No ServerRelativeUrl found for file {file_name}")
            return None

        try:
            # Download file content from SharePoint
            file_endpoint = f"/_api/web/GetFileByServerRelativeUrl('{server_relative_url}')/$value"
            file_content = self.api_client.send_request(endpoint=file_endpoint, return_raw=True)

            # Create temporary file with correct extension
            suffix = f".{file_extension}"
            with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(file_content)
                temp_file_path = Path(temp_file.name)

            try:
                # Parse the document from temporary file
                document = await file_parser.parse_as_document(path=temp_file_path, id=file_name)

                # Apply Eureka-specific processing if needed
                if source == EUREKA:
                    document = self.parser.update_titles_and_depths_eureka_nota(
                        document=document,
                        titles=self.parser.get_titles(filepath=str(temp_file_path)),
                        language=language,
                    )

                return document

            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except OSError:
                    logger.warning(f"Failed to delete temporary file {temp_file_path}")

        except Exception as e:
            logger.error(f"Failed to parse document {file_name}: {e}")
            return None

    @staticmethod
    def _create_cos_api() -> CosBucketApi:
        """Create COS API instance."""
        return create_cos_api()

    @staticmethod
    def _get_config_handler(project_name: str):
        """Get configuration handler."""
        return get_or_raise_config(project_name)

    @staticmethod
    def _get_languages(lang_args, config_handler) -> list[str]:
        """Get list of languages to process."""
        if hasattr(lang_args, "language") and lang_args.language:
            return [lang_args.language]
        return config_handler.get_config("languages")
