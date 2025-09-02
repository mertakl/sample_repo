In the following code some parts are ommmitted for simplicity;


async def run(self, project_args) -> None:
	"""Main execution method to run the entire synchronization process."""
	self._handle_deleted_files()

	newly_uploaded_by_lang = self._process_all_documents(project_args)

	await self._update_vector_db_for_languages(project_args, newly_uploaded_by_lang)
	

def _handle_deleted_files(self) -> None:
	"""Handle deletion of files that were removed from SharePoint."""
	deleted_files = self.sp_service.get_deleted_file_names()
	if deleted_files:
		for file_name in deleted_files:
			self.doc_processor.delete_document(file_name=file_name)
			
			

------------------
class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(  # noqa: D107
        self, api_client: SharePointAPIClient, cos_api: CosBucketApi, metadata_manager: MetadataManager
    ):
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager
        self.path_manager = PathManager()

    def process_document(self, doc: ProcessedDocument, parsed_args) -> tuple[bool, bytes | None]:
        """Process a single document. Returns (was_uploaded, file_content)."""
        file_info = doc.file
        file_name = file_info["Name"]
        last_modified = file_info["TimeLastModified"]

        file_path = self.path_manager.get_document_path(source=doc.source, language=doc.language, file_name=file_name)

        # Skip non-parseable files
        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc, parsed_args)
            return False, None

        # Check if upload is needed
        needs_upload = self._should_upload_document(file_path, last_modified)

        if needs_upload:
            file_content = self._upload_document(doc, file_path)
            return True, file_content

        return False, None

    def _should_upload_document(self, file_path: str, last_modified) -> bool:
        """Determine if document should be uploaded based on modification time and existence."""
        if DocumentFilter.is_recently_modified(last_modified):
            return True

        # Only upload old files if they don't exist in storage
        return not self.cos_api.file_exists(file_path)

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

    def _upload_document(self, doc: ProcessedDocument, document_path: str) -> bytes:
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
			
			
----------------------------------

    async def _update_vector_db_for_languages(self, project_args, newly_uploaded_by_lang: defaultdict) -> None:
        """Update vector database for all languages that have new documents."""
        languages_to_process = self._get_languages_to_process(project_args)

        for lang in languages_to_process:
            await self._update_vector_db_for_language(lang, newly_uploaded_by_lang, project_args)

    async def _update_vector_db_for_language(
        self, lang: str, newly_uploaded_by_lang: defaultdict, project_args
    ) -> None:
        """Update vector database for a specific language."""
        new_docs_for_lang = newly_uploaded_by_lang.get(lang)
        if not new_docs_for_lang:
            logger.info("No new documents to process for language: %s", lang)
            return

        await self.db_manager.update_for_language(
            language=lang, new_documents=new_docs_for_lang, project_name=project_args.project_name
        )
		
---------------------------
class VectorDBManager:
    """Manages parsing, chunking, and updating the vector database."""

    def __init__(  # noqa: D107
        self, config_handler: ConfigHandler, document_parser: DocumentParser, cos_api: CosBucketApi
    ):
        self.config_handler = config_handler
        self.parser = document_parser
        self.cos_api = cos_api

    async def update_for_language(
        self, language: str, new_documents: list[ProcessedDocument], project_name: str
    ) -> None:
        """Orchestrates the entire vector DB update process for a given language."""
        logger.info("Updating vector DB for %s with %s new documents.", language, len(new_documents))
        try:
            # 1. Parse documents
            data_source_to_documents = await self._parse_documents(
                language=language, new_documents=new_documents, project_name=project_name
            )
            if not any(data_source_to_documents.values()):
                logger.info("No parseable documents found for %s. Aborting update.", language)
                return

            # 2. Create chunks
            document_chunks = self._create_document_chunks(data_source_to_documents)
            if not document_chunks:
                logger.info("No document chunks created for %s. Aborting update.", language)
                return

            # 3. Initialize and update DB
            vector_db = self._initialize_vector_db(language)
            drop_and_resetup_vector_db(vector_db.vector_db_config)  # Assuming this is a required step
            await vector_db.from_chunks(document_chunks)

            # 4. Save to object storage
            await vector_db.to_cos(self.cos_api, should_overwrite_on_cos=True)
            logger.info("Successfully updated vector DB for %s.", language)

        except (ValueError, TypeError, OSError) as e:
            error_type = type(e).__name__
            logger.error(
                "%s error occurred while updating vector DB for %s: %s", error_type, language, e, exc_info=True
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Unexpected error occurred while updating vector DB for %s: %s", language, str(e), exc_info=True
            )

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

    def _create_document_chunks(self, data_source_to_documents: dict[str, list[Document]]) -> list[DocumentChunk]:
        """Concatenates documents by source and splits them into chunks."""
        splitter = DocumentSplitter(self.config_handler.get_config("document_splitter"))
        documents = self.parser.concat_documents(document=data_source_to_documents)
        document_chunks = splitter.split_documents(documents)

        # Check for duplicate keys
        unique_keys = len({chunk.key for chunk in document_chunks})
        if unique_keys != len(document_chunks):
            warnings.warn(
                f"Duplicate keys found: {unique_keys} unique keys for {len(document_chunks)} chunks.", stacklevel=2
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

        unknown_file = "Unknown File"

        for source, docs_to_parse in docs_by_source.items():
            for doc in docs_to_parse:
                try:
                    parsed_doc = await self._parse_document_content(
                        sp_file=doc.file, content=doc.content, source=source, language=language
                    )
                    if parsed_doc:
                        parsed_docs_by_source[source].append(parsed_doc)
                except (ValueError, TypeError, OSError, ParsingError) as e:
                    file_name = doc.file.get("Name", unknown_file)
                    logger.error("Error occurred while parsing document %s: %s", file_name, str(e))
                    unparsable_docs_log[source].append(f"{file_name} because {e!s}")
                except Exception as e:  # pylint: disable=broad-exception-caught
                    file_name = doc.file.get("Name", unknown_file)
                    logger.error("Unexpected error occurred while parsing document %s: %s", file_name, str(e))
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

        file_extension = Path(file_name).suffix.lstrip(".").lower()
        parser_config = self.parser.parser_config

        if file_extension not in parser_config["sources"].get(source, []):
            logger.warning("File extension '.%s' not supported for source '%s'.", file_extension, source)
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
            os.unlink(temp_file_path)  # Ensure cleanup
			
Files are coming from sharepoint. I upload them to cos bucket and keep track of the files in a csv file. 
I am not able to parse "doc" files in VectorDBManager. So I need to convert doc files to docx. Do you suggets to convert it at the beginning and use everywhere?
In this case delet files won't work as the incoming files will be original. Can you help?

##I need to use this method for conversion

def convert_doc_to_docx_locally(filepath: str | Path, path_to_docx: str | Path) -> None:
    """Converts a file or a folder of .doc to .docx format.

    Args:
        filepath: path to a single .doc or to a folder with one or several .doc (without *.doc)
        path_to_docx: path to a folder where the .docx will be written
    """
    subprocess.run(["lowriter", "--convert-to", "docx", f"{filepath}", "--outdir", f"{path_to_docx}"], check=False)
